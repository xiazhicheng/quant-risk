from datetime import date, timedelta

from scripts.quantrisk import swing
from scripts.quantrisk.swing import (
    daily_flow_score,
    daily_trend_score,
    intraday_dow_score,
    intraday_segment_score,
    swing_liquidity_filter,
    swing_score_one,
    swing_sl_tp,
    swing_validate,
)


def bars(count=90, step=0.2, start=10.0, prefix="2026-01-01"):
    base = date.fromisoformat(prefix)
    rows = []
    for i in range(count):
        close = start + i * step
        rows.append({
            "date": (base + timedelta(days=i)).isoformat(),
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.2,
            "close": close,
            "volume": 1000 + i * 20,
        })
    return rows


def test_trend_and_flow_are_technical_only():
    daily = bars()
    trend = daily_trend_score(daily)
    flow = daily_flow_score(daily, {"flow_5d": 100000000})
    assert 0 <= trend["score"] <= 30
    assert 0 <= flow["score"] <= 25
    assert trend["direction"] == "up"
    assert "PE" not in trend["reason"]
    assert "ROE" not in flow["reason"]


def test_intraday_missing_data_cannot_be_tradable():
    daily = bars()
    result = swing_score_one({"c": "600000", "n": "测试", "s": "其他", "p": 28}, daily, [], {})
    assert result["tradable"] is False
    assert result["verdict"] == "BLOCK"
    assert result["entry_eligible"] is False
    assert "数据质量" in result["status"]
    assert result["segment"]["available"] is False


def test_intraday_direction_conflict_blocks_entry(monkeypatch):
    daily = bars()
    up_segment = {"score": 25.0, "direction": "up", "available": True, "reason": "up"}
    down_stroke = {"score": 4.0, "direction": "down", "reason": "down"}
    monkeypatch.setattr("scripts.quantrisk.swing.daily_stroke_score", lambda _: down_stroke)
    monkeypatch.setattr("scripts.quantrisk.swing.intraday_segment_score", lambda _: up_segment)
    result = swing_score_one({"c": "600000", "n": "测试", "s": "其他", "p": 28}, daily, daily, {})
    assert result["direction_conflict"] is True
    assert result["tradable"] is False
    assert result["verdict"] == "BLOCK"
    assert "数据质量" in result["status"]


def test_swing_score_components_sum_to_100():
    daily = bars()
    result = swing_score_one({"c": "600000", "n": "测试", "s": "其他", "p": 28}, daily, daily, {"flow_5d": 1e8})
    expected = sum(result[k]["score"] for k in ("trend", "flow", "stroke", "segment"))
    assert result["total"] == expected
    report = {"selection_mode": "swing", "top10": [{
        "code": result["code"], "trend_score": result["trend"]["score"],
        "flow_score": result["flow"]["score"], "stroke_score": result["stroke"]["score"],
        "segment_score": result["segment"]["score"], "total": result["total"],
    }]}
    swing_validate(report)


def test_chan_downtrend_flags_cautious_layout(monkeypatch):
    """缠论整体走势偏空时，即使短线共振也只给'谨慎布局'，杜绝自相矛盾。"""
    daily = bars()
    up_stroke = {"score": 20.0, "direction": "up", "trend_direction": "down",
                 "start_date": "2026-01-01", "end_date": "2026-01-20",
                 "reason": "最近日线笔up 2026-01-01~2026-01-20",
                 "chan_conclusion": "缠论结论：🔴偏空 | 无中枢单边下跌"}
    up_segment = {"score": 25.0, "direction": "up", "available": True,
                  "start_date": "2026-01-01", "end_date": "2026-01-20",
                  "reason": "最近30分钟线段up 2026-01-01~2026-01-20",
                  "chan_conclusion": "缠论结论：🟢偏多 | 单中枢盘整（偏多）"}
    monkeypatch.setattr("scripts.quantrisk.swing.daily_stroke_score", lambda _: up_stroke)
    monkeypatch.setattr("scripts.quantrisk.swing.intraday_segment_score", lambda _: up_segment)
    result = swing_score_one({"c": "600000", "n": "测试", "s": "其他", "p": 28}, daily, daily, {})
    assert result["tradable"] is True
    assert result["verdict"] == "BLOCK"
    assert result["entry_eligible"] is False
    assert "数据质量" in result["status"]


