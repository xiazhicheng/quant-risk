"""交易摩擦与可成交性测试：涨跌停、停牌、滑点（2026-10-14）。

口径：A股 开盘涨停买不进 / 开盘跌停卖不出（ST 5%、创业科创 20%、北交所 30%、主板 10%）；
停牌（成交量 0 或缺失）当日不可成交；被挡下的卖单登记 pending 并在后续每日重试；
港股无涨跌停约束。
"""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from scripts.quantrisk.trendgate import TrendGateConfig, run_trendgate_backtest


def _base(n=40, code="600000", warmup=5, rebalance_days=5, top_n=1):
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = pd.DataFrame({code: np.full(n, 10.0)}, index=idx)
    op = close.copy()
    scores = pd.DataFrame({code: np.full(n, 1.0)}, index=idx)
    cfg = TrendGateConfig(gate_mode="index", top_n=top_n, gate_ma=3, gate_confirm_days=1,
                          warmup_days=warmup, rebalance_days=rebalance_days,
                          lot_size=1, min_score=0.0, use_ma20_timing=False,
                          max_exposure=1.0, initial_cash=1_000_000, commission_rate=0.0)
    return idx, close, op, scores, cfg


def _run(close, op, scores, cfg, volume=None):
    return run_trendgate_backtest(close, op, None, cfg, [], scores_override=scores,
                                  volume_df=volume)


def test_limit_up_blocks_buy_and_defers_to_next_rebalance():
    """开盘涨停（+10%）买不进：当日无成交、计数 +1，下个调仓日补上。"""
    idx, close, op, scores, cfg = _base()
    t = idx[5]
    op.loc[t, "600000"] = float(close.loc[idx[4], "600000"]) * 1.10
    r = _run(close, op, scores, cfg)
    assert r.execution["limit_up_blocked"] >= 1
    assert not [f for f in r.fills if f["date"] == str(t.date())]
    later = [f for f in r.fills if f["date"] > str(t.date())]
    assert later and later[0]["side"] == "buy"


def test_limit_down_blocks_sell_then_pending_retries_next_day():
    """开盘跌停（-10%）卖不出：登记 pending，次日恢复后重试成交。"""
    idx, close, op, scores, cfg = _base()
    t2 = idx[10]
    op.loc[t2, "600000"] = float(close.loc[idx[9], "600000"]) * 0.90
    r = _run(close, op, scores, cfg)
    assert r.execution["limit_down_blocked"] >= 1
    sells = [f for f in r.fills if f["side"] == "sell"]
    assert sells, "重试后应卖出"
    assert sells[0]["reason"].endswith("_retry")
    assert sells[0]["date"] == str(idx[11].date())
    assert r.execution["pending_sells"] == 0


def test_halt_zero_volume_blocks_fill():
    """停牌（volume=0）当日不可成交。"""
    idx, close, op, scores, cfg = _base()
    vol = pd.DataFrame(1_000_000.0, index=idx, columns=["600000"])
    t = idx[5]
    vol.loc[t, "600000"] = 0.0
    r = _run(close, op, scores, cfg, volume=vol)
    assert r.execution["halt_blocked"] >= 1
    assert not [f for f in r.fills if f["date"] == str(t.date())]
    assert r.execution["has_volume"] is True


def test_no_volume_matrix_skips_halt_check():
    """无 volume 矩阵时停牌检查自动跳过（向后兼容旧缓存）。"""
    idx, close, op, scores, cfg = _base()
    r = _run(close, op, scores, cfg, volume=None)
    assert r.execution["halt_blocked"] == 0
    assert r.execution["has_volume"] is False


def test_slippage_raises_buy_price_and_lowers_equity():
    """滑点：买入价更高、终值更低（卖侧同样扣减）。"""
    idx, close, op, scores, cfg = _base()
    r0 = _run(close, op, scores, replace(cfg, slippage=0.0))
    r1 = _run(close, op, scores, replace(cfg, slippage=0.01))
    assert r1.fills[0]["side"] == "buy"
    assert r1.fills[0]["price"] > r0.fills[0]["price"]
    assert r1.equity_curve.iloc[-1] < r0.equity_curve.iloc[-1]


def test_hk_market_has_no_price_limit():
    """港股（market='hk'）无涨跌停：+10% 开盘照常成交。"""
    idx, close, op, scores, cfg = _base()
    t = idx[5]
    op.loc[t, "600000"] = float(close.loc[idx[4], "600000"]) * 1.10
    r = _run(close, op, scores, replace(cfg, market="hk"))
    assert r.execution["limit_up_blocked"] == 0
    assert [f for f in r.fills if f["date"] == str(t.date())]


def test_chinext_uses_20pct_limit():
    """创业板（300 开头）涨跌停 20%：+11% 开盘不构成涨停、可买入。"""
    idx, close, op, scores, cfg = _base(code="300001")
    t = idx[5]
    op.loc[t, "300001"] = float(close.loc[idx[4], "300001"]) * 1.11
    r = _run(close, op, scores, cfg)
    assert r.execution["limit_up_blocked"] == 0
    assert [f for f in r.fills if f["date"] == str(t.date())]


def test_st_uses_5pct_limit():
    """ST 股涨跌停 5%：+6% 开盘即构成涨停、买不进。"""
    idx, close, op, scores, cfg = _base(code="600001")
    t = idx[5]
    op.loc[t, "600001"] = float(close.loc[idx[4], "600001"]) * 1.06
    universe = [{"code": "600001", "name": "ST测试"}]
    r = run_trendgate_backtest(close, op, None, cfg, universe, scores_override=scores)
    assert r.execution["limit_up_blocked"] >= 1
    assert not [f for f in r.fills if f["date"] == str(t.date())]


def test_disable_limit_check_restores_old_behavior():
    """关闭涨跌停约束（--no-limit-check 语义）→ 涨停价照常成交。"""
    idx, close, op, scores, cfg = _base()
    t = idx[5]
    op.loc[t, "600000"] = float(close.loc[idx[4], "600000"]) * 1.10
    r = _run(close, op, scores, replace(cfg, enforce_price_limits=False))
    assert r.execution["limit_up_blocked"] == 0
    assert [f for f in r.fills if f["date"] == str(t.date())]


def test_invalid_friction_params_rejected():
    idx, close, op, scores, cfg = _base()
    with pytest.raises(ValueError):
        _run(close, op, scores, replace(cfg, slippage=1.5))
    with pytest.raises(ValueError):
        _run(close, op, scores, replace(cfg, limit_pct=0.0))
    with pytest.raises(ValueError):
        _run(close, op, scores, replace(cfg, market="us"))


def test_default_config_is_backward_compatible():
    """默认 slippage=0 + 无 volume + 价格不触板 → 与旧口径一致（有成交、无受阻）。"""
    idx, close, op, scores, cfg = _base()
    r = _run(close, op, scores, cfg)
    assert r.fills and r.execution["limit_up_blocked"] == 0
    assert r.execution["limit_down_blocked"] == 0
    assert r.execution["halt_blocked"] == 0
    assert r.execution["slippage"] == 0.0
