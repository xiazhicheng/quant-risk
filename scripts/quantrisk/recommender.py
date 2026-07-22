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
    field_map: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Tuple[List[Dict], List[Tuple[str, str, str]]]:
    """中观硬约束过滤 — 市值/股价硬门槛；PE按行业阈值标记但不淘汰。

    Args:
        st: {code: {field_map["quote"]: {...}, field_map["indicator"]: {...}}}
        industry_thresholds: {sector_name: pe_threshold}
        code2sector: {code: sector_name}
        field_map: 数据字段名映射（HK用{"q":"quote","ind":"indicator"}，CN/US默认{"quote":"quote","indicator":"indicator"}）

    Returns:
        passed: [{code, name, sector, price, mcap, pe, ny, rev, pw, q, ind}]
        eliminated: [(code, name, reason)]
    """
    passed, elim = [], []
    default_pe_limit = industry_thresholds.get("其他", 60)
    q_key = (field_map or {}).get("q", "quote")
    ind_key = (field_map or {}).get("ind", "indicator")

    for code, info in st.items():
        q = info.get(q_key, {}) or {}
        ind = info.get(ind_key, {}) or {}
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


# ═══════════════════════════════════════════════════════════════
# 基本面一票否决（投资理念铁律：基本面为主，不合格者直接淘汰）
# ═══════════════════════════════════════════════════════════════

def fundamental_veto(
    passed: List[Dict[str, Any]],
    min_rev_yoy: float = -30.0,
    min_ny_yoy: float = -30.0,
    max_pe_neg: float = -10.0,
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str, str]]]:
    """基本面一票否决 — 严重基本面恶化的标的直接淘汰。

    贯彻"基本面为主"理念：技术面和热点再强，基本面崩塌的股票也不进评分池。

    Args:
        passed: meso_filter 通过后的标的列表
        min_rev_yoy: 营收同比下滑阈值（%），低于此值淘汰（默认 -30%）
        min_ny_yoy: 净利同比下滑阈值（%），低于此值淘汰（默认 -30%）
        max_pe_neg: PE 负值阈值，低于此值淘汰（默认 -10，即严重亏损）

    Returns:
        passed: 通过否决后的标的列表
        vetoed: [(code, name, reason)] 被否决的标的
    """
    passed_out, vetoed = [], []

    for p in passed:
        c = p["c"]
        n = p.get("n", "?")
        ny = p.get("ny", 0)
        rev = p.get("rev", 0)
        pe = p.get("pe", 0)

        reasons = []

        # 营收同比严重下滑 → 业务在萎缩
        if rev < min_rev_yoy:
            reasons.append(f"营收同比{rev:.1f}%（<-{abs(min_rev_yoy)}%）")

        # 净利同比严重下滑 → 盈利能力崩塌
        if ny < min_ny_yoy:
            reasons.append(f"净利同比{ny:.1f}%（<-{abs(min_ny_yoy)}%）")

        # PE 严重负值 → 巨亏，无法估值
        if pe < max_pe_neg:
            reasons.append(f"PE{pe:.1f}（严重亏损）")

        if reasons:
            vetoed.append((c, n, "; ".join(reasons)))
        else:
            passed_out.append(p)

    return passed_out, vetoed


# ── 辅助 ──────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 1.0, hi: float = 5.0) -> float:
    """限制到 [lo, hi] 范围并保留 1 位小数。"""
    return round(max(lo, min(hi, v)), 1)


def _percentile(values: List[float], v: float) -> float:
    """返回 v 在 values 中的百分位排名（0~1）。"""
    if not values:
        return 0.5
    ranked = sorted(values)
    n = len(ranked)
    # 比 v 小的比例
    smaller = sum(1 for x in ranked if x < v)
    return smaller / n


