#!/usr/bin/env python
"""策略适配性诊断 CLI —— 单股诊断 + 批量筛查（screen）。

单股:
  uv run scripts/analyze_fit.py 600519                 # A股（6 位代码）
  uv run scripts/analyze_fit.py 03033                  # 港股（5 位代码）

批量筛查（按适配度排序，分类列出网格候选 / 趋势型 / 门槛不足 / 流动性不足）:
  uv run scripts/analyze_fit.py --screen cn                  # 扫中证500 成分
  uv run scripts/analyze_fit.py --screen hk                  # 扫港股成交额 Top100
  uv run scripts/analyze_fit.py --screen cn --limit 100 --top 30
  uv run scripts/analyze_fit.py --screen cn --min-score 70

判据核心：趋势强度 |IR|（震荡←→趋势）+ 年化波动 + ER + 网格实测超额 + 一手资金门槛。

⚠️ 这是**历史特征筛选**，不是走势预测——|IR|/ER 无预测未来走势类型的能力
（已由 backtest_adaptive.py 实测否决），只用于筛掉明显不适合网格的标的。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import data, fit


async def fetch_universe_matrix(pool: list[dict], market: str, days: int, concurrency: int = 25):
    """并发拉取整个池子的**完整 OHLC**（fit 需要 high/low 做 ADX 与网格撮合）。"""
    async def one(item: dict):
        code = item["code"]
        if market == "港股":
            rows = await data.hk_kline_async(code, "day", count=days)
        else:
            rows = await data.cn_stock_kline_tencent_async(code, days=days)
        if not rows:
            return None
        df = pd.DataFrame.from_records(rows)
        if df.empty or "close" not in df:
            return None
        df["date"] = pd.to_datetime(df["date"])
        return {"code": code, "name": item.get("name") or code,
                "df": df.drop_duplicates("date").set_index("date").sort_index()}

    res = await data.parallel_map([lambda it=it: one(it) for it in pool],
                                  max_concurrency=concurrency)
    out = []
    for item in res:
        # parallel_map 用 return_exceptions=True → 过滤 Exception
        if isinstance(item, dict) and "df" in item:
            out.append(item)
    return out


async def run_screen(args) -> int:
    from quantrisk import rotation
    market = "港股" if args.screen == "hk" else "A股"
    # 池子优先用本地缓存（东财 push2 限流是常态，2026-10-09 实测多次失败）
    cache_key = "hk" if args.screen == "hk" else "cn"
    pool = None if args.no_cache else rotation.load_universe_cache(cache_key)
    if pool:
        pool_desc = (f"港股成交额 Top{len(pool)}（本地缓存）" if args.screen == "hk"
                     else f"中证500 成分（{len(pool)} 只，本地缓存）")
    else:
        try:
            if args.screen == "hk":
                pool = await rotation.fetch_hk_top_amount(args.limit or 100)
                pool_desc = f"港股成交额 Top{len(pool)}"
            else:
                pool = await rotation.fetch_zz500_constituents()
                pool_desc = f"中证500 成分（{len(pool)} 只）"
            rotation.save_universe_cache(cache_key, pool)
        except Exception as e:
            print(f"❌ 池子拉取失败且无本地缓存：{e}", file=sys.stderr)
            await data.close_async_session()
            return 1
    if args.limit and len(pool) > args.limit:
        pool = pool[: args.limit]
    print(f"池子：{pool_desc} → 扫描 {len(pool)} 只，开始拉取 K 线…", file=sys.stderr)

    items = await fetch_universe_matrix(pool, market, args.days)
    await data.close_async_session()
    print(f"取到 {len(items)} 只，开始诊断…", file=sys.stderr)

    spacings = tuple(args.spacing) if args.spacing else (0.02, 0.025)
    rows, skipped = [], []
    for it in items:
        try:
            r = fit.analyze_fit(it["df"], it["code"], it["name"], market,
                                spacings=spacings, lower=args.lower, upper=args.upper,
                                commission=args.commission)
            rows.append(fit.summarize(r, spacings))
        except Exception as e:
            skipped.append((it["code"], str(e)[:40]))
    print(f"有效诊断 {len(rows)} 只（跳过 {len(skipped)}）", file=sys.stderr)

    report = fit.render_screen(rows, market, pool_desc, min_score=args.min_score,
                               top=args.top, skipped=skipped)
    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"fit_screen_{args.screen}_{datetime.now():%Y%m%d}.md"
    f.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 报告已保存: {f}")
    return 0


async def fetch(code: str, days: int):
    """同一事件循环内取数（aiohttp session 与 loop 绑定）。"""
    if len(code) == 5:                                    # 港股
        rows = await data.hk_kline_async(code, "day", count=days)
        market = "港股"
    else:                                                  # A股/ETF
        rows = await data.cn_stock_kline_tencent_async(code, days=days)
        market = "A股"
    name = ""
    try:
        if len(code) == 5:
            q = await data.hk_stock_quote_tencent_async(code)
        else:
            q = await data.cn_stock_quote_tencent_async(code)
        name = (q or {}).get("name") or ""
    except Exception:
        pass
    await data.close_async_session()
    if not rows:
        return None, None, market
    df = pd.DataFrame.from_records(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index(), name, market


async def main_async(args) -> int:
    if args.screen:
        return await run_screen(args)
    if not args.code:
        print("❌ 需提供股票代码，或用 --screen cn|hk 批量筛查", file=sys.stderr)
        return 1
    df, name, market = await fetch(args.code, args.days)
    if df is None or df.empty:
        print(f"❌ {args.code} 无 K 线数据", file=sys.stderr)
        return 1
    spacings = tuple(args.spacing) if args.spacing else (0.02, 0.025)
    res = fit.analyze_fit(df, args.code, name or args.code, market,
                          spacings=spacings, lower=args.lower, upper=args.upper,
                          commission=args.commission)
    report = fit.render_fit(res)
    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"fit_{args.code}_{datetime.now():%Y%m%d}.md"
    f.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 报告已保存: {f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="策略适配性诊断（网格 vs 趋势）")
    ap.add_argument("code", nargs="?", default=None,
                    help="股票代码：A股 6 位（600519/002340）或港股 5 位（00700/03033）")
    ap.add_argument("--screen", choices=["cn", "hk"], default=None,
                    help="批量筛查：cn=中证500成分 / hk=港股成交额Top100")
    ap.add_argument("--limit", type=int, default=0, help="筛查上限（0=不限制）")
    ap.add_argument("--top", type=int, default=20, help="报告中每类展示条数")
    ap.add_argument("--min-score", type=float, default=70.0, help="网格候选的适配度阈值")
    ap.add_argument("--no-cache", action="store_true", help="忽略本地池子缓存，重新拉取")
    ap.add_argument("--days", type=int, default=800)
    ap.add_argument("--spacing", type=float, nargs="*", default=None,
                    help="网格间距（可多个，默认 0.02 0.025）")
    ap.add_argument("--lower", type=float, default=0.20)
    ap.add_argument("--upper", type=float, default=0.20)
    ap.add_argument("--commission", type=float, default=0.001)
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())