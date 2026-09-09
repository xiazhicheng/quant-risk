"""纯技术波段选股：日线趋势/量价/笔 + 30分钟线段。

该模块不读取基本面字段，也不调用周线缠论（2026-09-08 起方向判定改用道氏理论）。评分面向持有几天至 1-2 周。
"""
from __future__ import annotations

import re
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
    # 停牌/无成交拦截（2026-09-08 宏源证券000562案例）：退市残留代码行情冻结在停牌日
    #（价格/市值是历史快照、K线停在停牌前），实时成交量为 0 即不分析。
    # A股 quote 字段 volume（股），港股 volume_shares（股）；quote 缺失或字段缺失不拦截（防御误杀）。
    q = stock.get("q") if isinstance(stock.get("q"), dict) else {}
    raw_vol = q.get("volume", q.get("volume_shares"))
    if raw_vol is not None and _num(raw_vol) <= 0:
        return False, "停牌或无成交（成交量为0），不分析"
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
    flow_available = bool(flow and int((flow or {}).get("days") or 0) > 0)
    score = 8.0
    score += 6 if ratio >= 1.5 and pct5 > 0 else (3 if ratio >= 1.1 and pct5 > 0 else -3 if pct5 < 0 else 0)
    net = _num((flow or {}).get("flow_5d"))
    if flow_available:
        score += 6 if net > 0 else -3 if net < 0 else 0
    else:
        score = 0.0
    score = max(0.0, min(25.0, score))
    flow_text = f"主力5日{net/1e8:+.2f}亿" if flow_available else "主力资金数据缺失"
    return {"score": round(score, 1), "vol_ratio": round(ratio, 2), "pct_5d": round(pct5, 2),
            "flow_5d": net if flow_available else None, "available": flow_available,
            "quality": "VALUE" if flow_available else "MISSING",
            "reason": f"5日涨跌{pct5:+.2f}%，量比{ratio:.2f}x，{flow_text}"}


def _last_direction(items: List[Dict]) -> str:
    if not items:
        return ""
    return str(items[-1].get("direction", "")).lower()


# ────────────────────────────────────────────────────────────────
# 道氏理论趋势判定（2026-09-08 替代缠论，用户看不懂缠论术语）
# 核心逻辑：摆动点（枢轴）序列 → 道氏三句话判趋势（高点抬高+低点抬高=升势）
# ────────────────────────────────────────────────────────────────

def _find_pivots(klines: List[Dict], window: int = 3) -> List[Dict]:
    """摆动高低点（枢轴检测）：以**收盘价**为基准（道氏原则6：日内高低点是噪音，只关注收盘价）。

    klines[i].close 是 [i-window, i+window] 内最大→high pivot，最小→low pivot。
    相当于缠论『笔』的简化版，但规则直观：左右各 N 根 K 线的收盘价都不比自己高/低，就记一个摆动点。"""
    pivots: List[Dict] = []
    n = len(klines)
    for i in range(window, n - window):
        seg = klines[i - window:i + window + 1]
        hi = max(range(len(seg)), key=lambda k: _num(seg[k].get("close")))
        lo = min(range(len(seg)), key=lambda k: _num(seg[k].get("close")))
        if hi == window:
            pivots.append({"type": "high", "price": _num(klines[i].get("close")),
                           "date": klines[i].get("date"), "pivot_at": klines[i].get("date"),
                           "confirmed_at": klines[i + window].get("date")})
        if lo == window:
            pivots.append({"type": "low", "price": _num(klines[i].get("close")),
                           "date": klines[i].get("date"), "pivot_at": klines[i].get("date"),
                           "confirmed_at": klines[i + window].get("date")})
    # 合并相邻同类型摆动点，只保留更极端/更新的一个（避免连续小摆动干扰）
    merged: List[Dict] = []
    for p in pivots:
        if merged and merged[-1]["type"] == p["type"]:
            if p["price"] > merged[-1]["price"] if p["type"] == "high" else p["price"] < merged[-1]["price"]:
                merged[-1] = p
        else:
            merged.append(p)
    return merged