def fb_score(
    p: Dict[str, Any],
    sector: str,
    pe_limit: int,
) -> float:
    """基本面评分 — 返回 (score, debug_str)，debug_str 展示各维度计算明细。"""
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}
    rev = p.get("rev", 0)
    ny = p.get("ny", 0)

    def _v(k):
        return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)

    roe = _v("ROE") or _v("JQROE") or 0
    gr = _v("GROSS_PROFIT_RATIO") or 0
    dr = _v("DEBT_ASSET_RATIO") or 0
    pe = p.get("pe", 0)
    pb = q.get("pb", 0)
    dy = q.get("dividend_yield", 0)
    pm = q.get("profit_margin", 0)

    s = 2.0
    parts = [f"基础{s:.1f}"]

    # ── 营收增速 ──
    if rev > 50: c = 2.0; t = ">50%"
    elif rev > 30: c = 1.5; t = ">30%"
    elif rev > 20: c = 1.0; t = ">20%"
    elif rev > 10: c = 0.5; t = ">10%"
    elif rev > 0: c = 0.0; t = ">0%"
    elif rev < -50: c = -2.0; t = "<-50%"
    elif rev < -30: c = -1.0; t = "<-30%"
    elif rev < -10: c = -0.5; t = "<-10%"
    else: c = 0.0; t = "无数据"
    s += c
    parts.append(f"营收{rev:.1f}%({t}→{c:+.1f})")

    # ── ROE ──
    if roe > 30: s += 2.0; parts.append(f"ROE{roe:.1f}%(>30%→+2.0)")
    elif roe > 20: s += 1.5; parts.append(f"ROE{roe:.1f}%(>20%→+1.5)")
    elif roe > 15: s += 1.0; parts.append(f"ROE{roe:.1f}%(>15%→+1.0)")
    elif roe > 10: s += 0.5; parts.append(f"ROE{roe:.1f}%(>10%→+0.5)")
    elif roe > 5: s += 0.0; parts.append(f"ROE{roe:.1f}%(>5%→0)")
    elif roe < 0: s -= 1.5; parts.append(f"ROE{roe:.1f}%(<0→-1.5)")
    elif 0 < roe < 3: s -= 0.5; parts.append(f"ROE{roe:.1f}%(0~3%→-0.5)")
    else: parts.append(f"ROE?(无数据→0)")

    # ── 毛利率 ──
    if gr > 80: s += 1.5; parts.append(f"毛利率{gr:.1f}%(>80%→+1.5)")
    elif gr > 60: s += 1.0; parts.append(f"毛利率{gr:.1f}%(>60%→+1.0)")
    elif gr > 40: s += 0.5; parts.append(f"毛利率{gr:.1f}%(>40%→+0.5)")
    elif gr > 20: s += 0.0; parts.append(f"毛利率{gr:.1f}%(>20%→0)")
    elif 0 < gr < 10: s -= 0.5; parts.append(f"毛利率{gr:.1f}%(<10%→-0.5)")
    else: parts.append(f"毛利率?(无数据→0)")

    # ── 负债率 ──
    if dr > 0:
        if dr < 20: s += 1.0; parts.append(f"负债率{dr:.1f}%(<20%→+1.0)")
        elif dr < 30: s += 0.5; parts.append(f"负债率{dr:.1f}%(<30%→+0.5)")
        elif dr < 50: s += 0.0; parts.append(f"负债率{dr:.1f}%(<50%→0)")
        elif dr < 70: s -= 0.5; parts.append(f"负债率{dr:.1f}%(<70%→-0.5)")
        else: s -= 1.0; parts.append(f"负债率{dr:.1f}%(≥70%→-1.0)")
    else:
        parts.append("负债率?(无数据→0)")

    # ── PE 相对估值 ──
    if pe > 0:
        pe_ratio = pe / max(pe_limit, 1)
        if pe_ratio <= 0.3: s += 1.0; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤0.3→+1.0"
        elif pe_ratio <= 0.5: s += 0.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤0.5→+0.5"
        elif pe_ratio <= 0.8: s += 0.0; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤0.8→0"
        elif pe_ratio <= 1.0: s -= 0.0; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤1.0→0"
        elif pe_ratio <= 1.5: s -= 0.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}>1.0→-0.5"
        elif pe_ratio <= 2.0: s -= 1.0; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}>1.5→-1.0"
        else: s -= 1.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}>2.0→-1.5"
        parts.append(prt)
    elif pe < 0:
        s -= 2.0; parts.append("PE<0→-2.0")
    else:
        parts.append("PE?(无数据→0)")

    # ── 净利同比 ──
    if ny > 100: s += 1.0; parts.append(f"净利{ny:.1f}%(>100%→+1.0)")
    elif ny > 50: s += 0.5; parts.append(f"净利{ny:.1f}%(>50%→+0.5)")
    elif ny > 0: s += 0.0; parts.append(f"净利{ny:.1f}%(>0%→0)")
    elif ny < -100: s -= 2.0; parts.append(f"净利{ny:.1f}%(<-100%→-2.0)")
    elif ny < -50: s -= 1.0; parts.append(f"净利{ny:.1f}%(<-50%→-1.0)")
    else: parts.append(f"净利{ny:.1f}%(0~-50%→0)")

    # ── PB 市净率 ──
    if pb > 0:
        if pb < 1: s += 1.0; parts.append(f"PB{pb:.2f}(<1→+1.0)")
        elif pb < 2: s += 0.5; parts.append(f"PB{pb:.2f}(<2→+0.5)")
        elif pb < 3: s += 0.0; parts.append(f"PB{pb:.2f}(<3→0)")
        elif pb < 5: s -= 0.0; parts.append(f"PB{pb:.2f}(<5→0)")
        elif pb < 10: s -= 0.5; parts.append(f"PB{pb:.2f}(<10→-0.5)")
        else: s -= 1.0; parts.append(f"PB{pb:.2f}(≥10→-1.0)")
    else:
        parts.append("PB?(无数据→0)")

    # ── 股息率 ──
    if dy > 0:
        if dy > 5: s += 1.0; parts.append(f"股息率{dy:.1f}%(>5%→+1.0)")
        elif dy > 3: s += 0.5; parts.append(f"股息率{dy:.1f}%(>3%→+0.5)")
        elif dy > 1: s += 0.0; parts.append(f"股息率{dy:.1f}%(>1%→0)")
        else: parts.append(f"股息率{dy:.1f}%(>0%→0)")
    else:
        s -= 0.5; parts.append("股息率0%(=0→-0.5)")

    # ── 净利率 ──
    if pm > 0:
        if pm > 30: s += 1.0; parts.append(f"净利率{pm:.1f}%(>30%→+1.0)")
        elif pm > 15: s += 0.5; parts.append(f"净利率{pm:.1f}%(>15%→+0.5)")
        elif pm > 5: s += 0.0; parts.append(f"净利率{pm:.1f}%(>5%→0)")
        else: parts.append(f"净利率{pm:.1f}%(>0%→0)")
    elif pm < -10: s -= 1.0; parts.append(f"净利率{pm:.1f}%(<-10%→-1.0)")
    elif pm < 0: s -= 0.5; parts.append(f"净利率{pm:.1f}%(<0→-0.5)")
    else: parts.append("净利率?(无数据→0)")

    debug = "+".join(parts)
    return s, debug  # 返回 (未clamp原始分, debug明细)


