"""
quantrisk — 共享推荐引擎（Recommender）

跨市场共享的过滤/评分/格式化逻辑，A股/港股/美股共用。
各市场的差异化数据源（板块扫描、候选池、资金流向）由市场适配器提供。

设计原则:
  - 过滤/评分规则统一
  - 格式输出由 formatter.py 控制
  - 市场差异通过 adapters 隔离
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 共享过滤/评分逻辑
# ═══════════════════════════════════════════════════════════════

def meso_filter(
    st: Dict[str, Any],
    industry_thresholds: Dict[str, int],
    code2sector: Dict[str, str],
    secid_prefix: str = "hk",
) -> Tuple[List[Dict], List[Tuple[str, str, str]]]:
    """中观硬约束过滤 — 市值/股价硬门槛；PE按行业阈值标记但不淘汰。

    Args:
        st: {code: {quote: {...}, indicator: {...}}}
        industry_thresholds: {sector_name: pe_threshold}
        code2sector: {code: sector_name}
        secid_prefix: 'hk' | 'cn' | 'us'

    Returns:
        passed: [{code, name, sector, price, mcap, pe, ny, rev, pw, q, ind}]
        eliminated: [(code, name, reason)]
    """
    passed, elim = [], []
    default_pe_limit = industry_thresholds.get("其他", 60)

    for code, info in st.items():
        q = info.get("quote", {}) or {}
        ind = info.get("indicator", {}) or {}
        sector = code2sector.get(code, "其他")
        pe_limit = industry_thresholds.get(sector, default_pe_limit)

        price = q.get("price", 0)
        mcap = q.get("market_cap_100m") or q.get("market_cap", 0)
        pe = q.get("pe") or q.get("pe_ttm", 0)
        ny = (ind.get("HOLDER_PROFIT_YOY") or 0) if ind else 0
        rev = (ind.get("OPERATE_INCOME_YOY") or 0) if ind else 0

        rs, pw = [], []

        # 硬约束：市值和股价
        if mcap > 0 and mcap < 50:
            rs.append(f"市值{mcap:.0f}亿<50亿")
        if price > 0 and price < 1:
            rs.append(f"股价{price:.2f}<1元")

        # PE 标记但不淘汰
        if pe and pe > pe_limit:
            pw.append(f"⚠️PE{pe:.0f}>行业阈值{pe_limit}（{sector}）")
        if ny < -50:
            pw.append(f"⚠️净利同比{ny:.2f}%（恶化）")

        pw_str = "; ".join(pw) if pw else ""

        if rs:
            elim.append((code, q.get("name", "?"), "; ".join(rs)))
        else:
            passed.append({
                "c": code, "n": q.get("name", "?"), "s": sector,
                "p": price, "mc": mcap, "pe": pe, "ny": ny, "rev": rev,
                "pw": pw_str, "q": q, "ind": ind,
            })

    return passed, elim


def fb_score(
    p: Dict[str, Any],
    sector: str,
    pe_limit: int,
) -> int:
    """基本面评分 — 统一评分规则。

    评分维度:
      - 营收增速 (rev_yoy)
      - ROE
      - 毛利率
      - 负债率
      - PE 相对估值
      - 净利同比
    """
    ind = p.get("ind", {}) or {}
    rev = p.get("rev", 0)
    ny = p.get("ny", 0)

    def _v(k):
        return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)

    roe = _v("ROE") or _v("JQROE") or 0
    gr = _v("GROSS_PROFIT_RATIO") or 0
    dr = _v("DEBT_ASSET_RATIO") or 0
    pe = p.get("pe", 0)
    s = 3.0

    # 营收增速
    if rev > 30: s += 1
    elif rev > 15: s += 0.5
    elif rev < -10: s -= 1
    elif rev < 0: s -= 0.5

    # ROE
    if roe > 20: s += 1
    elif roe > 10: s += 0.5
    elif 0 < roe < 3: s -= 0.5
    elif roe < 0: s -= 1.0

    # 毛利率
    if gr > 60: s += 1
    elif gr > 30: s += 0.5
    elif 0 < gr < 10: s -= 0.5

    # 负债率
    if dr > 0:
        if dr < 30: s += 0.5
        elif dr > 70: s -= 0.5

    # PE 相对估值
    if pe > 0:
        pe_ratio = pe / max(pe_limit, 1)
        if pe_ratio <= 0.5: s += 0.5
        elif pe_ratio <= 1.0: pass
        elif pe_ratio <= 2.0: s -= 0.3
        else: s -= 0.8
    elif pe < 0: s -= 1.5

    # 净利同比
    if ny < -50: s -= 1.0
    elif ny < 0: s -= 0.5

    return max(1, min(5, round(s)))


def hot_score(
    p: Dict[str, Any],
    kl: List[Dict],
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    capital_flow: Optional[Dict[str, float]] = None,
    market: str = "hk",
) -> int:
    """热点评分 — 基于资金流向/成交量/动量。

    Args:
        market: 'hk' | 'cn' | 'us'
    """
    s, sec, c = 3.0, p.get("s", "其他"), p.get("c", "")
    flow = capital_flow.get(c, 0) if capital_flow else 0

    # ① 板块资金排名
    if sector_ranking:
        for name, data in sector_ranking:
            if name == sec:
                total = data.get("total_flow", 0)
                rank = data.get("rank", 0)
                if rank == 0 and total > 0:
                    s += 1.2
                elif rank < 3 and total > 0:
                    s += 0.8
                elif rank < 5:
                    s += 0.3 if total > 0 else -0.3
                else:
                    s -= 0.6
                break

    # ② 个股资金流向
    if flow > 5e8: s += 0.8
    elif flow > 2e8: s += 0.6
    elif flow > 1e8: s += 0.4
    elif flow > 5e7: s += 0.2
    elif flow > 1e7: s += 0.1
    elif flow < -5e7: s -= 0.5
    elif flow < -1e7: s -= 0.25

    # ③ 板块内龙头
    if sector_ranking:
        for name, data in sector_ranking:
            if name == sec:
                ranked = sorted(data.get("stocks", []), key=lambda x: x.get("flow", 0), reverse=True)
                for rank, st in enumerate(ranked):
                    if st.get("code") == c:
                        if rank == 0 and flow > 0: s += 0.5
                        elif rank < 3 and flow > 0: s += 0.25
                        break
                break

    # ④ 成交量替代（无资金流向数据时使用）
    if abs(flow) < 1e4 and kl and len(kl) >= 21:
        vols = [k.get("volume", 0) for k in kl[-21:]]
        if vols and vols[-1] > 0:
            avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
            vol_ratio = vols[-1] / max(avg_vol, 1)
            if vol_ratio > 2.0: s += 0.6
            elif vol_ratio > 1.5: s += 0.4
            elif vol_ratio < 0.5: s -= 0.3
            pc = (kl[-1]["close"] - kl[-21]["close"]) / kl[-21]["close"] * 100
            if pc > 10 and vol_ratio > 1.2: s += 0.3
            elif pc < -5 and vol_ratio > 1.2: s -= 0.3

    # ⑤ 20日动量
    if kl and len(kl) >= 20:
        pc = (kl[-1]["close"] - kl[-20]["close"]) / kl[-20]["close"] * 100
        if pc > 15: s += 0.5
        elif pc > 8: s += 0.25
        elif pc < -10: s -= 0.5
        elif pc < -5: s -= 0.25

    return max(1, min(5, round(s)))


def chan_score(
    p: Dict[str, Any],
    kl: List[Dict],
) -> Tuple[int, Dict[str, Any]]:
    """缠论评分 — 统一评分规则。"""
    from scripts.quantrisk.indicators import calc_ma, calc_macd, chan_risk_assessment

    if not kl or len(kl) < 60:
        return 3, {}
    s, d = 3.0, {}
    try:
        ma = calc_ma(kl, [5, 20, 60])
        md = calc_macd(kl)
        cv = chan_risk_assessment(kl)
        close = kl[-1]["close"]

        if ma and len(ma) > 0:
            last_ma = ma[-1]
            m5 = last_ma.get("ma5")
            m20 = last_ma.get("ma20")
            m60 = last_ma.get("ma60")
            if m5 and m20 and m60:
                d["ma5"] = round(m5, 2)
                d["ma20"] = round(m20, 2)
                d["ma60"] = round(m60, 2)
                d["pv5"] = round((close - m5) / m5 * 100, 1)
                d["pv20"] = round((close - m20) / m20 * 100, 1)
                d["pv60"] = round((close - m60) / m60 * 100, 1)
                if m5 > m20 > m60:
                    d["ma_alignment"] = "多头排列↑"
                    d["ma_trend"] = "强势"
                    s += 1.2
                    d["ma5_pos"] = "上方" if close > m5 else "下方"
                elif m5 < m20 < m60:
                    d["ma_alignment"] = "空头排列↓"
                    d["ma_trend"] = "弱势"
                    s -= 1.2
                else:
                    if close > m60:
                        s += 0.3
                        d["ma_trend"] = "偏多"
                    else:
                        s -= 0.3
                        d["ma_trend"] = "偏空"
                    if m5 > m20:
                        d["ma_alignment"] = "短期金叉"
                        s += 0.3
                    else:
                        d["ma_alignment"] = "短期死叉"
                        s -= 0.3
                above_count = sum([close > m5, close > m20, close > m60])
                d["ma_above_count"] = above_count
                d["ma_pos_summary"] = {3: "三线之上", 2: "两线之上", 1: "一线之上"}.get(above_count, "三线之下")

            if m5 and m20 and len(ma) >= 2:
                prev_m5 = ma[-2].get("ma5")
                prev_m20 = ma[-2].get("ma20")
                if prev_m5 and prev_m20:
                    if prev_m5 <= prev_m20 and m5 > m20:
                        d["ma_cross_short"] = "MA5金叉MA20↑"
                        s += 0.5
                    elif prev_m5 >= prev_m20 and m5 < m20:
                        d["ma_cross_short"] = "MA5死叉MA20↓"
                        s -= 0.5

            if m20 and m60 and len(ma) >= 2:
                prev_m20 = ma[-2].get("ma20")
                prev_m60 = ma[-2].get("ma60")
                if prev_m20 and prev_m60:
                    if prev_m20 <= prev_m60 and m20 > m60:
                        d["ma_cross_medium"] = "MA20金叉MA60↑"
                        s += 0.8
                    elif prev_m20 >= prev_m60 and m20 < m60:
                        d["ma_cross_medium"] = "MA20死叉MA60↓"
                        s -= 0.8

        if md and len(md) > 0:
            m = md[-1]
            hi = m.get("macd_hist", (m["dif"] - m["dea"]) * 2)
            d["mh"] = round(hi, 4)
            if len(md) >= 2:
                pm = md[-2]
                ph = pm.get("macd_hist", (pm["dif"] - pm["dea"]) * 2)
                if ph < 0 < hi: d["mc"] = "金叉↑"; s += 1
                elif ph > 0 > hi: d["mc"] = "死叉↓"; s -= 1
            elif hi > 0: s += 0.5
            else: s -= 0.5
            d["mc"] = d.get("mc", "无交叉")
        d["v"] = str(cv.get("verdict", "")) if isinstance(cv, dict) else ""
        sig = cv.get("signal", "") if isinstance(cv, dict) else ""
        if "买" in sig or "buy" in sig.lower(): s += 1
        elif "卖" in sig or "sell" in sig.lower(): s -= 1
    except Exception as e:
        d["e"] = str(e)
    return max(1, min(5, round(s))), d


def score_one(
    p: Dict[str, Any],
    kl: List[Dict],
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    capital_flow: Optional[Dict[str, float]] = None,
    industry_thresholds: Dict[str, int] = None,
    market: str = "hk",
) -> Dict[str, Any]:
    """单只股票三维评分。"""
    c = p["c"]
    pe_limit = (industry_thresholds or {}).get(p.get("s", "其他"), 60)

    fb = fb_score(p, p.get("s", "其他"), pe_limit)
    hot = hot_score(p, kl, sector_ranking, capital_flow, market)
    ch, cd = chan_score(p, kl)
    total = fb * 5 + hot * 3 + ch * 2

    return {
        "c": c, "n": p["n"], "s": p["s"], "p": p["p"], "mc": p["mc"], "pe": p["pe"],
        "fb": fb, "hot": hot, "ch": ch, "total": total, "pw": p.get("pw", ""),
        "ny": p.get("ny"), "rev": p.get("rev"), "kl": kl, "cd": cd,
        "q": p["q"], "ind": p["ind"],
    }


# ═══════════════════════════════════════════════════════════════
# 格式化输出辅助
# ═══════════════════════════════════════════════════════════════

def build_selection_data(
    ds: str,
    ss: Dict[str, Dict],
    elim: List[Tuple[str, str, str]],
    scored: List[Dict[str, Any]],
    passed_cnt: int,
    capital_flow: Optional[Dict[str, float]] = None,
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
) -> dict:
    """将内部数据结构转为 format_output() 所需的 JSON Schema。"""
    from scripts.quantrisk.indicators import calc_stop_loss_take_profit

    top10 = scored[:10]
    flow_all_zero = all(abs(v) < 1e4 for v in (capital_flow or {}).values()) if capital_flow else True

    # sectors
    sectors_data = []
    for sec_name, s_info in ss.items():
        sectors_data.append({
            "sector": sec_name,
            "count": s_info.get("c", 0),
            "pct": round(s_info.get("ap", 0)),
            "up": s_info.get("up", 0),
            "dn": s_info.get("dn", 0),
        })

    # eliminated
    eliminated_data = [{"code": c, "name": n, "reason": r} for c, n, r in elim]

    # top10
    top10_data = []
    for i, s in enumerate(top10):
        t = s["total"]
        advice = "强烈关注" if t >= 35 else ("可关注" if t >= 28 else ("观察" if t >= 22 else "回避"))
        top10_data.append({
            "rank": i + 1,
            "code": s["c"],
            "name": s["n"],
            "sector": s["s"],
            "fb": s["fb"],
            "hot": s["hot"],
            "ch": s["ch"],
            "total": t,
            "advice": advice,
        })

    # details (top 5)
    details_data = []
    for s in top10[:5]:
        idx = scored.index(s) + 1
        chg = (s["q"].get("change_pct") or 0) if s.get("q") else 0
        ind = s.get("ind", {}) or {}
        d = s.get("cd", {}) or {}
        sltp = {}

        kl = s.get("kl", [])
        if kl and len(kl) >= 20:
            sltp = calc_stop_loss_take_profit(entry_price=s["p"], klines=kl[-60:])
        sl_point = sltp.get("stop_loss") or round(s["p"] * 0.92, 2)
        tp_point = sltp.get("take_profit") or round(s["p"] * 1.15, 2)
        t = s["total"]
        advice = ("强烈关注，适合布局" if t >= 35 else
                  "可适当关注，等待入场时机" if t >= 28 else
                  "纳入观察清单，等待催化剂" if t >= 22 else "暂时回避，等待改善")

        # 热点描述
        if flow_all_zero:
            kl_s = s.get("kl", [])
            vr = 1.0
            if kl_s and len(kl_s) >= 21:
                vols = [k.get("volume", 0) for k in kl_s[-21:]]
                if vols and vols[-1] > 0:
                    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
                    vr = vols[-1] / max(avg_vol, 1)
            if vr > 2.0: vol_desc = f"放巨量({vr:.1f}x)"
            elif vr > 1.5: vol_desc = f"放量({vr:.1f}x)"
            elif vr < 0.5: vol_desc = f"缩量({vr:.1f}x)"
            else: vol_desc = f"量平({vr:.1f}x)"
            hot_desc = f"{s['s']}板块 {vol_desc} {'+' if chg >= 0 else ''}{chg:.2f}%"
        else:
            flow = capital_flow.get(s["c"], 0)
            flow_str = f"主力净{flow/1e8:+.2f}亿" if abs(flow) > 1e4 else "无明显资金流入"
            hot_desc = f"{s['s']}板块 {flow_str}"

        # 缠论信号
        v_str = str(d.get("v", ""))
        sig = v_str if v_str and v_str != "等待信号" else "macd待确认"
        macd_hist = d.get("mh", "?")
        ma60 = d.get("ma60", "?")
        ma60 = round(ma60, 2) if ma60 != "?" else "?"

        details_data.append({
            "rank": idx,
            "code": s["c"],
            "name": s["n"],
            "price": s.get("p"),
            "pct": chg,
            "advice": advice,
            "stop_loss": sl_point,
            "fb": {
                "score": s["fb"],
                "pe": s.get("pe", "?"),
                "revenue_yoy": s.get("rev", "?"),
                "net_profit_yoy": s.get("ny", "?"),
                "roe": ind.get("ROE") or ind.get("JQROE") or "?",
                "gross_margin": ind.get("GROSS_PROFIT_RATIO") or "?",
                "debt_ratio": ind.get("DEBT_ASSET_RATIO") or "?",
            },
            "hot": {
                "score": s["hot"],
                "desc": hot_desc,
            },
            "ch": {
                "score": s["ch"],
                "ma60": ma60,
                "price": s.get("p"),
                "macd_hist": macd_hist,
                "signal": sig,
            },
        })

    # summary
    summary_data = []
    for s in top10:
        kl = s.get("kl", [])
        sltp = {}
        if kl and len(kl) >= 20:
            sltp = calc_stop_loss_take_profit(entry_price=s["p"], klines=kl[-60:])
        sl_point = sltp.get("stop_loss") or round(s["p"] * 0.92, 2)
        tp_point = sltp.get("take_profit") or round(s["p"] * 1.15, 2)
        t = s["total"]
        advice = "强烈关注" if t >= 35 else ("可关注" if t >= 28 else ("观察" if t >= 22 else "回避"))
        summary_data.append({
            "code": f"{s['c']} {s['n']}",
            "advice": advice,
            "buy": s.get("p"),
            "stop_loss": sl_point,
            "take_profit": tp_point,
        })

    return {
        "date": ds,
        "sectors": sectors_data,
        "eliminated": eliminated_data,
        "passed_count": passed_cnt,
        "top10": top10_data,
        "details": details_data,
        "summary": summary_data,
    }