def _dow_health(daily: List[Dict], vol_ratio: float = 0.0) -> Dict[str, Any]:
    """第二步·验健康（道氏原则4：成交量确认趋势——上涨放量、回调缩量=健康；价涨量缩=强弩之末）。

    返回 {"healthy": bool, "note": str}；数据不足时默认健康（不误伤）。"""
    try:
        if len(daily) < 12:
            return {"healthy": True, "note": "数据不足跳过"}
        closes = [_num(x.get("close")) for x in daily[-12:]]
        vols = [_num(x.get("volume")) for x in daily[-12:]]
        up = closes[-1] >= closes[-6]          # 近5日方向
        up_vol = sum(vols[-5:]); base_vol = sum(vols[-12:-7])
        if base_vol <= 0:
            return {"healthy": True, "note": "量能缺失跳过"}
        if up:
            healthy = up_vol >= base_vol * 0.85
            note = "上涨放量，趋势健康" if up_vol > base_vol else (
                "上涨缩量（强弩之末隐患）" if not healthy else "上涨量能持平")
        else:
            healthy = up_vol <= base_vol * 1.15
            note = "回调缩量，健康回调" if healthy else "回调放量（警惕下跌）"
        return {"healthy": healthy, "note": note}
    except Exception:
        return {"healthy": True, "note": "计算异常跳过"}


def _dow_stage(daily: List[Dict], vol_ratio: float = 0.0, price: float = 0.0) -> tuple[str, str]:
    """阶段定位（道氏原则2：吸筹/公众参与/派发）——收盘价+量能判断处于趋势哪个位置：
    派发迹象=创近60日新高但缩量（缩量新高=强弩之末）；公众参与=创新高且放量；吸筹=底部区放量启动。"""
    try:
        if len(daily) < 60:
            return "未知", "数据不足"
        closes = [_num(x.get("close")) for x in daily]
        vr = float(vol_ratio or 0)
        peak = max(closes)
        close = closes[-1] if closes else price
        valley = min(closes[-60:])
        pos = (close - valley) / (peak - valley) if peak > valley else 0.5
        if close >= peak * 0.97:
            if 0 < vr < 1.0:
                return "派发", "缩量新高（强弩之末，警惕派发）"
            return "公众参与", "放量创新高（公众参与阶段，顺势持有）"
        if pos <= 0.3:
            return "吸筹", "底部区域" + ("放量启动（吸筹阶段）" if vr >= 1.2 else "（尚未放量，观望）")
        return "公众参与", "趋势中段（公众参与阶段，止损跟随）"
    except Exception:
        return "未知", "计算异常"


