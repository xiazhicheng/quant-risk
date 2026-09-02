from datetime import date, timedelta

from scripts.quantrisk.swing import (
    daily_flow_score,
    daily_trend_score,
    intraday_segment_score,
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
    assert result["status"] == "观望：等待日线笔与30分钟线段共振"
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
    assert "缠论整体偏空" in result["status"]


def test_intraday_segment_score_direction_matches_segment_not_stroke():
    """
    Regression test (2026-08-31): 30m 线段方向应基于 segments 而非 strokes。
    工行 01398 案例：min_bi_len=4 把同一天 7 根 bar（7.55→7.53→7.57→7.55→7.56→7.55→7.56）
    识别为 down 笔，导致 classify_trend 用 strokes[-1].direction=down 判定"偏空"，
    但 segments 方向是 up。修复后结论应与 segments 方向一致（偏多）。
    """
    import asyncio
    from scripts.quantrisk.data import stock_kline_30m_async, close_async_session

    async def _run():
        r = await stock_kline_30m_async("01398", "hk", range_="60d")
        if len(r["bars"]) < 40:
            return  # skip if data unavailable
        score = intraday_segment_score(r["bars"])
        if not score.get("available"):
            return
        # 关键断言：segment 方向=up 时，结论必须偏多（不能偏空）
        assert score["direction"] == "up", f"expected segment up, got {score['direction']}"
        concl = score.get("chan_conclusion", "")
        assert "🟢偏多" in concl, f"expected 偏多 conclusion for up segment, got: {concl}"
        assert "🔴偏空" not in concl, f"BUG: up segment shows 偏空: {concl}"

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
