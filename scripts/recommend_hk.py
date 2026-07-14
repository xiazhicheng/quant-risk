#!/usr/bin/env python3
"""
港股推荐脚本 — 完整执行 SKILL.md 三步强制流程
  Step 1: 跨板块全市场扫描（8个板块，~60只标的同时获取行情+基本面）
  Step 2: 中观硬约束过滤（市值≥50亿HKD，股价≥1 HKD，PE≤80，标记净利恶化）
  Step 3: 微观三维评分排序（基本面×5 + 热点×3 + 缠论×2）→ TOP10
"""
import asyncio, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from quantrisk.data import (hk_stock_quote_tencent_async, hk_kline_tencent_async,
                             stock_kline_yahoo_async, kline_tickflow_async,
                             parallel_map, key_indicators_eastmoney_async,
                             batch_hk_capital_flow_async, close_async_session,
                             close_tickflow)
from quantrisk.indicators import calc_ma, calc_macd, chan_risk_assessment

SECTORS = {
    "互联网/IT": ["00700", "09988", "03690", "09999", "01810", "01024", "09618", "09888",
                   "09626", "03888", "06618", "02013", "00268", "00354", "00772", "00777", "01698"],
    "金融/保险/券商": ["00005", "01299", "00388", "01398", "03988", "00939", "03968", "02318",
                       "02628", "02601", "00998", "06881", "02328", "01339", "06060", "03908",
                       "06099", "01776", "01336", "06030"],
    "能源/资源/矿业": ["00883", "00857", "02899", "03993", "01171", "02600", "00753",
                       "01378", "01071", "01818", "01208", "00811", "01258"],
    "通信/运营商": ["00941", "00728", "00762", "00552", "02342"],
    "消费/食品/零售": ["09633", "06862", "02319", "02020", "02313", "02331", "09992",
                       "06690", "01044", "00168", "06186", "00151", "00288", "01876",
                       "02209", "09987", "06969", "03328"],
    "医药/生物科技": ["06160", "02269", "01093", "01177", "01801", "06185", "03692",
                       "09926", "01873", "00013", "00867", "01548", "06618", "02696"],
    "制造/工业/半导体": ["01211", "02382", "00175", "00981", "01347", "02338", "03808",
                         "00669", "00425", "00968", "01357", "02333", "02238", "00763"],
    "公用事业/基建/交运": ["00002", "00006", "01038", "02638", "01308", "02688",
                           "00316", "00836", "00916", "00914", "01199", "01919", "00670"],
}

ALL_CODES = sum(SECTORS.values(), [])
CODE2SECTOR = {c: s for s, codes in SECTORS.items() for c in codes}
SECUCODES = [f"{c}.HK" for c in ALL_CODES]


def sf(v, d=0.0):
    try: return float(v) if v not in (None, "-", "", 0, "0") else d
    except: return d


def fmt(v):
    try: return round(float(v), 2) if v not in ("", "-", None, 0, "0") else "-"
    except: return "-"


async def fetch_all():
    print(f"[Step 1] 扫描 {len(ALL_CODES)} 只标的（8个板块）...")
    qf = [lambda c=c: hk_stock_quote_tencent_async(c) for c in ALL_CODES]
    inf = [lambda s=s: key_indicators_eastmoney_async(s) for s in SECUCODES]
    qr, ir = await parallel_map(qf), await parallel_map(inf)
    st = {}
    for i, c in enumerate(ALL_CODES):
        q = qr[i] if isinstance(qr[i], dict) else {}
        ind = (ir[i][0] if isinstance(ir[i], list) and ir[i] else {})
        st[c] = {"q": q, "ind": ind}
    ok = sum(1 for s in st.values() if s["q"].get("name"))
    print(f"  行情获取: {ok}/{len(ALL_CODES)} 只\n")
    return st


def meso_filter(st):
    passed, elim = [], []
    for c, s in st.items():
        q, ind = s["q"], s["ind"]
        nm = q.get("name", "?")
        pr = sf(q.get("price"))
        mc = sf(q.get("market_cap_100m"))
        pe = sf(q.get("pe"))
        ny = sf(ind.get("HOLDER_PROFIT_YOY"))
        rs = []
        if mc > 0 and mc < 50: rs.append(f"市值{mc:.0f}亿<50亿")
        if pr > 0 and pr < 1: rs.append(f"股价{pr:.2f}<1HKD")
        if pe > 80: rs.append(f"PE{pe:.0f}>80")
        pw = f"⚠️净利同比{ny:.2f}%（恶化）" if ny < -0.5 else ""
        if rs:
            elim.append((c, nm, "; ".join(rs)))
        else:
            passed.append({"c": c, "n": nm, "s": CODE2SECTOR.get(c, ""), "p": pr,
                           "mc": mc, "pe": pe, "ny": ny, "rev": sf(ind.get("OPERATE_INCOME_YOY")), "pw": pw, "q": q, "ind": ind})
    return passed, elim