def build_index_sync(indexes: Dict[str, Any], market: str) -> Dict[str, Any]:
    """指数同步信息（道氏原则3·指数必须相互验证）。

    cn：上证/深证/创业板三指数须形成合力——只要没有明显对冲涨跌（既有涨又有跌>0.3%）即算同步；
    hk：单指数（恒指）只作环境展示（上行/偏弱），sync=None 不参与降级。
    """
    market = market.lower()

    def _pct(key: str) -> float:
        return float((indexes.get(key) or {}).get("change_pct") or 0)
    if market == "cn":
        required = ("sh000001", "sz399001", "sz399006")
        if any(key not in indexes for key in required):
            return {"sync": None, "quality": "MISSING", "note": "主要指数数据缺失（禁止新开仓）"}
        sh, sz, cy = _pct("sh000001"), _pct("sz399001"), _pct("sz399006")
        note = f"上证{sh:+.2f}% 深证{sz:+.2f}% 创业板{cy:+.2f}%"
        signs = {(x > 0) - (x < 0) for x in (sh, sz, cy)}
        sync = len(signs) == 1
        return {"sync": sync, "quality": "VALUE",
                "note": note + ("（方向同步✅）" if sync else "（方向背离⚠️，信号不可靠）")}
    if "hkHSI" not in indexes:
        return {"sync": None, "quality": "MISSING", "note": "恒指数据缺失（禁止新开仓）"}
    hsi = _pct("hkHSI")
    return {"sync": None, "quality": "VALUE",
            "note": f"恒指{hsi:+.2f}%（{'上行环境' if hsi > 0 else '偏弱环境' if hsi < 0 else '横盘环境'}）"}


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
    """道氏一句话结论：定性（方向）+ 状态（摆动点结构）+ 明确边界（前低/前高，跌破/突破即状态切换）。

    用户原则（2026-09-08）：道氏理论的结论永远是定性的、状态的、带有明确边界的——
    不预测目标价，只描述当前处于什么趋势状态、状态切换的边界条件在哪（前高/前低摆动点）。"""
    dir_desc = {"up": "🟢上升趋势", "down": "🔴下降趋势"}.get(direction or "neutral", "🟡震荡")
    lows = [p["price"] for p in pivots if p["type"] == "low"]
    highs = [p["price"] for p in pivots if p["type"] == "high"]
    support = next((p for p in reversed(lows) if p < price), lows[-1] if lows else 0.0)
    resistance = next((p for p in reversed(highs) if p > price), highs[-1] if highs else 0.0)
    if direction == "up":
        action = "操作：回踩支撑企稳或放量突破再介入"
    elif direction == "down":
        action = "操作：观望，等止跌企稳信号"
    else:
        action = "操作：观望，等突破方向选择"
    parts = [f"道氏结论：{dir_desc}", f"状态：{trend_desc or '趋势未定型'}"]
    boundary = []
    if support > 0:
        boundary.append(f"跌破前低{support:.2f}转空")
    if resistance > 0:
        boundary.append(f"突破前高{resistance:.2f}延续")
    parts.append("边界：" + ("、".join(boundary) if boundary else "摆动点不足"))
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
    price = _num(daily[-1].get("close"))
    previous_low, previous_high = _last_pivot_prices(pivots)
    conclusion = _dow_conclusion(direction, desc, pivots, note, price=price)
    last = pivots[-1]
    return {"score": round(score, 1), "direction": direction, "trend_direction": direction,
            "start_date": last.get("pivot_at", last.get("date", "")), "confirmed_at": last.get("confirmed_at", ""),
            "end_date": daily[-1].get("date", ""),
            "previous_high": previous_high, "previous_low": previous_low,
            "high": previous_high, "low": previous_low,
            "conclusion": conclusion,
            "reason": f"最近日线趋势{direction or '未知'}（收盘价摆动点，高点/低点序列）"}


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
    previous_low, previous_high = _last_pivot_prices(pivots)
    conclusion = _dow_conclusion(direction, desc, pivots, note, price=_num(intraday[-1].get("close")))
    last = pivots[-1]
    return {"score": round(max(0.0, score), 1), "direction": direction, "available": True,
            "start_date": last.get("pivot_at", last.get("date", "")), "confirmed_at": last.get("confirmed_at", ""),
            "end_date": intraday[-1].get("date", ""),
            "previous_high": previous_high, "previous_low": previous_low,
            "high": previous_high, "low": previous_low,
            "conclusion": conclusion,
            "reason": f"最近30分钟趋势{direction or '未知'}（收盘价摆动点，高点/低点序列）"}


# 兼容别名：原缠论评分函数名保留，指向道氏实现，避免外部引用断裂
daily_stroke_score = daily_dow_score
intraday_segment_score = intraday_dow_score


