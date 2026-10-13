"""双引擎组合测试：加权求和 / 权重归一化 / 再平衡 / 相关性 / 单调性。"""

import numpy as np
import pandas as pd
import pytest

from scripts.quantrisk import dualengine
from scripts.quantrisk.dualengine import combine_equity, leg_correlation, weight_sweep


def _leg(returns: list[float], start=1_000_000.0) -> pd.Series:
    idx = pd.bdate_range("2025-01-01", periods=len(returns))
    return pd.Series(start * np.cumprod(1 + np.array(returns)), index=idx)


def test_combine_equal_weight_matches_single_leg():
    """两腿完全相同且等权 → 组合收益 = 单腿收益。"""
    a = _leg([0.01] * 100)
    b = _leg([0.01] * 100)
    r = combine_equity({"A": a, "B": b}, {"A": 0.5, "B": 0.5})
    assert r.metrics["total_return"] == pytest.approx(a.iloc[-1] / a.iloc[0] - 1, rel=1e-9)


def test_weights_are_normalized():
    """权重和不为 1 时自动归一化（0.5/0.5 与 1/1 等价）。"""
    a, b = _leg([0.01, -0.005] * 50), _leg([0.002, 0.001] * 50)
    r1 = combine_equity({"A": a, "B": b}, {"A": 0.5, "B": 0.5})
    r2 = combine_equity({"A": a, "B": b}, {"A": 1.0, "B": 1.0})
    assert r1.metrics["total_return"] == pytest.approx(r2.metrics["total_return"], rel=1e-9)


def test_full_weight_equals_single_leg():
    """100% 权重 = 该腿本身。"""
    a, b = _leg([0.01] * 50), _leg([-0.02] * 50)
    r = combine_equity({"A": a, "B": b}, {"A": 1.0, "B": 0.0})
    assert r.metrics["total_return"] == pytest.approx(a.iloc[-1] / a.iloc[0] - 1, rel=1e-9)


def test_diversification_lowers_vol_when_uncorrelated():
    """不相关两腿等权 → 组合波动低于两腿平均（分散化生效）。"""
    rng = np.random.default_rng(3)
    a = _leg(list(rng.normal(0.001, 0.02, 400)))
    b = _leg(list(rng.normal(0.001, 0.02, 400)))
    r = combine_equity({"A": a, "B": b}, {"A": 0.5, "B": 0.5})
    va, vb = a.pct_change().std(), b.pct_change().std()
    vc = r.equity_curve.pct_change().std()
    assert vc < (va + vb) / 2


def test_low_sharpe_leg_drags_sharpe():
    """数学必然：加入夏普更低的腿（正相关）会拉低组合夏普。"""
    rng = np.random.default_rng(5)
    common = rng.normal(0, 0.01, 500)
    good = _leg(list(common + rng.normal(0.002, 0.005, 500)))     # 高夏普
    bad = _leg(list(common + rng.normal(0.0001, 0.02, 500)))      # 低夏普
    full = combine_equity({"G": good, "B": bad}, {"G": 1.0, "B": 0.0}).metrics["sharpe"]
    half = combine_equity({"G": good, "B": bad}, {"G": 0.5, "B": 0.5}).metrics["sharpe"]
    assert half < full


def test_annual_rebalance_runs_and_differs():
    """年度再平衡可运行，且与不再平衡结果不同（权重漂移被纠正）。"""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2023-01-02", periods=600)
    a = pd.Series(1e6 * np.cumprod(1 + rng.normal(0.002, 0.01, 600)), index=idx)
    b = pd.Series(1e6 * np.cumprod(1 + rng.normal(-0.0005, 0.01, 600)), index=idx)
    r_no = combine_equity({"A": a, "B": b}, {"A": .5, "B": .5}, rebalance="none")
    r_an = combine_equity({"A": a, "B": b}, {"A": .5, "B": .5}, rebalance="annual")
    assert len(r_an.equity_curve) == len(r_no.equity_curve)
    # A 腿更强时不再平衡会让 A 权重漂升 → 收益更高；再平衡把它拉回 50% → 收益更低
    assert abs(r_an.metrics["total_return"] - r_no.metrics["total_return"]) > 1e-9


def test_correlation_calc():
    idx = pd.bdate_range("2025-01-01", periods=200)
    base = np.random.default_rng(1).normal(0, 0.01, 200)
    a = pd.Series(1e6 * np.cumprod(1 + base), index=idx)
    b = pd.Series(1e6 * np.cumprod(1 + base), index=idx)          # 完全相同
    c = pd.Series(1e6 * np.cumprod(1 - base), index=idx)          # 完全相反
    assert leg_correlation({"A": a, "B": b}) == pytest.approx(1.0, abs=1e-6)
    assert leg_correlation({"A": a, "B": c}) == pytest.approx(-1.0, abs=1e-6)


def test_weight_sweep_monotone_bounds():
    """扫描端点应等于各自单腿表现。"""
    rng = np.random.default_rng(11)
    a = _leg(list(rng.normal(0.002, 0.012, 300)))
    b = _leg(list(rng.normal(0.0002, 0.01, 300)))
    rows = weight_sweep({"A": a, "B": b}, [1.0, 0.5, 0.0])
    assert rows[0]["total_return"] == pytest.approx(a.iloc[-1] / a.iloc[0] - 1, rel=1e-9)
    assert rows[-1]["total_return"] == pytest.approx(b.iloc[-1] / b.iloc[0] - 1, rel=1e-9)


def test_misaligned_dates_intersect():
    """日期不齐时取交集，不报错。"""
    idx1 = pd.bdate_range("2025-01-01", periods=100)
    idx2 = pd.bdate_range("2025-01-20", periods=100)
    a = pd.Series(1e6 * np.cumprod(1 + np.full(100, 0.001)), index=idx1)
    b = pd.Series(1e6 * np.cumprod(1 + np.full(100, 0.001)), index=idx2)
    r = combine_equity({"A": a, "B": b}, {"A": .5, "B": .5})
    assert r.equity_curve.index[0] >= idx2[0]
    assert r.equity_curve.index[-1] <= idx1[-1]