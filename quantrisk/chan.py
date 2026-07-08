"""
quantrisk — 缠论（Chan Theory）+ 技术指标计算模块

从 SKILL.md Layer 3 + Layer 3.5 提取而成。
纯 Python 计算，零外部依赖（不需要 numpy/pandas）。

用法:
    from quantrisk.chan import chan_risk_assessment, chan_theory_full
    assessment = chan_risk_assessment(klines)
"""


# ═══════════════════════════════════════════════
# Layer 3: 技术指标层
# ═══════════════════════════════════════════════

def _ema(values: list[float], period: int) -> list[float]:
    result = [values[0]]
    k = 2 / (period + 1)
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def calc_ma(klines: list[dict], periods: list[int] = None) -> list[dict]:
    if periods is None:
        periods = [5, 10, 20, 60]
    closes = [k["close"] for k in klines]
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    result = []
    for i, k in enumerate(klines):
        row = {"date": k["date"], "close": k["close"]}
        for p in periods:
            row[f"ma{p}"] = round(sum(closes[i-p+1:i+1]) / p, 4) if i >= p-1 else None
        row["ema12"], row["ema26"] = round(ema12[i], 4), round(ema26[i], 4)
        result.append(row)
    return result


def calc_macd(klines: list[dict], fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict]:
    closes = [k["close"] for k in klines]
    dif = [round(f - s, 4) for f, s in zip(_ema(closes, fast), _ema(closes, slow))]
    dea = _ema(dif, signal)
    return [{"date": k["date"], "close": k["close"],
             "dif": round(dif[i], 4), "dea": round(dea[i], 4),
             "macd_hist": round((dif[i] - dea[i]) * 2, 4)}
            for i, k in enumerate(klines)]


