"""tests for scripts/jev_advice.py 纯函数（不触网、不依赖 API key）。"""
import pytest

from scripts.jev_advice import build_state, build_questions, _direction_label, local_dow_action

HOLDINGS = [
    {"code": "002640", "market": "cn", "shares": 3000, "avg_cost": 3.702},
    {"code": "02460", "market": "hk", "shares": 6800, "avg_cost": 9.492},
]

RESULTS = [
    {
        "code": "002640", "name": "跨境通", "price": 3.77, "total": 82.0,
        "status": "观望：日线趋势与30分钟趋势冲突",
        "stroke": {"direction": "neutral", "conclusion": "道氏结论：🟡震荡 | 边界：跌破前低3.24转空、突破前高3.87延续"},
        "segment": {"direction": "up", "conclusion": "道氏结论：🟢上升趋势"},
        "health": {"note": "上涨放量，趋势健康"},
        "flow": {"vol_ratio": 2.49, "flow_5d": 2.05e8},
        "stage": "吸筹", "stage_note": "底部区域放量启动（吸筹阶段）",
        "stop_loss": 3.39, "exit_rule": "移动止盈：自高点3.77回撤9.0%离场",
        "profile_extra": {"finance": {"roe": 32.08, "revenue_yoy": -2.5},
                          "business_mix": [{"item": "电子商务行业", "ratio": 97.0, "gross_margin": 10.3}],
                          "conception": {"boards": ["跨境电商", "拼多多概念"]}},
    },
    {
        "code": "02460", "name": "华润饮料", "price": 7.24, "total": 23.0,
        "status": "禁止开仓：关键行情数据质量=MISSING",
        "stroke": {"direction": "down", "conclusion": "道氏结论：🔴下降趋势"},
        "segment": {"direction": "neutral", "conclusion": "道氏结论：🟡震荡"},
        "health": {"note": "上涨缩量（强弩之末隐患）"},
        "flow": {"vol_ratio": 0.76, "flow_5d": None},
        "stage": "吸筹", "stage_note": "底部区域（尚未放量，观望）",
        "stop_loss": 6.89, "exit_rule": "移动止盈：自高点7.54回撤5.0%离场",
        "profile_extra": {},
    },
]


def test_direction_label():
    assert _direction_label({"stroke": {"direction": "up"}}, "stroke") == "上升"
    assert _direction_label({"stroke": {"direction": "down"}}, "stroke") == "下降"
    assert _direction_label({}, "stroke") == "无"


def test_build_state_account_layer():
    state = build_state(HOLDINGS, RESULTS)
    acct = state["账户"]
    # 总市值 = 3000*3.77 + 6800*7.24 = 11310 + 49232 = 60542
    assert acct["总市值"] == pytest.approx(60542.0)
    # 总成本 = 3000*3.702 + 6800*9.492 = 11106 + 64545.6 = 75651.6（注意 9.492*6800=64545.6）
    assert acct["总成本"] == pytest.approx(11106.0 + 64545.6)
    # 华润是 TOP1
    assert "华润饮料" in acct["集中度TOP1"]
    assert acct["持仓数"] == 2


def test_build_state_holdings_fields():
    state = build_state(HOLDINGS, RESULTS)
    h0, h1 = state["持仓"]
    assert h0["代码"] == "002640"
    assert h0["日线道氏方向"] == "震荡"
    assert h0["30分钟道氏方向"] == "上升"
    assert h0["量比"] == 2.49
    assert h0["基本面财务"]["revenue_yoy"] == -2.5
    # 缺失数据如实缺：华润无基本面财务 → 无该 key
    assert "基本面财务" not in h1
    assert "离场规则" in h1


def test_build_questions_shape():
    q = build_questions(HOLDINGS, RESULTS)
    # 2 只持仓 × (action + confidence) + 1 组合风险 = 5
    assert len(q) == 5
    assert "002640_action" in q and "02460_action" in q
    assert "002640_confidence" in q
    assert "portfolio_risk" in q
    # Choice 与 Score 类型可被 typesafe_sdk 识别（不触网构造即可）
    action = q["02460_action"]
    assert action.type == "choice"
    conf = q["02460_confidence"]
    assert conf.type == "score"
    assert action.criteria == {"buy": None, "hold": None, "reduce": None, "sell": None} or set(
        action.criteria) == {"buy", "hold", "reduce", "sell"}


def test_build_questions_instructions_contain_evidence():
    q = build_questions(HOLDINGS, RESULTS)
    inst = q["02460_action"].instructions
    assert "华润饮料" in inst and "02460" in inst
    assert "23" in inst or "道氏" in inst


def _mk_result(**overrides):
    r = {
        "code": "99999", "name": "测试", "price": 10.0, "total": 50.0,
        "status": "观望：等待日线趋势与30分钟小趋势共振",
        "stroke": {"direction": "neutral", "conclusion": "道氏结论：🟡震荡"},
        "segment": {"direction": "neutral", "conclusion": "道氏结论：🟡震荡"},
        "dow_step3": "方向未定或前低不足，等信号确认",
        "stage": "公众参与", "stop_loss": 9.0,
    }
    r.update(overrides)
    return r


def test_local_dow_action_downtrend_sells():
    # 日线道氏 down → sell（华润场景）
    r = _mk_result(stroke={"direction": "down", "conclusion": "道氏结论：🔴下降趋势"},
                   dow_step3="未跌破前低，趋势延续")
    action, conf, _ = local_dow_action(r, pnl_pct=-20)
    assert action == "sell"
    assert conf >= 0.8


def test_local_dow_action_break_prior_low_sells():
    r = _mk_result(status="观望：等待共振",
                   dow_step3="⚠️已跌破前低10.00（收盘价确认）→上升趋势结束，离场")
    action, _, reason = local_dow_action(r)
    assert action == "sell"


def test_local_dow_action_dual_up_buys():
    r = _mk_result(status="当前可布局",
                   stroke={"direction": "up"}, segment={"direction": "up"})
    action, conf, _ = local_dow_action(r)
    assert action == "buy"
    assert conf >= 0.8


def test_local_dow_action_conflict_reduces():
    r = _mk_result(stroke={"direction": "up"}, segment={"direction": "neutral"})
    action, _, reason = local_dow_action(r)
    assert action == "reduce"
    assert "冲突" in reason


def test_local_dow_action_dispatch_state_hold():
    # 数据质量不足（禁止开仓）→ 保守 hold
    r = _mk_result(status="禁止开仓：关键行情数据质量=MISSING，禁止新开仓")
    action, _, reason = local_dow_action(r)
    assert action == "hold"


def test_local_dow_action_distribution_reduces():
    r = _mk_result(stage="派发")
    action, _, reason = local_dow_action(r)
    assert action == "reduce"
    assert "派发" in reason