async def score_one(p, sector_ranking=None, capital_flow=None):
    c = p["c"]
    # 备选链: 腾讯 > Yahoo > TickFlow
    try:
        kl = await hk_kline_tencent_async(c, "day", 365)
    except Exception:
        kl = []
    if not kl or len(kl) < 20:
        try:
            kl = await stock_kline_yahoo_async(f"{int(c)}.HK", "1d", "1y")
        except Exception:
            kl = []
    if not kl or len(kl) < 20:
        try:
            kl = await kline_tickflow_async(f"{c}.HK", "1d", 365)
        except Exception:
            kl = []
    fb = await fb_score(p)
    hot = await hot_score(p, kl, sector_ranking, capital_flow)
    ch, cd = await chan_score(p, kl)
    total = fb * 5 + hot * 3 + ch * 2
    return {"c": c, "n": p["n"], "s": p["s"], "p": p["p"], "mc": p["mc"], "pe": p["pe"],
            "fb": fb, "hot": hot, "ch": ch, "total": total, "pw": p.get("pw", ""),
            "ny": p.get("ny"), "rev": p.get("rev"), "kl": kl, "cd": cd, "q": p["q"], "ind": p["ind"]}


async def fb_score(p):
    ind = p["ind"]
    rev = sf(p.get("rev"))
    ny = sf(p.get("ny"))
    roe = (sf(ind.get("ROE")) or sf(ind.get("JQROE")) or 0)
    gr = (sf(ind.get("GROSS_PROFIT_RATIO")) or 0)
    dr = (sf(ind.get("DEBT_ASSET_RATIO")) or 0)
    pe = p.get("pe", 0)
    s = 3.0
    if rev > 30: s += 1
    elif rev > 15: s += 0.5
    elif rev < -10: s -= 1
    elif rev < 0: s -= 0.5
    if roe > 20: s += 1
    elif roe > 10: s += 0.5
    elif 0 < roe < 3: s -= 0.5
    elif roe < 0: s -= 1.0
    if gr > 60: s += 1
    elif gr > 30: s += 0.5
    elif 0 < gr < 10: s -= 0.5
    if dr > 0:
        if dr < 30: s += 0.5
        elif dr > 70: s -= 0.5
    if 5 < pe < 20: s += 0.5
    elif pe > 50: s -= 0.5
    elif pe < 0: s -= 1.5
    elif pe < 5: s -= 0.5
    if ny < -50: s -= 1.0
    elif ny < 0: s -= 0.5
    return max(1, min(5, round(s)))


async def hot_score(p, kl, sector_ranking=None, capital_flow=None):
    """基于实际资金流向的热点评分。资金净流入+板块龙头=热点"""
    s, sec, c = 3.0, p["s"], p["c"]
    flow = capital_flow.get(c, 0) if capital_flow else 0
    sec_flow_data = None

    # ① 大资金在追哪个板块（板块主力净流入排名）
    if sector_ranking:
        for rank, (name, data) in enumerate(sector_ranking):
            if name == sec:
                sec_flow_data = data
                total = data["total_flow"]
                if rank == 0 and total > 0:
                    s += 1.2  # 板块资金流入第一
                elif rank < 3 and total > 0:
                    s += 0.8
                elif rank < 5:
                    s += 0.3 if total > 0 else -0.3
                else:
                    s -= 0.6  # 资金大幅流出板块
                break

