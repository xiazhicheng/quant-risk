"""基本面门禁测试（2026-09-24 grill Q1/Q4/Q5/Q6/Q13 落地验证）。

覆盖：分市场规则评估（纯函数）、TOP10 剔除、⛔ 渲染、回测 veto 解析与分组。
"""
import json

from scripts.quantrisk.gate import evaluate_gate
from scripts.quantrisk.swing import build_swing_report, render_swing_report, swing_validate


# ── evaluate_gate：A股严规则 ──

def test_cn_veto_on_negative_profit_debt_revenue():
    gate = evaluate_gate("cn", "某某股份", {"net_profit": -3.2, "debt_ratio": 75.0,
                                            "revenue_yoy": -25.0})
    assert gate["state"] == "veto"
    assert gate["rule_set"] == "cn_strict"
    assert len(gate["reasons"]) == 3  # 三条规则同时触发全部列出


def test_cn_veto_single_trigger():
    gate = evaluate_gate("cn", "某某股份", {"net_profit": 10.0, "debt_ratio": 65.0,
                                            "revenue_yoy": -25.0})
    assert gate["state"] == "veto"
    assert "营收同比" in gate["reasons"][0]


def test_cn_pass_healthy():
    gate = evaluate_gate("cn", "某某股份", {"net_profit": 5.0, "debt_ratio": 45.0,
                                            "revenue_yoy": 12.0})
    assert gate["state"] == "pass"
    assert gate["reasons"] == []


def test_cn_missing_metrics_is_unknown_not_vetoed():
    """共识四.3：财务数据缺失 → 未评估，不硬凑、不否决（fail-open）。"""
    gate = evaluate_gate("cn", "某某股份", {"net_profit": None, "debt_ratio": None,
                                            "revenue_yoy": None})
    assert gate["state"] == "unknown"


def test_cn_partial_metrics_pass_counts_as_pass():
    gate = evaluate_gate("cn", "某某股份", {"net_profit": None, "debt_ratio": 45.0,
                                            "revenue_yoy": None})
    assert gate["state"] == "pass"  # 有指标可查且通过


def test_cn_st_name_veto_even_without_metrics():
    gate = evaluate_gate("cn", "*ST某某", {"net_profit": None, "debt_ratio": None,
                                           "revenue_yoy": None})
    assert gate["state"] == "veto"
    assert "ST/退市风险" in gate["reasons"][0]


# ── evaluate_gate：港股松规则 ──

def test_hk_loose_boundary_75_debt_passes():
    """港股 75% 负债率在 cn 会否决、在 hk 通过（Q5=C 分市场差异化）。"""
    assert evaluate_gate("hk", "某-W", {"debt_ratio": 75.0})["state"] == "pass"
    assert evaluate_gate("cn", "某股份", {"net_profit": 1.0, "debt_ratio": 75.0,
                                          "revenue_yoy": 1.0})["state"] == "veto"


def test_hk_veto_above_80():
    gate = evaluate_gate("hk", "某-W", {"debt_ratio": 85.0})
    assert gate["state"] == "veto"
    assert gate["rule_set"] == "hk_loose"


def test_hk_dirty_debt_mapping_treated_as_missing():
    """腾讯 f[74] 曾误映射 5965%/负数杠杆率 → 脏数据视为缺失，不否决不通过。"""
    assert evaluate_gate("hk", "某-W", {"debt_ratio": 5965.0})["state"] == "unknown"
    assert evaluate_gate("hk", "某-W", {"debt_ratio": -28.0})["state"] == "unknown"


# ── 金融业豁免（2026-09-24 用户确认：只豁免负债率规则） ──

def test_cn_bank_debt_ratio_exempt():
    """银行负债率 91.9% 是存款负债商业模式，不否决；豁免必须 notes 留痕。"""
    gate = evaluate_gate("cn", "浦发银行", {"net_profit": 309.5, "debt_ratio": 91.9,
                                            "revenue_yoy": 3.55})
    assert gate["state"] == "pass"
    assert gate["reasons"] == []
    assert any("金融业豁免" in n for n in gate["notes"])


def test_hk_bank_debt_ratio_exempt():
    gate = evaluate_gate("hk", "建设银行", {"debt_ratio": 91.0})
    assert gate["state"] == "pass"
    assert any("金融业豁免" in n for n in gate["notes"])


def test_financial_still_vetted_on_negative_profit():
    """豁免仅限负债率：银行净利为负照样否决（Q5 其余规则对金融业照常生效）。"""
    gate = evaluate_gate("cn", "某银行", {"net_profit": -5.0, "debt_ratio": 91.0,
                                          "revenue_yoy": 3.0})
    assert gate["state"] == "veto"
    assert any("归母净利为负" in r for r in gate["reasons"])


