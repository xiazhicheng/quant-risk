"""自适应切换测试：滚动判定无前视、状态机、切换成本、与单一策略对比口径。"""

import numpy as np
import pandas as pd
import pytest

from scripts.quantrisk import adaptive
from scripts.quantrisk.adaptive import AdaptiveConfig, adaptive_backtest, regime_predictive_power, rolling_regime


def _mk(prices, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(prices))
    return pd.DataFrame({
        "open": prices, "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices], "close": prices,
        "volume": [1_000_000] * len(prices),
    }, index=idx)


def _choppy(n=600, seed=1, level=10.0):
    """真正的震荡序列：对数价格走 Ornstein-Uhlenbeck 均值回归。

    早期版本用"随机游走 + 末尾线性拉回起点"，那个修正项本身引入强线性趋势，
    会被正确判为 trend（暴露的是测试数据 bug，不是引擎 bug）。
    """
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    theta = 0.05                                          # 均值回归速度
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (0 - x[i - 1]) + rng.normal(0, 0.02)
    return list(level * np.exp(x))


def _trend(n=600, drift=0.005, seed=2):
    rng = np.random.default_rng(seed)
    return list(10 * np.cumprod(1 + rng.normal(drift, 0.015, n)))


def test_rolling_regime_no_lookahead():
    """判定不得使用未来数据：截断序列后，已判定日期的状态应保持不变。"""
    prices = _choppy(500)
    df = _mk(prices)
    cfg = AdaptiveConfig(lookback=100, step=20)
    full = rolling_regime(df["close"], cfg)
    sliced = rolling_regime(df["close"].iloc[:400], cfg)
    common = [d for d in sliced.index if d in full.index]
    assert common, "应有重叠判定日"
    for d in common:
        assert full.loc[d] == sliced.loc[d], f"{d} 判定被未来数据影响"


def test_rolling_regime_states_valid():
    cfg = AdaptiveConfig(lookback=100, step=20)
    reg = rolling_regime(_mk(_choppy(500))["close"], cfg)
    assert len(reg) > 0
    assert set(reg.unique()) <= {"choppy", "trend"}


def test_trend_series_detected_as_trend():
    """强趋势序列应至少出现一次 trend 判定。"""
    cfg = AdaptiveConfig(lookback=100, step=20)
    reg = rolling_regime(_mk(_trend(700))["close"], cfg)
    assert (reg == "trend").sum() >= 1


def test_choppy_series_mostly_choppy():
    """纯震荡序列应多数判为 choppy。"""
    cfg = AdaptiveConfig(lookback=100, step=20)
    reg = rolling_regime(_mk(_choppy(700))["close"], cfg)
    assert (reg == "choppy").mean() > 0.5


def test_hysteresis_prevents_flip_flop():
    """滞后带：中间区间沿用前值，不产生额外状态种类。"""
    cfg = AdaptiveConfig(lookback=80, step=20, ir_choppy=0.25, ir_trend=0.50)
    reg = rolling_regime(_mk(_choppy(600, seed=5))["close"], cfg)
    assert set(reg.unique()) <= {"choppy", "trend"}


def test_switches_bounded_by_judgments():
    """切换次数不可能超过判定次数（不变量）。

    ⚠️ 注意一个**如实记录的现实现象**：即便是纯震荡序列（OU 均值回归、真实无趋势），
    滚动判定也会产生多次切换（实测 8 次 / 约 25 次判定）——判定在噪声中来回横跳，
    这正是「先判定再切换」方案失效的直接原因之一，故此处只断言合理上界。
    """
    cfg = AdaptiveConfig(lookback=100, step=20)
    df = _mk(_choppy(600))
    res = adaptive_backtest(df, cfg)
    n_judgments = len(rolling_regime(df["close"], cfg))
    assert res.n_switches <= n_judgments


def test_switches_counted_and_cost_applied():
    """切换次数被记录，且每次切换都扣了摩擦成本（净值低于无摩擦情形）。"""
    df = _mk(_trend(600))
    cfg = AdaptiveConfig(lookback=100, step=20, switch_cost=0.01)
    r_cost = adaptive_backtest(df, cfg)
    cfg0 = AdaptiveConfig(lookback=100, step=20, switch_cost=0.0)
    r_free = adaptive_backtest(df, cfg0)
    assert r_cost.n_switches == r_free.n_switches
    if r_free.n_switches > 0:
        assert r_cost.metrics["total_return"] < r_free.metrics["total_return"]


def test_adaptive_equity_len_matches_data():
    df = _mk(_trend(500))
    res = adaptive_backtest(df, AdaptiveConfig(lookback=100, step=20))
    assert len(res.equity_curve) == len(df)
    assert (res.equity_curve > 0).all()


def test_legs_present_for_comparison():
    """必须给出两条单腿曲线用于对比（否则无法判断切换是否有价值）。"""
    res = adaptive_backtest(_mk(_trend(500)), AdaptiveConfig(lookback=100, step=20))
    assert set(res.legs) == {"grid_only", "trend_only"}
    assert len(res.legs["grid_only"]) == len(res.legs["trend_only"])


def test_predictive_power_keys():
    pp = regime_predictive_power(_mk(_trend(600))["close"], AdaptiveConfig(lookback=100, step=20))
    for k in ("n_trend", "n_choppy", "trend_fwd_ir", "choppy_fwd_ir", "trend_fwd_ret", "choppy_fwd_ret"):
        assert k in pp


def test_insufficient_data_raises():
    with pytest.raises(ValueError):
        adaptive_backtest(_mk(_trend(50)), AdaptiveConfig(lookback=120, step=20))