def swing_sl_tp(price: float, daily: List[Dict], stroke_low: float = 0.0) -> Dict[str, Any]:
    """ATR 动态止损 + 移动止盈替代固定目标价（2026-09-08 用户明确：道氏不预测目标，卖出用移动止盈）。

    止损（原方案A不变）：max(现价-2×ATR, 日线前低×0.985)，百分比 clamp 到 [5%, 11%]；ATR 缺失回退 -8%。
    卖出改用移动止盈（道氏原则5「趋势在明确反转前假设持续」）：
      ① 跌破最近道氏前低（收盘价确认）离场——第三信号
      ② 自近期最高收盘价回撤 2×ATR（clamp [5%, 11%]）离场——趋势跟随，不预测顶
    返回 {stop_loss, atr, stop_pct, trail_stop, trail_pct, peak, exit_rule}，不再输出固定 take_profit。
    """
    from scripts.quantrisk.indicators import calc_stop_loss_take_profit
    atr_raw = 0.0
    if price > 0 and daily and len(daily) > 14:
        r = calc_stop_loss_take_profit(price, klines=daily)
        atr_raw = float(r.get("atr") or 0.0)
    if atr_raw <= 0:
        stop = round(max(price * 0.92, stroke_low * 0.985), 2)
        stop_pct = 8.0
    else:
        stop_pct = min(max(2 * atr_raw / price * 100, 5.0), 11.0)
        stop = max(price * (1 - stop_pct / 100), stroke_low * 0.985)
    # 移动止盈：自近20日最高收盘价回撤（趋势保护，不预测目标）
    closes = [_num(x.get("close")) for x in daily[-20:]] if daily else []
    peak = max(closes) if closes else price
    if atr_raw > 0 and peak > 0:
        trail_pct = min(max(2 * atr_raw / peak * 100, 5.0), 11.0)
    else:
        trail_pct = 8.0
    trail_stop = round(peak * (1 - trail_pct / 100), 2)
    if stroke_low > 0:
        exit_rule = f"移动止盈：跌破前低{stroke_low:.2f}或自高点{peak:.2f}回撤{trail_pct:.1f}%离场"
    else:
        exit_rule = f"移动止盈：自高点{peak:.2f}回撤{trail_pct:.1f}%离场"
    return {"stop_loss": round(stop, 2), "atr": round(atr_raw, 4) if atr_raw > 0 else None,
            "stop_pct": round((price - stop) / price * 100, 1) if price > 0 else 0.0,
            "trail_stop": trail_stop, "trail_pct": trail_pct, "peak": peak, "exit_rule": exit_rule}


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
    price = _num(stock.get("p") or stock.get("price"))
    # ── 道氏三步框架（2026-09-08 用户明确）────────────────────────
    # 第二步·验健康：上涨放量/回调缩量（原则4 成交量确认趋势）
    health = _dow_health(daily, vol_ratio)
    # 三阶段：吸筹/公众参与/派发（原则2，悄悄减仓于派发前）
    stage, stage_note = _dow_stage(daily, vol_ratio, price)
    # 原则3·指数相互验证（pipeline 注入：cn 上证/深证/创业板，hk 仅恒指展示不参与降级）
    idx_sync = stock.get("index_sync") or {}
    idx_ok = idx_sync.get("sync")
    # 第三步·找信号：以收盘价确认是否跌破最近前低（原则6 收盘价最重要）
    stroke_low = _num(stroke.get("low"))
    if stroke.get("direction") == "up" and stroke_low > 0:
        if price < stroke_low:
            dow_step3 = f"⚠️已跌破前低{stroke_low:.2f}（收盘价确认）→上升趋势结束，离场"
        else:
            dow_step3 = f"未跌破前低{stroke_low:.2f}（收盘价确认），趋势延续"
    else:
        dow_step3 = "方向未定或前低不足，等信号确认"
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
    elif tradable and stage == "派发":
        status = "谨慎布局：三阶段-派发迹象（缩量新高）"
    elif tradable and not health["healthy"]:
        status = f"谨慎布局：趋势健康度隐患（{health['note']}）"
    elif tradable and idx_ok is False:
        status = "谨慎布局：指数不同步（上证/深证/创业板背离）"
    elif tradable:
        status = "当前可布局"
    else:
        status = "观望：等待日线趋势与30分钟小趋势共振"
    stop_base = stroke_low if stroke.get("direction") == "up" else 0
    sl_tp = swing_sl_tp(price, daily, stop_base)
    result = {"code": stock.get("c") or stock.get("code", ""), "name": stock.get("n") or stock.get("name", ""), "sector": stock.get("s") or stock.get("sector", "其他"), "price": price, "total": total,
            "market": stock.get("market") or ("cn" if str(stock.get("c") or "").isdigit() and len(str(stock.get("c") or "")) == 6 else "hk"),
            "as_of": stock.get("as_of") or "", "liquidity_ok": ok,
            "trend": trend, "flow": flow_score, "stroke": stroke, "segment": segment,
            "tradable": tradable, "status": status, "error": error, "direction_conflict": direction_conflict,
            "stop_loss": sl_tp["stop_loss"], "trail_stop": sl_tp["trail_stop"],
            "trail_pct": sl_tp["trail_pct"], "exit_rule": sl_tp["exit_rule"],
            "atr": sl_tp.get("atr"), "stop_pct": sl_tp.get("stop_pct"),
            "health": health, "stage": stage, "stage_note": stage_note,
            "dow_step3": dow_step3, "index_sync": idx_sync}
    # Structured decision facade. The Python reference remains authoritative in shadow mode.
    try:
        from .feature_engine import build_feature_snapshot
        from .rule_engine import PythonReferenceRuleEngine, SemanticaReteRuleEngine, ShadowRuleEngine
        features = build_feature_snapshot(result, strategy_id=str(stock.get("strategy_id") or "swing_band"),
                                           position=stock.get("position"))
        engine_mode = str(stock.get("rule_engine") or "shadow").lower()
        if engine_mode == "python":
            decision = PythonReferenceRuleEngine().evaluate(features)
        elif engine_mode == "semantica":
            decision = SemanticaReteRuleEngine().evaluate(features)
        else:
            decision = ShadowRuleEngine().evaluate(features)
        result.update({"strategy_id": features.strategy_id, "feature_snapshot": features.to_dict(),
                       "verdict": decision.verdict.value, "entry_eligible": decision.entry_eligible,
                       "rule_hits": [h.to_dict() for h in decision.rule_hits],
                       "decision_engine": decision.engine, "shadow_match": decision.shadow_match,
                       "shadow_verdict": decision.shadow_verdict,
                       "decision_error": decision.error})
        primary_reason = decision.rule_hits[0].reason if decision.rule_hits else ""
        if decision.verdict.value == "ALLOW":
            result["status"] = "当前可布局"
        elif decision.verdict.value == "BLOCK":
            result["status"] = f"禁止开仓：{primary_reason}"
        elif decision.verdict.value == "EXIT":
            result["status"] = f"离场：{primary_reason}"
        elif decision.verdict.value in ("WATCH", "REDUCE") and not result["status"].startswith(("谨慎布局", "观望")):
            result["status"] = f"谨慎布局：{primary_reason}"
    except Exception as exc:
        # No optional adapter or malformed facts: preserve report generation, fail closed for live.
        result.update({"verdict": "BLOCK", "entry_eligible": False,
                       "rule_hits": [{"rule_id": "FEATURE_ENGINE_ERROR_BLOCK", "verdict": "BLOCK",
                                       "priority": 1000, "reason": str(exc), "engine": "python"}],
                       "decision_engine": "python", "shadow_match": None, "shadow_verdict": "UNAVAILABLE",
                       "decision_error": str(exc)})
    return result