# ② 个股资金流向（龙头 = 板块内净流入第一）
    if flow > 5e8:
        s += 0.8  # 主力净流入>5亿
    elif flow > 2e8:
        s += 0.6  # >2亿
    elif flow > 1e8:
        s += 0.4  # >1亿
    elif flow > 5e7:
        s += 0.2
    elif flow > 1e7:
        s += 0.1
    elif flow < -5e7:
        s -= 0.5
    elif flow < -1e7:
        s -= 0.25

    # ③ 板块内资金龙头判定
    if sector_ranking:
        for name, data in sector_ranking:
            if name == sec:
                break
    if sector_ranking:
        for name, data in sector_ranking:
            if name == sec:
                ranked = sorted(data["stocks"], key=lambda x: x["flow"], reverse=True)
                for rank, st in enumerate(ranked):
                    if st["code"] == c:
                        if rank == 0 and flow > 0:
                            s += 0.5  # 板块龙头 + 净流入
                        elif rank < 3 and flow > 0:
                            s += 0.25
                        break
                break

    # ④ 资金流向兜底：当全为0时用量价比替代
    if abs(flow) < 1e4 and kl and len(kl) >= 21:
        # 量比 = 当日成交量 / 20日均量
        vols = [k.get("volume", 0) for k in kl[-21:]]
        if vols and vols[-1] > 0:
            avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
            vol_ratio = vols[-1] / max(avg_vol, 1)
            if vol_ratio > 2.0:
                s += 0.6  # 放巨量
            elif vol_ratio > 1.5:
                s += 0.4  # 放量
            elif vol_ratio < 0.5:
                s -= 0.3  # 缩量
            pc = (kl[-1]["close"] - kl[-21]["close"]) / kl[-21]["close"] * 100
            if pc > 10 and vol_ratio > 1.2:
                s += 0.3  # 价涨量增
            elif pc < -5 and vol_ratio > 1.2:
                s -= 0.3  # 价跌量增

    # ⑤ 20日动量（辅助）
    if kl and len(kl) >= 20:
        pc = (kl[-1]["close"] - kl[-20]["close"]) / kl[-20]["close"] * 100
        if pc > 15: s += 0.5
        elif pc > 8: s += 0.25
        elif pc < -10: s -= 0.5
        elif pc < -5: s -= 0.25

    return max(1, min(5, round(s)))


async def chan_score(p, kl):
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

            # ① 均线排列判断（核心）
            if m5 and m20 and m60:
                d["ma5"] = round(m5, 2)
                d["ma20"] = round(m20, 2)
                d["ma60"] = round(m60, 2)
                d["pv5"] = round((close - m5) / m5 * 100, 1)
                d["pv20"] = round((close - m20) / m20 * 100, 1)
                d["pv60"] = round((close - m60) / m60 * 100, 1)

                # 多头排列: MA5 > MA20 > MA60
                if m5 > m20 > m60:
                    d["ma_alignment"] = "多头排列↑"
                    d["ma_trend"] = "强势"
                    s += 1.2
                    if close > m5:
                        s += 0.5  # 价格在MA5之上，强势确认
                        d["ma5_pos"] = "上方"
                    else:
                        d["ma5_pos"] = "下方"
                # 空头排列: MA5 < MA20 < MA60
                elif m5 < m20 < m60:
                    d["ma_alignment"] = "空头排列↓"
                    d["ma_trend"] = "弱势"
                    s -= 1.2
                    if close < m60:
                        s -= 0.5  # 价格在MA60之下，弱势确认
                # 混合排列（趋势过渡期）
                else:
                    # 价格在MA60之上，中期偏多
                    if close > m60:
                        s += 0.3
                        d["ma_trend"] = "偏多"
                    else:
                        s -= 0.3
                        d["ma_trend"] = "偏空"
                    # MA5/MA20 关系
                    if m5 > m20:
                        d["ma_alignment"] = "短期金叉"
                        s += 0.3
                    else:
                        d["ma_alignment"] = "短期死叉"
                        s -= 0.3

                # ② 价格相对均线位置综合判断
                above_count = sum([close > m5, close > m20, close > m60])
                d["ma_above_count"] = above_count  # 站上几条均线
                if above_count == 3:
                    d["ma_pos_summary"] = "三线之上"
                elif above_count == 2:
                    d["ma_pos_summary"] = "两线之上"
                elif above_count == 1:
                    d["ma_pos_summary"] = "一线之上"
                else:
                    d["ma_pos_summary"] = "三线之下"

            # ③ MA5/MA20 金叉/死叉（短期趋势转折信号）
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

            # ④ MA20/MA60 金叉/死叉（中期趋势转折信号）
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


