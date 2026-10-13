"""闸门动量测试（TrendGate = rotation × MA20 择时闸门）：空仓/再入场/无未来函数/敞口。"""

import numpy as np
import pandas as pd

from scripts.quantrisk.trendgate import TrendGateConfig, run_trendgate_backtest


def _mk_data(dates: int = 260, n: int = 30, seed: int = 1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=dates)
    cols = [f"{600000 + i}" for i in range(n)]
    drift = np.linspace(0.0005, 0.004, n)
    p = pd.DataFrame(index=idx, columns=cols, dtype=float)
    for j, c in enumerate(cols):
        p[c] = 100.0 * np.cumprod(1 + rng.normal(drift[j], 0.02, dates))
    return p


def _mk_hs300(dates: int, up: bool = True) -> pd.Series:
    idx = pd.bdate_range("2025-01-01", periods=dates)
    drift = 0.0025 if up else -0.002
    px = 4000 * np.cumprod(1 + np.random.default_rng(1).normal(drift, 0.006, dates))
    return pd.Series(px, index=idx)


def test_gate_off_all_flat():
    """沪深300 长期下跌 → MA20 择时全程看空 → 组合应大部分时间为空仓。"""
    close = _mk_data(seed=1)
    hs300 = _mk_hs300(len(close), up=False)
    cfg = TrendGateConfig(warmup_days=60)
    res = run_trendgate_backtest(close, close.shift(1).fillna(close), hs300, cfg,
                             [{"code": c, "name": f"股{c}"} for c in close.columns])
    cash_days = (res.holdings.sum(axis=1) == 0).sum()
    assert cash_days / len(res.equity_curve) > 0.8
    # 空仓 → 净值几乎不动（无持仓收益）
    assert abs(res.metrics["total_return"]) < 0.01


def test_gate_on_matches_rotation_like():
    """沪深300 强上涨 → 择时几乎不关 → 组合行为接近 rotation（有持仓、有调仓）。"""
    close = _mk_data(seed=2)
    hs300 = _mk_hs300(len(close), up=True)
    cfg = TrendGateConfig(warmup_days=60)
    res = run_trendgate_backtest(close, close.shift(1).fillna(close), hs300, cfg,
                             [{"code": c, "name": f"股{c}"} for c in close.columns])
    rebs = [t for t in res.trades if t.get("action") == "rebalance"]
    assert len(rebs) >= 3
    cash_days = (res.holdings.sum(axis=1) == 0).sum()
    assert cash_days / len(res.equity_curve) < 0.5


def test_reentry_after_gate_reopens():
    """gate 由关转开 → 当日重建持仓（不等下个 20 日调仓周期）。"""
    close = _mk_data(seed=3)
    idx = close.index
    n = len(idx)
    # 涨(建仓期) → 跌(择时清仓期) → 涨(再入场期)
    seg = [(0, 90, 0.004), (90, 150, -0.006), (150, n, 0.006)]
    parts = []
    rng = np.random.default_rng(2)
    for a, b, drift in seg:
        parts.append(np.cumprod(1 + rng.normal(drift, 0.004, b - a)))
    px = 4000 * np.concatenate(parts)
    hs300 = pd.Series(px, index=idx)
    cfg = TrendGateConfig(warmup_days=65)
    res = run_trendgate_backtest(close, close.shift(1).fillna(close), hs300, cfg,
                             [{"code": c, "name": f"股{c}"} for c in close.columns])
    closes = [t for t in res.trades if t.get("action") == "timing_close"]
    rebs = [t for t in res.trades if t.get("action") == "rebalance"]
    assert len(closes) >= 1, "下跌段应触发择时清仓"
    assert len(rebs) >= 2, "转多后应有再入场"


def test_no_lookahead_open_price_mutation():
    """无未来函数：调仓日开盘价灾难化 → 决策 target 不变（决策只用 t-1）。"""
    close = _mk_data(seed=4)
    hs300 = _mk_hs300(len(close), up=True)
    open_df = close.shift(1).fillna(close)
    cfg = TrendGateConfig(warmup_days=60)
    universe = [{"code": c, "name": f"股{c}"} for c in close.columns]
    res_a = run_trendgate_backtest(close, open_df, hs300, cfg, universe)
    targets_a = {t["date"]: list(t.get("target", []))
                 for t in res_a.trades if t.get("action") == "rebalance"}

    open_mut = open_df.copy()
    for t in res_a.rebalance_dates:
        if t in open_mut.index:
            open_mut.loc[t, :] = 1e9
    res_b = run_trendgate_backtest(close, open_mut, hs300, cfg, universe)
    targets_b = {t["date"]: list(t.get("target", []))
                 for t in res_b.trades if t.get("action") == "rebalance"}
    assert targets_a == targets_b


def test_exposure_cap_reduces_risk_and_return():
    """总敞口上限：降低敞口 → 回撤与收益同步下降（风险预算刻度）。"""
    close = _mk_data(seed=6)
    hs300 = _mk_hs300(len(close), up=True)
    open_df = close.shift(1).fillna(close)
    uni = [{"code": c, "name": f"股{c}"} for c in close.columns]

    r_full = run_trendgate_backtest(close, open_df, hs300,
                                TrendGateConfig(warmup_days=65, max_exposure=1.0), uni)
    r_half = run_trendgate_backtest(close, open_df, hs300,
                                TrendGateConfig(warmup_days=65, max_exposure=0.5), uni)
    assert abs(r_half.metrics["max_drawdown"]) <= abs(r_full.metrics["max_drawdown"]) + 1e-9
    assert r_half.metrics["total_return"] <= r_full.metrics["total_return"] + 1e-9
    # 敞口减半 → 全年在场时的收益大致按比例缩小（宽松下界，避免取整噪声）
    assert r_half.metrics["total_return"] < r_full.metrics["total_return"]


def test_confirm_days_delays_entry():
    """入场确认日数越大 → 再入场越谨慎（调仓次数不增）。"""
    close = _mk_data(seed=7)
    n = len(close)
    rng = np.random.default_rng(9)
    # 反复穿越 MA20 的震荡指数（制造 whipsaw）
    px = 4000 * np.cumprod(1 + rng.normal(0.0, 0.012, n))
    hs300 = pd.Series(px, index=close.index)
    open_df = close.shift(1).fillna(close)
    uni = [{"code": c, "name": f"股{c}"} for c in close.columns]

    r1 = run_trendgate_backtest(close, open_df, hs300, TrendGateConfig(warmup_days=65, gate_confirm_days=1), uni)
    r5 = run_trendgate_backtest(close, open_df, hs300, TrendGateConfig(warmup_days=65, gate_confirm_days=5), uni)
    n1 = len([t for t in r1.trades if t.get("action") == "rebalance"])
    n5 = len([t for t in r5.trades if t.get("action") == "rebalance"])
    assert n5 <= n1


def test_no_timing_equals_rotation_behavior():
    """关闭择时 → 永不空仓（= rotation 满仓行为特征）。

    注意 warmup_days=65：rotation 得分需 60 日动量，首个调仓日 dates[60] 决策用
    dates[59]（pct60 尚为 NaN → 空仓），warmup=65 保证首期就有有效得分。
    """
    close = _mk_data(seed=5)
    hs300 = _mk_hs300(len(close), up=False)
    cfg = TrendGateConfig(warmup_days=65, use_ma20_timing=False)
    res = run_trendgate_backtest(close, close.shift(1).fillna(close), hs300, cfg,
                             [{"code": c, "name": f"股{c}"} for c in close.columns])
    cash_days = (res.holdings.sum(axis=1) == 0).sum()
    assert cash_days == 0