"""参数网格扫描工具测试：区间收益切分、约束标注、报告结构。"""
import argparse

import pandas as pd

from scripts.scan_trendgate_grid import _render, _segments


def _args(max_dd=0.20):
    return argparse.Namespace(
        commission=0.001, gate_ma=30, confirm=3, exposure=0.7,
        top_ns="3,5,10", rebalance_days="20,40,60", gates="index,stock",
        max_dd=max_dd, market="cn", slippage=0.001,
        no_limit_check=False, no_halt_check=False)


def _rows():
    return [
        {"top_n": 3, "rebalance_days": 20, "gate": "index", "total_return": 7.9512,
         "annual_return": 1.165, "max_drawdown": -0.1856, "sharpe": 2.580,
         "avg_exposure": 0.2979, "flat_ratio": 0.5846, "fills": 180,
         "seg": {"2024": 0.874, "2025": 2.3477, "前半段": 1.2289}},
        {"top_n": 3, "rebalance_days": 60, "gate": "index", "total_return": 3.9830,
         "annual_return": 0.7613, "max_drawdown": -0.2820, "sharpe": 1.948,
         "avg_exposure": 0.2996, "flat_ratio": 0.5846, "fills": 126,
         "seg": {"2024": 0.4921, "2025": 1.4157, "前半段": 0.7555}},
        {"top_n": 10, "rebalance_days": 20, "gate": "stock", "total_return": 0.5865,
         "annual_return": 0.1766, "max_drawdown": -0.2353, "sharpe": 0.768,
         "avg_exposure": 0.5054, "flat_ratio": 0.007, "fills": 821,
         "seg": {"2024": 0.271, "2025": 0.3857, "前半段": 0.1321}},
    ]


def test_segments_splits_by_year_and_halves():
    idx = pd.bdate_range("2024-01-01", periods=500)
    eq = pd.Series([100 * (1.001 ** i) for i in range(500)], index=idx)
    seg = _segments(eq)
    assert "2024" in seg and "2025" in seg          # 分年
    assert "前半段" in seg and "后半段" in seg        # 前后半段
    assert all(v > 0 for v in seg.values())         # 单调上行 → 各段为正


def test_segments_skips_single_day_year():
    idx = pd.bdate_range("2024-12-31", periods=1)
    assert _segments(pd.Series([100.0], index=idx)) == {}


def test_render_ranks_by_sharpe_and_flags_drawdown_breach():
    md = _render(_args(0.20), "cn", _rows(), pd.bdate_range("2024-01-01", periods=500))
    # 夏普 2.580 的 N=3/20日 排第一，夏普 1.948 的 60 日组合超回撤被标 ❌
    first = [l for l in md.splitlines() if l.startswith("| 1 |")][0]
    assert "3 |" in first and "20日" in first and "指数" in first
    assert "❌超回撤" in md
    assert "夏普最优" in md and "收益最优" in md and "回撤最小" in md
    assert "## 三、分年与前后半段" in md


def test_render_excludes_breaching_rows_from_recommendation():
    md = _render(_args(0.20), "cn", _rows(), pd.bdate_range("2024-01-01", periods=500))
    # 夏普最优行必须是满足约束的 N=3/20日（-18.56%），不能是超限的 60 日组合
    best = [l for l in md.splitlines() if l.startswith("- **夏普最优**")][0]
    assert "20 日" in best and "-18.56%" in best


def test_render_without_constraint_keeps_all():
    md = _render(_args(1.0), "hk", _rows(), pd.bdate_range("2024-01-01", periods=500))
    assert "❌超回撤" not in md
    assert "回撤约束" not in md


def test_render_marks_missing_metrics():
    row = {"top_n": 5, "rebalance_days": 20, "gate": "stock", "total_return": None,
           "annual_return": None, "max_drawdown": None, "sharpe": 0.0,
           "avg_exposure": None, "flat_ratio": None, "fills": 0, "seg": {}}
    md = _render(_args(1.0), "hk", [row], pd.bdate_range("2024-01-01", periods=100))
    assert "—" in md
