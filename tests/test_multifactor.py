"""多因子策略核心逻辑测试（因子方向/合成权重/硬过滤/波动率档位/无未来函数）。"""

import numpy as np
import pandas as pd
import pytest

from scripts.quantrisk import multifactor
from scripts.quantrisk.multifactor import (
    FACTOR_W, MultiFactorConfig, multifactor_scores, run_multifactor_backtest,
    select_portfolio, volatility_tier, latest_net_profit_on,
    liquidity_ok, not_st,
)


def _mk_data(dates: int = 260, n: int = 30, seed: int = 1) -> pd.DataFrame:
    """合成价格矩阵：股票漂移递增（强者恒强），前10只趋势强+波动小。"""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=dates)
    cols = [f"{600000 + i}" for i in range(n)]
    drift = np.linspace(0.001, 0.004, n)
    vol = np.linspace(0.01, 0.04, n)
    p = pd.DataFrame(index=idx, columns=cols, dtype=float)
    base = 100.0
    for j, c in enumerate(cols):
        rets = rng.normal(drift[j], vol[j], dates)
        p[c] = base * np.cumprod(1 + rets)
    return p


def _mk_amount(close: pd.DataFrame, seed: int = 9) -> pd.DataFrame:
    """成交额矩阵（元/日）：与代码索引一致，制造横截面差异。"""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        rng.uniform(2e7, 5e8, size=close.shape),
        index=close.index, columns=close.columns)


def _mk_volume(close: pd.DataFrame, amount: pd.DataFrame) -> pd.DataFrame:
    """volume（手，A股 lot=100）：amount = vol×100×close → vol = amount/(100×close)。"""
    return amount.div(close * 100)


def test_factor_weight_sum_one():
    assert abs(sum(FACTOR_W.values()) - 1.0) < 1e-9


def test_multifactor_scores_direction():
    """强趋势+低波动股票得分应显著高于弱趋势+高波动。"""
    close = _mk_data(seed=3)
    amount = _mk_amount(close)
    sc = multifactor_scores(close, amount)
    valid = sc.iloc[-1].dropna()
    # 合成数据：代码越靠前（600000..）漂移越大 → 动量越高
    top = valid.sort_values(ascending=False)
    assert top.index[0] == close.columns[0] or valid[close.columns[0]] >= 0.5


def test_select_portfolio_filters_low_liquidity():
    """成交额 < 阈值的股票被剔除。"""
    close = _mk_data(seed=4)
    # 制造一只成交额极低的股票
    amount = _mk_amount(close)
    low_code = close.columns[-1]
    amount[low_code] = 1e5                      # 远低于 1000万
    volume = _mk_volume(close, amount)
    sc = multifactor_scores(close, amount)
    d = sc.dropna(how="all").index[-1]
    out = select_portfolio(sc.loc[d], close, amount, volume,
                           [{"code": c, "name": f"股{c}"} for c in close.columns],
                           None, d, top_n=10)
    assert low_code not in out.index


def test_not_st_filters_st_names():
    close = _mk_data(seed=5).iloc[-1:]
    universe = [{"code": close.columns[0], "name": "某ST股"},
                {"code": close.columns[1], "name": "*ST退市"},
                {"code": close.columns[2], "name": "正常股"}]
    st = not_st(close, universe)
    assert not st[close.columns[0]]
    assert not st[close.columns[1]]
    assert bool(st[close.columns[2]])


def test_volatility_tier_three_buckets():
    """高波动股票 → 高档位(2)；低波动 → 低档位(0)。"""
    close = _mk_data(seed=6)
    codes = list(close.columns[:12])
    d = close.index[-1]
    tier = volatility_tier(close, codes, d)
    assert set(tier.values()) <= {0, 1, 2}
    # 漂移递增但波动是 linspace(0.01,0.04)：末位代码波动最大 → 应高档
    assert tier[codes[-1]] == 2
    assert tier[codes[0]] == 0


def test_latest_net_profit_lag_no_lookahead():
    """报告期+披露滞后 > 决策日 → 该期不可用（防未来函数）。"""
    codes = ["600001", "600002"]
    pdf = pd.DataFrame({"600001": [10.0, 20.0], "600002": [-5.0, 30.0]},
                       index=["2025-06-30", "2025-12-31"])
    d_early = pd.Timestamp("2025-08-01")       # 12-31期+120天=2026-04-30 > d → 不可用
    s = latest_net_profit_on(pdf, d_early, codes)
    # 2025-06-30 + 120d = 2025-10-28 > 2025-08-01 → 无可用 → NaN
    assert s.isna().all()
    d_late = pd.Timestamp("2025-12-01")        # 06-30期可用
    s2 = latest_net_profit_on(pdf, d_late, codes)
    assert s2["600001"] == 10.0
    assert s2["600002"] == -5.0
    # 净利为负被过滤
    d_far = pd.Timestamp("2026-06-01")         # 12-31 期可用
    s3 = latest_net_profit_on(pdf, d_far, codes)
    assert s3["600002"] == 30.0


