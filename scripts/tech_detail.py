#!/usr/bin/env python3
"""详细技术面分析脚本 — 输出四大师+技术面完整报告"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.quantrisk.report import StockAnalyzer
from scripts.quantrisk.data import (hk_kline_tencent_async, stock_kline_yahoo_async,
                                     kline_tickflow_async, key_indicators_eastmoney_async,
                                     close_async_session, close_tickflow, hk_stock_quote_tencent_async)
from scripts.quantrisk.indicators import chan_risk_assessment

def fmt(v, suffix="", dec=2):
    if v is None or v == "N/A":
        return "-"
    if isinstance(v, float):
        return f"{v:.{dec}f}{suffix}"
    return f"{v}{suffix}"

def _ma_signal(ma, price):
    """MA排列信号"""
    if not ma or not price:
        return "-", "-"
    m5 = ma.get("ma5") or 0
    m10 = ma.get("ma10") or 0
    m20 = ma.get("ma20") or 0
    m60 = ma.get("ma60") or 0
    if all(x > 0 for x in [m5, m10, m20, m60]):
        if m5 > m10 > m20 > m60 and price > m5:
            return "✅ 多头排列（强势）", f"MA5({fmt(m5)}) > MA10({fmt(m10)}) > MA20({fmt(m20)}) > MA60({fmt(m60)})，价格沿MA5上行"
        if m5 > m10 > m20 and price > m20:
            return "🟢 短多中多", f"短期/中期均线多头，价格在MA20({fmt(m20)})之上"
        if m5 > m10 and price > m5:
            return "🟡 短期金叉", f"MA5({fmt(m5)}) > MA10({fmt(m10)})，短多"
        if price < m60:
            return "🔴 破MA60", f"价格{fmt(price)} < MA60({fmt(m60)})，中期破位"
        if m10 < m60:
            return "⛔ 中期死叉", f"MA10({fmt(m10)}) < MA60({fmt(m60)})，中期走弱"
        return "➖ 盘整", f"均线交织，无明确方向"
    return "⚠️ 数据不足", "均线数据不完整"

def _macd_signal(macd):
    if not macd:
        return "-", "-"
    dif = macd.get("dif") or 0
    dea = macd.get("dea") or 0
    hist = macd.get("macd_hist") or (dif - dea) * 2
    signal = dif - dea
    d = "多头" if signal > 0 else "空头"
    strength = abs(signal)
    trend = "走强" if signal > dea else "走弱" if signal < dea else "持平"
    # 金叉/死叉判断
    if dif > dea and hist > 0:
        state = "✅ 多头（DIF在DEA上方）"
        desc = f"DIF({fmt(dif)}) > DEA({fmt(dea)})，柱值{fmt(hist)}，{d}趋势{trend}"
    elif dif < dea and hist < 0:
        state = "🔴 空头（DIF在DEA下方）"
        desc = f"DIF({fmt(dif)}) < DEA({fmt(dea)})，柱值{fmt(hist)}，{d}趋势{trend}"
    else:
        state = "➖ 方向模糊"
        desc = f"DIF({fmt(dif)}) - DEA({fmt(dea)}) = {fmt(signal)}，柱值{fmt(hist)}"
    return state, desc

def _rsi_signal(rsi):
    if not rsi:
        return "-"
    r6 = rsi.get("rsi6")
    r14 = rsi.get("rsi14")
    lines = []
    if r6 is not None:
        s = "超买 🔴" if r6 > 80 else "偏强 🟡" if r6 > 60 else "中性 ➖" if r6 > 40 else "偏弱 🔵" if r6 > 20 else "超卖 🟢"
        lines.append(f"RSI(6)={fmt(r6)} → {s}")
    if r14 is not None:
        s = "超买 🔴" if r14 > 70 else "偏强 🟡" if r14 > 55 else "中性 ➖" if r14 > 40 else "偏弱 🔵" if r14 > 25 else "超卖 🟢"
        lines.append(f"RSI(14)={fmt(r14)} → {s}")
    return " | ".join(lines)

def _kdj_signal(kdj):
    if not kdj:
        return "-", "-"
    k = kdj.get("k") or 0
    d = kdj.get("d") or 0
    j = kdj.get("j") or 0
    # KDJ 超买/超卖
    if k > 80 and d > 80:
        s = "🔴 高位（可能超买）"
        desc = f"K={fmt(k)}, D={fmt(d)}, J={fmt(j)}，K/D 均在80以上"
    elif k < 20 and d < 20:
        s = "🟢 低位（可能超卖）"
        desc = f"K={fmt(k)}, D={fmt(d)}, J={fmt(j)}，K/D 均在20以下"
    elif k > d:
        s = "🟡 K线上穿D线（偏多）"
        desc = f"K={fmt(k)} > D={fmt(d)}, J={fmt(j)}"
    elif k < d:
        s = "🔵 K线下穿D线（偏空）"
        desc = f"K={fmt(k)} < D={fmt(d)}, J={fmt(j)}"
    else:
        s = "➖ 交织"
        desc = f"K={fmt(k)}, D={fmt(d)}, J={fmt(j)}"
    return s, desc

def _boll_signal(boll, price):
    if not boll or price is None:
        return "-", "-"
    up = boll.get("upper") or 0
    mid = boll.get("mid") or 0
    dn = boll.get("lower") or 0
    bw = ((up - dn) / mid * 100) if mid else 0
    pos = ((price - dn) / (up - dn) * 100) if (up - dn) else 50
    
    if price >= up:
        s = "🔴 触及上轨（超买）"
        desc = f"价{fmt(price)} ≥ 上轨{fmt(up)}，布林带宽{bw:.1f}%"
    elif price <= dn:
        s = "🟢 触及下轨（超卖）"
        desc = f"价{fmt(price)} ≤ 下轨{fmt(dn)}，布林带宽{bw:.1f}%"
    elif pos > 70:
        s = "🟡 上轨附近"
        desc = f"价在布林{pos:.0f}%分位（上{fmt(up)}/中{fmt(mid)}/下{fmt(dn)}），带宽{bw:.1f}%"
    elif pos < 30:
        s = "🔵 下轨附近"
        desc = f"价在布林{pos:.0f}%分位（上{fmt(up)}/中{fmt(mid)}/下{fmt(dn)}），带宽{bw:.1f}%"
    else:
        s = "➖ 中轨附近"
        desc = f"价在布林{pos:.0f}%分位（上{fmt(up)}/中{fmt(mid)}/下{fmt(dn)}），带宽{bw:.1f}%"
    
    # 带宽判断
    if bw < 10:
        desc += " | ⚡ 带宽窄，可能变盘"
    elif bw > 50:
        desc += " | 📊 带宽宽，波动大"
    return s, desc

def _chan_detail(klines, code):
    """缠论详细分析"""
    if not klines or len(klines) < 60:
        return {"signal": "数据不足"}
    try:
        ch = chan_risk_assessment(klines)
        if not isinstance(ch, dict):
            return {"signal": "计算失败"}
        
        # 尝试获取周线数据
        week_kl = None
        try:
            import asyncio
            week_kl = asyncio.run(_fetch_week_kline(code))
        except:
            pass
        
        week_analysis = ""
        if week_kl and len(week_kl) >= 20:
            from scripts.quantrisk.indicators import calc_ma
            w_ma = calc_ma(week_kl, [60])
            if w_ma:
                w_ma60 = w_ma[-1].get("ma60", 0)
                w_close = week_kl[-1]["close"]
                if w_close > w_ma60 and w_ma60 > 0:
                    week_analysis = f"周线MA60={fmt(w_ma60)}，价格{fmt(w_close)}在MA60上方 → 偏多"
                elif w_close < w_ma60 and w_ma60 > 0:
                    week_analysis = f"周线MA60={fmt(w_ma60)}，价格{fmt(w_close)}在MA60下方 → 偏空"
                else:
                    week_analysis = "周线数据不足"
        
        return ch, week_analysis
    except Exception as e:
        return {"signal": f"错误: {e}"}

async def _fetch_week_kline(code):
    """获取周线K线"""
    kl = await hk_kline_tencent_async(code, "week", 104)
    if kl and len(kl) >= 20:
        return kl
    kl = await stock_kline_yahoo_async(f"{int(code)}.HK", "1wk", "2y")
    return kl

async def analyze(code, cost=None, shares=None):
    a = StockAnalyzer()
    try:
        result = await a.analyze_hk(code)
        if "error" in result:
            print(f"❌ 分析失败: {result['error']}")
            return
        
        tech = result.get("technicals", {})
        quote = result.get("quote", {})
        ind = result.get("indicator", {})
        
        price = quote.get("price", 0)
        name = quote.get("name", code)
        pnl = (price / cost - 1) * 100 if cost and price else None
        
        # ── 输出 ──
        print(f"\n{'='*65}")
        print(f"  📊 {name}（{code}）详细技术面分析")
        if cost:
            print(f"  持仓: {shares or '-'}股 | 成本 {fmt(cost)} | 现价 {fmt(price)} | 盈亏 {fmt(pnl, '%') if pnl else '-'}")
        print(f"{'='*65}\n")
        
        # === 1. MA排列 ===
        print("### ① 均线系统（MA排列）")
        print()
        ma = tech.get("ma", {})
        ma_sig, ma_desc = _ma_signal(ma, price)
        print(f"| 周期 | 价格 | 相对位置 |")
        print(f"|:----|:----:|:--------:|")
        for p, label in [(5,"MA5"), (10,"MA10"), (20,"MA20"), (60,"MA60")]:
            v = ma.get(f"ma{p}")
            if v:
                offset = (price / v - 1) * 100
                arrow = "🔺" if offset > 0 else "🔻"
                print(f"| {label} | {fmt(v)} | {arrow} {fmt(offset, '%')} |")
            else:
                print(f"| {label} | - | - |")
        print(f"\n**综合判断**: {ma_sig}")
        print(f"> {ma_desc}")
        print()
        
        # === 2. MACD ===
        print("### ② MACD 分析")
        print()
        macd = tech.get("macd", {})
        md_sig, md_desc = _macd_signal(macd)
        print(f"| 指标 | 值 |")
        print(f"|:----|:---:|")
        print(f"| DIF | {fmt(macd.get('dif'))} |")
        print(f"| DEA | {fmt(macd.get('dea'))} |")
        print(f"| MACD柱 | {fmt(macd.get('macd_hist') or (macd.get('dif',0)-macd.get('dea',0))*2)} |")
        print(f"\n**综合判断**: {md_sig}")
        print(f"> {md_desc}")
        print()
        
        # === 3. RSI ===
        print("### ③ RSI 相对强弱")
        print()
        rsi = tech.get("rsi", {})
        print(f"| 周期 | 值 | 判断 |")
        print(f"|:----|:---:|:----:|")
        for p in [6, 14]:
            v = rsi.get(f"rsi{p}")
            if v is not None:
                if p == 6:
                    s = "超买" if v > 80 else "偏强" if v > 60 else "中性" if v > 40 else "偏弱" if v > 20 else "超卖"
                else:
                    s = "超买" if v > 70 else "偏强" if v > 55 else "中性" if v > 40 else "偏弱" if v > 25 else "超卖"
                print(f"| RSI({p}) | {fmt(v)} | {s} |")
        print(f"\n{_rsi_signal(rsi)}")
        print()
        
        # === 4. KDJ ===
        print("### ④ KDJ 随机指标")
        print()
        kdj = tech.get("kdj", {})
        kdj_sig, kdj_desc = _kdj_signal(kdj)
        print(f"| 指标 | 值 |")
        print(f"|:----|:---:|")
        print(f"| K | {fmt(kdj.get('k'))} |")
        print(f"| D | {fmt(kdj.get('d'))} |")
        print(f"| J | {fmt(kdj.get('j'))} |")
        print(f"\n**综合判断**: {kdj_sig}")
        print(f"> {kdj_desc}")
        print()
        
        # === 5. 布林带 ===
        print("### ⑤ 布林带（BOLL）")
        print()
        boll = tech.get("boll", {})
        bl_sig, bl_desc = _boll_signal(boll, price)
        print(f"| 指标 | 值 |")
        print(f"|:----|:---:|")
        print(f"| 上轨 | {fmt(boll.get('upper'))} |")
        print(f"| 中轨 | {fmt(boll.get('mid'))} |")
        print(f"| 下轨 | {fmt(boll.get('lower'))} |")
        print(f"\n**综合判断**: {bl_sig}")
        print(f"> {bl_desc}")
        print()
        
        # === 6. 支撑/压力 ===
        print("### ⑥ 支撑与压力位")
        print()
        sr = tech.get("support_resistance", {})
        print(f"| 类型 | 价位 | 说明 |")
        print(f"|:----|:----:|:----:|")
        for sp in ["S1", "S2", "S3"]:
            v = sr.get(sp) or sr.get(sp.lower())
            if v:
                dist = (price / v - 1) * 100
                print(f"| {sp}支撑 | {fmt(v)} | 距现价 {fmt(dist, '%')} |")
        for rp in ["R1", "R2", "R3"]:
            v = sr.get(rp) or sr.get(rp.lower())
            if v:
                dist = (v / price - 1) * 100
                print(f"| {rp}压力 | {fmt(v)} | 距现价 {fmt(dist, '%')} |")
        # 日内高低
        print(f"| 日内低 | {fmt(quote.get('low'))} | 今日最低 |")
        print(f"| 日内高 | {fmt(quote.get('high'))} | 今日最高 |")
        print()
        
        # === 7. 缠论分析 ===
        print("### ⑦ 缠论分析")
        print()
        ch_result = _chan_detail(None, code)
        if isinstance(ch_result, tuple):
            ch, week_an = ch_result
        else:
            ch = ch_result
            week_an = ""
        
        if week_an:
            print(f"**周线定势**: {week_an}")
            print()
        
        if isinstance(ch, dict):
            trend = ch.get("trend", ch.get("direction", "未知"))
            stroke_c = ch.get("stroke_count", ch.get("strokes", 0))
            seg_c = ch.get("segment_count", ch.get("segments", 0))
            pivot_c = ch.get("pivot_count", ch.get("pivots", 0))
            signal = ch.get("signal", ch.get("conclusion", "无"))
            buy = ch.get("buy_point", ch.get("buy", ""))
            sell = ch.get("sell_point", ch.get("sell", ""))
            bias = ch.get("macd_bias", ch.get("bias", ""))
            
            print(f"| 维度 | 值 |")
            print(f"|:----|:---:|")
            print(f"| 趋势 | {trend} |")
            print(f"| 笔数 | {stroke_c} |")
            print(f"| 段数 | {seg_c} |")
            print(f"| 分型 | {pivot_c} |")
            print(f"| 信号 | {signal} |")
            if buy:
                print(f"| 买点 | {buy} |")
            if sell:
                print(f"| 卖点 | {sell} |")
            if bias:
                print(f"| 背驰 | {bias} |")
        print()
        
        # === 8. 止损/止盈 ===
        print("### ⑧ 止损与止盈")
        print()
        sltp = tech.get("stop_loss_take_profit", {})
        sl = sltp.get("stop_loss")
        tp = sltp.get("take_profit")
        print(f"| 类型 | 价位 | 距现价 |")
        print(f"|:----|:----:|:------:|")
        if sl:
            print(f"| 止损 | {fmt(sl)} | {fmt((price/sl-1)*100, '%')} |")
        if tp:
            print(f"| 止盈 | {fmt(tp)} | {fmt((tp/price-1)*100, '%')} |")
        print()
        
        # === 9. 量价分析 ===
        print("### ⑨ 量价关系")
        print()
        quote_change = quote.get("change_pct", 0)
        volume = quote.get("volume", 0)
        amount = quote.get("amount", 0)
        turnover = quote.get("turnover", 0)
        
        print(f"| 指标 | 值 |")
        print(f"|:----|:---:|")
        print(f"| 今日涨跌 | {fmt(quote_change, '%')} |")
        print(f"| 成交量 | {fmt(volume/10000 if volume else 0)}万股 |")
        print(f"| 成交额 | {fmt(amount/10000 if amount else 0)}万 |")
        if turnover:
            print(f"| 换手率 | {fmt(turnover, '%')} |")
        
        # 量价同步判断
        if quote_change > 1 and volume:
            print(f"\n➡ 价涨量随，量价配合正常" if volume > 0 else "")
        elif quote_change > 1 and volume == 0:
            print(f"\n⚠️ 缩量上涨，上涨动能不足")
        elif quote_change < -1 and volume:
            print(f"\n➡ 放量下跌，抛压较重")
        elif quote_change < -1:
            print(f"\n⚠️ 缩量下跌，卖盘衰竭")
        print()
        
        # === 10. 技术信号汇总 ===
        print("### 🔴🟢 技术信号汇总")
        print()
        signals = []
        
        # MA
        if "多头排列" in ma_sig:
            signals.append(("✅", "均线", "多头排列，趋势强劲"))
        elif "破MA60" in ma_sig:
            signals.append(("🔴", "均线", "跌破MA60，中期走弱"))
        elif "死叉" in ma_sig:
            signals.append(("🔴", "均线", "中期死叉，趋势转弱"))
        elif "金叉" in ma_sig:
            signals.append(("🟢", "均线", "短期金叉，短线偏多"))
        elif "盘整" in ma_sig:
            signals.append(("➖", "均线", "均线交织，方向不明"))
        
        # MACD
        if "多头" in md_sig:
            signals.append(("🟢", "MACD", "多头格局，DIF在DEA上方"))
        elif "空头" in md_sig:
            signals.append(("🔴", "MACD", "空头格局，DIF在DEA下方"))
        
        # RSI
        if rsi:
            r14 = rsi.get("rsi14") or 50
            if r14 > 70:
                signals.append(("🔴", "RSI", f"RSI(14)={fmt(r14)}超买，注意回调风险"))
            elif r14 < 30:
                signals.append(("🟢", "RSI", f"RSI(14)={fmt(r14)}超卖，反弹机会"))
        
        # KDJ
        if "超买" in kdj_sig:
            signals.append(("🔴", "KDJ", "K/D均在80以上，短期过热"))
        elif "超卖" in kdj_sig:
            signals.append(("🟢", "KDJ", "K/D均在20以下，短期超卖"))
        elif "偏多" in kdj_sig:
            signals.append(("🟢", "KDJ", "K线上穿D线，短线偏多"))
        elif "偏空" in kdj_sig:
            signals.append(("🔵", "KDJ", "K线下穿D线，短线偏空"))
        
        # Boll
        if "超买" in bl_sig:
            signals.append(("🔴", "布林", "触及上轨，超买信号"))
        elif "超卖" in bl_sig:
            signals.append(("🟢", "布林", "触及下轨，超卖信号"))
        elif "变盘" in bl_sig:
            signals.append(("⚡", "布林", "带宽收窄，可能变盘"))
        
        # Chan
        if isinstance(ch, dict):
            sig = ch.get("signal", "")
            if "买" in sig:
                signals.append(("🟢", "缠论", f"买入信号: {sig}"))
            elif "卖" in sig:
                signals.append(("🔴", "缠论", f"卖出信号: {sig}"))
        
        if not signals:
            signals.append(("➖", "综合", "无明确技术信号"))
        
        print(f"| 类型 | 指标 | 信号 |")
        print(f"|:----|:----|:-----|")
        for icon, name, desc in signals:
            print(f"| {icon} | {name} | {desc} |")
        
        # 整体技术倾向
        bullish = sum(1 for s in signals if s[0] in ["✅", "🟢", "⚡"])
        bearish = sum(1 for s in signals if s[0] in ["🔴", "🔵"])
        neutral = sum(1 for s in signals if s[0] == "➖")
        print()
        if bullish > bearish + 1:
            print(f"> **整体倾向**: 🟢 偏多（看多{ bullish} vs 看空{bearish}）")
        elif bearish > bullish + 1:
            print(f"> **整体倾向**: 🔴 偏空（看多{bullish} vs 看空{bearish}）")
        else:
            print(f"> **整体倾向**: ➖ 中性/震荡（看多{bullish} vs 看空{bearish}）")
        
        print(f"\n{'='*65}\n")
        
    finally:
        await a.close()

if __name__ == "__main__":
    codes = sys.argv[1:]
    if not codes:
        print("用法: uv run scripts/tech_detail.py <code1> <code2> ...")
        sys.exit(1)
    
    # 持仓信息（硬编码）
    portfolio = {
        "02460": {"cost": 10.334, "shares": 4600, "name": "华润饮料"},
        "03888": {"cost": 25.013, "shares": 1600, "name": "金山软件"},
    }
    
    for code in codes:
        info = portfolio.get(code, {})
        asyncio.run(analyze(code, info.get("cost"), info.get("shares")))
