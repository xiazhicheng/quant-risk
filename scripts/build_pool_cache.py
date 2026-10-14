#!/usr/bin/env python
"""为任意股票池构建完整行情缓存（close/open/volume 三矩阵，逐只容错）。

与 `patch_volume_cache.py`（只补 volume）不同，本工具从零构建整池矩阵：
逐只拉 K 线、失败重试 3 次后 fail-open（该股跳过，不中断整体）——适合
全市场这种千只级池子（腾讯 push2/日K 偶发 ServerDisconnected 是常态）。

用法:
  uv run scripts/build_pool_cache.py --market cn --pool all --days 800
  uv run scripts/build_pool_cache.py --market hk --pool hsi --days 800
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import data, rotation

POOLS = {
    "cn:all": rotation.fetch_all_a_constituents,
    "cn:zz500": rotation.fetch_zz500_constituents,
    "hk:hsi": rotation.fetch_hsi_constituents,
}


async def _one(code: str, market: str, days: int, sem: asyncio.Semaphore,
               retries: int = 3):
    for attempt in range(retries):
        async with sem:
            try:
                rows = (await data.hk_kline_async(code, "day", count=days)
                        if market == "hk"
                        else await data.cn_stock_kline_tencent_async(code, days=days))
            except Exception as exc:  # noqa: BLE001 - 单只失败必须隔离
                if attempt == retries - 1:
                    return code, None, f"{type(exc).__name__}"
                await asyncio.sleep(0.5 * (attempt + 1) * (1.5 ** attempt))
                continue
        if not rows:
            return code, None, "empty"
        df = pd.DataFrame.from_records(rows)
        if df.empty or "close" not in df:
            return code, None, "no_close"
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").set_index("date").sort_index()
        c = df["close"].astype(float)
        o = df["open"].astype(float) if "open" in df else c.copy()
        v = df["volume"].astype(float) if "volume" in df else None
        return code, (c, o, v), None
    return code, None, "unknown"


async def main_async(args) -> int:
    fetch = POOLS.get(f"{args.market}:{args.pool}")
    if fetch is None:
        raise SystemExit(f"❌ 未知池 {args.market}:{args.pool}（可选 {', '.join(POOLS)}）")
    uni_key = "all" if args.pool == "all" else ("hk_hsi" if args.market == "hk" else args.market)

    for attempt in range(4):
        try:
            universe = await fetch()
            break
        except Exception as exc:  # noqa: BLE001 - 池列表拉取整体重试
            if attempt == 3:
                raise
            print(f"  池列表拉取失败（{type(exc).__name__}），重试 {attempt+1}/3")
            await asyncio.sleep(2 * (attempt + 1))
    print(f"池 {args.pool}: {len(universe)} 只")
    cache_key = f"{uni_key}_d{args.days}"
    days = args.days

    sem = asyncio.Semaphore(args.concurrency)
    tasks = [_one(str(u["code"]), args.market, days, sem) for u in universe]
    closes, opens, vols, failed = {}, {}, {}, []
    done = 0
    for fut in asyncio.as_completed(tasks):
        code, trio, err = await fut
        done += 1
        if trio is None:
            failed.append((code, err))
        else:
            c, o, v = trio
            closes[code] = c
            opens[code] = o
            if v is not None:
                vols[code] = v
        if done % 500 == 0 or done == len(tasks):
            print(f"  进度 {done}/{len(tasks)}（成功 {len(closes)}，失败 {len(failed)}）")

    if not closes:
        raise SystemExit("❌ 全部失败，未写缓存")
    close_df = pd.DataFrame(closes)
    if len(close_df) > days:
        close_df = close_df.iloc[-days:]   # 截断到最近 days 个交易日（腾讯对老股可能返回全量历史）
    open_df = pd.DataFrame(opens).reindex(index=close_df.index, columns=close_df.columns)
    vol_df = pd.DataFrame(vols).reindex(index=close_df.index, columns=close_df.columns)
    rotation.save_cache(cache_key, close_df, open_df, vol_df)
    rotation.save_universe_cache(uni_key, universe)
    covered = int(vol_df.notna().any(axis=0).sum())
    print(f"✅ 已写 {cache_key}：{close_df.shape[1]} 只 × {close_df.shape[0]} 日"
          f"（volume 覆盖 {covered}/{close_df.shape[1]}）")
    if failed:
        print(f"⚠️ {len(failed)} 只失败（fail-open）："
              f"{', '.join(c for c, _ in failed[:15])}{' ...' if len(failed) > 15 else ''}")
    await data.close_async_session()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="构建整池行情缓存（close/open/volume，逐只容错）")
    ap.add_argument("--market", choices=["cn", "hk"], required=True)
    ap.add_argument("--pool", choices=["all", "zz500", "hsi"], default="zz500")
    ap.add_argument("--days", type=int, default=800)
    ap.add_argument("--concurrency", type=int, default=15)
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