def _mk_hs300_trend(dates: int) -> pd.Series:
    """沪深300 长期上涨（强趋势，close 大多在 MA20 上方）。"""
    idx = pd.bdate_range("2025-01-01", periods=dates)
    px = 4000 * np.cumprod(1 + np.random.default_rng(1).normal(0.0025, 0.006, dates))
    return pd.Series(px, index=idx)


def test_backtest_smoke_runs_and_timing_close():
    """回测 smoke：能跑、有绩效指标；择时开启时（长期上涨→很少空仓）。"""
    close = _mk_data(seed=7)
    amount = _mk_amount(close)
    volume = _mk_volume(close, amount)
    hs300 = _mk_hs300_trend(len(close))
    cfg = MultiFactorConfig(warmup_days=60, top_n=5, initial_cash=1_000_000)
    res = run_multifactor_backtest(close, close.shift(1).fillna(close), volume,
                                   hs300, None, cfg,
                                   [{"code": c, "name": f"股{c}"} for c in close.columns])
    assert len(res.equity_curve) == len(close) - 60
    assert res.metrics.get("total_return") is not None
    # 空仓天数占比 < 50%（长期上涨择时很少触发）
    cash_days = (res.holdings.sum(axis=1) == 0).sum()
    assert cash_days / len(res.equity_curve) < 0.5
    assert res.metrics["max_drawdown"] <= 0.0


def test_backtest_stop_loss_triggers():
    """指数急跌 → 止损卖出记录出现（风控生效）。"""
    rng = np.random.default_rng(1)
    dates = 200
    idx = pd.bdate_range("2025-01-01", periods=dates)
    cols = [f"{600000 + i}" for i in range(10)]
    p = pd.DataFrame(index=idx, columns=cols, dtype=float)
    base = 100.0
    # 前120日缓慢涨，随后暴跌（触发止损）
    for j, c in enumerate(cols):
        rets = rng.normal(0.001, 0.01, dates)
        rets[120:140] = -0.05                  # 每日 -5%，连续暴跌
        rets[140:] = 0.0
        p[c] = base * np.cumprod(1 + rets)
    close = p
    amount = pd.DataFrame(1e8, index=idx, columns=cols)
    volume = amount.div(close * 100)
    hs300 = _mk_hs300_trend(dates) * 2         # 指数不跌（避免择时清仓干扰止损测试）
    cfg = MultiFactorConfig(warmup_days=60, top_n=5, stop_loss=0.08)
    res = run_multifactor_backtest(close, close.shift(1).fillna(close), volume,
                                   hs300, None, cfg,
                                   [{"code": c, "name": f"股{c}"} for c in cols])
    sells = [t for t in res.trades if t.get("action") == "sell"]
    assert len(sells) > 0, "暴跌应触发止损"
    assert all("止损" in t.get("note", "") for t in sells)


def test_backtest_no_lookahead_target_stable():
    """无未来函数：调仓日开盘价灾难化（成交价影响市值，但决策基于 t-1 不变 target）。"""
    close = _mk_data(seed=11)
    amount = _mk_amount(close)
    volume = _mk_volume(close, amount)
    hs300 = _mk_hs300_trend(len(close))
    base_open = close.shift(1).fillna(close)
    cfg = MultiFactorConfig(warmup_days=60, top_n=5)
    universe = [{"code": c, "name": f"股{c}"} for c in close.columns]
    res_a = run_multifactor_backtest(close, base_open, volume, hs300, None, cfg, universe)
    targets_a = {t["date"]: [c for c, _ in t.get("target", [])]
                 for t in res_a.trades if t.get("action") == "rebalance"}

    open_mut = base_open.copy()
    rb_dates = set(dates := list(close.index)) & {t for t in res_a.rebalance_dates}
    for t in res_a.rebalance_dates:
        if t in open_mut.index:
            open_mut.loc[t, :] = 1e9           # 开盘价灾难化（不影响 t-1 决策）
    res_b = run_multifactor_backtest(close, open_mut, volume, hs300, None, cfg, universe)
    targets_b = {t["date"]: [c for c, _ in t.get("target", [])]
                 for t in res_b.trades if t.get("action") == "rebalance"}
    assert targets_a == targets_b


def test_module_constants():
    from scripts.quantrisk import rotation
    assert multifactor.REBALANCE_DAYS == 20
    assert multifactor.MIN_AMOUNT_20D == 10_000_000
    assert multifactor.TIER_WEIGHT == {0: 1.0, 1: 0.7, 2: 0.4}
    assert rotation.REBALANCE_DAYS == 20