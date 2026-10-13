"""策略适配性诊断测试：趋势/震荡判别、成交额单位、一手门槛、打分单调性。"""

import numpy as np
import pandas as pd
import pytest

from scripts.quantrisk import fit
from scripts.quantrisk.fit import _score_span, analyze_fit, calc_adx_series, efficiency_ratio


def _mk(prices, volume=1_000_000, start="2025-01-01"):
    idx = pd.bdate_range(start, periods=len(prices))
    return pd.DataFrame({
        "open": prices, "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices], "close": prices,
        "volume": [volume] * len(prices),
    }, index=idx)


def test_efficiency_ratio_bounds():
    """ER：直线走势 → 接近 1；来回震荡 → 接近 0。"""
    line = _mk(list(np.linspace(10, 20, 300)))["close"]
    zig = _mk(list(10 + 2 * np.sin(np.arange(300) * 0.5)))["close"]
    assert efficiency_ratio(line) > 0.7
    assert efficiency_ratio(zig) < 0.2


def test_adx_higher_in_trend():
    """ADX：单边趋势应高于震荡行情。"""
    up = _mk(list(np.linspace(10, 25, 300)))
    zig = _mk(list(10 + 2 * np.sin(np.arange(300) * 0.5)))
    adx_up = calc_adx_series(up["high"], up["low"], up["close"]).dropna().tail(250).mean()
    adx_zig = calc_adx_series(zig["high"], zig["low"], zig["close"]).dropna().tail(250).mean()
    assert adx_up > adx_zig


def test_trend_stock_unsuitable_for_grid():
    """强趋势（高漂移 + 中等噪音）→ 判不适合网格，且趋势视角为趋势型。

    漂移需足够强：日漂移 0.8% / 噪音 1.5% 使 |IR| 远超 0.5 阈值，
    否则随机性会把合成序列拉进"偏趋势"灰区（这正是 ER 主判据失效的那类情形）。
    """
    rng = np.random.default_rng(7)
    prices = list(10 * np.cumprod(1 + rng.normal(0.008, 0.015, 400)))
    res = analyze_fit(_mk(prices), "TEST", "趋势股", "A股")
    assert abs(res.features["ir"]) >= 0.5, f"测试序列 IR 不够强：{res.features['ir']:.3f}"
    assert res.scores["total"] < 45
    assert "不适合" in res.verdict_grid
    assert "趋势型" in res.verdict_trend


def test_choppy_stock_suitable_for_grid():
    """纯震荡（无净位移、路径曲折）→ 判适合网格，趋势视角非趋势型。"""
    rng = np.random.default_rng(2)
    prices = list(10 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))))   # 随机游走：净位移随机但路径曲折
    # 强制回到起点附近制造纯震荡
    prices = prices + (10 - prices[-1]) * np.linspace(0, 1, len(prices))
    res = analyze_fit(_mk(prices), "TEST", "震荡股", "A股")
    assert res.scores["total"] > 45
    assert "非趋势型" in res.verdict_trend


def test_amount_unit_a_share_multiplied_by_100():
    """A股 volume 单位=手 → 成交额须 ×100；港股不乘。"""
    px = 10.0
    df = _mk([px] * 200, volume=100_000)          # 10万股 = 1000 手... 即 volume=100000 手
    a = analyze_fit(df, "000001", "A", "A股")
    h = analyze_fit(df, "00001", "H", "港股")
    assert a.features["amount_60d"] == pytest.approx(px * 100_000 * 100)
    assert h.features["amount_60d"] == pytest.approx(px * 100_000)


def test_lot_cost_gate_blocks_expensive_stock():
    """高价股：一手金额超过每格预算 → 门槛不满足 + 适配度腰斩 + 建议最低本金。"""
    df = _mk([1400.0] * 200)                       # 1400 元/股 → 一手 14 万
    res = analyze_fit(df, "600519", "高价股", "A股", initial_cash=100_000)
    f = res.features
    assert not f["lot_ok"]
    assert f["lot_cost"] == pytest.approx(140_000)
    assert f["min_cash_needed"] > 1_000_000
    assert "资金门槛" in res.verdict_grid
    assert any("资金门槛" in r for r in res.reasons)


def test_cheap_liquid_stock_passes_gate():
    """低价股：一手几百元 → 门槛满足。"""
    df = _mk([5.0] * 200, volume=5_000_000)
    res = analyze_fit(df, "002340", "低价股", "A股", initial_cash=100_000)
    assert res.features["lot_ok"]
    assert "✓" in " ".join(res.reasons)


