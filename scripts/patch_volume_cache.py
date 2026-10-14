#!/usr/bin/env python
"""为已有 close/open 缓存补 volume 矩阵（停牌/无量判定用）。

不动既有 close.csv / open.csv —— 只按它们的 index/columns 对齐补 volume.csv，
保证价格口径与既有回测完全可比。逐只拉取、单只失败重试 3 次后 fail-open
（该列留空 = 停牌检查对该股不生效），不因个别接口断连中断整体。

用法:
  uv run scripts/patch_volume_cache.py --key cn_d800 --market cn
  uv run scripts/patch_volume_cache.py --key hk_hsi_d800 --market hk
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import data, rotation


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
                await asyncio.sleep(0.4 * (attempt + 1))
                continue
        if not rows:
            return code, None, "empty"
        df = pd.DataFrame.from_records(rows)
        if "volume" not in df or df.empty:
            return code, None, "no_volume"
        df["date"] = pd.to_datetime(df["date"])
        s = df.drop_duplicates("date").set_index("date")["volume"].astype(float).sort_index()
        return code, s, None
    return code, None, "unknown"


async def main_async(args) -> int:
    d = rotation.CACHE_DIR / args.key
    if not (d / "close.csv").exists():
        raise SystemExit(f"❌ 缓存不存在: {d}/close.csv")
    close = pd.read_csv(d / "close.csv", index_col=0, parse_dates=True)
    days = len(close)
    codes = list(close.columns)
    print(f"基准矩阵：{len(codes)} 只 × {days} 日（{close.index[0]:%Y-%m-%d} → {close.index[-1]:%Y-%m-%d}）")

    sem = asyncio.Semaphore(args.concurrency)
    tasks = [_one(str(c), args.market, days, sem) for c in codes]
    results = await asyncio.gather(*tasks)

    vols, failed = {}, []
    for code, s, err in results:
        if s is None:
            failed.append((code, err))
            continue
        vols[code] = s.reindex(close.index)
    if not vols:
        raise SystemExit("❌ 全部失败，未写 volume.csv")
    vol_df = pd.DataFrame(vols).reindex(columns=close.columns)
    vol_df.to_csv(d / "volume.csv")
    covered = int(vol_df.notna().any(axis=0).sum())
    print(f"✅ 已写 {d}/volume.csv：覆盖 {covered}/{len(codes)} 只"
          f"（有效值 {int(vol_df.notna().sum().sum())} 个）")
    if failed:
        print(f"⚠️ {len(failed)} 只失败（该股停牌检查 fail-open）："
              f"{', '.join(c for c, _ in failed[:10])}{' ...' if len(failed) > 10 else ''}")
    await data.close_async_session()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="补 volume 矩阵到已有行情缓存")
    ap.add_argument("--key", required=True, help="缓存目录名，如 cn_d800 / hk_hsi_d800")
    ap.add_argument("--market", choices=["cn", "hk"], required=True)
    ap.add_argument("--concurrency", type=int, default=8, help="并发度（默认 8，越低越不易被断连）")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