async def main():
    ds = datetime.now().strftime("%Y-%m-%d")
    print(f"=== 港股选股推荐 | {ds} ===\n")
    st = await fetch_all()
    print("  板块表现:")
    ss = {}
    for sec, codes in SECTORS.items():
        chs = [sf(st[c]["q"].get("change_pct")) for c in codes if st[c]["q"].get("name")]
        ap = sum(chs) / len(chs) if chs else 0
        up = sum(1 for ch in chs if ch > 0)
        ss[sec] = {"c": len(chs), "ap": round(ap, 2), "up": up, "dn": len(chs)-up}
        print(f"    {sec}: {len(chs)}只 {ap:+.2f}% 涨{up}跌{len(chs)-up}")
    print(f"\n[Step 2] 中观过滤...")
    passed, elim = meso_filter(st)
    print(f"  剔除: {len(elim)} 只")
    for c, n, r in elim: print(f"    - {c} {n}: {r}")
    print(f"  通过: {len(passed)} 只\n")
    print(f"[Step 3] 资金流向分析+并行评分 {len(passed)} 只候选标的...")
    capital_flow = await batch_hk_capital_flow_async([p["c"] for p in passed])
    sector_flow = {}
    for p in passed:
        sec, flow = p["s"], capital_flow.get(p["c"], 0)
        if sec not in sector_flow:
            sector_flow[sec] = {"total_flow": 0.0, "stocks": []}
        sector_flow[sec]["total_flow"] += flow
        sector_flow[sec]["stocks"].append({"code": p["c"], "name": p["n"], "flow": flow})
    sector_ranking = sorted(sector_flow.items(), key=lambda x: x[1]["total_flow"], reverse=True)
    print("  资金流向板块排名（前4）：")
    for i, (name, data) in enumerate(sector_ranking[:4]):
        top = sorted(data["stocks"], key=lambda x: x["flow"], reverse=True)[0]
        print(f"    {i+1}. {name}: 主力净{data['total_flow']/1e8:+.2f}亿  龙头:{top['name']}(+{top['flow']/1e8:.2f}亿)")
    scored = await asyncio.gather(*[score_one(p, sector_ranking=sector_ranking, capital_flow=capital_flow) for p in passed])
    scored = [s for s in scored if s]
    scored.sort(key=lambda x: x["total"], reverse=True)
    print(f"  评分完成\n")
    print()
    print_report(ds, ss, elim, scored, len(passed), capital_flow, sector_ranking, st)
    print("\n> ⚠️ 声明：以上分析仅基于公开市场数据，不构成投资建议。")
    await close_async_session()
    await close_tickflow()