def hot_score(
    p: Dict[str, Any],
    kl: List[Dict],
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    market: str = "hk",
) -> int:
    """热点评分 — 基于近5日成交额变化+股价收盘价变化（替代资金流向）。

    港股资金流向数据长期缺失，改用K线数据计算：
      ① 板块整体表现（板块平均5日涨跌幅排名）
      ② 近5日成交额变化（后5日/前5日成交额比）
      ③ 近5日收盘价变化
      ④ 量价共振（涨且量放大加分，跌且量放大减分）
      ⑤ 板块内相对强弱（个股vs板块平均）

    Args:
        p: 股票信息
        kl: 日K线数据
        sector_ranking: [(sector_name, {"avg_5d_pct": ..., "stock_count": ..., "rank": ...})]
        market: 市场标识
    """
    s, sec, c = 2.0, p.get("s", "其他"), p.get("c", "")

    # ① 板块整体表现 — 用板块平均5日涨跌幅排名代替资金流向排名
    if sector_ranking:
        for name, data in sector_ranking:
            if name == sec:
                rank = data.get("rank", 999)
                total_sectors = max(len(sector_ranking), 1)
                # 前1/3 加分，中间不动，后1/3 减分
                if rank == 0:
                    s += 1.5
                elif rank == 1:
                    s += 1.0
                elif rank == 2:
                    s += 0.5
                elif rank >= total_sectors * 0.7:
                    s -= 0.5
                break

    # ② 近5日成交额变化
    vol_5d_ratio = 1.0
    if kl and len(kl) >= 10:
        recent_5_vol = sum(k.get("volume", 0) or 0 for k in kl[-5:])
        prev_5_vol = sum(k.get("volume", 0) or 0 for k in kl[-10:-5])
        if prev_5_vol > 0 and recent_5_vol > 0:
            vol_5d_ratio = recent_5_vol / prev_5_vol
            if vol_5d_ratio > 2.0:
                s += 1.5
            elif vol_5d_ratio > 1.5:
                s += 1.0
            elif vol_5d_ratio > 1.2:
                s += 0.5
            elif vol_5d_ratio < 0.4:
                s -= 1.0
            elif vol_5d_ratio < 0.6:
                s -= 0.5
            elif vol_5d_ratio < 0.8:
                s -= 0.2

    # ③ 近5日收盘价变化
    pct_5d = 0.0
    if kl and len(kl) >= 6:
        close_5d_ago = kl[-6].get("close", 0) or 0
        close_now = kl[-1].get("close", 0) or 0
        if close_5d_ago > 0:
            pct_5d = (close_now - close_5d_ago) / close_5d_ago * 100
            if pct_5d > 15:
                s += 1.5
            elif pct_5d > 10:
                s += 1.0
            elif pct_5d > 5:
                s += 0.5
            elif pct_5d > 0:
                s += 0.2
            elif pct_5d < -15:
                s -= 1.5
            elif pct_5d < -10:
                s -= 1.0
            elif pct_5d < -5:
                s -= 0.5
            elif pct_5d < -2:
                s -= 0.2

    # ④ 量价共振
    if kl and len(kl) >= 10:
        recent_5_vol = sum(k.get("volume", 0) or 0 for k in kl[-5:])
        prev_5_vol = sum(k.get("volume", 0) or 0 for k in kl[-10:-5])
        close_5d_ago = kl[-6].get("close", 0) or 0
        close_now = kl[-1].get("close", 0) or 0
        if prev_5_vol > 0 and close_5d_ago > 0:
            v_ratio = recent_5_vol / prev_5_vol
            p_ratio = (close_now - close_5d_ago) / close_5d_ago * 100
            if p_ratio > 3 and v_ratio > 1.2:
                s += 0.5  # 量价齐升
            elif p_ratio < -3 and v_ratio > 1.2:
                s -= 0.5  # 放量下跌

    # ⑤ 板块内相对强弱（个股vs板块平均）
    if sector_ranking and kl and len(kl) >= 6:
        for name, data in sector_ranking:
            if name == sec:
                sector_avg_5d = data.get("avg_5d_pct", 0)
                close_5d_ago = kl[-6].get("close", 0) or 0
                close_now = kl[-1].get("close", 0) or 0
                if close_5d_ago > 0:
                    stock_5d = (close_now - close_5d_ago) / close_5d_ago * 100
                    relative = stock_5d - sector_avg_5d
                    if relative > 5:
                        s += 0.5
                    elif relative > 2:
                        s += 0.2
                    elif relative < -5:
                        s -= 0.5
                    elif relative < -2:
                        s -= 0.2
                break

    return s  # 未clamp，百分位排名会处理归一化


