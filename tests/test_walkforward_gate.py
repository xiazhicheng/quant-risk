"""Walk-forward 闸门验证测试：滚动段计算、净值日期对齐（回归）、报告渲染。

回归背景：引擎只从 warmup 之后记录净值（range(cfg.warmup_days, len(dates))），
早期版本按「窗口内位置」切片 equity_curve，导致所有滚动段指标为空
（超额恒为 0）。此处用只从 warmup 起有净值的曲线锁死日期对齐口径。
"""
import argparse

import pandas as pd
import pytest

from scripts.walkforward_gate import _eval_segment, _render, _rolling_starts


# ── 滚动段起点 ──────────────────────────────────────────────────────────────

def test_rolling_starts_count_and_bounds():
    starts = _rolling_starts(807, warmup=120, eval_days=120, step=20)
    assert len(starts) == 29
    assert starts[0] == 120
    assert starts[-1] + 120 <= 807          # 每段都落在样本内
    assert all(b - a == 20 for a, b in zip(starts, starts[1:]))


def test_rolling_starts_raises_when_short():
    with pytest.raises(ValueError):
        _rolling_starts(200, warmup=120, eval_days=120, step=20)


def test_rolling_starts_single_segment_when_exact():
    # 恰好 warmup + eval_days + 1 日 → 只有一段
    assert _rolling_starts(241, warmup=120, eval_days=120, step=20) == [120]


# ── 净值日期对齐（回归）────────────────────────────────────────────────────

def test_eval_segment_aligns_by_date_not_position():
    """曲线只从 warmup 后开始；评测段必须按日期取到，不能按位置切片。"""
    seg_dates = pd.bdate_range("2024-01-02", periods=5)
    curve = pd.Series([100.0, 110.0, 121.0, 133.1, 146.41], index=seg_dates)
    seg = _eval_segment(curve, seg_dates)
    assert len(seg) == 5
    assert seg.iloc[0] == pytest.approx(1.0)          # 归一到 1.0
    assert seg.iloc[-1] == pytest.approx(1.4641)      # 完整吃到段内收益


def test_eval_segment_ignores_dates_before_curve_start():
    """段日期落在曲线记录起点之前的部分被丢弃，只留交集。"""
    curve_dates = pd.bdate_range("2024-03-01", periods=4)
    curve = pd.Series([50.0, 55.0, 60.0, 66.0], index=curve_dates)
    seg_dates = pd.bdate_range("2024-01-02", periods=50)   # 起点远早于曲线
    seg = _eval_segment(curve, seg_dates)
    assert len(seg) == 4
    assert seg.iloc[0] == pytest.approx(1.0)


def test_eval_segment_empty_when_no_overlap():
    curve = pd.Series([1.0, 2.0], index=pd.bdate_range("2024-01-01", periods=2))
    seg_dates = pd.bdate_range("2025-01-01", periods=5)
    seg = _eval_segment(curve, seg_dates)
    assert len(seg) < 2        # 触发 _metrics 返回空 → 报告显示 —


def test_eval_segment_single_point_is_not_usable():
    d = pd.bdate_range("2024-01-01", periods=1)
    assert len(_eval_segment(pd.Series([1.0], index=d), d)) < 2


# ── 报告渲染 ────────────────────────────────────────────────────────────────

def _args():
    return argparse.Namespace(eval_days=120, step=20, warmup=120, initial_cash=1_000_000.0,
                              gate_ma=30, confirm=3, exposure=0.7, rebalance_days=20,
                              commission=0.001)


def test_render_contains_core_sections_and_rows():
    full = [{"n": 5, "idx_ret": 0.41, "stk_ret": 0.73, "exc": 0.32,
             "idx_dd": -0.15, "stk_dd": -0.17, "idx_sharpe": 0.82, "stk_sharpe": 1.04}]
    roll = [{"n": 5, "n_win": 29, "win_rate": 0.724, "exc_mean": 0.066, "exc_med": 0.08,
             "exc_min": -0.137, "exc_max": 0.214, "sharpe_diff": 0.44, "dd_diff": -0.017}]
    detail = [{"n": 5, "seg": "2024-01-02~2024-06-28", "idx_ret": 0.14, "stk_ret": 0.04,
               "exc": -0.10, "idx_dd": -0.04, "stk_dd": -0.08}]
    md = _render(_args(), "hk / 恒指成分池 / N=5", full, roll, detail, 807,
                 pd.Timestamp("2023-07-06"), pd.Timestamp("2026-10-13"))
    assert "# Walk-forward 闸门验证" in md
    assert "## 一、全区间口径" in md and "## 二、滚动窗口验证" in md and "## 三、滚动窗口明细" in md
    assert "| 5 |" in md                      # 各表都有该 N 的行
    assert "72.4%" in md                      # 胜率
    assert "2024-01-02~2024-06-28" in md
    assert "## 四、边界与风险" in md
    assert "不是独立样本外" in md


def test_render_marks_missing_metrics():
    """指标缺失（空 dict）应渲染为 —，而不是伪造 0。"""
    md = _render(_args(), "hk", [], [{"n": 3, "n_win": 2, "win_rate": 0.0,
                                      "exc_mean": 0.0, "exc_med": 0.0, "exc_min": 0.0,
                                      "exc_max": 0.0, "sharpe_diff": 0.0, "dd_diff": 0.0}],
                 [{"n": 3, "seg": "2024-01-02~2024-06-28", "idx_ret": None, "stk_ret": None,
                   "exc": 0.0, "idx_dd": None, "stk_dd": None}], 10,
                 pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-10"))
    assert "| 3 | 2024-01-02~2024-06-28 | — | — |" in md
