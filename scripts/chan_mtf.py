#!/usr/bin/env python3
"""
缠论多周期联立分析（5m / 60m / 日K / 周K）
多数据源自动切换：Yahoo → 腾讯 fqkline → TickFlow

用法:
    python3 scripts/chan_mtf.py <code1> [code2] ...
    python3 scripts/chan_mtf.py 09999                  # 单只
    python3 scripts/chan_mtf.py 09999 00700 02269     # 多只对比
"""
import asyncio, sys
from datetime import datetime
from scripts.quantrisk.data import (stock_kline_yahoo_async, kline_tickflow_async,
                                     hk_kline_tencent_async, hk_stock_quote_tencent_async,
                                     close_async_session, close_tickflow)
from scripts.quantrisk.indicators import calc_ma, calc_macd, chan_risk_assessment, calc_support_resistance

# ── 数据源配置 ──────────────────────────────────
# (显示标签, Yahoo间隔, Yahoo范围, 显示名, 备选数据源)
TF_CONFIG = [
    ("短期", "5m", "5d",  "5分钟",  []),
    ("中期", "60m", "1mo", "60分钟", []),
    ("长期", "1d", "1y",   "日K",    ["tickflow", "tencent"]),
    ("超长", "weekly", "1y", "周K",    ["tencent_week"]),
]

async def get_klines_multi(code: str, label: str, interval: str, range_: str, name_cn: str, fallbacks: list):
    """多源自动切换获取K线"""
    results = []  # (source, klines)
    
    # 1. Yahoo（优先用于分钟级）
    klines = await stock_kline_yahoo_async(f"{code}.HK", interval, range_)
    if klines and len(klines) >= 20:
        results.append(("Yahoo", klines))
    
    # For weekly data, skip Yahoo and use Tencent weekly directly
    if label == "超长":
        for fb in fallbacks:
            if fb == "tencent_week":
                klines = await hk_kline_tencent_async(code, "week", 120)
                if klines and len(klines) >= 10:
                    return "tencent_week", klines
        return None, 0
    
    # 2. Fallbacks
    for fb in fallbacks:
        if fb == "tickflow":
            klines = await kline_tickflow_async(f"{code}.HK", "1d", 365)
        elif fb == "tencent":
            klines = await hk_kline_tencent_async(code, "day", 365)
        elif fb == "tencent_week":
            klines = await hk_kline_tencent_async(code, "week", 120)
        else:
            continue
        if klines and len(klines) >= 20:
            results.append((fb, klines))
            break  # 只取第一个成功的备选
    
    if not results:
        return None, 0
    
    # 如果有多个源，选K线最多的
    best = max(results, key=lambda r: len(r[1]))
    return best[0], best[1]

async def analyze_mtf(code):
    """多周期缠论分析单只股票"""
    quote = await hk_stock_quote_tencent_async(code)
    name = quote.get("name", code)
    price = quote.get("price", 0)
    change = quote.get("change_pct", 0)
    
    print(f"\n{'='*60}")
    print(f"  {name}（{code}）— {price:.2f} HKD ({change:+.2f}%)")
    print(f"{'='*60}")
    
    timeframes = []
    for label, interval, range_, name_cn, fallbacks in TF_CONFIG:
        source, klines = await get_klines_multi(code, label, interval, range_, name_cn, fallbacks)
        
        if not klines or len(klines) < 20:
            timeframes.append({"label": label, "name": name_cn, "klines": [], "error": f"数据不足", "count": 0, "source": None})
            print(f"  [{label}][{name_cn}] ❌ 无可用K线（已尝试Yahoo+备选）")
            continue
        
        # 缠论
        chan = chan_risk_assessment(klines)
        # 技术指标
        ma_data = calc_ma(klines, [60])
        ma = ma_data[-1] if ma_data and len(ma_data) > 0 else {}
        macd_data = calc_macd(klines)
        macd = macd_data[-1] if macd_data and len(macd_data) > 0 else {}
        sr = calc_support_resistance(klines)
        
        close = klines[-1]["close"]
        ma60 = ma.get("ma60", 0)
        macd_hist = macd.get("macd_hist", 0) if isinstance(macd, dict) else macd.get("histogram", 0)
        pct_vs_ma60 = round((close - ma60) / ma60 * 100, 1) if ma60 else None
        
        tf = {
            "label": label, "name": name_cn, "klines": klines, "chan": chan,
            "ma": ma, "macd": macd, "count": len(klines), "close": close,
            "ma60": ma60, "pct_vs_ma60": pct_vs_ma60, "macd_hist": macd_hist,
            "sr": sr, "source": source,
        }
        timeframes.append(tf)
        
        # 打印摘要
        chan_v = chan.get("chan_verdict", "?")
        chan_s = chan.get("chan_score", 0)
        trend = chan.get("trend", {}).get("description", "")
        signals = "; ".join(f"{s['signal']}({s['severity']})" for s in chan.get("risk_signals", [])[:2])
        pos = chan.get("relative_position", "")
        dist = chan.get("distance_to_pivot_pct", "")
        pivot = f" | 中枢:{pos}{'('+str(dist)+'%)' if dist is not None else ''}" if pos else ""
        
        arrow = "⬆" if (pct_vs_ma60 and close > ma60 and macd_hist > 0) else \
                "⬇" if (pct_vs_ma60 and close < ma60 and macd_hist < 0) else "→"
        direction = "多头" if arrow == "⬆" else "空头" if arrow == "⬇" else "震荡"
        print(f"  [{label}][{name_cn}] {arrow} {direction} | {source} {len(klines)}根 | "
              f"MA60偏离={pct_vs_ma60}% | MACD柱={macd_hist:+.4f} | 缠论:{chan_v}({chan_s}){pivot}")
        if signals:
            print(f"        信号: {signals}")
        if trend:
            print(f"        走势: {trend}")
        if label == "超长" and interval == "1d":
            print(f"        区间: {klines[0]['date']} ~ {klines[-1]['date']}")
    
    return {"code": code, "name": name, "price": price, "timeframes": timeframes}