def calc_rsi(klines: list[dict], periods: list[int] = None) -> list[dict]:
    if periods is None:
        periods = [6, 12, 24]
    closes = [k["close"] for k in klines]
    changes = [0.0] + [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains, losses = [max(c, 0) for c in changes], [max(-c, 0) for c in changes]
    result = []
    for i, k in enumerate(klines):
        row = {"date": k["date"], "close": k["close"]}
        for p in periods:
            if i < p:
                row[f"rsi{p}"] = None; continue
            ag, al = sum(gains[i-p+1:i+1])/p, sum(losses[i-p+1:i+1])/p
            row[f"rsi{p}"] = 100.0 if al == 0 else round(100 - 100/(1+ag/al), 2)
        result.append(row)
    return result


def calc_kdj(klines: list[dict], n: int = 9, m1: int = 3, m2: int = 3) -> list[dict]:
    k_val, d_val = 50.0, 50.0
    result = []
    for i, kline in enumerate(klines):
        if i < n - 1:
            result.append({"date": kline["date"], "close": kline["close"],
                           "k": None, "d": None, "j": None}); continue
        w = klines[i-n+1:i+1]
        hn, ln = max(i["high"] for i in w), min(i["low"] for i in w)
        rsv = (kline["close"]-ln)/(hn-ln)*100 if hn != ln else 50.0
        k_val, d_val = (1/m1)*rsv + (1-1/m1)*k_val, (1/m2)*k_val + (1-1/m2)*d_val
        result.append({"date": kline["date"], "close": kline["close"],
                       "k": round(k_val, 2), "d": round(d_val, 2), "j": round(3*k_val-2*d_val, 2)})
    return result


def calc_boll(klines: list[dict], period: int = 20, num_std: float = 2.0) -> list[dict]:
    closes = [k["close"] for k in klines]
    result = []
    for i, k in enumerate(klines):
        if i < period - 1:
            result.append({"date": k["date"], "close": k["close"],
                           "upper": None, "middle": None, "lower": None, "bandwidth": None})
            continue
        w = closes[i-period+1:i+1]
        ma, std = sum(w)/period, (sum((x-sum(w)/period)**2 for x in w)/period)**0.5
        up, lo = ma+num_std*std, ma-num_std*std
        result.append({"date": k["date"], "close": k["close"],
                       "upper": round(up, 4), "middle": round(ma, 4), "lower": round(lo, 4),
                       "bandwidth": round((up-lo)/ma*100, 2) if ma else None})
    return result


# ═══════════════════════════════════════════════
# Layer 3.5: 缠论层（Chan Theory）
# ═══════════════════════════════════════════════

def kline_contain(klines: list[dict]) -> list[dict]:
    """
    K线包含处理：向上的K线取高高（high 取 max, low 取 max），
    向下的K线取低低（high 取 min, low 取 min）。
    """
    if len(klines) < 3:
        return klines
    result = [dict(klines[0])]
    for i in range(1, len(klines)):
        curr = dict(klines[i])
        prev = result[-1]
        if len(result) >= 2:
            direction = "up" if result[-1]["high"] > result[-2]["high"] else "down"
        else:
            direction = "up" if curr["high"] > prev["high"] else "down"
        if (curr["high"] >= prev["high"] and curr["low"] <= prev["low"]) or \
           (curr["high"] <= prev["high"] and curr["low"] >= prev["low"]):
            if direction == "up":
                merged = dict(prev)
                merged["high"] = max(prev["high"], curr["high"])
                merged["low"] = max(prev["low"], curr["low"])
                merged["close"] = curr["close"] if curr["close"] > prev["close"] else prev["close"]
                merged["volume"] = prev.get("volume", 0) + curr.get("volume", 0)
                result[-1] = merged
            else:
                merged = dict(prev)
                merged["high"] = min(prev["high"], curr["high"])
                merged["low"] = min(prev["low"], curr["low"])
                merged["close"] = curr["close"] if curr["close"] < prev["close"] else prev["close"]
                merged["volume"] = prev.get("volume", 0) + curr.get("volume", 0)
                result[-1] = merged
        else:
            result.append(curr)
    return result


def find_fractals(klines: list[dict]) -> list[dict]:
    """识别顶分型和底分型。返回 [{index, type("top"/"bottom"), high, low, date}, ...]"""
    if len(klines) < 3:
        return []
    processed = kline_contain(klines)
    fractals = []
    for i in range(1, len(processed) - 1):
        prev_k, cur_k, next_k = processed[i - 1], processed[i], processed[i + 1]
        if cur_k["high"] > prev_k["high"] and cur_k["high"] > next_k["high"]:
            fractals.append({
                "index": i, "type": "top",
                "high": cur_k["high"], "low": cur_k["low"], "date": cur_k["date"],
            })
        elif cur_k["low"] < prev_k["low"] and cur_k["low"] < next_k["low"]:
            fractals.append({
                "index": i, "type": "bottom",
                "high": cur_k["high"], "low": cur_k["low"], "date": cur_k["date"],
            })
    return fractals


def build_strokes(klines: list[dict], fractals: list[dict] = None) -> list[dict]:
    """从分型序列构建笔。"""
    if fractals is None:
        fractals = find_fractals(klines)
    if len(fractals) < 2:
        return []
    filtered = [fractals[0]]
    for f in fractals[1:]:
        last = filtered[-1]
        if f["type"] == last["type"]:
            if f["type"] == "top" and f["high"] > last["high"]:
                filtered[-1] = f
            elif f["type"] == "bottom" and f["low"] < last["low"]:
                filtered[-1] = f
        else:
            filtered.append(f)
    strokes = []
    i = 0
    while i < len(filtered) - 1:
        a, b = filtered[i], filtered[i + 1]
        if a["type"] == b["type"]:
            i += 1; continue
        span = b["index"] - a["index"]
        if span < 4:
            if i + 2 < len(filtered):
                c = filtered[i + 2]
                if c["type"] != a["type"] and (c["index"] - a["index"]) >= 4:
                    i += 1; continue
            i += 1; continue
        direction = "down" if a["type"] == "top" else "up"
        strokes.append({
            "type": a["type"],
            "start_index": a["index"], "end_index": b["index"],
            "start_date": a["date"], "end_date": b["date"],
            "high": max(a["high"], b["high"]), "low": min(a["low"], b["low"]),
            "direction": direction,
        })
        i += 1
    return strokes


def build_segments(klines: list[dict], strokes: list[dict] = None) -> list[dict]:
    """从笔构建线段。"""
    if strokes is None:
        strokes = build_strokes(klines)
    if len(strokes) < 3:
        return []
    segments = []
    i = 0
    while i <= len(strokes) - 3:
        s1, s2, s3 = strokes[i], strokes[i + 1], strokes[i + 2]
        if s1["direction"] == s2["direction"] or s2["direction"] == s3["direction"]:
            i += 1; continue
        overlap_high = min(s1["high"], s2["high"], s3["high"])
        overlap_low = max(s1["low"], s2["low"], s3["low"])
        if overlap_high <= overlap_low:
            i += 1; continue
        j = i + 3
        while j < len(strokes):
            next_s = strokes[j]
            new_high = min(overlap_high, next_s["high"])
            new_low = max(overlap_low, next_s["low"])
            if new_high <= new_low:
                break
            overlap_high, overlap_low = new_high, new_low
            j += 1
        seg_direction = s1["direction"]
        seg = {
            "start_index": strokes[i]["start_index"],
            "end_index": strokes[j - 1]["end_index"],
            "start_date": strokes[i]["start_date"],
            "end_date": strokes[j - 1]["end_date"],
            "high": max(s["high"] for s in strokes[i:j]),
            "low": min(s["low"] for s in strokes[i:j]),
            "stroke_count": j - i,
            "direction": seg_direction,
        }
        segments.append(seg)
        i = j
    return segments


def find_pivots(segments: list[dict], min_overlap: int = 3) -> list[dict]:
    """从线段中识别中枢。"""
    if len(segments) < min_overlap:
        return []
    pivots = []
    i = 0
    while i <= len(segments) - min_overlap:
        hi = segments[i]["high"]
        lo = segments[i]["low"]
        count = 1
        j = i + 1
        while j < len(segments):
            new_hi = min(hi, segments[j]["high"])
            new_lo = max(lo, segments[j]["low"])
            if new_hi <= new_lo:
                break
            hi, lo = new_hi, new_lo
            count += 1
            j += 1
        if count >= min_overlap:
            pivots.append({
                "start_index": segments[i]["start_index"],
                "end_index": segments[j - 1]["end_index"],
                "start_date": segments[i]["start_date"],
                "end_date": segments[j - 1]["end_date"],
                "high": hi, "low": lo, "segment_count": count,
                "zg": hi, "zd": lo, "zz_width": round(hi - lo, 4),
            })
            i = j
        else:
            i += 1
    return pivots


def classify_trend(pivots: list[dict], segments: list[dict]) -> dict:
    """根据中枢数量识别走势类型。"""
    if not pivots:
        if segments:
            up_count = sum(1 for s in segments if s["direction"] == "up")
            down_count = len(segments) - up_count
            if up_count > down_count:
                return {"type": "uptrend", "pivot_count": 0, "direction": "up",
                        "description": "无中枢单边上涨"}
            else:
                return {"type": "downtrend", "pivot_count": 0, "direction": "down",
                        "description": "无中枢单边下跌"}
        return {"type": "unknown", "pivot_count": 0, "direction": "neutral",
                "description": "无足够数据判断"}
    if len(pivots) == 1:
        direction = "up" if segments and segments[-1]["direction"] == "up" else "down"
        return {"type": "consolidation", "pivot_count": 1, "direction": direction,
                "description": f"单中枢盘整（{'偏多' if direction=='up' else '偏空'}）"}
    first_pz = pivots[0]
    last_pz = pivots[-1]
    is_up = last_pz["high"] > first_pz["high"] and last_pz["low"] > first_pz["low"]
    if is_up:
        return {"type": "uptrend", "pivot_count": len(pivots),
                "direction": "up", "description": f"上涨趋势，含 {len(pivots)} 个中枢"}
    else:
        return {"type": "downtrend", "pivot_count": len(pivots),
                "direction": "down", "description": f"下跌趋势，含 {len(pivots)} 个中枢"}


def detect_divergence(klines: list[dict], segments: list[dict] = None,
                      strokes: list[dict] = None) -> list[dict]:
    """检测背驰：MACD 面积对比 + 力度衰减。"""
    if segments is None:
        segments = build_segments(klines)
    if not segments or len(segments) < 2:
        return []
    macd_data = calc_macd(klines)
    if not macd_data:
        return []
    macd_map = {m["date"]: m for m in macd_data}
    macd_dates = [m["date"] for m in macd_data]
    divergences = []
    for i in range(len(segments) - 1):
        s1, s2 = segments[i], segments[i + 1]
        if s1["direction"] != s2["direction"]:
            continue
        s1_start_dt = s1["start_date"]
        s1_end_dt = s1["end_date"]
        s2_start_dt = s2["start_date"]
        s2_end_dt = s2["end_date"]

        def macd_area(start_date: str, end_date: str) -> float:
            area = 0.0
            in_range = False
            for d in macd_dates:
                if d >= start_date:
                    in_range = True
                if in_range:
                    if d > end_date:
                        break
                    m = macd_map.get(d, {})
                    hist = abs(m.get("macd_hist", 0))
                    area += hist
            return area

        s1_area = macd_area(s1_start_dt, s1_end_dt)
        s2_area = macd_area(s2_start_dt, s2_end_dt)

        if s1["direction"] == "up":
            price_higher = s2["high"] > s1["high"]
            macd_weaker = s2_area < s1_area * 0.85
            if price_higher and macd_weaker:
                severity = "strong" if s2_area < s1_area * 0.5 else "weak"
                divergences.append({
                    "type": "top_divergence", "date": s2["end_date"], "severity": severity,
                    "detail": f"顶背驰：{'强' if severity=='strong' else '弱'}，MACD 面积从 {s1_area:.1f} 衰减至 {s2_area:.1f}",
                })
        else:
            price_lower = s2["low"] < s1["low"]
            macd_weaker = s2_area < s1_area * 0.85
            if price_lower and macd_weaker:
                severity = "strong" if s2_area < s1_area * 0.5 else "weak"
                divergences.append({
                    "type": "bottom_divergence", "date": s2["end_date"], "severity": severity,
                    "detail": f"底背驰：{'强' if severity=='strong' else '弱'}，MACD 面积从 {s1_area:.1f} 衰减至 {s2_area:.1f}",
                })
    return divergences


def find_buy_sell_points(klines: list[dict], pivots: list[dict] = None,
                          segments: list[dict] = None,
                          divergences: list[dict] = None) -> dict:
    """
    缠论三类买卖点定位。
    返回 {"buy_points": [...], "sell_points": [...]}
    """
    if segments is None:
        segments = build_segments(klines)
    if pivots is None:
        pivots = find_pivots(segments)
    if divergences is None:
        divergences = detect_divergence(klines, segments)
    result = {"buy_points": [], "sell_points": []}
    if not klines or len(klines) < 10:
        return result
    last_price = klines[-1]["close"]

    for d in divergences:
        if d["type"] == "bottom_divergence":
            result["buy_points"].append({
                "type": "first_buy", "level": "strong" if d["severity"] == "strong" else "weak",
                "price": last_price, "detail": f"一买（{d['detail']}）",
            })
    for d in divergences:
        if d["type"] == "top_divergence":
            result["sell_points"].append({
                "type": "first_sell", "level": "strong" if d["severity"] == "strong" else "weak",
                "price": last_price, "detail": f"一卖（{d['detail']}）",
            })

    if pivots and segments:
        last_pivot = pivots[-1]
        if last_price > last_pivot["zg"]:
            result["buy_points"].append({
                "type": "third_buy", "level": "potential", "price": last_price,
                "detail": f"价格 {last_price} 位于中枢上方 {last_pivot['zg']}，回踩不入中枢则构成三买",
            })
        elif last_price < last_pivot["zd"]:
            if result["buy_points"]:
                first_buy_price = result["buy_points"][0].get("price", last_price)
                if last_price <= first_buy_price * 1.03:
                    result["buy_points"].append({
                        "type": "second_buy", "level": "potential", "price": last_price,
                        "detail": f"二买试探：一买后回调不创新低，当前 {last_price}",
                    })
        if pivots and segments and len(segments) >= 3:
            last_pivot = pivots[-1]
            if last_price < last_pivot["zd"]:
                result["sell_points"].append({
                    "type": "third_sell", "level": "potential", "price": last_price,
                    "detail": f"三卖警示：价格 {last_price} 跌破中枢下沿 {last_pivot['zd']}，反弹不回中枢则确认三卖",
                })
    return result


def chan_theory_full(klines: list[dict], min_stroke_span: int = 4) -> dict:
    """
    缠论全流程计算：包含处理 → 分型 → 笔 → 线段 → 中枢 → 背驰 → 买卖点。
    返回完整结构。
    """
    if not klines or len(klines) < 10:
        return {"error": "K线数据不足（至少 10 根）"}
    klines_clean = kline_contain(klines)
    fractals = find_fractals(klines)
    strokes = build_strokes(klines, fractals)
    segments = build_segments(klines, strokes)
    pivots = find_pivots(segments)
    divergences = detect_divergence(klines, segments, strokes)
    buy_sell = find_buy_sell_points(klines, pivots, segments, divergences)
    trend = classify_trend(pivots, segments)
    return {
        "klines_count": len(klines),
        "klines_clean_count": len(klines_clean),
        "fractals_count": len(fractals),
        "fractals": fractals,
        "strokes_count": len(strokes),
        "strokes": strokes,
        "segments_count": len(segments),
        "segments": segments,
        "pivots_count": len(pivots),
        "pivots": pivots,
        "divergences_count": len(divergences),
        "divergences": divergences,
        "buy_sell_points": buy_sell,
        "trend": trend,
        "current_price": klines[-1]["close"] if klines else None,
    }


def chan_risk_assessment(klines: list[dict]) -> dict:
    """
    基于缠论输出风控评估结论：
    - 当前走势类型
    - 背驰信号
    - 买卖点区域
    - 中枢位置
    - 综合评分
    """
    result = chan_theory_full(klines)
    if "error" in result:
        return result
    trend = result["trend"]
    pivots = result["pivots"]
    divergences = result["divergences"]
    buy_sell = result["buy_sell_points"]
    price = result["current_price"]

    relative_position = "unknown"
    distance_to_pivot = None
    if pivots:
        last_pz = pivots[-1]
        if price > last_pz["zg"]:
            relative_position = "above_pivot"
            distance_to_pivot = round((price - last_pz["zg"]) / last_pz["zg"] * 100, 2)
        elif price < last_pz["zd"]:
            relative_position = "below_pivot"
            distance_to_pivot = round((price - last_pz["zd"]) / last_pz["zd"] * 100, 2)
        else:
            relative_position = "within_pivot"
            distance_to_pivot = 0.0

    risk_signals = []
    for d in divergences:
        if d["type"] == "top_divergence":
            risk_signals.append({"signal": "bearish_divergence", "severity": d["severity"], "detail": d["detail"]})
        elif d["type"] == "bottom_divergence":
            risk_signals.append({"signal": "bullish_divergence", "severity": d["severity"], "detail": d["detail"]})
    if buy_sell.get("buy_points"):
        for bp in buy_sell["buy_points"]:
            risk_signals.append({"signal": f"{bp['type']}", "severity": bp.get("level", "potential"), "detail": bp["detail"]})
    if buy_sell.get("sell_points"):
        for sp in buy_sell["sell_points"]:
            risk_signals.append({"signal": f"{sp['type']}", "severity": sp.get("level", "potential"), "detail": sp["detail"]})
    if relative_position == "above_pivot":
        risk_signals.append({"signal": "above_pivot", "severity": "bullish",
                             "detail": f"价格位于中枢上方 {distance_to_pivot}%，偏强"})
    elif relative_position == "below_pivot":
        risk_signals.append({"signal": "below_pivot", "severity": "bearish",
                             "detail": f"价格位于中枢下方 {distance_to_pivot}%，偏弱"})
    else:
        risk_signals.append({"signal": "within_pivot", "severity": "neutral",
                             "detail": "价格在中枢内震荡，等待方向选择"})

    score = 0
    if trend["direction"] == "up":
        score += 2
    elif trend["direction"] == "down":
        score -= 2
    if relative_position == "above_pivot":
        score += 1
    elif relative_position == "below_pivot":
        score -= 1
    bull_div = sum(1 for d in divergences if d["type"] == "bottom_divergence")
    bear_div = sum(1 for d in divergences if d["type"] == "top_divergence")
    score += bull_div * 3 - bear_div * 3

    if score >= 3:
        chan_verdict = "偏多"
    elif score <= -3:
        chan_verdict = "偏空"
    else:
        chan_verdict = "中性"

    return {
        "trend": trend,
        "relative_position": relative_position,
        "distance_to_pivot_pct": distance_to_pivot,
        "risk_signals": risk_signals,
        "chan_score": score,
        "chan_verdict": chan_verdict,
        "pivots": pivots,
        "strokes_count": result["strokes_count"],
        "segments_count": result["segments_count"],
        "divergences": divergences,
        "buy_sell_points": buy_sell,
    }


__all__ = [
    # 技术指标
    "_ema", "calc_ma", "calc_macd", "calc_rsi", "calc_kdj", "calc_boll",
    # 缠论
    "kline_contain", "find_fractals", "build_strokes", "build_segments",
    "find_pivots", "classify_trend", "detect_divergence",
    "find_buy_sell_points", "chan_theory_full", "chan_risk_assessment",
]