def rank_swing_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Entry-eligible stocks rank first; score only compares strength inside the same verdict tier."""
    verdict_rank = {"ALLOW": 4, "WATCH": 3, "REDUCE": 2, "EXIT": 1, "BLOCK": 0}
    return sorted(results, key=lambda x: (bool(x.get("entry_eligible", False)),
                                          verdict_rank.get(str(x.get("verdict", "WATCH")), 0),
                                          x.get("total", 0)), reverse=True)


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
        verdict = str(r.get("verdict") or ("ALLOW" if r.get("tradable") else "WATCH"))
        if verdict == "REDUCE" or r["status"].startswith("谨慎布局"):
            advice = "🟡谨慎布局"
        elif verdict == "ALLOW":
            advice = "🟢当前可布局"
        elif verdict == "EXIT":
            advice = "🔴离场"
        elif verdict == "BLOCK":
            advice = "⚪禁止开仓"
        else:
            advice = "🟡观望"
        top_rows.append({"rank": rank, "code": r["code"], "name": r["name"], "sector": r["sector"],
                         "trend_score": r["trend"]["score"], "flow_score": r["flow"]["score"],
                         "stroke_score": r["stroke"]["score"], "segment_score": r["segment"]["score"],
                         "total": r["total"], "advice": advice,
                         "strategy_id": r.get("strategy_id", "swing_band"),
                         "verdict": verdict, "entry_eligible": r.get("entry_eligible", False),
                         "rule_hits": r.get("rule_hits", [])})
        details.append({**r, "rank": rank})
        summary.append({"code": r["code"], "name": r["name"], "advice": advice,
                        "buy": r["status"], "stop_loss": r["stop_loss"],
                        "trail_stop": r["trail_stop"], "exit_rule": r["exit_rule"], "total": r["total"]})
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
        meta = f"行业：{prof['industry']} | " if prof.get("industry") else ""
        lines.append(f"- 📋 **简况**：{body}（{meta}主营业务文字数据缺失：港股F10无免费源，LLM联网补）")
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
    elif market == "hk" and conc.get("boards"):
        # 港股降级：腾讯 plate 所属板块（2026-09-08 免费源，题材要点仍缺失）
        lines.append(f"- 🎯 **看点**：所属板块：{'、'.join(conc['boards'][:4])}（题材要点数据缺失，LLM联网补）")
    else:
        lines.append("- 🎯 **看点**：数据缺失（港股题材接口不可用）" if market == "hk"
                     else "- 🎯 **看点**：数据缺失")
    # ---- 📌 近期动态 ----
    ann = r.get("announcements") or []
    if ann:
        ann_text = "；".join(f"{a.get('date', '')} {a.get('title', '')}" for a in ann[:2])
        lines.append(f"- 📌 近期动态：{ann_text}")
    elif market == "cn":
        lines.append("- 📌 近期动态：数据缺失")
    else:
        lines.append("- 📌 近期动态：数据缺失（港股公告接口不可用）")
    return "\n".join(lines)


def _score_brief(section: Dict[str, Any], kind: str) -> str:
    """从各维度 reason 提取评分要点（推荐结论表「评分要点」列展示用）。

    示例：日线趋势 reason「MA5/10/20/60=13.14/...，4条均线之上，MACD柱+0.3439」→「4线之上MACD+0.34」；
    量价资金「5日涨跌+12.61%，量比2.78x，主力5日+0.23亿」→「量比2.78/主力+0.23亿」；
    道氏「最近日线趋势up（摆动点：高点/低点序列）」→「up」。"""
    reason = str(section.get("reason", ""))
    if kind == "trend":
        m = re.search(r"(\d)条均线之上", reason)
        h = re.search(r"MACD柱([+-][\d.]+)", reason)
        hist = f"{float(h.group(1)):+.2f}" if h else ""
        return f"{m.group(1)}线之上MACD{hist}"
    if kind == "flow":
        v = re.search(r"量比([\d.]+)x", reason)
        f = re.search(r"主力5日([+-][\d.]+)亿", reason)
        parts = []
        if v:
            parts.append(f"量比{v.group(1)}")
        if f:
            parts.append(f"主力{f.group(1)}亿")
        return "/".join(parts) if parts else (reason[:12] or "无")
    if kind == "segment":
        if section.get("available") is False:
            return "未启用/缺失"
        return str(section.get("direction") or "无")
    return str(section.get("direction") or (reason[:12] if reason else "无"))


def render_swing_report(data: Dict[str, Any], market: str) -> str:
    """波段模式独立渲染器：只展示日线趋势/量价/道氏趋势方向。"""
    label = "A股" if market == "cn" else "港股"
    first_strategy = str((data.get("details") or [{}])[0].get("strategy_id") or "swing_band")
    lines = [f"## {label}波段选股推荐 | {data.get('date', '')}", "", "> 持有周期不预设：由道氏破前低/移动止盈离场信号自然决定（高抛低吸，时间不确定）；纯技术筛选，不使用基本面评分或否决。",
             "> 评分说明（满分100）：**日线趋势30分**=均线多头排列+MACD；**日线量价资金25分**=量比放量+主力净流入；**日线道氏20分**=日线摆动点趋势方向（道氏三句话）；**30分钟道氏25分**=30m摆动点趋势，有则优化入场、缺失不阻断、与日线冲突则观望。",
             "> 道氏三步（用户框架）：①定方向=盘价摆动点判趋势（只做多）；②验健康=涨放量/回调缩量+主要指数同步；③找信号=收盘价未跌破前低则趋势延续，跌破离场。**卖出用移动止盈不预测目标**。",
             "",
             "### 推荐结论", "", "| 排名 | 标的 | 日线趋势 | 日线量价资金 | 日线道氏 | 30分钟道氏 | 总分 | 操作 | 评分要点 |", "|:---:|:----|:---:|:---:|:---:|:---:|:---:|:----|:----|"]
    detail_map = {d.get("code"): d for d in data.get("details", [])}
    if data.get("details"):
        first = data["details"][0]
        engine_label = first.get("decision_engine", "python")
        if first.get("shadow_match") is not None:
            engine_label = f"shadow（Python主裁决，{'一致' if first.get('shadow_match') else '差异'}）"
        lines.insert(4, f"> 策略：`{first.get('strategy_id', 'swing_band')}` ｜规则：`{engine_label}` ｜审计：{'完整' if first.get('audit_complete') else '本地outbox待同步'}")
    for row in data.get("top10", []):
        d = detail_map.get(row["code"]) or {}
        brief = " / ".join(_score_brief(d[k], k) for k in ("trend", "flow", "stroke", "segment")) if d else ""
        lines.append(f"| {row['rank']} | {row['name']}（{row['code']}） | {row['trend_score']}/30 | {row['flow_score']}/25 | {row['stroke_score']}/20 | {row['segment_score']}/25 | **{row['total']}/100** | {row['advice']} | {brief} |")
    lines += ["", "### 逐只波段信号", ""]
    for r in data.get("details", []):
        trend, flow, stroke, segment = r["trend"], r["flow"], r["stroke"], r["segment"]
        health = r.get("health") or {}
        idx = r.get("index_sync") or {}
        vol_ratio = (flow or {}).get("vol_ratio") or 0
        lines += [f"#### {r['rank']}. {r['name']}（{r['code']}）— {r['status']}",
                  f"**现价**：{r['price']:.2f} | **总分**：{r['total']}/100 | **止损**：{r['stop_loss']:.2f}（-{r.get('stop_pct', 8.0):.1f}%）| {r.get('exit_rule', '移动止盈')}" +
                  (f"，ATR{r.get('atr')}" if r.get('atr') else ""),
                  _render_profile_line(r, market),
                  f"- 日线趋势（30）：{trend['reason']}", f"- 日线量价/资金（25）：{flow['reason']}",
                  f"- 日线道氏（20）：{stroke['reason']}", f"- 30分钟道氏（25）：{segment['reason']}",
                  f"- 道氏①定方向：{stroke.get('conclusion', '数据缺失')}",
                  f"- 道氏②验健康：{health.get('note', '数据缺失')}（量比{vol_ratio}x）｜指数：{idx.get('note', '数据缺失')}",
                  f"- 道氏③找信号：{r.get('dow_step3', '数据缺失')}",
                  f"- 三阶段：{r.get('stage', '未知')}｜{r.get('stage_note', '')}"]
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


async def _attach_decision_receipts(report: Dict[str, Any], stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist shortlist decisions to the local outbox; never calls a broker."""
    import uuid
    from .provenance import DecisionOutbox, build_receipt
    from .rule_engine import PythonReferenceRuleEngine
    from .strategy_config import load_strategy_config
    from .strategy_models import DecisionResult, RuleHit, RunMode, Verdict

    stock_by_code = {str(stock.get("c") or stock.get("code")): stock for stock in stocks}
    run_id = uuid.uuid4().hex
    outbox = DecisionOutbox()
    for detail in report.get("details", []):
        stock = stock_by_code.get(str(detail.get("code")), {})
        try:
            features_raw = detail.get("feature_snapshot") or {}
            from .feature_engine import build_feature_snapshot
            features = build_feature_snapshot(detail, str(stock.get("strategy_id") or "tactical"), stock.get("position"))
            hits = tuple(RuleHit(str(hit["rule_id"]), Verdict(str(hit["verdict"])), int(hit.get("priority", 0)),
                                 str(hit.get("reason", "")), str(hit.get("engine", "python")))
                         for hit in (detail.get("rule_hits") or []))
            decision = DecisionResult(Verdict(str(detail.get("verdict") or "BLOCK")),
                                      bool(detail.get("entry_eligible")), hits,
                                      str(detail.get("decision_engine") or "python"),
                                      str(detail.get("decision_error") or ""),
                                      detail.get("shadow_match"), str(detail.get("shadow_verdict") or ""))
            config = load_strategy_config(features.strategy_id)
            mode = RunMode(str(stock.get("run_mode") or "research"))
            receipt = build_receipt(run_id, features, decision, config.version, config.ruleset_hash, mode)
            detail["receipt_hash"] = outbox.enqueue(receipt)
            detail["audit_complete"] = receipt.audit_complete
        except Exception as exc:
            detail["receipt_hash"] = ""
            detail["audit_complete"] = False
            detail["audit_error"] = str(exc)
    report["run_id"] = run_id
    report["outbox"] = str(outbox.path)
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
    report = await attach_company_profiles(report, market)
    return await _attach_decision_receipts(report, normalized)


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
        if not row.get("entry_eligible", False) and row.get("verdict") == "ALLOW":
            raise ValueError(f"裁决矛盾: {row.get('code')}")
        if row.get("entry_eligible", False) and row.get("verdict") not in ("ALLOW",):
            raise ValueError(f"可布局与裁决不一致: {row.get('code')}")


