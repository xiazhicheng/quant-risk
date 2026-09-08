"""纯技术波段选股：日线趋势/量价/笔 + 30分钟线段。

该模块不读取基本面字段，也不调用周线缠论（2026-09-08 起方向判定改用道氏理论）。评分面向持有几天至 1-2 周。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "", "-") else default
    except (TypeError, ValueError):
        return default


def swing_liquidity_filter(stock: Dict[str, Any], daily: List[Dict]) -> tuple[bool, str]:
    """只检查可交易性，不读取 PE/ROE/营收/净利等基本面。"""
    price = _num(stock.get("p") or stock.get("price"))
    if price <= 0:
        return False, "价格数据缺失或无效"
    if not daily or len(daily) < 60:
        return False, f"日K数据不足（{len(daily)}根，至少60根）"
    closes = [_num(x.get("close")) for x in daily[-20:]]
    if any(x <= 0 for x in closes):
        return False, "日K存在无效收盘价"
    volumes = [_num(x.get("volume")) for x in daily[-20:]]
    if sum(volumes) <= 0:
        return False, "成交量数据缺失"
    # ST/*ST/退市风险股硬拦截（*ST 以 * 开头，startswith("ST") 会漏，必须用 in 判断）
    name = str(stock.get("n") or stock.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        return False, "ST/退市风险股，波段不参与"
    # 次新股警示：上市不足一年（约250个交易日），趋势/ATR参考价值有限，不阻断
    if len(daily) < 250:
        return True, "次新股警示：上市不足1年，趋势与ATR参考价值有限"
    return True, ""


def daily_trend_score(daily: List[Dict]) -> Dict[str, Any]:
    from scripts.quantrisk.indicators import calc_ma, calc_macd
    if len(daily) < 60:
        return {"score": 0.0, "direction": "", "reason": "日K数据缺失"}
    ma = calc_ma(daily, [5, 10, 20, 60])
    macd = calc_macd(daily)
    last = ma[-1] if ma else {}
    close = _num(daily[-1].get("close"))
    m5, m10, m20, m60 = (_num(last.get(k)) for k in ("ma5", "ma10", "ma20", "ma60"))
    score = 0.0
    if m5 > m10 > m20 > m60: score += 14
    elif m5 > m20 > m60: score += 10
    elif m5 > m20: score += 6
    elif m5 < m10 < m20 < m60: score -= 10
    elif m5 < m20 < m60: score -= 7
    else: score -= 2
    above = sum(close > x for x in (m5, m10, m20, m60) if x > 0)
    score += {4: 8, 3: 5, 2: 2, 1: -2, 0: -5}.get(above, 0)
    hist = _num(macd[-1].get("macd_hist")) if macd else 0
    score += 5 if hist > 0 else -4
    direction = "up" if score >= 16 else ("down" if score <= 10 else "neutral")
    # 突破加分：价格创近60日新高时 +3（补满 30 分刻度，同时是道氏突破确认信号）
    if direction == "up":
        recent_highs = [_num(x.get("high")) for x in daily[-60:]]
        if recent_highs and close >= max(recent_highs):
            score += 3
    score = max(0.0, min(30.0, score))
    return {"score": round(score, 1), "direction": direction,
            "ma5": round(m5, 2), "ma10": round(m10, 2), "ma20": round(m20, 2), "ma60": round(m60, 2),
            "above_count": above, "macd_hist": round(hist, 4),
            "reason": f"MA5/10/20/60={m5:.2f}/{m10:.2f}/{m20:.2f}/{m60:.2f}，{above}条均线之上，MACD柱{hist:+.4f}"}


def daily_flow_score(daily: List[Dict], flow: Optional[Dict] = None) -> Dict[str, Any]:
    if len(daily) < 10:
        return {"score": 0.0, "reason": "日K数据缺失"}
    recent = sum(_num(x.get("volume")) for x in daily[-5:])
    prior = sum(_num(x.get("volume")) for x in daily[-10:-5])
    ratio = recent / prior if prior > 0 else 0
    c5, c0 = _num(daily[-6].get("close")), _num(daily[-1].get("close"))
    pct5 = (c0 - c5) / c5 * 100 if c5 > 0 else 0
    score = 8.0
    score += 6 if ratio >= 1.5 and pct5 > 0 else (3 if ratio >= 1.1 and pct5 > 0 else -3 if pct5 < 0 else 0)
    net = _num((flow or {}).get("flow_5d"))
    score += 6 if net > 0 else -3 if net < 0 else 0
    score = max(0.0, min(25.0, score))
    return {"score": round(score, 1), "vol_ratio": round(ratio, 2), "pct_5d": round(pct5, 2),
            "flow_5d": net, "reason": f"5日涨跌{pct5:+.2f}%，量比{ratio:.2f}x，主力5日{net/1e8:+.2f}亿"}


def _last_direction(items: List[Dict]) -> str:
    if not items:
        return ""
    return str(items[-1].get("direction", "")).lower()


# ────────────────────────────────────────────────────────────────
# 道氏理论趋势判定（2026-09-08 替代缠论，用户看不懂缠论术语）
# 核心逻辑：摆动点（枢轴）序列 → 道氏三句话判趋势（高点抬高+低点抬高=升势）
# ────────────────────────────────────────────────────────────────

def _find_pivots(klines: List[Dict], window: int = 3) -> List[Dict]:
    """摆动高低点（枢轴检测）：klines[i] 是 [i-window, i+window] 内最高→high pivot，最低→low pivot。
    相当于缠论『笔』的简化版，但规则直观：左右各 N 根 K 线都不比自己高/低，就记一个摆动点。"""
    pivots: List[Dict] = []
    n = len(klines)
    for i in range(window, n - window):
        seg = klines[i - window:i + window + 1]
        hi = max(range(len(seg)), key=lambda k: _num(seg[k].get("high")))
        lo = min(range(len(seg)), key=lambda k: _num(seg[k].get("low")))
        if hi == window:
            pivots.append({"type": "high", "price": _num(klines[i].get("high")),
                           "date": klines[i].get("date")})
        if lo == window:
            pivots.append({"type": "low", "price": _num(klines[i].get("low")),
                           "date": klines[i].get("date")})
    # 合并相邻同类型摆动点，只保留更极端/更新的一个（避免连续小摆动干扰）
    merged: List[Dict] = []
    for p in pivots:
        if merged and merged[-1]["type"] == p["type"]:
            if p["price"] > merged[-1]["price"] if p["type"] == "high" else p["price"] < merged[-1]["price"]:
                merged[-1] = p
        else:
            merged.append(p)
    return merged


def _dow_trend(pivots: List[Dict]) -> tuple[str, str]:
    """道氏三句话：高点抬高且低点抬高=上升趋势；高点走低且低点走低=下降趋势；否则震荡。"""
    highs = [p for p in pivots if p["type"] == "high"][-3:]
    lows = [p for p in pivots if p["type"] == "low"][-3:]
    if len(highs) >= 2 and len(lows) >= 2:
        h_up = highs[-1]["price"] > highs[-2]["price"]
        l_up = lows[-1]["price"] > lows[-2]["price"]
        if h_up and l_up:
            return "up", "高点、低点连续抬高"
        if not h_up and not l_up:
            return "down", "高点、低点连续走低"
    return "neutral", "高低点交错，方向未定"


def _last_pivot_prices(pivots: List[Dict]) -> tuple[float, float]:
    """最近摆动低点=支撑位，最近摆动高点=压力位。"""
    lows = [p["price"] for p in pivots if p["type"] == "low"]
    highs = [p["price"] for p in pivots if p["type"] == "high"]
    return (lows[-1] if lows else 0.0), (highs[-1] if highs else 0.0)


def _macd_divergence_note(klines: List[Dict], pivots: List[Dict]) -> str:
    """道氏趋势的动能预警：价格方向与动能（MACD柱）方向背离时提示（道氏用动能验证趋势强弱，
    用于对冲道氏反转确认的滞后性）。价创新高但柱峰走低=动能走弱；价创新低但柱谷抬高=动能转强。"""
    from scripts.quantrisk.indicators import calc_macd
    try:
        macd = calc_macd(klines)
    except Exception:
        return ""
    if not macd:
        return ""
    idx_of = {k.get("date"): i for i, k in enumerate(klines)}
    highs = [p for p in pivots if p["type"] == "high"][-2:]
    lows = [p for p in pivots if p["type"] == "low"][-2:]
    for grp, up in ((highs, True), (lows, False)):
        if len(grp) < 2:
            continue
        i0, i1 = idx_of.get(grp[0]["date"]), idx_of.get(grp[1]["date"])
        if i0 is None or i1 is None or i0 < 0 or i1 < 0:
            continue
        h0 = _num(macd[i0].get("macd_hist")) if i0 < len(macd) else 0
        h1 = _num(macd[i1].get("macd_hist")) if i1 < len(macd) else 0
        if up and grp[1]["price"] > grp[0]["price"] and h1 < h0:
            return "⚠️动能走弱预警：价创新高但上涨动能收缩"
        if not up and grp[1]["price"] < grp[0]["price"] and h1 > h0:
            return "✅动能转强信号：价创新低但下跌动能收窄"
    return ""


def _dow_conclusion(direction: str, trend_desc: str, pivots: List[Dict], note: str = "", price: float = 0.0) -> str:
    """道氏一句话结论（规则八三要素保持）：方向 + 趋势描述 + 支撑/压力 + 操作含义。
    支撑=最近低于现价的摆动低点，压力=最近高于现价的摆动高点（已突破的不算压力）。"""
    dir_desc = {"up": "🟢上升趋势", "down": "🔴下降趋势"}.get(direction or "neutral", "🟡震荡")
    lows = [p["price"] for p in pivots if p["type"] == "low"]
    highs = [p["price"] for p in pivots if p["type"] == "high"]
    support = next((p for p in reversed(lows) if p < price), lows[-1] if lows else 0.0)
    resistance = next((p for p in reversed(highs) if p > price), highs[-1] if highs else 0.0)
    sup = f"{support:.2f}" if support > 0 else "—"
    res = f"{resistance:.2f}" if resistance > 0 else "—"
    if direction == "up":
        action = "操作：回踩支撑企稳或放量突破再介入"
    elif direction == "down":
        action = "操作：观望，等止跌企稳信号"
    else:
        action = "操作：观望，等突破方向选择"
    parts = [f"道氏结论：{dir_desc}", trend_desc or "趋势未定型", f"支撑{sup}/压力{res}"]
    if note:
        parts.append(note)
    parts.append(action)
    return " | ".join(parts)


def daily_dow_score(daily: List[Dict]) -> Dict[str, Any]:
    """日线道氏次级趋势评分（20分，替代原缠论日线笔）：
    摆动点序列判方向 + 均线确认，输出 up/down/neutral + 道氏结论。"""
    if len(daily) < 60:
        return {"score": 0.0, "direction": "", "trend_direction": "", "reason": "日线数据缺失",
                "conclusion": "道氏结论：数据缺失"}
    pivots = _find_pivots(daily, window=4)
    if len(pivots) < 4:
        return {"score": 0.0, "direction": "", "trend_direction": "", "reason": "日线摆动点不足",
                "conclusion": "道氏结论：日线摆动点不足，无法判趋势"}
    direction, desc = _dow_trend(pivots)
    score = 20.0 if direction == "up" else 4.0 if direction == "down" else 8.0
    # 均线辅助确认趋势质量：MA20 上行加分，下行减分（道氏用均线验证趋势）
    from scripts.quantrisk.indicators import calc_ma
    try:
        ma = calc_ma(daily, [20, 60])
        if len(ma) >= 6:
            ma20_slope = _num(ma[-1].get("ma20")) - _num(ma[-6].get("ma20"))
            if direction == "up" and ma20_slope > 0:
                score = 20.0
            elif direction == "down" and ma20_slope < 0:
                score = 4.0
            elif direction == "neutral" and ma20_slope > 0:
                score = 10.0
    except Exception:
        pass
    score = max(0.0, min(20.0, score))
    note = _macd_divergence_note(daily, pivots)
    conclusion = _dow_conclusion(direction, desc, pivots, note, price=_num(daily[-1].get("close")))
    last = pivots[-1]
    return {"score": round(score, 1), "direction": direction, "trend_direction": direction,
            "start_date": last.get("date", ""), "end_date": daily[-1].get("date", ""),
            "high": _num(daily[-1].get("high")), "low": _num(daily[-1].get("low")),
            "conclusion": conclusion,
            "reason": f"最近日线趋势{direction or '未知'}（摆动点：高点/低点序列）"}


def intraday_dow_score(intraday: List[Dict]) -> Dict[str, Any]:
    """30分钟道氏小趋势评分（25分，替代原缠论30分钟线段）：
    30m 摆动点序列判方向，确认短线入场是否与日线共振。"""
    if len(intraday) < 40:
        return {"score": 0.0, "direction": "", "available": False,
                "reason": f"30分钟K线不足（{len(intraday)}根，至少40根）",
                "conclusion": "道氏结论：30分钟数据缺失"}
    pivots = _find_pivots(intraday, window=2)
    if len(pivots) < 4:
        return {"score": 0.0, "direction": "", "available": False, "reason": "30分钟摆动点不足",
                "conclusion": "道氏结论：30分钟无确认趋势"}
    direction, desc = _dow_trend(pivots)
    score = 25.0 if direction == "up" else 3.0 if direction == "down" else 8.0
    note = _macd_divergence_note(intraday, pivots)
    conclusion = _dow_conclusion(direction, desc, pivots, note, price=_num(intraday[-1].get("close")))
    last = pivots[-1]
    return {"score": round(max(0.0, score), 1), "direction": direction, "available": True,
            "start_date": last.get("date", ""), "end_date": intraday[-1].get("date", ""),
            "high": _num(intraday[-1].get("high")), "low": _num(intraday[-1].get("low")),
            "conclusion": conclusion,
            "reason": f"最近30分钟趋势{direction or '未知'}（摆动点：高点/低点序列）"}


# 兼容别名：原缠论评分函数名保留，指向道氏实现，避免外部引用断裂
daily_stroke_score = daily_dow_score
intraday_segment_score = intraday_dow_score


def swing_sl_tp(price: float, daily: List[Dict], stroke_low: float = 0.0) -> Dict[str, Any]:
    """ATR 动态止损/目标（方案A，2026-09-01 替代固定 -8%/+10%）。

    低波动票（如工行 2ATR≈4%）止损自动收窄，高波动票（如康希诺 2ATR≈27%）自动放宽，
    不再一刀切。规则：
      - 止损 = max(现价 - 2×ATR, 日线笔低点×0.985)，百分比 clamp 到 [5%, 11%]
      - 目标 = 现价 + 3×ATR，百分比 clamp 到 [8%, 25%]，且目标比例 ≥ 止损比例×1.5（RR≥1.5:1）
      - ATR 缺失（日K不足15根）时回退固定 -8%/+10%
    """
    from scripts.quantrisk.indicators import calc_stop_loss_take_profit
    atr_raw = 0.0
    if price > 0 and daily and len(daily) > 14:
        r = calc_stop_loss_take_profit(price, klines=daily)
        atr_raw = float(r.get("atr") or 0.0)
    if atr_raw <= 0:
        stop = round(max(price * 0.92, stroke_low * 0.985), 2)
        target = round(price * 1.10, 2)
        return {"stop_loss": stop, "take_profit": target, "atr": None,
                "stop_pct": 8.0, "target_pct": 10.0}
    stop_pct = min(max(2 * atr_raw / price * 100, 5.0), 11.0)
    target_pct = min(max(3 * atr_raw / price * 100, stop_pct * 1.5, 8.0), 25.0)
    stop = max(price * (1 - stop_pct / 100), stroke_low * 0.985)
    target = price * (1 + target_pct / 100)
    return {"stop_loss": round(stop, 2), "take_profit": round(target, 2),
            "atr": round(atr_raw, 4),
            "stop_pct": round((price - stop) / price * 100, 1),
            "target_pct": round((target - price) / price * 100, 1)}


def swing_score_one(stock: Dict[str, Any], daily: List[Dict], intraday: List[Dict],
                    flow: Optional[Dict] = None) -> Dict[str, Any]:
    ok, error = swing_liquidity_filter(stock, daily)
    trend = daily_trend_score(daily)
    flow_score = daily_flow_score(daily, flow)
    # 别名指向道氏实现（daily_dow_score/intraday_dow_score），测试可 monkeypatch 别名
    stroke = daily_stroke_score(daily)
    segment = intraday_segment_score(intraday)
    direction_conflict = bool(stroke["direction"] and segment["direction"] and
                              stroke["direction"] != segment["direction"])
    tradable = ok and segment.get("available", False) and not direction_conflict and \
        stroke["direction"] == "up" and segment["direction"] == "up"
    overall_dn = stroke.get("trend_direction") == "down"  # 道氏整体趋势偏空
    # 滞后性纪律代码级落地（2026-09-08 用户明确）：动能走弱预警强制降级
    momentum_weak = ("动能走弱预警" in str(stroke.get("conclusion", ""))
                     or "动能走弱预警" in str(segment.get("conclusion", "")))
    # Q8（2026-09-08 grill 第二轮）：量比<1 缩量降级 + 5日涨幅>25% 透支警示（三刀筛自动化）
    vol_ratio = float(flow_score.get("vol_ratio") or 0)
    pct_5d = float(flow_score.get("pct_5d") or 0)
    low_volume = 0 < vol_ratio < 1.0        # 缩量上涨：量比<1
    overheated = pct_5d > 25.0              # 透支：5日涨幅>25%
    total = round(trend["score"] + flow_score["score"] + stroke["score"] + segment["score"], 1)
    if not ok:
        status = "数据缺失"
    elif direction_conflict:
        status = "观望：日线趋势与30分钟趋势冲突"
    elif tradable and momentum_weak:
        status = "谨慎布局：上升趋势但动能走弱"
    elif tradable and overall_dn:
        status = "谨慎布局：短线共振但道氏整体偏空"
    elif tradable and low_volume:
        status = "谨慎布局：缩量上涨（量比<1，资金未跟进）"
    elif tradable and overheated:
        status = "谨慎布局：5日涨幅过大（透支风险，勿追高）"
    elif tradable:
        status = "当前可布局"
    else:
        status = "观望：等待日线趋势与30分钟小趋势共振"
    price = _num(stock.get("p") or stock.get("price"))
    stop_base = _num(stroke.get("low")) if stroke.get("direction") == "up" else 0
    sl_tp = swing_sl_tp(price, daily, stop_base)
    stop, target = sl_tp["stop_loss"], sl_tp["take_profit"]
    return {"code": stock.get("c") or stock.get("code", ""), "name": stock.get("n") or stock.get("name", ""),
            "sector": stock.get("s") or stock.get("sector", "其他"), "price": price, "total": total,
            "trend": trend, "flow": flow_score, "stroke": stroke, "segment": segment,
            "tradable": tradable, "status": status, "error": error, "direction_conflict": direction_conflict,
            "stop_loss": stop, "take_profit": target, "atr": sl_tp.get("atr"),
            "stop_pct": sl_tp.get("stop_pct"), "target_pct": sl_tp.get("target_pct")}


def rank_swing_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(results, key=lambda x: (x.get("tradable", False), x.get("total", 0)), reverse=True)


def build_swing_report(ds: str, stocks: List[Dict[str, Any]], results: List[Dict[str, Any]],
                       market: str) -> Dict[str, Any]:
    """把纯技术结果转换为市场无关的结构化报告。"""
    ranked = rank_swing_results(results)
    top10 = ranked[:10]
    sectors: Dict[str, Dict[str, Any]] = {}
    for s in stocks:
        sec = s.get("s", "其他")
        item = sectors.setdefault(sec, {"sector": sec, "count": 0, "pct": 0.0, "up": 0, "dn": 0})
        item["count"] += 1
        chg = _num((s.get("q") or {}).get("change_pct"))
        item["pct"] += chg
        item["up"] += int(chg > 0)
        item["dn"] += int(chg <= 0)
    for item in sectors.values():
        item["pct"] = round(item["pct"] / max(item["count"], 1), 2)
    top_rows = []
    details = []
    summary = []
    for rank, r in enumerate(top10, 1):
        if r["status"].startswith("谨慎布局"):
            advice = "🟡谨慎布局"
        elif r["tradable"]:
            advice = "🟢当前可布局"
        else:
            advice = "🟡观望" if r["status"] != "数据缺失" else "⚪数据缺失"
        top_rows.append({"rank": rank, "code": r["code"], "name": r["name"], "sector": r["sector"],
                         "trend_score": r["trend"]["score"], "flow_score": r["flow"]["score"],
                         "stroke_score": r["stroke"]["score"], "segment_score": r["segment"]["score"],
                         "total": r["total"], "advice": advice})
        details.append({**r, "rank": rank})
        summary.append({"code": r["code"], "name": r["name"], "advice": advice,
                        "buy": r["status"], "stop_loss": r["stop_loss"],
                        "take_profit": r["take_profit"], "total": r["total"]})
    return {"date": ds, "market": market, "selection_mode": "swing", "sectors": list(sectors.values()),
            "eliminated": [], "vetoed": [], "passed_count": len(stocks), "top10": top_rows,
            "details": details, "summary": summary}


def _render_profile_line(r: Dict[str, Any], market: str) -> str:
    """仿同花顺APP三tab渲染公司简介：📋简况（行业/主营构成）｜📊财务｜🎯看点（题材/板块/近期动态）。
    数据缺失如实标注，A股走东财F10+datacenter，港股降级为腾讯财务字段。"""
    prof = r.get("profile") or {}
    extra = r.get("profile_extra") or {}
    lines = []
    # ---- 📋 简况 ----
    if prof.get("error"):
        lines.append(f"- 📋 **简况**：数据缺失（{prof['error']}）")
    elif market == "cn":
        brief = str(prof.get("brief", "")).strip()
        if len(brief) > 120:
            brief = brief[:120] + "…"
        meta = []
        if prof.get("industry"):
            meta.append(f"行业：{prof['industry']}")
        if prof.get("chairman"):
            meta.append(f"法人：{prof['chairman']}")
        if prof.get("gm"):
            meta.append(f"总经理：{prof['gm']}")
        mix = "；".join(f"{m['item']} {m['ratio']}%（毛利率{m['gross_margin']}%）"
                       for m in (extra.get("business_mix") or [])[:3])
        line = f"- 📋 **简况**：{brief or '数据缺失'}"
        if meta:
            line += f"（{' | '.join(meta)}）"
        if mix:
            line += f"\n  - 主营构成：{mix}"
        lines.append(line)
    else:
        fin = []
        if isinstance(prof.get("pe_ttm"), (int, float)) and prof.get("pe_ttm", 0) > 0:
            fin.append(f"PE(TTM) {prof['pe_ttm']}")
        if isinstance(prof.get("roe"), (int, float)):
            fin.append(f"ROE {prof['roe']}%")
        if isinstance(prof.get("market_cap_100m"), (int, float)) and prof.get("market_cap_100m", 0) > 0:
            fin.append(f"市值{prof['market_cap_100m']}亿")
        body = " | ".join(fin) if fin else "数据缺失"
        lines.append(f"- 📋 **简况**：{body}（主营业务/行业数据缺失：港股F10不可用）")
    # ---- 📊 财务 ----
    fin_b = extra.get("finance") or {}
    if market == "cn" and fin_b:
        fdate = fin_b.get("report_date", "")
        lines.append(f"- 📊 **财务**（{fdate}）：营收{fin_b.get('revenue')}亿（同比{fin_b.get('revenue_yoy')}%）｜"
                     f"净利{fin_b.get('profit')}亿（同比{fin_b.get('profit_yoy')}%）｜ROE {fin_b.get('roe')}%｜"
                     f"毛利率{fin_b.get('gross_margin')}%｜净利率{fin_b.get('net_margin')}%｜负债率{fin_b.get('debt_ratio')}%")
    elif market == "hk":
        fin = []
        if isinstance(prof.get("pe_ttm"), (int, float)) and prof.get("pe_ttm", 0) > 0:
            fin.append(f"PE(TTM) {prof['pe_ttm']}")
        if isinstance(prof.get("roe"), (int, float)):
            fin.append(f"ROE {prof['roe']}%")
        if isinstance(prof.get("dividend_yield"), (int, float)) and prof.get("dividend_yield", 0) > 0:
            fin.append(f"股息率 {prof['dividend_yield']}%")
        if isinstance(prof.get("debt_ratio"), (int, float)) and prof.get("debt_ratio", 0) > 0:
            fin.append(f"负债率 {prof['debt_ratio']}%")
        body = " | ".join(fin) if fin else "数据缺失"
        lines.append(f"- 📊 **财务**：{body}")
    else:
        lines.append("- 📊 **财务**：数据缺失")
    # ---- 🎯 看点 ----
    conc = extra.get("conception") or {}
    if market == "cn" and (conc.get("boards") or conc.get("themes")):
        raw_boards = conc.get("boards") or []
        # 概念/题材类板块优先（如并购重组概念、液冷服务器），常规行业/地区板块殿后
        concept_first = [b for b in raw_boards if "概念" in b or "题材" in b]
        concept_first += [b for b in raw_boards if "概念" not in b and "题材" not in b]
        boards = "、".join(concept_first[:8])
        themes = "；".join(f"{t.get('keyword')}：{t.get('content')[:50]}" for t in (conc.get("themes") or [])[:2])
        line = "- 🎯 **看点**："
        if themes:
            line += themes
        if boards:
            line += (f"（所属板块：{boards}）" if themes else f"所属板块：{boards}")
        lines.append(line)
    else:
        lines.append("- 🎯 **看点**：数据缺失（港股题材接口不可用）" if market == "hk"
                     else "- 🎯 **看点**：数据缺失")
    # ---- 📌 近期动态 ----
    ann = r.get("announcements") or []
    if market == "cn":
        if ann:
            ann_text = "；".join(f"{a.get('date', '')} {a.get('title', '')}" for a in ann[:2])
            lines.append(f"- 📌 近期动态：{ann_text}")
        else:
            lines.append("- 📌 近期动态：数据缺失")
    else:
        lines.append("- 📌 近期动态：数据缺失（港股公告接口不可用）")
    return "\n".join(lines)


def render_swing_report(data: Dict[str, Any], market: str) -> str:
    """波段模式独立渲染器：只展示日线趋势/量价/道氏趋势方向。"""
    label = "A股" if market == "cn" else "港股"
    lines = [f"## {label}波段选股推荐 | {data.get('date', '')}", "", "> 持有周期：几天至 1-2 周；纯技术筛选，不使用基本面评分或否决。",
             "> 评分说明（满分100）：**日线趋势30分**=均线多头排列+MACD；**日线量价资金25分**=量比放量+主力净流入；**日线道氏20分**=日线摆动点趋势方向（道氏三句话）；**30分钟道氏25分**=30m摆动点趋势确认短线入场（缺失或与日线趋势冲突则观望）。",
             "",
             "### 推荐结论", "", "| 排名 | 标的 | 日线趋势 | 日线量价资金 | 日线道氏 | 30分钟道氏 | 总分 | 操作 |", "|:---:|:----|:---:|:---:|:---:|:---:|:---:|:----|"]
    for row in data.get("top10", []):
        lines.append(f"| {row['rank']} | {row['name']}（{row['code']}） | {row['trend_score']}/30 | {row['flow_score']}/25 | {row['stroke_score']}/20 | {row['segment_score']}/25 | **{row['total']}/100** | {row['advice']} |")
    lines += ["", "### 逐只波段信号", ""]
    for r in data.get("details", []):
        trend, flow, stroke, segment = r["trend"], r["flow"], r["stroke"], r["segment"]
        lines += [f"#### {r['rank']}. {r['name']}（{r['code']}）— {r['status']}",
                  f"**现价**：{r['price']:.2f} | **总分**：{r['total']}/100 | **止损**：{r['stop_loss']:.2f}（-{r.get('stop_pct', 8.0):.1f}%）| **目标**：{r['take_profit']:.2f}（+{r.get('target_pct', 10.0):.1f}%）" +
                  (f"，ATR{r.get('atr')}" if r.get('atr') else ""),
                  _render_profile_line(r, market),
                  f"- 日线趋势（30）：{trend['reason']}", f"- 日线量价/资金（25）：{flow['reason']}",
                  f"- 日线道氏（20）：{stroke['reason']}", f"- 30分钟道氏（25）：{segment['reason']}",
                  f"- 日线道氏：{stroke.get('conclusion', '数据缺失')}",
                  f"- 30分钟道氏：{segment.get('conclusion', '数据缺失')}"]
        if r.get("direction_conflict"):
            lines.append("- ⚠️ 日线趋势与30分钟道氏趋势方向冲突，禁止当前布局。")
        if r.get("error"):
            lines.append(f"- 数据状态：{r['error']}")
        lines.append("")
    lines += ["### 波段纪律", "", "- 30分钟道氏缺失或与日线趋势冲突：只观望，不补默认分。", "- 放量突破或回踩确认后再入场；单只仓位建议不超过20%。", "- ⚠️ 道氏滞后性：趋势反转确认天然滞后，标 ⚠️动能走弱预警（价新高但 MACD 柱收缩）的上升趋势严格等回踩支撑、不追当日涨幅、仓位减半；高位放量滞涨视为衰竭信号。", "- 跌破技术止损无条件离场，持仓3-5个交易日缩量滞涨则减仓。", "", "> ⚠️ 声明：基于公开市场行情与技术指标自动生成，不构成投资建议。"]
    return "\n".join(lines)


async def attach_company_profiles(report: Dict[str, Any], market: str) -> Dict[str, Any]:
    """为 TOP10 逐只附加公司三tab资料（简况/财务/看点）+ 近期公告，并发5限流，失败标注数据缺失不阻塞报告。"""
    import asyncio
    from scripts.quantrisk.data import (company_survey_async, recent_announcements_async,
                                        business_mix_async, finance_brief_async, core_conception_async)
    sem = asyncio.Semaphore(5)

    async def one(r: Dict[str, Any]) -> None:
        async with sem:
            try:
                r["profile"] = await company_survey_async(r["code"], market)
            except Exception as exc:
                r["profile"] = {"error": f"{type(exc).__name__}: {str(exc)[:60]}"}
            extra: Dict[str, Any] = {}
            for key, fn in (("business_mix", business_mix_async), ("finance", finance_brief_async),
                            ("conception", core_conception_async)):
                try:
                    extra[key] = await fn(r["code"], market)
                except Exception:
                    extra[key] = {}
            r["profile_extra"] = extra
            try:
                r["announcements"] = await recent_announcements_async(r["code"], market)
            except Exception:
                r["announcements"] = []

    await asyncio.gather(*[one(r) for r in report.get("details", [])[:10]], return_exceptions=True)
    return report


async def run_swing_pipeline(stocks: List[Dict[str, Any]], market: str,
                             daily_fetch: Any, flow_fetch: Any) -> Dict[str, Any]:
    """市场适配器提供日K/资金流函数，核心只做纯技术评分。"""
    import asyncio
    daily_results = await asyncio.gather(*[daily_fetch(s["c"]) for s in stocks], return_exceptions=True)
    flow_results = await asyncio.gather(*[flow_fetch(s["c"]) for s in stocks], return_exceptions=True)
    results = []
    normalized = []
    for stock, daily, flow in zip(stocks, daily_results, flow_results):
        daily = daily if isinstance(daily, list) else []
        flow = flow if isinstance(flow, dict) else {}
        normalized.append(stock)
        results.append(swing_score_one(stock, daily, stock.get("intraday", []), flow))
    report = build_swing_report(__import__("datetime").datetime.now().strftime("%Y-%m-%d"), normalized, results, market)
    return await attach_company_profiles(report, market)


def swing_report_text(data: Dict[str, Any], market: str) -> str:
    return render_swing_report(data, market)


def swing_score_with_intraday(stock: Dict[str, Any], daily: List[Dict], intraday: List[Dict],
                              flow: Optional[Dict] = None) -> Dict[str, Any]:
    return swing_score_one(stock, daily, intraday, flow)


def intraday_from_result(result: Dict[str, Any]) -> List[Dict]:
    return result.get("bars", []) if isinstance(result, dict) and result.get("available") else []


def swing_validate(data: Dict[str, Any]) -> None:
    if data.get("selection_mode") != "swing":
        raise ValueError("selection_mode 必须为 swing")
    for row in data.get("top10", []):
        total = sum(row.get(k, 0) or 0 for k in ("trend_score", "flow_score", "stroke_score", "segment_score"))
        if abs(total - row.get("total", 0)) > 0.2:
            raise ValueError(f"波段分数构成不一致: {row.get('code')}")
        if row.get("segment_score", 0) <= 0 and "当前可布局" in row.get("advice", ""):
            raise ValueError(f"30分钟道氏缺失却允许布局: {row.get('code')}")


__all__ = ["swing_liquidity_filter", "daily_trend_score", "daily_flow_score", "daily_stroke_score",
           "intraday_segment_score", "swing_sl_tp", "swing_score_one", "swing_score_with_intraday",
           "rank_swing_results", "build_swing_report", "render_swing_report", "run_swing_pipeline",
           "attach_company_profiles", "swing_report_text",
           "intraday_from_result", "swing_validate"]


async def run_swing_pipeline_with_intraday(stocks: List[Dict[str, Any]], market: str,
                                           daily_fetch: Any, flow_fetch: Any, intraday_fetch: Any) -> Dict[str, Any]:
    """先日线粗筛，再拉取30分钟K线完成最终评分。"""
    import asyncio
    daily_results = await asyncio.gather(*[daily_fetch(s["c"]) for s in stocks], return_exceptions=True)
    flow_results = await asyncio.gather(*[flow_fetch(s["c"]) for s in stocks], return_exceptions=True)
    candidates = []
    for stock, daily, flow in zip(stocks, daily_results, flow_results):
        daily = daily if isinstance(daily, list) else []
        flow = flow if isinstance(flow, dict) else {}
        quick = daily_trend_score(daily)
        candidates.append((quick["score"] + daily_flow_score(daily, flow)["score"], stock, daily, flow))
    candidates.sort(key=lambda x: x[0], reverse=True)
    shortlist = candidates[:min(len(candidates), 80)]
    intraday_results = await asyncio.gather(*[intraday_fetch(s["c"]) for _, s, _, _ in shortlist], return_exceptions=True)
    results, normalized = [], []
    for (_, stock, daily, flow), intra in zip(shortlist, intraday_results):
        bars = intraday_from_result(intra) if isinstance(intra, dict) else []
        results.append(swing_score_one(stock, daily, bars, flow))
        normalized.append(stock)
    report = build_swing_report(__import__("datetime").datetime.now().strftime("%Y-%m-%d"), normalized, results, market)
    return await attach_company_profiles(report, market)

__all__.append("run_swing_pipeline_with_intraday")
