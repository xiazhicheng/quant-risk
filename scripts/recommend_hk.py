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

from quantrisk.data import (hk_stock_quote_tencent_async, kline_tickflow_async,
                             parallel_map, key_indicators_eastmoney_async,
                             close_async_session, close_tickflow)
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


async def score_one(p):
    c = p["c"]
    kl = await kline_tickflow_async(f"{c}.HK", "1d", 365)
    if not kl or len(kl) < 20:
        try:
            from quantrisk.data import stock_kline_yahoo_async
            kl = await stock_kline_yahoo_async(f"{int(c)}.HK", "1d", "1y")
        except Exception:
            kl = []
    fb = await fb_score(p)
    hot = await hot_score(p, kl)
    ch, cd = await chan_score(p, kl)
    total = fb * 5 + hot * 3 + ch * 2
    return {"c": c, "n": p["n"], "s": p["s"], "p": p["p"], "mc": p["mc"], "pe": p["pe"],
            "fb": fb, "hot": hot, "ch": ch, "total": total, "pw": p.get("pw", ""),
            "ny": p.get("ny"), "rev": p.get("rev"), "kl": kl, "cd": cd, "q": p["q"], "ind": p["ind"]}


async def fb_score(p):
    ind = p["ind"]
    rev = sf(p.get("rev"))
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
    if gr > 60: s += 1
    elif gr > 30: s += 0.5
    elif 0 < gr < 10: s -= 0.5
    if dr > 0:
        if dr < 30: s += 0.5
        elif dr > 70: s -= 0.5
    if 5 < pe < 20: s += 0.5
    elif pe > 50: s -= 0.5
    return max(1, min(5, round(s)))


async def hot_score(p, kl):
    s, sec = 3.0, p["s"]
    hm = {"互联网/IT": 0.5, "消费/食品/零售": 0.3}
    wm = {"公用事业/基建/交运": -0.3, "通信/运营商": -0.3}
    s += hm.get(sec, 0) + wm.get(sec, 0)
    if kl and len(kl) >= 20:
        pc = (kl[-1]["close"] - kl[-20]["close"]) / kl[-20]["close"] * 100
        if pc > 10: s += 1
        elif pc > 5: s += 0.5
        elif pc < -10: s -= 1
        elif pc < -5: s -= 0.5
    amt = sf(p["q"].get("amount_100m"))
    if amt > 30: s += 0.5
    return max(1, min(5, round(s)))


async def chan_score(p, kl):
    if not kl or len(kl) < 30:
        return 3, {}
    s, d = 3.0, {}
    try:
        ma = calc_ma(kl, [60])
        md = calc_macd(kl)
        cv = chan_risk_assessment(kl)
        close = kl[-1]["close"]
        if ma and len(ma) > 0 and ma[-1].get("ma60"):
            m60 = ma[-1]["ma60"]
            d["ma60"] = round(m60, 2)
            d["pv"] = round((close - m60) / m60 * 100, 1)
            if close > m60: s += 0.5
            else: s -= 0.5
        if md and len(md) > 0:
            m = md[-1]
            hi = m.get("histogram", m["macd"] - m["signal"])
            d["mh"] = round(hi, 4)
            if len(md) >= 2:
                pm = md[-2]
                ph = pm.get("histogram", pm["macd"] - pm["signal"])
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
    print(f"[Step 3] 并行评分 {len(passed)} 只候选标的...")
    scored = await asyncio.gather(*[score_one(p) for p in passed])
    scored = [s for s in scored if s]
    scored.sort(key=lambda x: x["total"], reverse=True)
    print(f"  评分完成\n")
    print_report(ds, ss, elim, scored, len(passed))
    print("\n> ⚠️ 声明：以上分析仅基于公开市场数据，不构成投资建议。")
    await close_async_session()
    await close_tickflow()