def test_intraday_dow_conclusion_matches_direction():
    """
    道氏 30m 趋势：direction 与 conclusion 的方向描述必须一致（不能自相矛盾）。
    用实时数据验证，数据缺失时跳过（数据诚实，不做强方向断言——行情会变）。
    """
    import asyncio
    from scripts.quantrisk.data import stock_kline_30m_async, close_async_session

    async def _run():
        r = await stock_kline_30m_async("01398", "hk", range_="60d")
        if len(r["bars"]) < 40:
            return  # skip if data unavailable
        score = intraday_dow_score(r["bars"])
        if not score.get("available"):
            return
        concl = score.get("conclusion", "")
        assert "道氏结论" in concl
        # direction 与结论方向一致
        if score["direction"] == "up":
            assert "🟢上升趋势" in concl, f"up direction shows wrong concl: {concl}"
        elif score["direction"] == "down":
            assert "🔴下降趋势" in concl, f"down direction shows wrong concl: {concl}"
        elif score["direction"] == "neutral":
            assert "🟡震荡" in concl, f"neutral direction shows wrong concl: {concl}"

    asyncio.run(_run())
    asyncio.run(close_async_session())


def _bars_with_amplitude(count=90, start=10.0, amp=0.005, prefix="2026-01-01"):
    """构造指定单日振幅的日K（用于 ATR/止损止盈测试）。amp 为相对昨收的波幅比例。"""
    base = date.fromisoformat(prefix)
    rows = []
    close = start
    for i in range(count):
        high = close * (1 + amp)
        low = close * (1 - amp)
        rows.append({
            "date": (base + timedelta(days=i)).isoformat(),
            "open": close,
            "high": high,
            "low": low,
            "close": close + (high - low) * 0.4,
            "volume": 1000 + i * 20,
        })
        close = rows[-1]["close"]
    return rows


def test_swing_sl_tp_atr_dynamic_range():
    """方案A止损（2026-09-01）+ 移动止盈替代固定目标（2026-09-08 用户明确：道氏不预测目标）。

    低波动票（日振幅0.5%）：2ATR% 远低于 8%，止损 clamp 到 5% 下限；
    移动止盈=自近期最高收盘价回撤 2ATR%（clamp 5%-11%），不输出固定目标价。
    """
    low_vol = _bars_with_amplitude(amp=0.005)   # 日振幅 0.5%
    r = swing_sl_tp(10.0, low_vol, stroke_low=0.0)
    assert r["atr"] is not None
    assert 5.0 <= r["stop_pct"] <= 11.0
    assert 5.0 <= r["trail_pct"] <= 11.0
    assert "take_profit" not in r and "target_pct" not in r   # 移动止盈无固定目标
    assert r["trail_stop"] < r["peak"]
    assert "移动止盈" in r["exit_rule"]
    assert r["stop_loss"] < 10.0


def test_swing_sl_tp_atr_high_volatility_capped():
    """高波动票（日振幅4%）：2ATR% 远超 8%，止损 clamp 到 11% 上限，移动止盈回撤同样 clamp。"""
    high_vol = _bars_with_amplitude(amp=0.04)
    r = swing_sl_tp(10.0, high_vol, stroke_low=0.0)
    assert r["atr"] is not None
    assert 5.0 <= r["stop_pct"] <= 11.0
    assert r["trail_pct"] <= 11.0
    assert r["trail_stop"] < r["peak"]    # 移动止盈=自最高收盘价回撤，必低于高点
    assert r["stop_loss"] < 10.0


def test_swing_sl_tp_fallback_without_atr():
    """ATR 缺失（日K不足）时止损回退固定 -8%，移动止盈回撤 8% 兜底。"""
    r = swing_sl_tp(10.0, [], stroke_low=9.0)
    assert r["atr"] is None
    assert r["stop_loss"] == round(max(10 * 0.92, 9 * 0.985), 2)
    assert r["trail_pct"] == 8.0
    assert "移动止盈" in r["exit_rule"]


