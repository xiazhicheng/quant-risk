"""事件驱动换仓模式（rebalance_mode='event'）测试。

口径：event = 不强制换仓（掉出双动量排名不卖）；每日只认卖出信号（闸门关闭）；
调仓日才评估买入信号——持仓数 < N 时新信号入场，已有持仓低于目标权重才补足加仓。
"""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from scripts.quantrisk.trendgate import TrendGateConfig, run_trendgate_backtest


def _setup(n=60, top_n=2, gate_ma=3, warmup=5, rebalance_days=5,
           b_tail="flat"):
    """A 全程最强；B 前 20 日次强、之后掉出排名；C 后 40 日新晋强势。

    b_tail='flat'  → B 后段横盘（不破 MA，事件驱动下不该被卖）
    b_tail='down'  → B 后段下跌（跌破 MA，触发卖出信号）
    """
    idx = pd.bdate_range("2025-01-01", periods=n)
    b_tail_px = np.full(n - 20, 14.0) if b_tail == "flat" else np.linspace(14.0, 6.0, n - 20)
    close = pd.DataFrame({
        "A": np.linspace(10, 30, n),
        "B": np.concatenate([np.linspace(10, 14, 20), b_tail_px]),
        "C": np.concatenate([np.full(20, 10.0), np.linspace(10, 25, n - 20)]),
    }, index=idx)
    scores = pd.DataFrame({
        "A": np.full(n, 1.0),
        "B": np.concatenate([np.full(20, 0.9), np.full(n - 20, 0.1)]),
        "C": np.concatenate([np.full(20, 0.1), np.full(n - 20, 0.95)]),
    }, index=idx)
    cfg = TrendGateConfig(gate_mode="stock", rebalance_mode="event", top_n=top_n,
                          gate_ma=gate_ma, gate_confirm_days=1, warmup_days=warmup,
                          rebalance_days=rebalance_days, lot_size=1, min_score=0.0)
    return close, close.shift(1).bfill(), scores, cfg


def _run(close, op, scores, cfg):
    return run_trendgate_backtest(close, op, None, cfg, [], scores_override=scores)


def test_event_never_force_rebalances():
    """事件驱动不产生 rebalance 卖出（periodic 会产生）——核心机制差异。"""
    close, op, scores, cfg = _setup()
    r_event = _run(close, op, scores, cfg)
    r_periodic = _run(close, op, scores, replace(cfg, rebalance_mode="periodic"))
    assert not any(f["reason"] == "rebalance" for f in r_event.fills)
    assert any(f["reason"] == "rebalance" for f in r_periodic.fills)


def test_event_keeps_holding_that_dropped_out_of_rank():
    """掉出排名但未触发卖出信号的持仓继续保留（不换仓）。"""
    close, op, scores, cfg = _setup(b_tail="flat")
    r = _run(close, op, scores, cfg)
    # B 后 40 日仍被持有（periodic 会在调仓日把它换成 C）
    assert r.holdings["B"].iloc[-1] > 0
    assert all(f["reason"] != "rank_drop" for f in r.fills)


def test_event_sells_on_stock_gate_close():
    """B 后段跌破自身 MA → 触发 stock_gate_close 卖出。"""
    close, op, scores, cfg = _setup(b_tail="down")
    r = _run(close, op, scores, cfg)
    reasons = [f["reason"] for f in r.fills]
    assert "stock_gate_close" in reasons
    assert r.holdings["B"].iloc[-1] == 0


def test_event_position_count_capped_at_top_n():
    """持仓数不超过 top_n（旧仓不卖时新信号进不来是机制特性）。"""
    close, op, scores, cfg = _setup(b_tail="flat")
    r = _run(close, op, scores, cfg)
    assert (r.holdings.gt(0).sum(axis=1) <= cfg.top_n).all()


def test_event_rank_drop_sells_only_when_enabled():
    """exit_on_rank_drop=True 时，掉出排名的持仓才被卖出。"""
    close, op, scores, cfg = _setup(b_tail="flat")
    r = _run(close, op, scores, replace(cfg, exit_on_rank_drop=True))
    assert any(f["reason"] == "rank_drop" for f in r.fills)


def test_event_entries_use_expected_reasons():
    """成交原因只应是事件驱动的三类（入场/加仓/闸门离场），无 rebalance。"""
    close, op, scores, cfg = _setup(b_tail="down")
    r = _run(close, op, scores, cfg)
    allowed = {"event_entry", "event_add", "stock_gate_close"}
    assert {f["reason"] for f in r.fills} <= allowed
    assert any(f["reason"] == "event_entry" for f in r.fills)


def test_event_index_gate_clears_all_positions():
    """指数闸门关闭 → 全部清仓（整体避险在事件驱动下仍保留）。"""
    n = 60
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = pd.DataFrame({"A": np.linspace(10, 20, n), "B": np.linspace(10, 18, n)}, index=idx)
    scores = pd.DataFrame({"A": 1.0, "B": 0.9}, index=idx)
    gate = pd.Series(np.concatenate([np.full(30, 100.0), np.linspace(50.0, 20.0, n - 30)]), index=idx)
    cfg = TrendGateConfig(gate_mode="index", rebalance_mode="event", top_n=2, gate_ma=3,
                          gate_confirm_days=1, warmup_days=5, rebalance_days=5,
                          lot_size=1, min_score=0.0)
    r = run_trendgate_backtest(close, close.shift(1).bfill(), gate, cfg, [],
                               scores_override=scores)
    assert any(f["reason"] == "index_gate_close" for f in r.fills)
    assert r.holdings.sum(axis=1).iloc[-1] == 0


def test_invalid_rebalance_mode_rejected():
    close, op, scores, cfg = _setup()
    with pytest.raises(ValueError):
        _run(close, op, scores, replace(cfg, rebalance_mode="daily"))


def test_invalid_add_tolerance_rejected():
    close, op, scores, cfg = _setup()
    with pytest.raises(ValueError):
        _run(close, op, scores, replace(cfg, add_tolerance=1.5))


def test_periodic_mode_unchanged_by_new_fields():
    """新字段默认不改变原有 periodic 行为（回归保护）。"""
    close, op, scores, cfg = _setup()
    legacy = replace(cfg, rebalance_mode="periodic")
    r = run_trendgate_backtest(close, op, None, legacy, [], scores_override=scores)
    assert r.metrics["total_return"] > 0
    assert any(f["reason"] == "rebalance" for f in r.fills)