def chan_score(
    p: Dict[str, Any],
    kl: List[Dict],
) -> Tuple[int, Dict[str, Any]]:
    """缠论评分 — 统一评分规则（已细化多 tier 版本）。"""
    from scripts.quantrisk.indicators import calc_ma, calc_macd, chan_risk_assessment

    if not kl or len(kl) < 60:
        return 3, {}
    s, d = 2.0, {}
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
                # MA排列 — 细化 7 档
                if m5 > m20 > m60 and close > m5:
                    d["ma_alignment"] = "三线多头↑"
                    d["ma_trend"] = "强势"
                    s += 1.5
                elif m5 > m20 > m60:
                    d["ma_alignment"] = "多头排列↑"
                    d["ma_trend"] = "强势"
                    s += 1.2
                elif m5 < m20 < m60 and close < m60:
                    d["ma_alignment"] = "三线空头↓"
                    d["ma_trend"] = "弱势"
                    s -= 1.2
                elif m5 < m20 < m60:
                    d["ma_alignment"] = "空头排列↓"
                    d["ma_trend"] = "弱势"
                    s -= 0.6
                else:
                    if close > m60:
                        d["ma_trend"] = "偏多"
                        s += 0.5
                    else:
                        d["ma_trend"] = "偏空"
                        s -= 0.3
                    if m5 > m20:
                        d["ma_alignment"] = "短期金叉"
                        s += 0.3
                    else:
                        d["ma_alignment"] = "短期死叉"
                        s -= 0.3
                above_count = sum([close > m5, close > m20, close > m60])
                d["ma_above_count"] = above_count
                d["ma_pos_summary"] = {3: "三线之上", 2: "两线之上", 1: "一线之上"}.get(above_count, "三线之下")

            # MA交叉 — 细化 5 档
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
                        s += 1.0
                    elif prev_m20 >= prev_m60 and m20 < m60:
                        d["ma_cross_medium"] = "MA20死叉MA60↓"
                        s -= 1.0

        # MACD — 细化 6 档
        if md and len(md) > 0:
            m = md[-1]
            hi = m.get("macd_hist", (m["dif"] - m["dea"]) * 2)
            d["mh"] = round(hi, 4)
            if len(md) >= 2:
                pm = md[-2]
                ph = pm.get("macd_hist", (pm["dif"] - pm["dea"]) * 2)
                if ph < 0 < hi:
                    d["mc"] = "金叉↑"
                    s += 1.2 if hi > 0.5 else 0.8
                elif ph > 0 > hi:
                    d["mc"] = "死叉↓"
                    s -= 1.2 if hi < -0.5 else 0.8
                elif hi > 0:
                    s += 0.3
                else:
                    s -= 0.3
            elif hi > 0:
                s += 0.3
            else:
                s -= 0.3
            d["mc"] = d.get("mc", "无交叉")

        # 缠论信号 — 从 chan_risk_assessment 的 buy_sell_points 提取买卖点
        cv_data = cv if isinstance(cv, dict) else {}
        buy_pts = cv_data.get("buy_sell_points", {}).get("buy_points", [])
        sell_pts = cv_data.get("buy_sell_points", {}).get("sell_points", [])
        sig = ""
        if buy_pts:
            top_level = max(bp.get("level", "weak") for bp in buy_pts)
            sig = f"买点({top_level})"
            s += 1.5 if top_level == "strong" else 1.0
        elif sell_pts:
            top_level = max(sp.get("level", "potential") for sp in sell_pts)
            sig = f"卖点({top_level})"
            s -= 1.5 if top_level == "strong" else 1.0
        else:
            # 无明确买卖点，用 chan_verdict 补充趋势判断
            cv_verdict = cv_data.get("chan_verdict", "")
            if "偏多" in cv_verdict:
                sig = "趋势偏多"
                s += 0.3
            elif "偏空" in cv_verdict:
                sig = "趋势偏空"
                s -= 0.3
            else:
                sig = "中性震荡"
        d["v"] = sig

        # ── 深度缠论数据（2026-07-21 新增） ──
        # 最近底分型 / 顶分型
        fractals = cv_data.get("fractals", [])
        if fractals:
            # 最近一个底分型
            bottom_fx = [f for f in fractals if f.get("type") == "bottom"][-1]
            d["day_bottom_fx"] = bottom_fx.get("low")
            d["day_bottom_fx_date"] = bottom_fx.get("date", "")
            # 最近一个顶分型
            top_fx = [f for f in fractals if f.get("type") == "top"][-1]
            d["day_top_fx"] = top_fx.get("high")
            # 是否站上 MA5（底分型后价格站上 MA5）
            if m5 and bottom_fx.get("low"):
                d["day_above_ma5"] = close > m5

        # 最近一笔方向
        strokes = cv_data.get("strokes", [])
        if strokes:
            last_bi = strokes[-1]
            d["day_last_bi_dir"] = last_bi.get("direction", "")

        # 买卖点详情
        bs_parts = []
        for bp in buy_pts:
            bs_parts.append(f"{bp.get('type','')}-{bp.get('level','')}")
        for sp in sell_pts:
            bs_parts.append(f"{sp.get('type','')}-{sp.get('level','')}")
        d["buy_sell_detail"] = "; ".join(bs_parts) if bs_parts else "无"

        # 背驰详情
        div_parts = []
        for div in cv_data.get("divergences", []):
            div_parts.append(f"{div.get('type','')}({div.get('severity','')})")
        d["divergence_detail"] = "; ".join(div_parts) if div_parts else "无"

        # 缠论综合结论
        d["chan_verdict"] = cv_data.get("chan_verdict", "")
    except Exception as e:
        d["e"] = str(e)
    return s, d  # 未clamp，百分位排名会处理归一化