def test_swing_sl_tp_stroke_low_raises_stop():
    """日线笔低点高于 ATR 止损时，止损抬到笔低点×0.985（结构位兜底）。"""
    low_vol = _bars_with_amplitude(amp=0.005)
    r_near = swing_sl_tp(10.0, low_vol, stroke_low=9.8)   # 笔低点贴近现价
    assert r_near["stop_loss"] == round(9.8 * 0.985, 2)
    assert r_near["stop_pct"] <= 5.0 + 1e-9


# ────────────────────────────────────────────────────────────────
# 道氏理论专项测试（2026-09-08 替代缠论）
# ────────────────────────────────────────────────────────────────
from scripts.quantrisk.swing import _find_pivots, _dow_trend, daily_dow_score, _dow_conclusion


def _wave_bars(count=120, base=10.0, prefix="2026-01-01"):
    """正弦波 K 线（振幅 ±1.5、周期约38根、微涨趋势）：产生真实波峰波谷，便于摆动点检测。"""
    import math
    from datetime import date, timedelta
    d0 = date.fromisoformat(prefix)
    rows = []
    for i in range(count):
        close = base + i * 0.05 + math.sin(i / 6.0) * 1.5
        rows.append({"date": (d0 + timedelta(days=i)).isoformat(), "open": close - 0.1,
                     "high": close + 0.4, "low": close - 0.3, "close": close, "volume": 1000})
    return rows


def test_find_pivots_detects_swings():
    rows = _wave_bars()
    pivots = _find_pivots(rows, window=3)
    assert len(pivots) >= 4
    types = {p["type"] for p in pivots}
    assert types == {"high", "low"}


def test_dow_trend_three_states():
    # 上升趋势：高点抬高、低点抬高
    up = [{"type": "low", "price": 10}, {"type": "high", "price": 12},
          {"type": "low", "price": 11}, {"type": "high", "price": 14}]
    assert _dow_trend(up)[0] == "up"
    # 下降趋势：高点走低、低点走低
    down = [{"type": "high", "price": 20}, {"type": "low", "price": 18},
            {"type": "high", "price": 17}, {"type": "low", "price": 15}]
    assert _dow_trend(down)[0] == "down"
    # 震荡：高低点交错
    neutral = [{"type": "high", "price": 20}, {"type": "low", "price": 15},
               {"type": "high", "price": 18}, {"type": "low", "price": 16}]
    assert _dow_trend(neutral)[0] == "neutral"


def test_daily_dow_score_conclusion_format():
    rows = _wave_bars()
    score = daily_dow_score(rows)
    assert 0 <= score["score"] <= 20
    assert "道氏结论" in score["conclusion"]
    assert "状态：" in score["conclusion"] and "边界：" in score["conclusion"]
    assert "方向未定" in score["conclusion"] or "抬高" in score["conclusion"] or "走低" in score["conclusion"]


def test_dow_conclusion_action_mapping():
    pivots = [{"type": "low", "price": 10}, {"type": "high", "price": 12},
              {"type": "low", "price": 11}, {"type": "high", "price": 14}]
    up = _dow_conclusion("up", "高点、低点连续抬高", pivots)
    assert "🟢上升趋势" in up and "回踩支撑企稳" in up
    down = _dow_conclusion("down", "高点、低点连续走低", pivots)
    assert "🔴下降趋势" in down and "观望" in down


def test_status_wording_is_dow(monkeypatch):
    """状态文案必须用道氏而非缠论：monkeypatch 别名仍生效（回归保护）。"""
    daily = bars()
    up_stroke = {"score": 20.0, "direction": "up", "trend_direction": "down",
                 "reason": "最近日线趋势up", "conclusion": "道氏结论：🔴下降趋势 | 高点、低点连续走低"}
    up_segment = {"score": 25.0, "direction": "up", "available": True,
                  "reason": "最近30分钟趋势up", "conclusion": "道氏结论：🟢上升趋势"}
    monkeypatch.setattr("scripts.quantrisk.swing.daily_stroke_score", lambda _: up_stroke)
    monkeypatch.setattr("scripts.quantrisk.swing.intraday_segment_score", lambda _: up_segment)
    result = swing_score_one({"c": "600000", "n": "测试", "s": "其他", "p": 28}, daily, daily, {})
    assert result["verdict"] == "BLOCK"
    assert result["entry_eligible"] is False
    assert "数据质量" in result["status"]
    assert "缠论" not in result["status"]