def test_score_span_clipping():
    """打分线性映射与截断。"""
    assert _score_span(0.0, 0.0, 1.0, 10.0) == 0.0
    assert _score_span(1.0, 0.0, 1.0, 10.0) == 10.0
    assert _score_span(0.5, 0.0, 1.0, 10.0) == pytest.approx(5.0)
    assert _score_span(-5.0, 0.0, 1.0, 10.0) == 0.0
    assert _score_span(99.0, 0.0, 1.0, 10.0) == 10.0


def test_ir_drives_regime_score():
    """趋势强度 |IR| 越大 → 震荡属性分越低（网格主判据）。"""
    rng = np.random.default_rng(3)
    strong = list(10 * np.cumprod(1 + rng.normal(0.006, 0.015, 400)))   # 强趋势
    flat = list(10 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))))
    flat = flat + (10 - flat[-1]) * np.linspace(0, 1, len(flat))        # 无净位移
    s_strong = analyze_fit(_mk(strong), "T1", "强趋势", "A股").scores["regime"]
    s_flat = analyze_fit(_mk(flat), "T2", "无方向", "A股").scores["regime"]
    assert s_flat > s_strong


def test_insufficient_data_raises():
    with pytest.raises(ValueError):
        analyze_fit(_mk([10.0] * 50), "T", "太短", "A股")


def test_report_contains_key_sections():
    rng = np.random.default_rng(9)
    prices = list(10 * np.exp(np.cumsum(rng.normal(0, 0.018, 400))))
    prices = prices + (10 - prices[-1]) * np.linspace(0, 1, len(prices))
    res = analyze_fit(_mk(prices), "000001", "测试", "A股")
    md = fit.render_fit(res)
    for kw in ("趋势强度", "适配度打分", "裁决", "同仓位买持", "一手金额", "不能对单股使用"):
        assert kw in md, f"报告缺少 {kw}"

# ── screen 模式（批量筛查）──

def _choppy(n=400, seed=1, level=10.0):
    """真正的震荡序列（OU 均值回归），供 screen 相关测试使用。"""
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = x[i - 1] + 0.05 * (0 - x[i - 1]) + rng.normal(0, 0.02)
    return list(level * np.exp(x))


def _fit_result(prices, code="000001", name="测试", market="A股", **kw):
    return analyze_fit(_mk(prices), code, name, market, **kw)


def test_summarize_keys_for_screening():
    """summarize 必须给出排序/制表所需的全部字段。"""
    res = _fit_result(_choppy(400))
    row = fit.summarize(res)
    for k in ("code", "name", "px", "ir", "ann_vol", "amount", "lot_cost", "lot_ok",
              "score", "verdict_grid", "verdict_trend", "avg_excess",
              "grid_ret", "bh_ret", "grid_lower", "grid_upper", "kind"):
        assert k in row, f"缺字段 {k}"
    assert row["grid_lower"] == pytest.approx(row["px"] * 0.80)
    assert row["grid_upper"] == pytest.approx(row["px"] * 1.20)


def test_summarize_kind_classification():
    """kind 三分类：震荡 / 混合 / 趋势。"""
    rng = np.random.default_rng(7)
    strong = list(10 * np.cumprod(1 + rng.normal(0.008, 0.015, 400)))
    assert fit.summarize(_fit_result(strong))["kind"] == "趋势"
    assert fit.summarize(_fit_result(_choppy(400, seed=3)))["kind"] in ("震荡", "混合")


def test_render_screen_has_required_sections():
    res = _fit_result(_choppy(400), code="000021", name="深科技")
    md = fit.render_screen([fit.summarize(res)], "A股", "测试池")
    for kw in ("批量策略适配性筛查", "统计", "网格候选池", "趋势型标的",
               "资金门槛不足", "使用说明", "不能对单股使用", "历史特征筛选"):
        assert kw in md, f"报告缺少 {kw}"


def test_screen_excludes_absolute_loser_from_candidates():
    """适配分达标但**网格绝对收益为负**的标的不进候选池（只靠超额会误纳）。"""
    win = fit.summarize(_fit_result(_choppy(400, seed=3), code="A", name="赢家"))
    loser = dict(win, code="B", name="亏家", score=99.0, lot_ok=True,
                 grid_ret=-0.05, avg_excess=0.02)
    md = fit.render_screen([win, loser], "A股", "池", min_score=70.0, top=5)
    cand_block = md.split("## 🔴 趋势型标的")[0]
    assert "赢家" in cand_block
    assert "亏家" not in cand_block
    assert "绝对亏损" in md


def test_screen_flags_lot_gate_violators():
    """高价股（一手超预算）应进"资金门槛不足"而不是候选池。"""
    df = _mk([1400.0] * 200)
    res = analyze_fit(df, "600519", "高价股", "A股", initial_cash=100_000)
    md = fit.render_screen([fit.summarize(res)], "A股", "池")
    assert "资金门槛不足" in md
    assert "600519" in md.split("## 🔴 资金门槛不足")[1]
