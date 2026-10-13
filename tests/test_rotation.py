"""市场轮动策略核心逻辑测试（无未来函数 / 横截面排名 / 100股取整 / 空仓）。"""

import numpy as np
import pandas as pd
import pytest

from scripts.quantrisk import rotation
from scripts.quantrisk.rotation import (
    RotationBacktestConfig, cross_section_scores, run_backtest, select_on_date,
)


def _mk_close(dates: int = 260, n_stocks: int = 30, seed: int = 1) -> pd.DataFrame:
    """合成 260 日 × 30 只股票的价格矩阵：随机游走（趋势股有漂移，便于出排名）。"""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=dates)
    cols = [f"{600000 + i}" for i in range(n_stocks)]
    drift = np.linspace(0.0005, 0.004, n_stocks)          # 不同趋势强度
    p = pd.DataFrame(index=idx, columns=cols, dtype=float)
    base = 100.0
    for j, c in enumerate(cols):
        rets = rng.normal(drift[j], 0.02, dates)
        p[c] = base * np.cumprod(1 + rets)
    return p


def test_scores_cross_section_rank_in_0_1():
    """横截面排名归一化到 0~1，且为逐行（每交易日）计算。"""
    close = _mk_close()
    sc = cross_section_scores(close)
    assert sc.shape == close.shape
    # 预热期后可计算的日期占比合理
    valid = sc.dropna(how="all")
    assert len(valid) >= 150
    row = valid.iloc[-1].dropna()
    assert row.between(0, 1).all()
    # 排名最高分与最低分应接近 0 和 1（样本多时）
    assert row.max() >= 0.9
    assert row.min() <= 0.1


def test_scores_reward_momentum_both_windows():
    """动量最强的股票得分应最高：pct20/pct60 均领先 → 综合得分最高。"""
    close = _mk_close(seed=3)
    sc = cross_section_scores(close)
    valid = sc.iloc[-1].dropna().sort_values(ascending=False)
    ret20 = close.pct_change(20, fill_method=None).iloc[-1]
    ret60 = close.pct_change(60, fill_method=None).iloc[-1]
    top_code = valid.index[0]
    # 得分第一的股票其 20/60 日涨幅排名不应在池内垫底
    assert ret20[top_code] >= ret20.median()
    assert ret60[top_code] >= ret60.median()


def test_select_on_date_min_score_and_topn():
    close = _mk_close(seed=5)
    sc = cross_section_scores(close)
    d = sc.dropna(how="all").index[-1]
    out = select_on_date(sc, d, min_score=0.65, top_n=10)
    assert len(out) <= 10
    if not out.empty:
        assert (out >= 0.65).all()
        assert out.is_monotonic_decreasing


def test_select_on_date_empty_when_below_threshold():
    """无合格标的 → 空 Series（空仓）。"""
    close = _mk_close(seed=7)
    sc = cross_section_scores(close)
    d = sc.dropna(how="all").index[-1]
    out = select_on_date(sc, d, min_score=0.99, top_n=10)
    assert out.empty


def _mk_market_flat(n_days: int = 200, n: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """无趋势平盘市场：所有股票同涨同跌（便于校验等权与取整）。"""
    idx = pd.bdate_range("2025-01-01", periods=n_days)
    cols = [f"{600000 + i}" for i in range(n)]
    closes = np.tile(1.0 + np.linspace(0, 0.2, n_days)[:, None], (1, n))
    close = pd.DataFrame(closes, index=idx, columns=cols)
    open_df = close.shift(1).fillna(close)
    return close, open_df


def test_backtest_equal_weight_and_lot():
    """调仓日持仓等权（100股取整后近似等权）、股数为 100 的倍数。"""
    close, open_df = _mk_market_flat()
    cfg = RotationBacktestConfig(initial_cash=1_000_000, warmup_days=60, top_n=5, min_score=0.0)
    res = run_backtest(close, open_df, cfg)
    assert len(res.equity_curve) == len(close) - cfg.warmup_days
    # 最近一次调仓持仓
    last = res.trades[-1]["positions"]
    assert len(last) <= 5
    for code, shares in last.items():
        assert shares % 100 == 0
        assert shares > 0
    # 等权：各持仓市值接近（±15%）
    close_row = close.iloc[-1]
    vals = [shares * close_row[code] for code, shares in last.items()]
    mean = np.mean(vals)
    assert all(abs(v / mean - 1) < 0.15 for v in vals), f"等权偏离: {vals}"


def test_backtest_empty_holdings_when_no_target():
    """min_score 过高 → 无合格标的 → 空仓（市值=现金=初始值±残差）。"""
    close, open_df = _mk_market_flat()
    cfg = RotationBacktestConfig(initial_cash=500_000, warmup_days=60, min_score=0.999)
    res = run_backtest(close, open_df, cfg)
    assert res.holdings.sum(axis=1).max() == 0            # 全程空仓
    assert abs(res.equity_curve.iloc[-1] - 500_000) < 1e-6


def test_backtest_no_lookahead():
    """无未来函数：调仓日 t 的决策只依赖 ≤t-1 的行情。

    验证方法：把调仓日及其后三天的价格全部篡改为 −1000（灾难性暴跌），
    只要决策基于 t-1，t 日开盘价被篡改只会拉低当日市值，但决策选股
    （用 t-1 数据）不受影响——即：篡改后调仓 target 与篡改前完全一致。
    """
    close = _mk_close(seed=11)
    open_df = close.copy()
    cfg = RotationBacktestConfig(warmup_days=60, top_n=5, min_score=0.0)
    res_a = run_backtest(close, open_df, cfg)
    targets_a = {tr["date"]: tr["target"] for tr in res_a.trades}

    close_mut = close.copy()
    rb = res_a.rebalance_dates
    for t in rb:
        if t in close_mut.index:
            close_mut.loc[t, :] = -1000.0                  # 调仓日收盘价灾难化
    res_b = run_backtest(close_mut, open_df, cfg)
    targets_b = {tr["date"]: [c for c in tr["target"]] for tr in res_b.trades}
    # 决策日信息未变 → target 相同（open 未篡改，成交价不受影响）
    assert targets_a == targets_b


def test_metrics_calc():
    """指标：累计收益/年化/回撤/夏普 能算且数值域合理。"""
    close, open_df = _mk_market_flat()
    cfg = RotationBacktestConfig(warmup_days=60, top_n=5, min_score=0.0)
    res = run_backtest(close, open_df, cfg)
    m = res.metrics
    assert "total_return" in m and "max_drawdown" in m and "sharpe" in m
    assert m["max_drawdown"] <= 0.0                        # 回撤非正
    assert abs(m["annual_return"] - m["total_return"]) < 1.0  # 平盘市场年化≈累计


def test_rotation_module_imports():
    """模块可导入且默认参数符合规格。"""
    assert rotation.REBALANCE_DAYS == 20
    assert rotation.MIN_SCORE == 0.65
    assert rotation.TOP_N == 10
    assert rotation.WARMUP_DAYS == 120
    assert rotation.LOT_SIZE == 100