def print_mtf_report(results):
    """输出多周期缠论联立分析报告"""
    for r in results:
        print(f"\n{'='*60}")
        print(f"  📊 多周期缠论联立 | {r['name']}（{r['code']}）— {r['price']:.2f} HKD")
        print(f"{'='*60}")
        
        for tf in r["timeframes"]:
            if tf.get("error"):
                continue
            
            chan = tf["chan"]
            close = tf.get("close", 0)
            ma60 = tf.get("ma60", 0)
            pct = tf.get("pct_vs_ma60", "")
            mc = tf.get("macd_hist", 0)
            sr = tf.get("sr", {})
            
            # 周期判断
            if close > ma60 and mc > 0:
                direction = "多头排列 ⬆"
            elif close > ma60:
                direction = "偏多（MACD待确认）"
            elif close < ma60 and mc < 0:
                direction = "空头排列 ⬇"
            elif close < ma60:
                direction = "偏空（MACD待确认）"
            else:
                direction = "中性 →"
            
            print(f"\n  ┌─ [{tf['label']}] {tf['name']} — {direction}（{tf.get('source','')}）")
            print(f"  ├ K线: {tf['count']}根 | {tf['klines'][0]['date']} ~ {tf['klines'][-1]['date']}")
            print(f"  ├ 价格: {close:.2f} | MA60={ma60:.2f} | 偏离={pct}%" if ma60 else f"  ├ 价格: {close:.2f}")
            print(f"  ├ MACD柱: {mc:+.4f}")
            print(f"  ├ 支撑: {sr.get('support', 'N/A')} | 压力: {sr.get('resistance', 'N/A')}")
            
            # 缠论信号
            for s in chan.get("risk_signals", [])[:3]:
                print(f"  ├ 💡 {s['signal']}({s['severity']}): {s.get('detail','')[:70]}")
            
            # 买卖点
            bsp = chan.get("buy_sell_points", {})
            for bp in bsp.get("buy_points", []):
                print(f"  ├ 🟢 买点: {bp['type']}({bp.get('level','')}) — {bp.get('detail','')[:60]}")
            for sp in bsp.get("sell_points", []):
                print(f"  ├ 🔴 卖点: {sp['type']}({sp.get('level','')}) — {sp.get('detail','')[:60]}")
            
            # 中枢
            pos = chan.get("relative_position", "")
            dist = chan.get("distance_to_pivot_pct", "")
            if pos:
                print(f"  └ 中枢: {pos}{' ('+str(dist)+'%)' if dist is not None else ''}")
        
        # 多周期联立结论
        print(f"\n  🔗 多周期联立:")
        for level, lname in [("短期", "[短期]5分钟"), ("中期", "[中期]60分钟"), ("长期", "[长期]日K"), ("超长", "[超长]周K")]:
            tf = next((t for t in r["timeframes"] if t["label"] == level), None)
            if tf and not tf.get("error"):
                close = tf.get("close", 0)
                ma60 = tf.get("ma60", 0)
                mc = tf.get("macd_hist", 0)
                ch = tf.get("chan", {}).get("chan_verdict", "?")
                arrow = "⬆" if (close > ma60 and mc > 0) else "⬇" if (close < ma60 and mc < 0) else "→"
                src = tf.get("source", "")
                print(f"    {lname}: {arrow} 缠论={ch} | MA60={tf.get('pct_vs_ma60','?')}% | MACD={mc:+.4f} | 数据={src}")
        
        # 多周期共振/背离
        tfs = [t for t in r["timeframes"] if not t.get("error")]
        if len(tfs) >= 2:
            directions = [(t["label"], "up" if t["close"] > t["ma60"] else "down") for t in tfs]
            all_up = all(d == "up" for _, d in directions)
            all_down = all(d == "down" for _, d in directions)
            mixed = not all_up and not all_down
            if all_up:
                print(f"    ⚡ 共振信号: 所有周期多头共振！")
            elif all_down:
                print(f"    ⚡ 共振信号: 所有周期空头共振！")
            elif mixed:
                ups = [l for l, d in directions if d == "up"]
                downs = [l for l, d in directions if d == "down"]
                print(f"    ⚠ 背离信号: 短期{downs}vs长期{ups} — 趋势矛盾，等待方向确认")
        print()

async def main():
    codes = sys.argv[1:] if len(sys.argv) > 1 else ["09999", "00700", "02269"]
    results = []
    for code in codes:
        r = await analyze_mtf(code)
        results.append(r)
    print_mtf_report(results)
    await close_async_session()
    await close_tickflow()

if __name__ == "__main__":
    asyncio.run(main())
