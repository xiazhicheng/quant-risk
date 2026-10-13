#!/usr/bin/env python
"""Point-in-Time 池检验（PIT）——检验"当前池快照"带来的前视偏差。

问题：用「今天的成交额 Top100」回测过去 = 提前知道谁会变热（幸存者/前视偏差）。
本脚本按 point-in-time 原则重建池子：**每个交易日只用截至该日可得的 20 日均成交额
排名**取 Top N，再与「静态池（当前 Top N）」对照，量化偏差并给出无前视结论。

用法:
  uv run scripts/pit_check.py --market hk --candidates 500 --pool 100 --days 600
  uv run scripts/pit_check.py --market hk --no-clean      # 保留复权跳变股（默认剔除）

数据源: 池=东财 clist（新浪榜单兜底）；日K=腾讯（港股 volume 单位=股，A股=手×100）。
输出: report/pit_{market}_YYYYmmdd.md
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import rotation, trendgate

JUMP_DROP, JUMP_UP = -0.30, 0.50     # 单日跳变阈值（港股无涨跌幅限制，多为合股/拆股复权问题）


async def _index_kline(symbol: str, days: int):
    from quantrisk import data
    d = await data._tencent_kline_get(f"{symbol},day,,,{days},qfq")
    kd = ((d or {}).get("data") or {}).get(symbol) or {}
    rows = kd.get("day") or kd.get("qfqday") or []
    if not rows:
        return None
    s = pd.Series({r[0]: float(r[2]) for r in rows if len(r) >= 3})
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def build_pit(close: pd.DataFrame, volume: pd.DataFrame, pool_n: int, lot: int):
    """逐期池 + 池内排名 + 池等权指数。返回 (pit_scores, pit_ew_index, pool_by_date)。"""
    amount = volume.reindex_like(close) * lot * close
    amt20 = amount.rolling(20).mean()
    pool_by_date: dict = {}
    for d in amt20.index:
        row = amt20.loc[d].dropna()
        if not row.empty:
            pool_by_date[d] = list(row.nlargest(pool_n).index)

    # 池内横截面排名（非当期池 → NaN，选股自然跳过）
    ret20, ret60 = close.pct_change(20), close.pct_change(60)
    pit = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for d, pool in pool_by_date.items():
        r20, r60 = ret20.loc[d, pool].rank(pct=True), ret60.loc[d, pool].rank(pct=True)
        pit.loc[d, pool] = (0.5 * r20 + 0.5 * r60).where(r20.notna() & r60.notna())

    # 池等权指数（无前视的可比基准；也是"池内等权闸门"的信号源）
    rets = close.pct_change()
    ew_daily = pd.Series(0.0, index=close.index)
    for d, pool in pool_by_date.items():
        r = rets.loc[d, pool].dropna()
        if len(r):
            ew_daily.loc[d] = r.mean()
    return pit, (1 + ew_daily).cumprod(), pool_by_date


async def main_async(args) -> int:
    market = args.market
    lot = 1 if market == "hk" else 100
    gate_symbol = "hkHSI" if market == "hk" else "sh000300"

    # ── 候选集（远大于当期池，才能体现"当时的池"与"现在的池"的差异）──
    cache_u = rotation.load_universe_cache(f"pit_{market}_cand")
    if cache_u and len(cache_u) >= args.candidates and not args.no_cache:
        cand = cache_u[: args.candidates]
        print(f"候选集(缓存): {len(cand)} 只")
    else:
        if market == "hk":
            cand = await rotation.fetch_hk_top_amount(args.candidates)
        else:
            cand = await rotation.fetch_zz500_constituents()
        print(f"候选集: {len(cand)} 只")
        if not args.no_cache:
            rotation.save_universe_cache(f"pit_{market}_cand", cand)

    # ── 行情 ──
    key = f"pit_{market}_cand_d{args.days}"
    hit = None if args.no_cache else rotation.cache_matrix(key)
    if hit and len(hit) == 3:
        close, open_df, volume = hit
        print(f"行情(缓存): {close.shape}")
    else:
        close, open_df, volume = await rotation.load_close_open_volume(cand, market, args.days)
        print(f"行情: {close.shape}")
        if not args.no_cache:
            rotation.save_cache(key, close, open_df, volume)

    # ── 数据清洗：剔除复权跳变股（否则脏数据会制造假收益）──
    ret = close.pct_change()
    bad = set(ret.columns[((ret < JUMP_DROP).sum() + (ret > JUMP_UP).sum()) > 0])
    n_bad = len(bad)
    if not args.no_clean and n_bad:
        keep = [c for c in close.columns if c not in bad]
        close, open_df, volume = close[keep], open_df[keep], volume[keep]
        print(f"剔除复权跳变股 {n_bad} 只 → 保留 {len(keep)} 只")
    else:
        print(f"复权跳变股 {n_bad} 只（{'保留' if args.no_clean else '无'}）")

    codes = list(close.columns)
    static_pool = codes[: args.pool]                     # 静态池 = 当前排名前 N
    pit_scores, pit_ew, _ = build_pit(close, volume, args.pool, lot)
    static_ew = (1 + close[static_pool].pct_change().mean(axis=1).fillna(0.0)).cumprod()
    gate_idx = await _index_kline(gate_symbol, len(close) + 200)

    cfg = trendgate.TrendGateConfig(commission_rate=args.commission)
    uni = [c for c in cand if c["code"] in set(codes)]

    runs = [
        ("静态池(当前排名) + 恒指闸门", close[static_pool], open_df[static_pool], gate_idx, None),
        ("静态池(当前排名) + 池等权闸门", close[static_pool], open_df[static_pool], static_ew, None),
        ("PIT池(逐期重算) + 恒指闸门", close, open_df, gate_idx, pit_scores),
        ("PIT池(逐期重算) + 池等权闸门", close, open_df, pit_ew, pit_scores),
    ]
    rows = []
    for label, c, o, g, sc in runs:
        r = trendgate.run_trendgate_backtest(c, o, g, cfg, uni, scores_override=sc)
        m = r.metrics
        cash = float((r.holdings.sum(axis=1) == 0).mean() * 100)
        rows.append((label, r, m, cash))

    idx = rows[-1][1].equity_curve.index

    def seg(s):
        x = s.reindex(idx).dropna()
        return float(x.iloc[-1] / x.iloc[0] - 1) if len(x) > 1 else float("nan")

    bench = {"静态池等权(当前快照)": seg(static_ew), "PIT池等权(无前视)": seg(pit_ew),
             f"市场指数({'恒生指数' if market == 'hk' else '沪深300'})": seg(gate_idx)}

    L = [f"# Point-in-Time 池检验 | {market.upper()} | {idx[0].date()} → {idx[-1].date()}",
         "", "## 方法", "",
         f"- 候选集 {len(cand)} 只（清洗后 {len(codes)} 只）；当期池 = 截至该日 **20 日均成交额 Top {args.pool}**",
         "- **静态池** = 用「当前」成交额排名选出的池子回溯回测（含前视/幸存者偏差）",
         "- **PIT 池** = 每个交易日只用「截至该日可得」的成交额排名重建池子（无前视）",
         "- 选股得分在**当期池内**做横截面排名（非池内标的置 NaN）",
         f"- 复权跳变清洗：单日 <{JUMP_DROP:.0%} 或 >{JUMP_UP:.0%} 视为合股/拆股脏数据，"
         f"{'已剔除' if not args.no_clean else '未剔除'}", "",
         "## 结果", "",
         "| 方案 | 累计收益 | 年化 | 最大回撤 | 夏普 | 空仓占比 |",
         "|:--|:--|:--|:--|:--|:--|"]
    for label, _r, m, cash in rows:
        L.append(f"| {label} | {m['total_return']*100:.2f}% | {m['annual_return']*100:.2f}% | "
                 f"{m['max_drawdown']*100:.2f}% | {m['sharpe']:.3f} | {cash:.1f}% |")
    L += ["", "## 基准（同池可比）", "", "| 基准 | 区间收益 |", "|:--|:--|"]
    for k, v in bench.items():
        L.append(f"| {k} | {v*100:.2f}% |")
    L += ["", "## 超额（相对各自可比基准）", "", "| 方案 | 相对基准 |", "|:--|:--|"]
    for label, _r, m, _c in rows:
        ref = bench["PIT池等权(无前视)"] if label.startswith("PIT") else bench["静态池等权(当前快照)"]
        L.append(f"| {label} | {(m['total_return'] - ref)*100:+.2f}pp |")
    L += ["",
          f"> 静态池等权 vs PIT池等权 = {(bench['静态池等权(当前快照)'] - bench['PIT池等权(无前视)'])*100:+.2f}pp"
          " ← **池子快照本身带来的偏差量级**",
          "",
          "> ⚠️ 声明：免费公开数据源回测，未含滑点/停牌冲击；PIT 仍有残余偏差"
          "（退市与已边缘化标的从榜单消失）。不构成投资建议。"]

    report = "\n".join(L)
    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"pit_{market}_{datetime.now():%Y%m%d}.md"
    out_file.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\n📄 报告已保存: {out_file}")

    from quantrisk import data
    await data.close_async_session()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Point-in-Time 池检验（前视偏差量化）")
    ap.add_argument("--market", choices=["cn", "hk"], default="hk")
    ap.add_argument("--candidates", type=int, default=500, help="候选集大小（远大于当期池）")
    ap.add_argument("--pool", type=int, default=100, help="当期池大小（成交额 Top N）")
    ap.add_argument("--days", type=int, default=600)
    ap.add_argument("--commission", type=float, default=0.001)
    ap.add_argument("--no-clean", action="store_true", help="不剔除复权跳变股")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())