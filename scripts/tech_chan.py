#!/usr/bin/env python3
"""
缠论为核心的技术分析 — 四大师 + 缠论深度分析
输出：分型→笔→中枢→背驰→买卖点 + 周线定势
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.quantrisk.report import StockAnalyzer
from scripts.quantrisk.data import (hk_kline_tencent_async, stock_kline_yahoo_async,
                                     kline_tickflow_async, close_async_session, close_tickflow)
from scripts.quantrisk.chan import chan_theory_full, calc_ma
from scripts.quantrisk.chain_renderer import render_mermaid_raw

def fmt(v, dec=2):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{dec}f}"
    return str(v)

async def fetch_klines(code, period="1d", days=730):
    """多源获取K线"""
    if period == "1wk":
        # 周线：只用 Yahoo，TickFlow 不支持周线
        kl = await stock_kline_yahoo_async(f"{int(code)}.HK", "1wk", f"{max(days//365,2)}y")
        return kl or []
    # 日线
    kl = await stock_kline_yahoo_async(f"{int(code)}.HK", "1d", f"{days//365}y")
    if kl and len(kl) >= 60:
        return kl
    kl = await kline_tickflow_async(f"{code}.HK", "1d", days)
    return kl or []

def _print_industry_chain(mermaid_text: str = "", industry: str = "",
                          bottleneck: str = "", vs_leader: str = ""):
    """输出产业链 Mermaid 全景图 — 由 LLM 传入临时生成"""
    if not mermaid_text:
        return
    if industry:
        print(f"**{industry}**")
        print()
    print(render_mermaid_raw(mermaid_text))
    print()
    if bottleneck:
        print(f"**卡脖子环节**: {bottleneck}")
    if vs_leader:
        print(f"**对标/转型关键**: {vs_leader}")
    print()

async def analyze(code, cost=None, shares=None):
    a = StockAnalyzer()
    try:
        # 获取行情 + 日K + 周K
        result = await a.analyze_hk(code)
        if "error" in result:
            print(f"❌ 分析失败: {result['error']}")
            return
        
        # 获取周K
        week_kl = await fetch_klines(code, "1wk", 520)
        # 获取日K (Yahoo)
        day_kl = await fetch_klines(code, "1d", 730)
        
        quote = result.get("quote", {})
        ind = result.get("indicator", {})
        tech = result.get("technicals", {})
        
        price = quote.get("price", 0)
        name = quote.get("name", code)
        pnl = (price / cost - 1) * 100 if cost and price else None
        
        print(f"\n{'='*65}")
        print(f"  📊 {name}（{code}）— 缠论深度分析")
        if cost:
            print(f"  持仓: {shares or '-'}股 | 成本 {cost} | 现价 {price} | 盈亏 {fmt(pnl)+'%' if pnl else '-'}")
        print(f"{'='*65}\n")
        
        # =====================
        # 0. 产业链Mermaid
        # =====================
        print("## 产业链全景图")
        print()
        # 产业链数据由 LLM 传入（参数链），此处为空待调用方补入
        # _print_industry_chain(mermaid_text=..., industry=..., bottleneck=..., vs_leader=...)
        
        # =====================
        # 1. 周线定大势
        # =====================
        print("## ① 周线定大势")
        print()
        if week_kl and len(week_kl) >= 20:
            w_ma = calc_ma(week_kl, [60])
            w_ma60 = w_ma[-1]["ma60"] if w_ma and w_ma[-1].get("ma60") else None
            w_close = week_kl[-1]["close"]
            w_high = max(k["high"] for k in week_kl[-20:])
            w_low = min(k["low"] for k in week_kl[-20:])
            
            # 周线均线
            if w_ma60 and w_close > w_ma60 * 1.05:
                w_ma_signal = "✅ 偏多（价格在MA60上方 +5%）"
            elif w_ma60 and w_close > w_ma60:
                w_ma_signal = "🟢 偏多（价格在MA60上方）"
            elif w_ma60 and w_close < w_ma60 * 0.95:
                w_ma_signal = "🔴 偏空（价格在MA60下方 -5%）"
            elif w_ma60 and w_close < w_ma60:
                w_ma_signal = "🔵 偏空（价格在MA60下方）"
            else:
                w_ma_signal = "➖ 中性（MA60数据不足）"
            
            # 周线缠论
            w_chan = chan_theory_full(week_kl, min_bi_len=5)
            w_trend = w_chan.get("trend", {}).get("description", "未知")
            w_strokes = w_chan.get("strokes_count", 0)
            w_pivots = w_chan.get("pivots_count", 0)
            w_div = w_chan.get("divergences", [])
            w_bs = w_chan.get("buy_sell_points", {})
            
            print(f"| 指标 | 值 |")
            print(f"|:----|:---|")
            print(f"| 周收盘 | {fmt(w_close)} |")
            if w_ma60:
                print(f"| 周MA60 | {fmt(w_ma60)} |")
            print(f"| 20周区间 | {fmt(w_low)} ~ {fmt(w_high)} |")
            print(f"| MA60判断 | {w_ma_signal} |")
            print(f"| 缠论走势 | {w_trend} |")
            print(f"| 周线笔数 | {w_strokes} |")
            print(f"| 周线中枢 | {w_pivots}个 |")
            
            # 周线背驰
            if w_div:
                for d in w_div:
                    icon = "🔴" if "顶" in d.get("detail","") else "🟢"
                    print(f"| 周线背驰 | {icon} {d.get('detail','')} |")
            
            # 周线买卖点
            if w_bs.get("buy_points"):
                for bp in w_bs["buy_points"]:
                    print(f"| 周线买点 | 🟢 {bp['detail']} |")
            if w_bs.get("sell_points"):
                for sp in w_bs["sell_points"]:
                    print(f"| 周线卖点 | 🔴 {sp['detail']} |")
            
            # 周线中枢详情
            w_pivots_detail = w_chan.get("pivots", [])
            if w_pivots_detail:
                for i, pz in enumerate(w_pivots_detail):
                    print(f"| 中枢{i+1} | ZG={fmt(pz['zg'])} ZD={fmt(pz['zd'])} ZZ={fmt(pz['zz'])} |")
            
            print()
        else:
            print("  周线数据不足（<20根），无法分析\n")
        
        # =====================
        # 2. 日线缠论全分析
        # =====================
        print("## ② 日线缠论全分析")
        print()
        
        if day_kl and len(day_kl) >= 60:
            chan = chan_theory_full(day_kl, min_bi_len=6)
            
            if "error" in chan:
                print(f"  ❌ {chan['error']}\n")
            else:
                trend = chan.get("trend", {})
                fractals = chan.get("fractals", [])
                strokes = chan.get("strokes", [])
                segments = chan.get("segments", [])
                pivots = chan.get("pivots", [])
                divergences = chan.get("divergences", [])
                bs = chan.get("buy_sell_points", {})
                
                # 2a. 走势总览
                print("### ②-a 走势总览")
                print()
                print(f"| 维度 | 值 |")
                print(f"|:----|:---|")
                print(f"| 走势类型 | {trend.get('description','未知')} |")
                print(f"| K线数 | {chan.get('klines_count',0)}（处理后{chan.get('klines_clean_count',0)}） |")
                print(f"| 分型数 | {chan.get('fractals_count',0)} |")
                print(f"| 笔数 | {chan.get('strokes_count',0)} |")
                print(f"| 线段数 | {chan.get('segments_count',0)} |")
                print(f"| 中枢数 | {chan.get('pivots_count',0)} |")
                print()
                
                # 2b. 分型序列
                print("### ②-b 近期分型序列（最近5个）")
                print()
                if fractals:
                    print(f"| 类型 | 日期 | 价格 |")
                    print(f"|:----|:----:|:----:|")
                    for f in fractals[-5:]:
                        icon = "🔺顶" if f["type"] == "top" else "🔻底"
                        print(f"| {icon} | {f['date']} | {fmt(f['fx'])} |")
                print()
                
                # 2c. 笔序列
                print("### ②-c 笔序列（最近全部）")
                print()
                if strokes:
                    print(f"| # | 方向 | 区间 | 高 | 低 | 状态 |")
                    print(f"|:-:|:----:|:----:|:--:|:--:|:----:|")
                    for i, s in enumerate(strokes):
                        icon = "↑" if s["direction"] == "up" else "↓"
                        broken = "💥突破" if s.get("broken") else "正常"
                        print(f"| {i+1} | {icon} | {s['start_date']}~{s['end_date']} | {fmt(s['high'])} | {fmt(s['low'])} | {broken} |")
                    
                    # 最近笔方向判断
                    last_s = strokes[-1]
                    ls_icon = "↑上涨" if last_s["direction"] == "up" else "↓下跌"
                    print(f"\n> **最近笔方向**: {ls_icon}（{last_s['start_date']} ~ {last_s['end_date']}）")
                    if last_s.get("broken"):
                        print(f"> **💥 笔断裂**: {'向上突破创新高' if last_s['direction']=='up' else '向下突破创新低'}")
                print()
                
                # 2d. 中枢
                print("### ②-d 中枢分析")
                print()
                if pivots:
                    for i, pz in enumerate(pivots):
                        print(f"**中枢{i+1}**: {pz['start_date']} ~ {pz['end_date']}（{pz['stroke_count']}笔）")
                        print(f"  - ZG（中枢上沿）: **{fmt(pz['zg'])}**")
                        print(f"  - ZD（中枢下沿）: **{fmt(pz['zd'])}**")
                        print(f"  - ZZ（中枢中轴）: **{fmt(pz['zz'])}**")
                        print(f"  - 区间宽度: {fmt(pz['zz_width'])}")
                        print(f"  - 价格相对位置: ", end="")
                        if price > pz["zg"]:
                            print(f"✅ **中枢上方**（{fmt((price-pz['zg'])/pz['zg']*100,'%')}）")
                        elif price < pz["zd"]:
                            print(f"🔴 **中枢下方**（{fmt((pz['zd']-price)/pz['zd']*100,'%')}）")
                        else:
                            print(f"➖ **中枢内部**")
                else:
                    print("  无中枢（笔数不足3笔）")
                print()
                
                # 2e. 背驰
                print("### ②-e 背驰检测")
                print()
                if divergences:
                    for d in divergences:
                        icon = "🟢" if "底" in d["detail"] else "🔴"
                        sev = "⚡强" if d["severity"] == "strong" else "弱"
                        print(f"  {icon} {sev}背驰: {d['detail']}")
                else:
                    print("  无背驰信号")
                print()
                
                # 2f. 买卖点
                print("### ②-f 买卖点信号")
                print()
                has_signal = False
                if bs.get("buy_points"):
                    has_signal = True
                    for bp in bs["buy_points"]:
                        lv = "⚡强信号" if bp.get("level") == "strong" else "弱信号" if bp.get("level") == "weak" else "潜在"
                        print(f"  🟢 **{bp['type']}**（{lv}）: {bp['detail']}")
                if bs.get("sell_points"):
                    has_signal = True
                    for sp in bs["sell_points"]:
                        lv = "⚡强信号" if sp.get("level") == "strong" else "弱信号" if sp.get("level") == "weak" else "潜在"
                        print(f"  🔴 **{sp['type']}**（{lv}）: {sp['detail']}")
                if not has_signal:
                    print("  无明确买卖点信号")
                print()
                
                # 2g. 缠论综合裁决
                print("### ②-g 缠论综合裁决")
                print()
                ra = chan_risk_assessment_simple(day_kl)
                if ra:
                    print(f"| 维度 | 值 |")
                    print(f"|:----|:---|")
                    print(f"| 缠论评分 | {ra.get('chan_score','-')}（±10） |")
                    print(f"| 缠论裁决 | {ra.get('chan_verdict','-')} |")
                    print(f"| 趋势方向 | {ra.get('trend',{}).get('description','-')} |")
        else:
            print("  日线数据不足（<60根），需更多K线\n")
        
        # =====================
        # 3. 辅助：MA排列 + MACD
        # =====================
        print("## ③ 辅助信号（MA + MACD）")
        print()
        ma = tech.get("ma", {})
        macd = tech.get("macd", {})
        boll = tech.get("boll", {})
        
        # MA
        print("**均线**:")
        for p in [5, 10, 20, 60]:
            v = ma.get(f"ma{p}")
            if v:
                off = (price / v - 1) * 100
                icon = "🔺" if off > 0 else "🔻"
                print(f"  MA{p}: {fmt(v)}（{icon}{fmt(off)}%）")
        
        # MACD
        print(f"\n**MACD**: DIF={fmt(macd.get('dif'))} DEA={fmt(macd.get('dea'))} 柱={fmt(macd.get('macd_hist') or (macd.get('dif',0)-macd.get('dea',0))*2)}")
        
        # 布林
        bu = boll.get("upper")
        bm = boll.get("mid")
        bl = boll.get("lower")
        if bu and bm and bl:
            pos = (price - bl) / (bu - bl) * 100
            bw = (bu - bl) / bm * 100
            print(f"\n**布林**: 上{fmt(bu)} 中{fmt(bm)} 下{fmt(bl)} | 位置{fmt(pos)}% | 带宽{fmt(bw)}%")
        
        # =====================
        # 4. 止损/止盈
        # =====================
        print("\n## ④ 止损与止盈")
        print()
        sltp = tech.get("stop_loss_take_profit", {})
        sl = sltp.get("stop_loss")
        tp = sltp.get("take_profit")
        print(f"| 类型 | 价位 | 距现价 |")
        print(f"|:----|:----:|:------:|")
        if sl:
            print(f"| 止损 | {fmt(sl)} | -{fmt((1-price/sl)*100)}% |")
        if tp:
            print(f"| 止盈 | {fmt(tp)} | +{fmt((tp/price-1)*100)}% |")
        
        # 缠论止损
        if day_kl and len(day_kl) >= 60:
            ch2 = chan_theory_full(day_kl)
            pivots2 = ch2.get("pivots", [])
            if pivots2:
                last_zd = pivots2[-1]["zd"]
                print(f"| 缠论支撑 | {fmt(last_zd)} | 中枢下沿 |")
            strokes2 = ch2.get("strokes", [])
            if strokes2 and len(strokes2) >= 2:
                # 最近向下笔低点作为参考
                down_s = [s for s in strokes2 if s["direction"] == "down"]
                if down_s:
                    last_dn = down_s[-1]["low"]
                    print(f"| 笔支撑 | {fmt(last_dn)} | 最近向下笔低点 |")
                up_s = [s for s in strokes2 if s["direction"] == "up"]
                if up_s:
                    last_up = up_s[-1]["high"]
                    print(f"| 笔压力 | {fmt(last_up)} | 最近向上笔高点 |")
        
        print(f"\n{'='*65}\n")
        
    finally:
        await a.close()

def chan_risk_assessment_simple(klines):
    """简化版缠论裁决"""
    try:
        from scripts.quantrisk.chan import chan_risk_assessment
        return chan_risk_assessment(klines)
    except:
        return None

async def close_all():
    await close_async_session()
    await close_tickflow()

if __name__ == "__main__":
    codes = sys.argv[1:]
    if not codes:
        print("用法: uv run scripts/tech_chan.py <code1> <code2> ...")
        sys.exit(1)
    
    portfolio = {
        "02460": {"cost": 10.334, "shares": 4600, "name": "华润饮料"},
        "03888": {"cost": 25.013, "shares": 1600, "name": "金山软件"},
    }
    
    for code in codes:
        info = portfolio.get(code, {})
        asyncio.run(analyze(code, info.get("cost"), info.get("shares")))
    
    asyncio.run(close_all())