def test_non_financial_name_not_exempt():
    gate = evaluate_gate("cn", "某某股份", {"net_profit": 1.0, "debt_ratio": 75.0,
                                            "revenue_yoy": 1.0})
    assert gate["state"] == "veto"
    assert gate["notes"] == []


# ── build_swing_report：TOP10 剔除 ──

def _result(code, name, total, veto=False):
    r = {"code": code, "name": name, "sector": "其他", "price": 10.0, "total": total,
         "trend": {"score": total, "reason": "MA5/10/20/60=9.9/9.8/9.7/9.6，4条均线之上，MACD柱+0.30"},
         "flow": {"score": 0, "reason": "量比1.50x，主力5日+0.20亿", "vol_ratio": 1.5, "pct_5d": 3.0},
         "stroke": {"score": 0, "reason": "up", "direction": "up", "low": 9.5},
         "segment": {"score": 0, "reason": "up", "direction": "up", "available": True},
         "tradable": True, "status": "当前可布局", "error": "",
         "stop_loss": 9.0, "trail_stop": 9.5, "exit_rule": "移动止盈",
         "verdict": "ALLOW", "entry_eligible": True, "rule_hits": []}
    if veto:
        r["gate"] = {"state": "veto", "reasons": ["负债率75.0%（>70%）"], "rule_set": "cn_strict"}
        r["veto"] = True
    else:
        r["gate"] = {"state": "pass", "reasons": [], "rule_set": "cn_strict"}
        r["veto"] = False
    return r


def test_vetoed_high_score_excluded_from_top10():
    """总分更高的被否决标的不得挤掉低分通过标的进 TOP10（Q1）。"""
    high_veto = _result("600001", "否决票", 95.0, veto=True)
    low_pass = _result("600002", "通过票", 80.0, veto=False)
    report = build_swing_report("2026-09-24", [], [high_veto, low_pass], "cn")
    assert [r["code"] for r in report["top10"]] == ["600002"]
    assert [v["code"] for v in report["vetoed"]] == ["600001"]
    assert report["vetoed"][0]["reasons"] == ["负债率75.0%（>70%）"]
    swing_validate(report)  # 不得抛"门禁否决标的混入TOP10"


def test_render_shows_veto_section_and_updated_header():
    report = build_swing_report("2026-09-24", [],
                                [_result("600001", "否决票", 95.0, veto=True),
                                 _result("600002", "通过票", 80.0)], "cn")
    md = render_swing_report(report, "cn")
    assert "### ⛔ 基本面门禁否决" in md
    assert "否决票（600001）" in md
    assert "负债率75.0%（>70%）" in md
    assert "只否决不加分" in md            # 头部说明已更新
    assert "通过票（600002）" in md         # 通过票仍在推荐表
    assert "✅ 基本面门禁：通过" in md       # 逐只门禁状态行


def test_render_omits_veto_section_when_empty():
    report = build_swing_report("2026-09-24", [], [_result("600002", "通过票", 80.0)], "cn")
    assert "### ⛔ 基本面门禁否决" not in render_swing_report(report, "cn")


# ── backtest：veto 解析与分组字段 ──

def test_backtest_parser_records_veto_group(tmp_path):
    from scripts.backtest_swing import _record_from_report
    md = tmp_path / "recommend-cn-20260924-daily.md"
    md.write_text(
        "## A股波段选股推荐 | 2026-09-24\n"
        "### 推荐结论\n"
        "| 排名 | 标的 |\n|:---:|:----|\n"
        "| 1 | 通过票（600002） |\n"
        "#### 1. 通过票（600002）— 当前可布局\n"
        "**现价**：10.0 | **总分**：80.0/100 | **止损**：9.0\n"
        "### ⛔ 基本面门禁否决（只否决不加分，不进评分）\n"
        "| 标的 | 总分 | 原状态 | 否决原因 |\n"
        "|:----|:---:|:----|:----|\n"
        "| 否决票（600001） | 95.0 | 当前可布局 | 负债率75.0%（>70%） |\n"
        "### 逐只波段信号\n",
        encoding="utf-8")
    records = _record_from_report(str(md))
    assert len(records) == 2
    by_veto = {r["code"]: r for r in records}
    assert by_veto["600002"]["veto"] is False and by_veto["600002"]["total"] == 80.0
    assert by_veto["600001"]["veto"] is True
    assert by_veto["600001"]["total"] == 95.0
    assert by_veto["600001"]["status"] == "门禁否决"