# ────────────────────────────────────────────────────────────────
# Q1/Q2/Q3 新增行为测试（2026-09-08 grill 后落地）
# ────────────────────────────────────────────────────────────────

def test_trend_score_breakout_can_reach_30():
    """Q1：突破近60日新高加3分，日线趋势刻度补齐到30（原上限27）。"""
    daily = bars()
    r = daily_trend_score(daily)
    assert 27.0 <= r["score"] <= 30.0
    assert r["direction"] == "up"


def test_momentum_weak_force_cautious(monkeypatch):
    """Q2：动能走弱预警强制降级为谨慎布局（滞后性纪律代码级落地）。"""
    daily = bars()
    up_stroke = {"score": 20.0, "direction": "up", "trend_direction": "up",
                 "reason": "最近日线趋势up",
                 "conclusion": "道氏结论：🟢上升趋势 | ⚠️动能走弱预警：价创新高但上涨动能收缩 | 操作：回踩支撑企稳"}
    up_segment = {"score": 25.0, "direction": "up", "available": True,
                  "reason": "最近30分钟趋势up", "conclusion": "道氏结论：🟢上升趋势"}
    monkeypatch.setattr("scripts.quantrisk.swing.daily_stroke_score", lambda _: up_stroke)
    monkeypatch.setattr("scripts.quantrisk.swing.intraday_segment_score", lambda _: up_segment)
    result = swing_score_one({"c": "600000", "n": "测试", "s": "其他", "p": 28}, daily, daily, {})
    assert result["tradable"] is True
    assert result["verdict"] == "BLOCK"
    assert result["entry_eligible"] is False
    assert "数据质量" in result["status"]


def test_st_stock_blocked():
    """Q3：*ST/ST/退市 名称硬拦截，不进波段。"""
    daily = bars()
    ok_star, msg_star = swing_liquidity_filter({"c": "600000", "n": "*ST尔雅", "s": "其他", "p": 6.0}, daily)
    assert ok_star is False and "ST" in msg_star
    ok_st, _ = swing_liquidity_filter({"c": "600000", "n": "ST某某", "s": "其他", "p": 6.0}, daily)
    assert ok_st is False
    ok_retire, msg_retire = swing_liquidity_filter({"c": "600000", "n": "某某退", "s": "其他", "p": 6.0}, daily)
    assert ok_retire is False and "退" in msg_retire


def test_suspended_stock_blocked():
    """2026-09-08 宏源证券000562案例：实时成交量为 0 的停牌/退市残留代码不进波段。"""
    daily = bars()
    ok, msg = swing_liquidity_filter(
        {"c": "000562", "n": "宏源证券", "s": "其他", "p": 30.5, "q": {"volume": 0}}, daily)
    assert ok is False and "停牌" in msg


def test_suspended_hk_stock_blocked():
    """港股 quote 字段 volume_shares=0 同样拦截。"""
    daily = bars()
    ok, msg = swing_liquidity_filter(
        {"c": "00700", "n": "测试", "s": "其他", "p": 300, "q": {"volume_shares": 0}}, daily)
    assert ok is False and "停牌" in msg


def test_suspended_detection_ignores_missing_quote():
    """quote 缺失或字段缺失时不拦截（防御误杀：停牌判定依赖行情数据）。"""
    daily = bars()
    ok, _ = swing_liquidity_filter({"c": "600000", "n": "测试", "s": "其他", "p": 28}, daily)
    assert ok is True
    ok2, _ = swing_liquidity_filter(
        {"c": "600000", "n": "测试", "s": "其他", "p": 28, "q": {"change_pct": 1.2}}, daily)
    assert ok2 is True