def _raw_score_one(
    p: Dict[str, Any],
    kl: List[Dict],
    industry_thresholds: Dict[str, int],
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    market: str = "hk",
) -> Dict[str, Any]:
    """计算单只股票的原始分（fb/hot/ch，未做百分位排名）。"""
    c = p["c"]
    pe_limit = industry_thresholds.get(p.get("s", "其他"), 60)

    fb, fb_debug = fb_score(p, p.get("s", "其他"), pe_limit)
    hot = hot_score(p, kl, sector_ranking, market)
    ch, cd = chan_score(p, kl)

    return {
        "c": c, "n": p["n"], "s": p["s"], "p": p["p"], "mc": p["mc"], "pe": p["pe"],
        "fb_raw": fb, "hot_raw": hot, "ch_raw": ch,
        "fb_debug": fb_debug,
        "pw": p.get("pw", ""), "ny": p.get("ny"), "rev": p.get("rev"),
        "q": p.get("q", {}), "ind": p.get("ind", {}), "kl": kl, "cd": cd,
    }


def percentile_score_all(
    raw_scores: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """对所有已算好原始分的候选股做池内百分位排名，归一化到 1-5。

    Args:
        raw_scores: _raw_score_one 的返回结果列表，每项含 fb_raw/hot_raw/ch_raw。

    返回:
        按总分降序排列的 scored 列表，每项含 fb/hot/ch/total/advice。
    """
    if not raw_scores:
        return []

    fb_raws = [r["fb_raw"] for r in raw_scores]
    hot_raws = [r["hot_raw"] for r in raw_scores]
    ch_raws = [r["ch_raw"] for r in raw_scores]

    for r in raw_scores:
        fb_pct = _percentile(fb_raws, r["fb_raw"])
        hot_pct = _percentile(hot_raws, r["hot_raw"])
        ch_pct = _percentile(ch_raws, r["ch_raw"])
        # 百分位 0~1 映射到 1~5
        r["fb"] = round(1 + fb_pct * 4, 1)
        r["hot"] = round(1 + hot_pct * 4, 1)
        r["ch"] = round(1 + ch_pct * 4, 1)
        # 加权得分：基本面60分(×12) + 技术面40分(hot×4 + ch×4) = 100分
        r["fb_w"] = round(r["fb"] * 12, 1)
        r["hot_w"] = round(r["hot"] * 4, 1)
        r["ch_w"] = round(r["ch"] * 4, 1)
        r["total"] = round(r["fb_w"] + r["hot_w"] + r["ch_w"], 1)
        # 建议（按100分制）
        t = r["total"]
        if t >= 70: r["advice"] = "强烈关注"
        elif t >= 56: r["advice"] = "可关注"
        elif t >= 44: r["advice"] = "观察"
        else: r["advice"] = "回避"

    return sorted(raw_scores, key=lambda r: r["total"], reverse=True)


def score_one(
    p: Dict[str, Any],
    kl: List[Dict],
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    industry_thresholds: Dict[str, int] = None,
    market: str = "hk",
) -> Dict[str, Any]:
    """单只股票三维评分。"""
    c = p["c"]
    pe_limit = (industry_thresholds or {}).get(p.get("s", "其他"), 60)

    fb, _ = fb_score(p, p.get("s", "其他"), pe_limit)
    fb = _clamp(fb)
    hot = _clamp(hot_score(p, kl, sector_ranking, market))
    ch, cd = _clamp(chan_score(p, kl)[0]), chan_score(p, kl)[1]
    fb_w = round(fb * 12, 1)
    hot_w = round(hot * 4, 1)
    ch_w = round(ch * 4, 1)
    total = round(fb_w + hot_w + ch_w, 1)

    return {
        "c": c, "n": p["n"], "s": p["s"], "p": p["p"], "mc": p["mc"], "pe": p["pe"],
        "fb": fb, "hot": hot, "ch": ch, "total": total,
        "fb_w": fb_w, "hot_w": hot_w, "ch_w": ch_w,
        "pw": p.get("pw", ""),
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
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    vetoed: Optional[List[Tuple[str, str, str]]] = None,
) -> dict:
    """将内部数据结构转为 format_output() 所需的 JSON Schema。

    Args:
        vetoed: 基本面一票否决的标的 [(code, name, reason)]，追加到 eliminated 之前展示
    """
    from scripts.quantrisk.indicators import calc_stop_loss_take_profit

    top10 = scored[:10]

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
        advice = "强烈关注" if t >= 70 else ("可关注" if t >= 56 else ("观察" if t >= 44 else "回避"))
        top10_data.append({
            "rank": i + 1,
            "code": s["c"],
            "name": s["n"],
            "sector": s["s"],
            "fb": s["fb"],
            "hot": s["hot"],
            "ch": s["ch"],
            "fb_w": s.get("fb_w", round(s["fb"] * 12, 1)),
            "hot_w": s.get("hot_w", round(s["hot"] * 4, 1)),
            "ch_w": s.get("ch_w", round(s["ch"] * 4, 1)),
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
        advice = ("强烈关注，适合布局" if t >= 70 else
                  "可适当关注，等待入场时机" if t >= 56 else
                  "纳入观察清单，等待催化剂" if t >= 44 else "暂时回避，等待改善")

        # 热点描述 — 基于近5日成交额变化+收盘价变化
        kl_s = s.get("kl", [])
        vol_5d_ratio = 1.0
        pct_5d = 0.0
        if kl_s and len(kl_s) >= 10:
            recent_5_vol = sum(k.get("volume", 0) or 0 for k in kl_s[-5:])
            prev_5_vol = sum(k.get("volume", 0) or 0 for k in kl_s[-10:-5])
            if prev_5_vol > 0 and recent_5_vol > 0:
                vol_5d_ratio = recent_5_vol / prev_5_vol
        if kl_s and len(kl_s) >= 6:
            c5 = kl_s[-6].get("close", 0) or 0
            c0 = kl_s[-1].get("close", 0) or 0
            if c5 > 0:
                pct_5d = (c0 - c5) / c5 * 100

        # 量比描述
        if vol_5d_ratio > 2.0:
            vol_desc = f"放巨量({vol_5d_ratio:.1f}x)"
        elif vol_5d_ratio > 1.5:
            vol_desc = f"放量({vol_5d_ratio:.1f}x)"
        elif vol_5d_ratio < 0.5:
            vol_desc = f"缩量({vol_5d_ratio:.1f}x)"
        else:
            vol_desc = f"量平({vol_5d_ratio:.1f}x)"

        pct_desc = f"{'%2B' if pct_5d >= 0 else ''}{pct_5d:.2f}%"
        hot_desc = f"{s['s']}板块 5日量{vol_desc} | 5日涨幅{pct_desc}"

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
            "take_profit": tp_point,
            "total": s["total"],
            "fb": {
                "score": s["fb"],
                "score_w": s.get("fb_w", round(s["fb"] * 12, 1)),
                "debug": s.get("fb_debug", ""),
                "pe": s.get("pe", "?"),
                "revenue_yoy": s.get("rev", "?"),
                "net_profit_yoy": s.get("ny", "?"),
                "roe": ind.get("ROE") or ind.get("JQROE") or "?",
                "gross_margin": ind.get("GROSS_PROFIT_RATIO") or "?",
                "debt_ratio": ind.get("DEBT_ASSET_RATIO") or "?",
            },
            "hot": {
                "score": s["hot"],
                "score_w": s.get("hot_w", round(s["hot"] * 4, 1)),
                "desc": hot_desc,
            },
            "ch": {
                "score": s["ch"],
                "score_w": s.get("ch_w", round(s["ch"] * 4, 1)),
                "ma60": ma60,
                "price": s.get("p"),
                "macd_hist": macd_hist,
                "signal": sig,
                "ma_alignment": d.get("ma_alignment", ""),
                "ma_trend": d.get("ma_trend", ""),
                "mc": d.get("mc", ""),
                "ma_pos_summary": d.get("ma_pos_summary", ""),
                "ma_cross_short": d.get("ma_cross_short", ""),
                "ma_cross_medium": d.get("ma_cross_medium", ""),
                # 深度缠论（2026-07-21 新增）
                "week_ma60": d.get("week_ma60", "?"),
                "week_chan_verdict": d.get("week_chan_verdict", ""),
                "day_ma5": d.get("ma5", "?"),
                "day_bottom_fx": d.get("day_bottom_fx", "?"),
                "day_top_fx": d.get("day_top_fx", "?"),
                "day_bottom_fx_date": d.get("day_bottom_fx_date", ""),
                "day_last_bi_dir": d.get("day_last_bi_dir", ""),
                "day_above_ma5": bool(d.get("day_above_ma5", False)),
                "buy_sell_detail": d.get("buy_sell_detail", ""),
                "divergence_detail": d.get("divergence_detail", ""),
                "chan_verdict": d.get("chan_verdict", ""),
            },
            "vol_5d_ratio": round(vol_5d_ratio, 2),
            "pct_5d": round(pct_5d, 2),
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
        advice = "强烈关注" if t >= 70 else ("可关注" if t >= 56 else ("观察" if t >= 44 else "回避"))
        summary_data.append({
            "code": f"{s['c']} {s['n']}",
            "advice": advice,
            "buy": s.get("p"),
            "stop_loss": sl_point,
            "take_profit": tp_point,
        })

    # 基本面一票否决记录
    vetoed_data = [{"code": c, "name": n, "reason": r} for c, n, r in (vetoed or [])]

    return {
        "date": ds,
        "sectors": sectors_data,
        "eliminated": eliminated_data,
        "vetoed": vetoed_data,
        "passed_count": passed_cnt,
        "top10": top10_data,
        "details": details_data,
        "summary": summary_data,
    }