def test_snapshot_rows_carry_gate_state():
    from scripts.backtest_snapshot import _rows_from_snapshot
    snap = {"as_of": "2026-09-24", "pool_mode": "amount+board", "board_of": {},
            "results": [
                {"code": "600002", "name": "通过票", "status": "当前可布局", "total": 80,
                 "verdict": "ALLOW", "gate": {"state": "pass"}},
                {"code": "600001", "name": "否决票", "status": "当前可布局", "total": 95,
                 "verdict": "ALLOW", "veto": True},
                {"code": "600003", "name": "老票", "status": "观望", "total": 60,
                 "verdict": "WATCH"},
            ]}
    rows = _rows_from_snapshot(snap, "cn")
    states = {r["code"]: r["gate"] for r in rows}
    assert states == {"600002": "pass", "600001": "veto", "600003": ""}


# ── 单股分析（analyze_swing）门禁展示面（2026-09-24 Q1 补齐） ──

def test_apply_gate_veto_caps_status_without_touching_score():
    """单股 veto 封顶「⛔门禁否决」，总分/评分不动（只否决不加分）。"""
    from scripts.analyze_swing import _apply_gate_to_result
    r = {"status": "当前可布局", "total": 88.0}
    _apply_gate_to_result(r, {"state": "veto", "reasons": ["负债率75.0%（>70%）"],
                              "notes": [], "rule_set": "cn_strict"})
    assert r["veto"] is True
    assert r["status"].startswith("⛔门禁否决")
    assert "负债率75.0%" in r["status"]
    assert r["total"] == 88.0


def test_apply_gate_pass_unknown_keep_status():
    from scripts.analyze_swing import _apply_gate_to_result
    r = {"status": "当前可布局"}
    _apply_gate_to_result(r, {"state": "pass", "reasons": [], "notes": [], "rule_set": "cn_strict"})
    assert r["veto"] is False and r["status"] == "当前可布局"
    r2 = {"status": "谨慎布局：指数不同步"}
    _apply_gate_to_result(r2, {"state": "unknown", "reasons": [], "notes": [], "rule_set": "hk_loose"})
    assert r2["veto"] is False and r2["status"] == "谨慎布局：指数不同步"


def test_entry_exit_conditions_gate_veto():
    """⛔门禁否决状态的上车条件 = 禁止新建仓/不加仓；离场条件照常（卖出归道氏/止损）。"""
    from scripts.quantrisk.swing import _entry_exit_conditions
    r = {"price": 10.0, "status": "⛔门禁否决：负债率75.0%（>70%）",
         "trend": {"ma5": 9.8, "ma10": 9.5}, "stroke": {"low": 9.0},
         "peak": 10.5, "stop_loss": 9.2, "stop_pct": 8.0, "exit_rule": "移动止盈"}
    entry, exit_line = _entry_exit_conditions(r)
    assert "禁止新建仓" in entry and "不加仓" in entry
    assert "跌破止损 9.2" in exit_line


def test_render_one_shows_gate_lines():
    """单股报告逐只门禁行：⛔否决 / ✅通过（含金融业豁免留痕）。"""
    from scripts.analyze_swing import render_one
    base = {"market": "cn", "name": "测试", "code": "600000", "price": 10.0, "total": 70.0,
            "status": "⛔门禁否决：负债率75.0%（>70%）",
            "trend": {"score": 20, "reason": "r", "ma5": 9.8, "ma10": 9.5},
            "flow": {"score": 15, "reason": "r", "vol_ratio": 1.2},
            "stroke": {"score": 15, "reason": "r", "direction": "up", "low": 9.0,
                       "conclusion": "道氏结论：🟢上升趋势"},
            "segment": {"score": 20, "reason": "r", "direction": "up", "available": True,
                        "conclusion": "道氏结论：🟢上升趋势"},
            "health": {"note": "健康"}, "index_sync": {"note": "同步"},
            "intraday_count": 100, "dow_step3": "趋势延续", "stage": "公众参与",
            "stage_note": "", "stop_loss": 9.2, "stop_pct": 8.0, "exit_rule": "移动止盈",
            "peak": 10.5, "error": "", "direction_conflict": False,
            "gate": {"state": "veto", "reasons": ["负债率75.0%（>70%）"], "notes": []}}
    out = render_one(base)
    assert "⛔ **基本面门禁：否决" in out
    assert "禁止新建仓" in out
    base["gate"] = {"state": "pass", "reasons": [],
                    "notes": ["金融业豁免负债率规则（91.9%>70% 不作否决）"]}
    base["status"] = "当前可布局"
    out2 = render_one(base)
    assert "✅ 基本面门禁：通过" in out2 and "金融业豁免" in out2