def test_suspended_stock_status_data_missing(monkeypatch):
    """停牌股在评分层面 tradable=False、status=数据缺失（不进入可布局语义）。"""
    daily = bars()
    up_stroke = {"score": 20.0, "direction": "up", "trend_direction": "up",
                 "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    up_segment = {"score": 25.0, "direction": "up", "available": True,
                  "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    monkeypatch.setattr("scripts.quantrisk.swing.daily_stroke_score", lambda _: up_stroke)
    monkeypatch.setattr("scripts.quantrisk.swing.intraday_segment_score", lambda _: up_segment)
    monkeypatch.setattr("scripts.quantrisk.swing.daily_flow_score",
                        lambda _d, _f: {"score": 10.0, "vol_ratio": 1.5, "pct_5d": 3.0, "flow_5d": 1e8})
    result = swing_score_one({"c": "000562", "n": "宏源证券", "s": "其他", "p": 30.5, "q": {"volume": 0}},
                             daily, daily, {})
    assert result["tradable"] is False
    assert result["verdict"] == "BLOCK"
    assert "停牌" in result["status"]


def test_new_stock_warns_but_not_blocked():
    """Q3：次新股（日K<250根）警示但不阻断。"""
    daily = bars(count=100)  # 100 根 < 250
    ok, msg = swing_liquidity_filter({"c": "600000", "n": "量化派", "s": "其他", "p": 4.0}, daily)
    assert ok is True
    assert "次新股" in msg


def test_low_volume_downgrade(monkeypatch):
    """Q8：量比<1 缩量上涨强制降级为谨慎布局。"""
    daily = bars()
    up_stroke = {"score": 20.0, "direction": "up", "trend_direction": "up",
                 "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    up_segment = {"score": 25.0, "direction": "up", "available": True,
                  "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    monkeypatch.setattr("scripts.quantrisk.swing.daily_stroke_score", lambda _: up_stroke)
    monkeypatch.setattr("scripts.quantrisk.swing.intraday_segment_score", lambda _: up_segment)
    monkeypatch.setattr("scripts.quantrisk.swing.daily_flow_score",
                        lambda _d, _f: {"score": 10.0, "vol_ratio": 0.5, "pct_5d": 3.0, "flow_5d": 1e8})
    result = swing_score_one({"c": "600000", "n": "测试", "s": "其他", "p": 28}, daily, daily, {})
    assert result["tradable"] is True
    assert result["status"].startswith("谨慎布局")
    assert "缩量" in result["status"]


def test_overheated_downgrade(monkeypatch):
    """Q8：5日涨幅>25% 透支降级为谨慎布局。"""
    daily = bars()
    up_stroke = {"score": 20.0, "direction": "up", "trend_direction": "up",
                 "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    up_segment = {"score": 25.0, "direction": "up", "available": True,
                  "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    monkeypatch.setattr("scripts.quantrisk.swing.daily_stroke_score", lambda _: up_stroke)
    monkeypatch.setattr("scripts.quantrisk.swing.intraday_segment_score", lambda _: up_segment)
    monkeypatch.setattr("scripts.quantrisk.swing.daily_flow_score",
                        lambda _d, _f: {"score": 10.0, "vol_ratio": 1.5, "pct_5d": 30.0, "flow_5d": 1e8})
    result = swing_score_one({"c": "600000", "n": "测试", "s": "其他", "p": 28}, daily, daily, {})
    assert result["status"].startswith("谨慎布局")
    assert "透支" in result["status"]


def test_dow_conclusion_boundary_format():
    """用户原则（2026-09-08）：道氏结论=定性方向+状态描述+明确边界（前低/前高切换条件），不预测价格。"""
    pivots = [{"type": "high", "price": 14.26, "date": "d1"}, {"type": "low", "price": 12.14, "date": "d2"}]
    c = _dow_conclusion("up", "高点、低点连续抬高", pivots, price=13.93)
    assert "🟢上升趋势" in c
    assert "状态：高点、低点连续抬高" in c
    assert "边界：" in c
    assert "跌破前低12.14转空" in c and "突破前高14.26延续" in c


def test_score_brief_extraction():
    """推荐结论表「评分要点」列：从各维度 reason 提取简短要点。"""
    from scripts.quantrisk.swing import _score_brief
    t = _score_brief({"reason": "MA5/10/20/60=13.14/12.81/12.43/12.28，4条均线之上，MACD柱+0.3439"}, "trend")
    assert t == "4线之上MACD+0.34"
    f = _score_brief({"reason": "5日涨跌+12.61%，量比2.78x，主力5日+0.23亿"}, "flow")
    assert f == "量比2.78/主力+0.23亿"
    s = _score_brief({"reason": "最近日线趋势up（摆动点：高点/低点序列）", "direction": "up"}, "stroke")
    assert s == "up"


def test_render_swing_report_score_brief_column():
    """推荐结论表必须带「评分要点」列，分数可溯源。"""
    report = {"date": "2026-09-08", "market": "hk", "selection_mode": "swing",
              "top10": [{"rank": 1, "code": "00317", "name": "中船防务", "trend_score": 27.0, "flow_score": 20.0,
                         "stroke_score": 20.0, "segment_score": 25.0, "total": 92.0, "advice": "🟡谨慎布局"}],
              "details": [{"code": "00317", "name": "中船防务", "rank": 1, "status": "谨慎布局：上升趋势但动能走弱",
                           "price": 13.93, "total": 92.0, "stop_loss": 13.21, "take_profit": 15.19,
                           "stop_pct": 5.2, "target_pct": 9.0, "atr": 0.42,
                           "trend": {"reason": "MA5/10/20/60=13.14/12.81/12.43/12.28，4条均线之上，MACD柱+0.3439"},
                           "flow": {"reason": "5日涨跌+12.61%，量比2.78x，主力5日+0.23亿"},
                           "stroke": {"reason": "最近日线趋势up（摆动点：高点/低点序列）", "direction": "up"},
                           "segment": {"reason": "最近30分钟趋势up（摆动点：高点/低点序列）", "direction": "up"}}],
              "summary": [], "sectors": []}
    text = swing.render_swing_report(report, "hk")
    assert "评分要点" in text
    assert "4线之上MACD+0.34" in text and "量比2.78/主力+0.23亿" in text


def test_entry_exit_conditions_cautious():
    """上车/离场条件（2026-09-10 用户确认）：谨慎布局必须翻译成触发价清单，卖出条件完整列出。"""
    from scripts.quantrisk.swing import _entry_exit_conditions
    r = {"price": 220.78, "status": "谨慎布局：上升趋势但动能走弱",
         "trend": {"ma5": 211.49, "ma10": 198.78},
         "stroke": {"low": 179.91, "direction": "up"},
         "peak": 222.30, "stop_loss": 196.49, "stop_pct": 11.0,
         "exit_rule": "移动止盈：跌破前低179.91或自高点222.30回撤11.0%离场"}
    entry, exit_line = _entry_exit_conditions(r)
    assert "回踩 198.78-211.49（MA5/MA10）" in entry      # 回踩带
    assert "现价220.78勿追" in entry                       # 勿追警示
    assert "放量突破 222.30 介入" in entry                 # 突破确认
    assert "跌破止损 196.49（-11.0%）无条件离场" in exit_line  # 止损
    assert "跌破前低179.91" in exit_line                    # 移动止盈·破前低
    assert "自高点222.30回撤11.0%" in exit_line             # 移动止盈·回撤
    assert "持仓3-5日缩量滞涨减仓" in exit_line             # 缩量滞涨纪律


def test_entry_exit_conditions_watch_and_allow():
    """观望=突破确认再介入；当前可布局=现价分批介入。"""
    from scripts.quantrisk.swing import _entry_exit_conditions
    watch = {"price": 14.51, "status": "观望：日线趋势与30分钟趋势冲突",
             "trend": {"ma5": 14.13, "ma10": 13.27}, "stroke": {"low": 11.54},
             "peak": 14.62, "stop_loss": 12.91, "stop_pct": 11.0, "exit_rule": "移动止盈"}
    e, x = _entry_exit_conditions(watch)
    assert e.startswith("放量突破 14.62 确认后再介入")
    assert "现价14.51勿追" in e
    allow = {"price": 13.93, "status": "当前可布局", "trend": {"ma5": 13.5, "ma10": 13.2},
             "stroke": {"low": 12.9}, "peak": 14.0, "stop_loss": 13.21, "stop_pct": 5.2, "exit_rule": "移动止盈"}
    e2, _ = _entry_exit_conditions(allow)
    assert "现价 13.93 附近分批介入" in e2
    assert "回踩 13.20-13.50（MA5/MA10）" in e2


def test_render_swing_report_entry_exit_lines():
    """每日报告逐只信号必须含上车/离场两行（2026-09-10 用户确认：状态要可执行）。"""
    report = {"date": "2026-09-10", "market": "cn", "selection_mode": "swing",
              "top10": [{"rank": 1, "code": "603083", "name": "剑桥科技", "trend_score": 27.0, "flow_score": 17.0,
                         "stroke_score": 20.0, "segment_score": 25.0, "total": 89.0, "advice": "🟡谨慎布局"}],
              "details": [{"code": "603083", "name": "剑桥科技", "rank": 1,
                           "status": "谨慎布局：上升趋势但动能走弱",
                           "price": 220.78, "total": 89.0, "stop_loss": 196.49, "stop_pct": 11.0,
                           "atr": 13.12, "peak": 222.30, "exit_rule": "移动止盈：跌破前低179.91或自高点222.30回撤11.0%离场",
                           "trend": {"reason": "MA5/10/20/60=211.49/198.78/190.70/188.82，4条均线之上，MACD柱+8.5762",
                                     "ma5": 211.49, "ma10": 198.78},
                           "flow": {"reason": "5日涨跌+18.56%，量比1.22x，主力5日+9.49亿", "vol_ratio": 1.22},
                           "stroke": {"reason": "最近日线趋势up（收盘价摆动点，高点/低点序列）", "direction": "up",
                                      "low": 179.91, "conclusion": "道氏结论：🟢上升趋势"},
                           "segment": {"reason": "最近30分钟趋势up（收盘价摆动点，高点/低点序列）", "direction": "up"},
                           "health": {"note": "上涨量能持平"}, "stage": "公众参与", "stage_note": "趋势中段",
                           "dow_step3": "未跌破前低179.91（收盘价确认），趋势延续", "index_sync": {"note": "方向同步✅"}}],
              "summary": [], "sectors": []}
    text = swing.render_swing_report(report, "cn")
    assert "📌 **上车条件**：回踩 198.78-211.49（MA5/MA10） 企稳（现价220.78勿追）｜放量突破 222.30 介入" in text
    assert "🚪 **离场条件**：跌破止损 196.49（-11.0%）无条件离场" in text
    assert "跌破前低179.91" in text and "持仓3-5日缩量滞涨减仓" in text


# ────────────────────────────────────────────────────────────────
# 道氏三步框架测试（2026-09-08 用户框架：定方向→验健康→找信号 + 移动止盈 + 指数同步）
# ────────────────────────────────────────────────────────────────

def test_dow_health_up_wins_volume():
    """第二步·验健康：上涨放量=健康；上涨缩量=隐患（原则4 成交量确认趋势）。"""
    from scripts.quantrisk.swing import _dow_health
    base = [{"date": f"d{i}", "close": 10.0, "volume": 1000} for i in range(7)]
    up_vol = base + [{"date": f"d{i}", "close": 10.5 + i * 0.1, "volume": 2000} for i in range(5)]
    assert _dow_health(up_vol)["healthy"] is True
    shrink_vol = base + [{"date": f"d{i}", "close": 10.5 + i * 0.1, "volume": 300} for i in range(5)]
    h = _dow_health(shrink_vol)
    assert h["healthy"] is False and "缩量" in h["note"]


def test_dow_health_pullback_shrink():
    """回调缩量=健康回调；回调放量=警惕（原则4）。"""
    from scripts.quantrisk.swing import _dow_health
    up = [{"date": f"d{i}", "close": 10.0 + i * 0.2, "volume": 2000} for i in range(7)]
    pullback_shrink = up + [{"date": f"d{i}", "close": 11.2 - i * 0.1, "volume": 400} for i in range(5)]
    assert _dow_health(pullback_shrink)["healthy"] is True
    pullback_surge = up + [{"date": f"d{i}", "close": 11.2 - i * 0.1, "volume": 3000} for i in range(5)]
    h = _dow_health(pullback_surge)
    assert h["healthy"] is False and "放量" in h["note"]


def test_dow_stage_distribution_warns():
    """三阶段：缩量新高=派发迹象（强弩之末），不提示可重仓。"""
    from scripts.quantrisk.swing import _dow_stage
    closes = [10 + i * 0.05 for i in range(60)]
    closes[-1] = max(closes) + 0.5            # 收盘创新高
    daily = [{"date": f"d{i}", "close": c, "volume": 1000} for i, c in enumerate(closes)]
    stage, note = _dow_stage(daily, vol_ratio=0.5, price=closes[-1])
    assert stage == "派发" and "缩量新高" in note


def test_dow_stage_accumulation_bottom():
    """三阶段：高位回落后在底部区间放量启动=吸筹阶段。"""
    from scripts.quantrisk.swing import _dow_stage
    closes = [15.0] * 30 + [10 + i * 0.02 for i in range(30)]   # 高位回落后底部爬升（close 距60日最低近）
    daily = [{"date": f"d{i}", "close": c, "volume": 1000} for i, c in enumerate(closes)]
    stage, _ = _dow_stage(daily, vol_ratio=1.5, price=closes[-1])
    assert stage == "吸筹"


def test_build_index_sync_cn_divergence():
    """原则3·指数相互验证：上证涨深证跌=背离（sync False）；同向=同步。"""
    from scripts.quantrisk.swing import build_index_sync
    diverge = {"sh000001": {"change_pct": 0.5}, "sz399001": {"change_pct": -0.6}, "sz399006": {"change_pct": 1.2}}
    assert build_index_sync(diverge, "cn")["sync"] is False
    align = {"sh000001": {"change_pct": 0.5}, "sz399001": {"change_pct": 0.8}, "sz399006": {"change_pct": 1.2}}
    assert build_index_sync(align, "cn")["sync"] is True
    assert build_index_sync({}, "cn")["sync"] is None          # 指数缺失不降级
    hk = {"hkHSI": {"change_pct": -0.4}}
    assert build_index_sync(hk, "hk")["sync"] is None          # 港股恒指只展示


def test_index_divergence_downgrade(monkeypatch):
    """道氏原则3：指数背离→双周期共振也强制降级为谨慎布局。"""
    daily = bars()
    up_stroke = {"score": 20.0, "direction": "up", "trend_direction": "up", "low": 9.5,
                 "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    up_segment = {"score": 25.0, "direction": "up", "available": True,
                  "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    monkeypatch.setattr("scripts.quantrisk.swing.daily_stroke_score", lambda _: up_stroke)
    monkeypatch.setattr("scripts.quantrisk.swing.intraday_segment_score", lambda _: up_segment)
    monkeypatch.setattr("scripts.quantrisk.swing.daily_flow_score",
                        lambda _d, _f: {"score": 15.0, "vol_ratio": 1.5, "pct_5d": 3.0, "flow_5d": 1e8})
    stock = {"c": "600000", "n": "测试", "s": "其他", "p": 28, "q": {"volume": 1e7},
             "index_sync": {"sync": False, "note": "上证+0.5% 深证-0.6% 创业板+1.2%（背离⚠️）"}}
    result = swing_score_one(stock, daily, daily, {})
    assert result["tradable"] is True
    assert result["status"].startswith("谨慎布局")
    assert "指数不同步" in result["status"]


def test_dow_step3_breakout_check(monkeypatch):
    """第三步·找信号：以收盘价确认是否跌破前低（原则6 收盘价最重要）。"""
    daily = bars()
    up_stroke = {"score": 20.0, "direction": "up", "trend_direction": "up", "low": 9.0,
                 "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    up_segment = {"score": 25.0, "direction": "up", "available": True,
                  "reason": "up", "conclusion": "道氏结论：🟢上升趋势"}
    monkeypatch.setattr("scripts.quantrisk.swing.daily_stroke_score", lambda _: up_stroke)
    monkeypatch.setattr("scripts.quantrisk.swing.intraday_segment_score", lambda _: up_segment)
    monkeypatch.setattr("scripts.quantrisk.swing.daily_flow_score",
                        lambda _d, _f: {"score": 15.0, "vol_ratio": 1.5, "pct_5d": 3.0, "flow_5d": 1e8})
    # 现价 28 > 前低 9.0：未跌破，趋势延续
    r_hold = swing_score_one({"c": "600000", "n": "测试", "s": "其他", "p": 28, "q": {"volume": 1e7}}, daily, daily, {})
    assert "趋势延续" in r_hold["dow_step3"]