def print_report(ds, ss, elim, scored, passed_cnt):
    top10 = scored[:10]
    print("=" * 80, "\n")
    print(f"## 港股选股推荐 | {ds}\n")
    print("### ① 全市场扫描（8 板块）\n")
    print("| 板块 | 扫描只数 | 今日表现 |")
    print("|------|:-------:|---------|")
    for sec in SECTORS:
        s = ss.get(sec, {"c": 0, "ap": 0, "up": 0, "dn": 0})
        pf = f"{s['ap']:+.2f}%（涨{s['up']}跌{s['dn']}）" if s['ap'] != 0 else "数据不足"
        print(f"| {sec} | {s['c']} | {pf} |")
    print()
    print("### ② 中观过滤（剔除明细）\n")
    print("| 剔除标的 | 原因 |")
    print("|---------|------|")
    for c, n, r in elim: print(f"| {c} {n} | {r} |")
    if not elim: print("| - | 无剔除 |")
    print(f"\n候选池 **{passed_cnt}** 只通过过滤。\n")
    print("### ⭐ 三维评分 TOP10\n")
    print("| 排名 | 标的 | 板块 | 基本面(×5) | 热点(×3) | 缠论(×2) | 总分 | 建议 |")
    print("|:----:|------|:----:|:----------:|:--------:|:--------:|:----:|------|")
    sugs = []
    for i, s in enumerate(top10):
        t = s["total"]
        sg = "强烈关注" if t >= 35 else ("可关注" if t >= 28 else ("观察" if t >= 22 else "回避"))
        sugs.append((s["c"], s["n"], s["p"], sg, t))
        print(f"| ⭐{i+1} | **{s['c']} {s['n']}** | {s['s']} | {s['fb']} | {s['hot']} | {s['ch']} | **{t}** | {sg} |")
    print()
    for s in top10[:5]:
        idx = scored.index(s) + 1
        print(f"#### {idx}. {s['n']}（{s['c']}）— {fmt(s['p'])} 港元\n")
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
        mh = fmt(d.get("mh"))
        pv = d.get("pv", "")
        mc_str = d.get("mc", "")
        v_str = d.get("v", "等待信号")
        fb_j = (f"营收={rev_str}%/净利={ny_str}%/ROE={roe_str}/"
                f"毛利率={gr_str}/负债率={dr_str}/PE={pe_str}")
        fb_j += "。基本面优秀。" if s["fb"] >= 4 else ("。基本面稳健。" if s["fb"] >= 3 else "。基本面一般。")
        hot_j = f"{s['s']}板块表现{'活跃' if s['hot']>=4 else '温和' if s['hot']>=3 else '偏弱'}"
        chan_j = f"MA60={pp}/现价={fmt(s['p'])}/{pv}%。MACD柱={mh}/{mc_str}/{v_str}"
        chan_j += "。结构向好。" if s["ch"] >= 4 else ("。结构中性。" if s["ch"] >= 3 else "。结构偏空。")
        print("| 维度 | 评分 | 依据 |")
        print("|:----:|:----:|------|")
        print(f"| 📊 **基本面** | **{s['fb']}/5** | {fb_j} |")
        print(f"| 🔥 **热点** | **{s['hot']}/5** | {hot_j} |")
        print(f"| 🔧 **缠论** | **{s['ch']}/5** | {chan_j} |")
        print()
        t = s["total"]
        adv = ("强烈关注，适合布局" if t >= 35 else
               "可适当关注，等待入场时机" if t >= 28 else
               "纳入观察清单，等待催化剂" if t >= 22 else "暂时回避，等待改善")
        print(f"**建议**：{adv}。市值{fmt(s.get('mc'))}亿。")
        kl = s.get("kl", [])
        if kl and len(kl) >= 20:
            from quantrisk.indicators import calc_stop_loss_take_profit
            sltp = calc_stop_loss_take_profit(entry_price=s["p"], klines=kl[-60:])
            print(f"**止损**：{sltp.get('stop_loss', 'N/A')} | **目标**：{sltp.get('take_profit', 'N/A')}")
        print()
    print("### 综合建议\n")
    print("| 标的 | 建议 | 入场区间 | 止损 | 目标 |")
    print("|:----|:----:|:--------:|:----:|:----:|")
    for c, n, p, sg, t in sugs:
        print(f"| {c} | {sg} | {round(p*0.97,2)}-{round(p*1.03,2)} | {round(p*0.92,2)} | {round(p*1.15,2)} |")
    print()

if __name__ == "__main__":
    asyncio.run(main())
