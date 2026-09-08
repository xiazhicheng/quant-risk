from datetime import date, timedelta

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
    assert result["status"] == "观望：等待日线趋势与30分钟小趋势共振"
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
    assert "冲突" in result["status"]


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
    assert result["status"].startswith("谨慎布局")
    assert "道氏整体偏空" in result["status"]


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
    """方案A（2026-09-01）：止损/目标按 ATR 动态，不再固定 -8%/+10%。

    低波动票（日振幅0.5%）：2ATR% 远低于 8%，止损 clamp 到 5% 下限；
    目标至少 8%，且 RR>=1.5（目标比例 >= 止损比例*1.5）。
    """
    low_vol = _bars_with_amplitude(amp=0.005)   # 日振幅 0.5%
    r = swing_sl_tp(10.0, low_vol, stroke_low=0.0)
    assert r["atr"] is not None
    assert 5.0 <= r["stop_pct"] <= 11.0
    assert r["target_pct"] >= r["stop_pct"] * 1.5
    assert r["target_pct"] >= 8.0
    assert r["target_pct"] <= 25.0
    assert r["stop_loss"] < 10.0 < r["take_profit"]


def test_swing_sl_tp_atr_high_volatility_capped():
    """高波动票（日振幅4%）：2ATR% 远超 8%，止损 clamp 到 11% 上限，目标上限 25%。"""
    high_vol = _bars_with_amplitude(amp=0.04)
    r = swing_sl_tp(10.0, high_vol, stroke_low=0.0)
    assert r["atr"] is not None
    assert 5.0 <= r["stop_pct"] <= 11.0
    assert r["target_pct"] <= 25.0
    assert r["take_profit"] > 10.0
    assert r["stop_loss"] < 10.0


def test_swing_sl_tp_fallback_without_atr():
    """ATR 缺失（日K不足）时回退固定 -8%/+10%（旧逻辑兜底）。"""
    r = swing_sl_tp(10.0, [], stroke_low=9.0)
    assert r["atr"] is None
    assert r["stop_loss"] == round(max(10 * 0.92, 9 * 0.985), 2)
    assert r["take_profit"] == 11.0


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
    assert "支撑" in score["conclusion"] and "压力" in score["conclusion"]
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
    assert result["status"].startswith("谨慎布局")
    assert "道氏整体偏空" in result["status"]
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
    assert result["status"].startswith("谨慎布局")
    assert "动能走弱" in result["status"]


def test_st_stock_blocked():
    """Q3：*ST/ST/退市 名称硬拦截，不进波段。"""
    daily = bars()
    ok_star, msg_star = swing_liquidity_filter({"c": "600000", "n": "*ST尔雅", "s": "其他", "p": 6.0}, daily)
    assert ok_star is False and "ST" in msg_star
    ok_st, _ = swing_liquidity_filter({"c": "600000", "n": "ST某某", "s": "其他", "p": 6.0}, daily)
    assert ok_st is False
    ok_retire, msg_retire = swing_liquidity_filter({"c": "600000", "n": "某某退", "s": "其他", "p": 6.0}, daily)
    assert ok_retire is False and "退" in msg_retire


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
