"""纯技术波段选股：日线趋势/量价/笔 + 30分钟线段。

该模块不读取基本面字段，也不调用周线缠论。评分面向持有几天至 1-2 周。
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
    score = max(0.0, min(30.0, score))
    direction = "up" if score >= 16 else ("down" if score <= 10 else "neutral")
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


def _chan_conclusion(direction: str, trend: Dict, pivots: List[Dict],
                     divergences: List[Dict], buy_sell: Dict) -> str:
    """缠论一句话结论（规则八）：方向 + 走势/中枢/买卖点/背驰 + 操作含义。

    direction 为最近一笔/线段方向，trend 为整体走势类型；两者冲突时以整体走势为准，
    并明确提示当前仅是反弹笔（下跌趋势中的反弹不构成反转）。
    """
    trend_direction = str((trend or {}).get("direction", "") or "neutral")
    overall = trend_direction if trend_direction in ("up", "down") else direction
    dir_desc = {"up": "🟢偏多", "down": "🔴偏空"}.get(overall, "🟡中性")
    trend_desc = str((trend or {}).get("description", "") or "走势未定型")
    signals = []
    buy_points = (buy_sell or {}).get("buy_points", []) or []
    sell_points = (buy_sell or {}).get("sell_points", []) or []
    if buy_points:
        names = {"first_buy": "一买", "second_buy": "二买", "third_buy": "三买"}
        signals.append("买卖点：" + "/".join(names.get(p.get("type"), p.get("type")) for p in buy_points))
    if sell_points:
        names = {"first_sell": "一卖", "second_sell": "二卖", "third_sell": "三卖"}
        signals.append("卖点：" + "/".join(names.get(p.get("type"), p.get("type")) for p in sell_points))
    for d in (divergences or [])[-1:]:
        signals.append(str(d.get("detail", "背驰信号")))
    if pivots:
        last_pivot = pivots[-1]
        signals.append(f"中枢[{last_pivot.get('zd')}~{last_pivot.get('zg')}]")
    # 最近笔方向与整体走势冲突时明确提示
    if trend_direction in ("up", "down") and direction and direction != trend_direction:
        conflict = "下跌趋势中的反弹笔" if trend_direction == "down" else "上涨趋势中的回调笔"
        signals.append(conflict)
    if not signals:
        signals.append("当前无买卖点信号，等待背驰或突破确认")
    # 操作含义
    if overall == "up" and (buy_points or divergences):
        action = "操作：可布局，回踩中枢/MA5企稳后介入"
    elif overall == "up":
        action = "操作：等回踩确认或放量突破再介入"
    elif overall == "down":
        action = "操作：观望，警惕续跌，等底背驰信号"
    else:
        action = "操作：观望，等方向选择"
    return f"缠论结论：{dir_desc} | {trend_desc} | {'；'.join(signals)} → {action}"


def daily_stroke_score(daily: List[Dict]) -> Dict[str, Any]:
    from scripts.quantrisk.chan import chan_theory_full
    if len(daily) < 60:
        return {"score": 0.0, "direction": "", "reason": "日线笔数据缺失",
                "chan_conclusion": "缠论结论：数据缺失"}
    result = chan_theory_full(daily, min_bi_len=6)
    strokes = result.get("strokes", []) or []
    if not strokes:
        return {"score": 0.0, "direction": "", "reason": "日线没有确认笔",
                "chan_conclusion": "缠论结论：数据缺失"}
    last = strokes[-1]
    direction = _last_direction(strokes)
    score = 20.0 if direction == "up" else 4.0 if direction == "down" else 8.0
    if last.get("is_breakout") or last.get("breakthrough"):
        score += 2 if direction == "up" else -2
    score = max(0.0, min(20.0, score))
    conclusion = _chan_conclusion(direction, result.get("trend", {}),
                                  result.get("pivots", []), result.get("divergences", []),
                                  result.get("buy_sell_points", {}))
    trend_direction = str((result.get("trend", {}) or {}).get("direction", "") or "neutral")
    return {"score": round(score, 1), "direction": direction, "trend_direction": trend_direction,
            "start_date": last.get("start_date", ""), "end_date": last.get("end_date", ""),
            "high": last.get("high"), "low": last.get("low"),
            "chan_conclusion": conclusion,
            "reason": f"最近日线笔{direction or '未知'} {last.get('start_date','')}~{last.get('end_date','')}"}


def intraday_segment_score(intraday: List[Dict]) -> Dict[str, Any]:
    from scripts.quantrisk.chan import chan_theory_full
    if len(intraday) < 40:
        return {"score": 0.0, "direction": "", "available": False,
                "reason": f"30分钟K线不足（{len(intraday)}根，至少40根）",
                "chan_conclusion": "缠论结论：30分钟数据缺失"}
    result = chan_theory_full(intraday, min_bi_len=4)
    segments = result.get("segments", []) or []
    if not segments:
        return {"score": 0.0, "direction": "", "available": False, "reason": "30分钟没有确认线段",
                "chan_conclusion": "缠论结论：30分钟无确认线段"}
    last = segments[-1]
    direction = _last_direction(segments)
    score = 25.0 if direction == "up" else 3.0 if direction == "down" else 8.0
    if last.get("is_breakout") or last.get("breakthrough"):
        score = min(25.0, score + (2 if direction == "up" else -2))
    # 关键修复（2026-08-31）：30m 线段分析的方向应基于 segments 而非 strokes。
    # classify_trend(pivots, strokes) 对单中枢盘整用 strokes[-1].direction 判定趋势，
    # 但 30m 的 strokes 因 min_bi_len=4 较细，当天 7 根 bar 的价格小波动就可能
    # 形成噪声笔，导致 direction 被误判为 down（见 工行 01398: 收盘 7.55→7.53→7.57
    # 被误判为 down 笔，实际只是 up 线段内的正常波动）。
    # 修复：用 segments 的 direction 构造 trend，与 30m 分析粒度一致。
    trend_for_conclusion = dict(result.get("trend", {}) or {})
    seg_strokes = [{"direction": s.get("direction", "up")} for s in segments]
    from scripts.quantrisk.chan import classify_trend
    trend_by_segment = classify_trend(result.get("pivots", []), seg_strokes)
    trend_for_conclusion["direction"] = trend_by_segment.get("direction", trend_for_conclusion.get("direction", "neutral"))
    trend_for_conclusion["description"] = trend_by_segment.get("description", trend_for_conclusion.get("description", ""))
    conclusion = _chan_conclusion(direction, trend_for_conclusion,
                                  result.get("pivots", []), result.get("divergences", []),
                                  result.get("buy_sell_points", {}))
    return {"score": round(max(0.0, score), 1), "direction": direction, "available": True,
            "start_date": last.get("start_date", ""), "end_date": last.get("end_date", ""),
            "high": last.get("high"), "low": last.get("low"),
            "chan_conclusion": conclusion,
            "reason": f"最近30分钟线段{direction or '未知'} {last.get('start_date','')}~{last.get('end_date','')}"}


def swing_score_one(stock: Dict[str, Any], daily: List[Dict], intraday: List[Dict],
                    flow: Optional[Dict] = None) -> Dict[str, Any]:
    ok, error = swing_liquidity_filter(stock, daily)
    trend = daily_trend_score(daily)
    flow_score = daily_flow_score(daily, flow)
    stroke = daily_stroke_score(daily)
    segment = intraday_segment_score(intraday)
    direction_conflict = bool(stroke["direction"] and segment["direction"] and
                              stroke["direction"] != segment["direction"])
    tradable = ok and segment.get("available", False) and not direction_conflict and \
        stroke["direction"] == "up" and segment["direction"] == "up"
    chan_dn = stroke.get("trend_direction") == "down"  # 缠论整体走势偏空
    total = round(trend["score"] + flow_score["score"] + stroke["score"] + segment["score"], 1)
    if not ok:
        status = "数据缺失"
    elif direction_conflict:
        status = "观望：日线笔与30分钟线段冲突"
    elif tradable and chan_dn:
        status = "谨慎布局：短线共振但缠论整体偏空"
    elif tradable:
        status = "当前可布局"
    else:
        status = "观望：等待日线笔与30分钟线段共振"
    price = _num(stock.get("p") or stock.get("price"))
    stop_base = _num(stroke.get("low")) if stroke.get("direction") == "up" else 0
    stop = round(max(price * 0.92, stop_base * 0.985) if price > 0 else 0, 2)
    target = round(price * 1.10, 2) if price > 0 else 0
    return {"code": stock.get("c") or stock.get("code", ""), "name": stock.get("n") or stock.get("name", ""),
            "sector": stock.get("s") or stock.get("sector", "其他"), "price": price, "total": total,
            "trend": trend, "flow": flow_score, "stroke": stroke, "segment": segment,
            "tradable": tradable, "status": status, "error": error, "direction_conflict": direction_conflict,
            "stop_loss": stop, "take_profit": target}


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


def render_swing_report(data: Dict[str, Any], market: str) -> str:
    """波段模式独立渲染器：只展示日线趋势/量价/笔/30分钟线段。"""
    label = "A股" if market == "cn" else "港股"
    lines = [f"## {label}波段选股推荐 | {data.get('date', '')}", "", "> 持有周期：几天至 1-2 周；纯技术筛选，不使用基本面评分或否决。", "",
             "### 推荐结论", "", "| 排名 | 标的 | 日线趋势 | 日线量价资金 | 日线笔 | 30分钟线段 | 总分 | 操作 |", "|:---:|:----|:---:|:---:|:---:|:---:|:---:|:----|"]
    for row in data.get("top10", []):
        lines.append(f"| {row['rank']} | {row['name']}（{row['code']}） | {row['trend_score']}/30 | {row['flow_score']}/25 | {row['stroke_score']}/20 | {row['segment_score']}/25 | **{row['total']}/100** | {row['advice']} |")
    lines += ["", "### 逐只波段信号", ""]
    for r in data.get("details", []):
        trend, flow, stroke, segment = r["trend"], r["flow"], r["stroke"], r["segment"]
        lines += [f"#### {r['rank']}. {r['name']}（{r['code']}）— {r['status']}",
                  f"**现价**：{r['price']:.2f} | **总分**：{r['total']}/100 | **止损**：{r['stop_loss']:.2f} | **目标**：{r['take_profit']:.2f}",
                  f"- 日线趋势（30）：{trend['reason']}", f"- 日线量价/资金（25）：{flow['reason']}",
                  f"- 日线笔（20）：{stroke['reason']}", f"- 30分钟线段（25）：{segment['reason']}",
                  f"- 日线缠论：{stroke.get('chan_conclusion', '数据缺失')}",
                  f"- 30分钟缠论：{segment.get('chan_conclusion', '数据缺失')}"]
        if r.get("direction_conflict"):
            lines.append("- ⚠️ 日线笔与30分钟线段方向冲突，禁止当前布局。")
        if r.get("error"):
            lines.append(f"- 数据状态：{r['error']}")
        lines.append("")
    lines += ["### 波段纪律", "", "- 30分钟线段缺失或与日线笔冲突：只观望，不补默认分。", "- 放量突破或回踩确认后再入场；单只仓位建议不超过20%。", "- 跌破技术止损无条件离场，持仓3-5个交易日缩量滞涨则减仓。", "", "> ⚠️ 声明：基于公开市场行情与技术指标自动生成，不构成投资建议。"]
    return "\n".join(lines)


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
    return build_swing_report(__import__("datetime").datetime.now().strftime("%Y-%m-%d"), normalized, results, market)


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
            raise ValueError(f"30分钟线段缺失却允许布局: {row.get('code')}")


__all__ = ["swing_liquidity_filter", "daily_trend_score", "daily_flow_score", "daily_stroke_score",
           "intraday_segment_score", "swing_score_one", "swing_score_with_intraday", "rank_swing_results",
           "build_swing_report", "render_swing_report", "run_swing_pipeline", "intraday_from_result", "swing_validate"]


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
    return build_swing_report(__import__("datetime").datetime.now().strftime("%Y-%m-%d"), normalized, results, market)

__all__.append("run_swing_pipeline_with_intraday")