__all__ = ["swing_liquidity_filter", "daily_trend_score", "daily_flow_score", "daily_stroke_score",
           "intraday_segment_score", "swing_sl_tp", "swing_score_one", "swing_score_with_intraday",
           "rank_swing_results", "build_swing_report", "render_swing_report", "run_swing_pipeline",
           "attach_company_profiles", "swing_report_text",
           "intraday_from_result", "swing_validate"]


async def run_swing_pipeline_with_intraday(stocks: List[Dict[str, Any]], market: str,
                                           daily_fetch: Any, flow_fetch: Any, intraday_fetch: Any,
                                           snapshot_path: str = "") -> Dict[str, Any]:
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
    # 30m 为入场优化（有则用、缺失不阻断）：统一尝试拉取，缺失由规则层按非硬门槛处理
    intraday_results = await asyncio.gather(*[intraday_fetch(s["c"]) for _, s, _, _ in shortlist], return_exceptions=True)
    results, normalized = [], []
    for (_, stock, daily, flow), intra in zip(shortlist, intraday_results):
        bars = intraday_from_result(intra) if isinstance(intra, dict) else []
        results.append(swing_score_one(stock, daily, bars, flow))
        normalized.append(stock)
    report = build_swing_report(__import__("datetime").datetime.now().strftime("%Y-%m-%d"), normalized, results, market)
    report = await attach_company_profiles(report, market)
    if snapshot_path:
        from .snapshot import write_snapshot
        snapshot = write_snapshot({"market": market, "stocks": normalized, "results": results}, snapshot_path)
        report["snapshot"] = snapshot
        for result in results:
            result["snapshot_hash"] = snapshot["snapshot_hash"]
    return await _attach_decision_receipts(report, normalized)

__all__.append("run_swing_pipeline_with_intraday")