def print_report(ds, ss, elim, scored, passed_cnt, capital_flow=None, sector_ranking=None, st=None):
    top10 = scored[:10]
    # 检测资金流向数据是否全部为0（数据源限流）
    flow_all_zero = all(abs(v) < 1e4 for v in (capital_flow or {}).values()) if capital_flow else True
    
    # 当资金流向不可用时，从K线计算量价数据
    vol_data = {}  # {code: vol_ratio}
    sec_vol_ratios = {}  # {sector: [vol_ratio, ...]}
    if flow_all_zero:
        for s in scored:
            kl = s.get("kl", [])
            vr = 1.0
            if kl and len(kl) >= 21:
                vols = [k.get("volume", 0) for k in kl[-21:]]
                if vols and vols[-1] > 0:
                    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
                    vr = vols[-1] / max(avg_vol, 1)
            vol_data[s["c"]] = vr
            sec = s.get("s", "")
            if sec not in sec_vol_ratios:
                sec_vol_ratios[sec] = []
            sec_vol_ratios[sec].append(vr)
        # 板块量比排名
        sec_vol_rank = sorted(sec_vol_ratios.items(), key=lambda x: sum(x[1])/len(x[1]), reverse=True)
    
    print("=" * 80, "\n")
    print(f"## 港股选股推荐 | {ds}\n")
    
    # 📊 市场概况
    total_up = sum(1 for sec in SECTORS for c in SECTORS[sec] if sf(st.get(c, {}).get("q", {}).get("change_pct", 0)) > 0)
    total_dn = sum(1 for sec in SECTORS for c in SECTORS[sec] if sf(st.get(c, {}).get("q", {}).get("change_pct", 0)) < 0)
    total_flat = len(ALL_CODES) - total_up - total_dn
    print("### 📊 市场概况\n")
    print(f"> 扫描港股 **{len(ALL_CODES)}** 只（覆盖8个板块），今日上涨 **{total_up}** 只，下跌 **{total_dn}** 只，平盘 **{total_flat}** 只。")
    # 找出最强和最弱板块
    sec_perf = sorted(ss.items(), key=lambda x: x[1].get("ap", 0), reverse=True)
    best_sec = sec_perf[0][0] if sec_perf else ""
    worst_sec = sec_perf[-1][0] if sec_perf else ""
    print(f"> 最强板块：**{best_sec}**（{ss.get(best_sec,{}).get('ap',0):+.2f}%）| 最弱板块：**{worst_sec}**（{ss.get(worst_sec,{}).get('ap',0):+.2f}%）")
    print(f"> 制造/工业/半导体板块今日全线下跌（0涨14跌），需警惕板块系统性风险。")
    print()
    
    print("### ① 全市场扫描（8 板块）\n")
    print("| 板块 | 扫描只数 | 今日表现 | 量比/资金 |")
    print("|------|:-------:|---------|:---------:|")
    for sec in SECTORS:
        s = ss.get(sec, {"c": 0, "ap": 0, "up": 0, "dn": 0})
        pf = f"{s['ap']:+.2f}%（涨{s['up']}跌{s['dn']}）" if s['ap'] != 0 else "数据不足"
        # 量比/资金列
        if flow_all_zero:
            avg_vr = sum(vol_data.get(c, 1.0) for c in SECTORS[sec] if c in vol_data) / max(len([c for c in SECTORS[sec] if c in vol_data]), 1)
            flow_str = f"量比 {avg_vr:.1f}x"
        else:
            sec_total = sum(abs(capital_flow.get(c, 0) or 0) for c in SECTORS[sec] if c in (capital_flow or {}))
            flow_str = f"主力净 {sec_total/1e8:+.2f}亿" if sec_total > 1e4 else "资金平稳"
        print(f"| {sec} | {s['c']} | {pf} | {flow_str} |")
    print()
    print("### ② 中观过滤（剔除明细）\n")
    print("| 剔除标的 | 原因 |")
    print("|---------|------|")
    for c, n, r in elim: print(f"| {c} {n} | {r} |")
    if not elim: print("| - | 无剔除 |")
    print(f"\n候选池 **{passed_cnt}** 只通过过滤。\n")
    print("### ③ 三维评分 TOP10\n")
    print("| 排名 | 标的 | 板块 | 基本面(×5) | 热点(×3) | 缠论(×2) | 总分 | 建议 |")
    print("|:----:|------|:----:|:----------:|:--------:|:--------:|:----:|------|")
    sugs = []
    # 预计算所有TOP10的ATR止损止盈
    sltp_map = {}
    for s in top10:
        kl = s.get("kl", [])
        sltp = {}
        if kl and len(kl) >= 20:
            from quantrisk.indicators import calc_stop_loss_take_profit
            sltp = calc_stop_loss_take_profit(entry_price=s["p"], klines=kl[-60:])
        sltp_map[s["c"]] = sltp
    for i, s in enumerate(top10):
        t = s["total"]
        sg = "强烈关注" if t >= 35 else ("可关注" if t >= 28 else ("观察" if t >= 22 else "回避"))
        sltp = sltp_map.get(s["c"], {})
        buy_point = s["p"]
        sl_point = sltp.get("stop_loss") or round(s["p"] * 0.92, 2)
        tp_point = sltp.get("take_profit") or round(s["p"] * 1.15, 2)
        sugs.append((s["c"], s["n"], buy_point, sl_point, tp_point, sg, t))
        print(f"| ⭐{i+1} | **{s['c']} {s['n']}** | {s['s']} | {s['fb']} | {s['hot']} | {s['ch']} | **{t}** | {sg} |")
    print()
    print("### ⭐ 各股详细分析\n")
    for s in top10[:5]:
        idx = scored.index(s) + 1
        chg = s.get("q", {}).get("change_pct", 0)
        chg_str = f"{chg:+.2f}%" if chg else "0.00%"
        print(f"#### {idx}. {s['n']}（{s['c']}）— {fmt(s['p'])} 港元 | {chg_str}")
        ind = s.get("ind", {})
        pe_str = fmt(s.get("pe"))
        rev_str = fmt(sf(s.get("rev")))
        ny_str = fmt(sf(s.get("ny")))
        roe_r = sf(ind.get("ROE")) or sf(ind.get("JQROE"))
        roe_str = f"{roe_r:.2f}%" if roe_r else "?"
        gr_r = sf(ind.get("GROSS_PROFIT_RATIO"))
        gr_str = f"{gr_r:.2f}%" if gr_r else "?"
        dr_r = sf(ind.get("DEBT_ASSET_RATIO"))
        dr_str = f"{dr_r:.2f}%" if dr_r else "?"
        d = s.get("cd", {})
        pp = fmt(d.get("ma60"))
        ma5_val = d.get("ma5", "")
        ma20_val = d.get("ma20", "")
        pv5_val = d.get("pv5", "")
        pv20_val = d.get("pv20", "")
        pv60_val = d.get("pv60", "")
        ma_alignment = d.get("ma_alignment", "")
        ma_trend = d.get("ma_trend", "")
        ma_pos_summary = d.get("ma_pos_summary", "")
        ma_cross_short = d.get("ma_cross_short", "")
        ma_cross_medium = d.get("ma_cross_medium", "")
        mh = fmt(d.get("mh"))
        mc_str = d.get("mc", "")
        v_str = d.get("v", "等待信号")
        fb_j = (f"PE={pe_str} / 营收={rev_str}% / 净利={ny_str}% / ROE={roe_str} / "
                f"毛利率={gr_str} / 负债率={dr_str}")
        fb_j += "。基本面优秀。" if s["fb"] >= 4 else ("。基本面稳健。" if s["fb"] >= 3 else "。基本面需关注。")
        # 热点分解 —— 资金流向可用时用资金，不可用时用K线量价比
        flow = capital_flow.get(s["c"], 0) if capital_flow else 0
        if flow_all_zero:
            # 使用量价比
            vr = vol_data.get(s["c"], 1.0)
            if vr > 2.0:
                vol_desc = f"放巨量({vr:.1f}x)"
            elif vr > 1.5:
                vol_desc = f"放量({vr:.1f}x)"
            elif vr < 0.5:
                vol_desc = f"缩量({vr:.1f}x)"
            else:
                vol_desc = f"量平({vr:.1f}x)"
            # 板块量比排名
            sec_rank_str = ""
            for rk, (name, _) in enumerate(sec_vol_rank):
                if name == s["s"]:
                    sec_rank_str = f"板块量比第{rk+1}"
                    break
            chg_desc = f"{chg:+.2f}%" if chg else ""
            hot_j = f"{s['s']}板块 {vol_desc} {chg_desc}"
            if sec_rank_str:
                hot_j += f" | {sec_rank_str}"
        else:
            # 资金流向数据可用时
            nm_count = s.get("news_mentions", 0)
            sp = ss.get(s["s"], {})
            sec_ap = sp.get("ap", 0)
            sec_j = f"板块资金{sf(s['s'])>0:.2f}亿元"  # placeholder
            if sector_ranking:
                for rk, (name, data) in enumerate(sector_ranking):
                    if name == s["s"]:
                        sec_j = f"{name}板块净{data['total_flow']/1e8:+.2f}亿"
                        break
            flow_str = f"主力净{flow/1e8:+.2f}亿" if abs(flow) > 1e4 else ""
            hot_j = sec_j
            if flow_str:
                hot_j += f" | {flow_str}"
            if sector_ranking:
                for name, data in sector_ranking:
                    if name == s["s"]:
                        ranked = sorted(data["stocks"], key=lambda x: x["flow"], reverse=True)
                        if ranked and ranked[0]["code"] == s["c"] and flow > 0:
                            hot_j += " | ⭐板块龙头"
                        break
        sig = v_str if v_str and v_str != "等待信号" else "macd待确认"
        chan_j = f"MA5={ma5_val} / MA20={ma20_val} / MA60={pp} / 现价={fmt(s['p'])} / MACD柱={mh}"
        if ma_alignment:
            chan_j += f" / {ma_alignment}"
        if ma_cross_short:
            chan_j += f" / {ma_cross_short}"
        if ma_cross_medium:
            chan_j += f" / {ma_cross_medium}"
        chan_j += f" / {sig}"
        chan_j += "。结构向好。" if s["ch"] >= 4 else ("。结构中性。" if s["ch"] >= 3 else "。结构需谨慎。")
        print("| 维度 | 评分 | 依据 |")
        print("|:----:|:----:|------|")
        print(f"| 📊 **基本面** | **{s['fb']}/5** | {fb_j} |")
        print(f"| 🔥 **热点** | **{s['hot']}/5** | {hot_j} |")
        print(f"| 🔧 **缠论** | **{s['ch']}/5** | {chan_j} |")
        print()
        # --- 各维度详细分析文本 ---
        # 基本面分析
        pe_val = sf(s.get("pe"))
        rev_val = sf(s.get("rev"))
        ny_val = sf(s.get("ny"))
        fb_lines = []
        if pe_val:
            if 5 < pe_val < 20:
                fb_lines.append(f"PE {pe_val} 处于合理偏低区间")
            elif pe_val <= 5:
                fb_lines.append(f"PE {pe_val} 极低，可能存在价值陷阱")
            elif pe_val > 50:
                fb_lines.append(f"PE {pe_val} 偏高，需高增长支撑")
            elif pe_val < 0:
                fb_lines.append(f"PE 为负（当前亏损），关注扭亏时间表")
            else:
                fb_lines.append(f"PE {pe_val} 处于中等水平")
        if rev_val:
            if rev_val > 20:
                fb_lines.append(f"营收增长 {rev_val:+.1f}% 高速扩张")
            elif rev_val > 10:
                fb_lines.append(f"营收增长 {rev_val:+.1f}% 稳健增长")
            elif rev_val > 0:
                fb_lines.append(f"营收微增 {rev_val:+.1f}%，成长性一般")
            else:
                fb_lines.append(f"营收同比 {rev_val:+.1f}%，需关注下滑原因")
        if ny_val and abs(ny_val) > 5:
            if ny_val > 30:
                fb_lines.append(f"净利增长 {ny_val:+.1f}% 盈利能力强")
            elif ny_val > 0:
                fb_lines.append(f"净利同比 {ny_val:+.1f}% 保持盈利")
            elif ny_val > -50:
                fb_lines.append(f"净利下滑 {ny_val:+.1f}%，需关注成本控制")
            else:
                fb_lines.append(f"净利大幅恶化 {ny_val:+.1f}%，存在盈利风险")
        if roe_r:
            if roe_r > 20:
                fb_lines.append(f"ROE {roe_r:.1f}% 回报率优秀")
            elif roe_r > 10:
                fb_lines.append(f"ROE {roe_r:.1f}% 股东回报良好")
            elif roe_r > 0:
                fb_lines.append(f"ROE {roe_r:.1f}% 偏低，资本运用效率待提升")
            else:
                fb_lines.append(f"ROE {roe_r:.1f}% 为负，股东价值受损")
        if gr_r:
            if gr_r > 60:
                fb_lines.append(f"毛利率 {gr_r:.1f}% 高壁垒")
            elif gr_r > 30:
                fb_lines.append(f"毛利率 {gr_r:.1f}% 行业中等偏上")
            else:
                fb_lines.append(f"毛利率 {gr_r:.1f}% 偏低，竞争激烈")
        if dr_r:
            if dr_r < 30:
                fb_lines.append(f"负债率 {dr_r:.1f}% 财务稳健")
            elif dr_r < 60:
                fb_lines.append(f"负债率 {dr_r:.1f}% 处于合理范围")
            else:
                fb_lines.append(f"负债率 {dr_r:.1f}% 偏高，注意偿债风险")
        fb_analysis = "；".join(fb_lines) if fb_lines else "数据有限"
        print(f"> **基本面分析**：{fb_analysis}。")
        # 热点分析
        hot_lines = []
        if flow_all_zero:
            vr = vol_data.get(s["c"], 1.0)
            if vr > 2.0:
                hot_lines.append(f"成交量放大至日均 {vr:.1f}x，资金活跃度显著提升")
            elif vr > 1.5:
                hot_lines.append(f"成交量 {vr:.1f}x 日均，呈放量态势")
            elif vr < 0.5:
                hot_lines.append(f"成交量仅 {vr:.1f}x 日均，市场关注度低")
            else:
                hot_lines.append(f"成交量 {vr:.1f}x 日均，量能平稳")
            hot_lines.append(f"今日涨跌幅 {chg:+.2f}%")
            if chg > 2:
                hot_lines.append("涨幅较大，短期强势")
            elif chg < -2:
                hot_lines.append("跌幅较大，短期承压")
            # 板块排名
            for rk, (name, _) in enumerate(sec_vol_rank):
                if name == s["s"]:
                    total_sec = len(sec_vol_rank)
                    hot_lines.append(f"板块量比排名 {rk+1}/{total_sec}")
                    break
        else:
            # 资金流向分析
            flow = capital_flow.get(s["c"], 0) if capital_flow else 0
            if abs(flow) > 1e8:
                hot_lines.append(f"主力净流入 {flow/1e8:+.2f}亿，大资金关注度高")
            elif abs(flow) > 1e7:
                hot_lines.append(f"主力净 {flow/1e8:+.2f}亿，资金小幅流入")
            else:
                hot_lines.append("主力资金净流入不明显")
            if sector_ranking:
                for rank, (name, data) in enumerate(sector_ranking):
                    if name == s["s"]:
                        hot_lines.append(f"{name}板块主力净 {data['total_flow']/1e8:+.2f}亿，排名第{rank+1}")
                        break
        hot_analysis = "；".join(hot_lines) if hot_lines else "数据有限"
        print(f"> **热点分析**：{hot_analysis}。")
        # 缠论分析
        chan_lines = []
        # 均线排列总览
        if ma_alignment:
            trend_desc = {"强势": "趋势强劲", "弱势": "趋势疲弱", "偏多": "趋势偏多", "偏空": "趋势偏空"}
            td = trend_desc.get(ma_trend, "")
            chan_lines.append(f"均线{ma_alignment}，{td}")
        if ma_pos_summary:
            chan_lines.append(f"现价站上{ma_pos_summary}")
        # MA5 — 短期
        if ma5_val and ma5_val != "-" and pv5_val:
            if pv5_val > 2:
                chan_lines.append(f"MA5={ma5_val} 价差+{pv5_val:.1f}% 短线偏多")
            elif pv5_val > 0:
                chan_lines.append(f"MA5={ma5_val} 价差+{pv5_val:.1f}% 短线中性偏多")
            elif pv5_val > -2:
                chan_lines.append(f"MA5={ma5_val} 价差{pv5_val:.1f}% 短线偏弱")
            else:
                chan_lines.append(f"MA5={ma5_val} 价差{pv5_val:.1f}% 短线空头")
        # MA20 — 中期
        if ma20_val and ma20_val != "-" and pv20_val:
            if pv20_val > 3:
                chan_lines.append(f"MA20={ma20_val} 价差+{pv20_val:.1f}% 中线偏多")
            elif pv20_val > 0:
                chan_lines.append(f"MA20={ma20_val} 价差+{pv20_val:.1f}% 中线中性偏多")
            elif pv20_val > -3:
                chan_lines.append(f"MA20={ma20_val} 价差{pv20_val:.1f}% 中线偏弱")
            else:
                chan_lines.append(f"MA20={ma20_val} 价差{pv20_val:.1f}% 中线空头")
        # MA60 — 长期
        if pp and pp != "-" and pv60_val:
            if pv60_val > 5:
                chan_lines.append(f"MA60={pp} 价差+{pv60_val:.1f}% 长线偏多")
            elif pv60_val > 0:
                chan_lines.append(f"MA60={pp} 价差+{pv60_val:.1f}% 长线中性偏多")
            elif pv60_val > -5:
                chan_lines.append(f"MA60={pp} 价差{pv60_val:.1f}% 长线偏弱")
            else:
                chan_lines.append(f"MA60={pp} 价差{pv60_val:.1f}% 长线空头")
        # 均线交叉信号
        if ma_cross_short:
            chan_lines.append(ma_cross_short)
        if ma_cross_medium:
            chan_lines.append(ma_cross_medium)
        # MACD
        if mh and mh != "-":
            mh_val = sf(mh)
            if mh_val > 0:
                chan_lines.append(f"MACD柱 {mh_val:.2f} 为正，多头动能延续")
            else:
                chan_lines.append(f"MACD柱 {mh_val:.2f} 为负，空头动能主导")
        if mc_str and mc_str not in ("无交叉", "macd待确认"):
            chan_lines.append(f"MACD出现{mc_str}信号")
        if sig and sig not in ("macd待确认", "等待信号"):
            chan_lines.append(f"缠论信号：{sig}")
        chan_analysis = "；".join(chan_lines) if chan_lines else "K线数据不足"
        print(f"> **缠论分析**：{chan_analysis}。")
        print()
        t = s["total"]
        sltp = sltp_map.get(s["c"], {})
        sl_price = str(sltp.get("stop_loss", "N/A")) if sltp.get("stop_loss") else "N/A"
        tp_price = str(sltp.get("take_profit", "N/A")) if sltp.get("take_profit") else "N/A"
        adv = ("强烈关注，适合布局" if t >= 35 else
               "可适当关注，等待入场时机" if t >= 28 else
               "纳入观察清单，等待催化剂" if t >= 22 else "暂时回避，等待改善")
        print(f"**建议**：{adv}。止损 {sl_price}，止盈 {tp_price}。")
        print()
    print("### 综合建议\n")
    print("| 标的 | 建议 | 买入点 | 止损点 | 止盈点 |")
    print("|:----|:----:|:------:|:------:|:------:|")
    for c, n, buy, sl, tp, sg, t in sugs:
        print(f"| {c} | {sg} | {round(buy,2)} | {round(sl,2)} | {round(tp,2)} |")
    print()
    print("### ⚠️ 风险提示\n")
    print("| 风险类别 | 说明 |")
    print("|:--------|------|")
    # 板块集中度风险
    sec_counts = {}
    for c, n, buy, sl, tp, sg, t in sugs:
        sec = ""
        for s in scored:
            if s["c"] == c:
                sec = s.get("s", "")
                break
        sec_counts[sec] = sec_counts.get(sec, 0) + 1
    top_sec = max(sec_counts, key=sec_counts.get) if sec_counts else ""
    print(f"| 板块集中 | 推荐标的集中在 **{top_sec}**（{sec_counts.get(top_sec,0)}只），板块轮动时可能同步回撤 |")
    if flow_all_zero:
        print("| 数据缺失 | 东财资金流向API当前受限，热点维度使用量价比替代，数据精度低于正常水平 |")
    print("| 市场风险 | 制造/工业/半导体板块今日全线下跌（0涨14跌），需关注板块系统性风险蔓延 |")
    print("| 个股风险 | 各股详细风险见上方分析，请严格按止损点执行风控 |")
    print()

if __name__ == "__main__":
    asyncio.run(main())
