#!/usr/bin/env python3
"""
港股全量分析脚本
用法:
    uv run scripts/analyze_hk.py 03690          # 单只分析
    uv run scripts/analyze_hk.py 03690 00268     # 多只批量
    uv run scripts/analyze_hk.py 03690 00268 --json  # JSON 输出
"""
import asyncio, json, sys
from pathlib import Path
# Ensure project root is on sys.path so `scripts.*` imports work
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.quantrisk.report import StockAnalyzer

async def main():
    args = sys.argv[1:]
    codes = [a for a in args if not a.startswith("--")]
    json_mode = "--json" in args

    if not codes:
        print("用法: uv run scripts/analyze_hk.py 03690 [00268 ...]")
        sys.exit(1)

    a = StockAnalyzer()
    results = await a.analyze_hk_batch(codes)

    if json_mode:
        print(json.dumps(results, ensure_ascii=False, default=str, indent=2))
    else:
        for code, r in results.items():
            q = r.get("quote", {})
            t = r.get("technicals", {})
            y = r.get("yahoo_stats", {})
            ind = r.get("indicator", {})
            print(f"\n{'=' * 60}")
            print(f"📊 {r.get('name', '未知')} ({code})")
            print(f"{'=' * 60}")
            print(f"  现价: {q.get('price','N/A')}  |  涨跌: {q.get('change_pct','N/A')}%")
            print(f"  PE: {q.get('pe','N/A')}  |  市值: {q.get('market_cap_100m','N/A')}亿")
            print(f"  日内: {q.get('low','N/A')} ~ {q.get('high','N/A')}  |  振幅: {q.get('amp','N/A')}%")
            print(f"  成交额: {q.get('amount_100m','N/A')}")

            if y:
                print(f"  远期PE: {y.get('forward_pe','N/A')} | 目标价: {y.get('target_mean','N/A')}  |  评级: {y.get('recommendation','N/A')}")

            if ind:
                print(f"  最新营收: {ind.get('OPERATE_INCOME','N/A')}  |  营收同比: {ind.get('OPERATE_INCOME_YOY','N/A')}%")
                print(f"  净利润: {ind.get('HOLDER_PROFIT','N/A')}  |  净利同比: {ind.get('HOLDER_PROFIT_YOY','N/A')}%")

            if t.get("error"):
                print(f"  技术面: {t['error']}")
            else:
                ma = t.get("ma", {})
                print(f"  MA5/10/20/60: {ma.get('ma5','-')}/{ma.get('ma10','-')}/{ma.get('ma20','-')}/{ma.get('ma60','-')}")
                print(f"  MACD柱: {t['macd'].get('macd_hist','N/A')}  |  RSI14: {t['rsi'].get('rsi14','N/A')}")
                print(f"  布林上/中/下: {t['boll'].get('upper','-')}/{t['boll'].get('middle','-')}/{t['boll'].get('lower','-')}")
                print(f"  支撑/压力: {t['support_resistance']}")
                print(f"  止损/止盈: {t['stop_loss_take_profit'].get('stop_loss','-')}/{t['stop_loss_take_profit'].get('take_profit','-')}")
                print(f"  缠论: {t['chan'].get('chan_verdict','N/A')}  |  笔: {t['chan'].get('strokes_count',0)} 段: {t['chan'].get('segments_count',0)}")

    await a.close()

if __name__ == "__main__":
    asyncio.run(main())
