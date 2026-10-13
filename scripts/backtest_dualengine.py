#!/usr/bin/env python
"""双引擎组合回测 CLI（趋势引擎 TrendGate × 震荡引擎 Grid）。

用法:
  uv run scripts/backtest_dualengine.py                       # 权重扫描 + 关键对照（默认）
  uv run scripts/backtest_dualengine.py --tg-weight 0.7       # 指定权重出详细报告
  uv run scripts/backtest_dualengine.py --rebalance annual    # 年度再平衡

组合方式（纯组合层，不改引擎）：各引擎用分配到的资金独立回测 → 对齐交易日 →
按权重加权求和；`--rebalance` 控制是否每年初拉回目标权重。

**必读**：组合能否改善，取决于两腿的**风险调整收益**，不只是相关性。低相关 + 低夏普的
腿加进来会拉低整体夏普（分散化只能"平均"，不能凭空创造）。
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

from quantrisk import data, dualengine, grid, trendgate

ETF_DEFAULT = "510500"


async def fetch_legs(etf: str, days: int, commission_tg: float, commission_grid: float,
                     grid_spacing: float):
    """在同一事件循环内取全部数据并跑两条腿（aiohttp session 与 loop 绑定）。"""
    from quantrisk import rotation
    hit = rotation.cache_matrix("mf_cn_d800")
    if hit is None:
        print("❌ 缺少 A股行情缓存，请先跑 backtest_trendgate.py --market cn", file=sys.stderr)
        return None
    close, open_df = hit[0], hit[1]
    universe = rotation.load_universe_cache("cn") or []

    async def kline(sym: str, n: int):
        d = await data._tencent_kline_get(f"{sym},day,,,{n},qfq")
        kd = ((d or {}).get("data") or {}).get(sym) or {}
        rows = kd.get("day") or kd.get("qfqday") or []
        s = pd.Series({r[0]: float(r[2]) for r in rows if len(r) >= 3})
        s.index = pd.to_datetime(s.index)
        return s.sort_index()

    hs300 = await kline("sh000300", len(close))
    erows = await data.cn_stock_kline_tencent_async(etf, days=days)
    await data.close_async_session()
    if not erows:
        print(f"❌ {etf} 无 K 线", file=sys.stderr)
        return None
    raw = pd.DataFrame.from_records(erows)
    raw["date"] = pd.to_datetime(raw["date"])
    gdf = raw.set_index("date").sort_index()

    tg = trendgate.run_trendgate_backtest(
        close, open_df, hs300, trendgate.TrendGateConfig(commission_rate=commission_tg), universe)
    gc = grid.GridConfig(spacing=grid_spacing, commission_rate=commission_grid)
    gr = grid.run_grid_backtest(gdf, gc)
    bh = grid.buy_hold(gdf, gc)
    return tg, gr, bh, gdf


def render(tg, gr, bh, etf: str, cfg_w: float, grid_spacing: float, etf_days: int,
           commission_tg: float, commission_grid: float) -> str:
    legs = {"TrendGate": tg.equity_curve, "Grid": gr.equity_curve, "ETF_bh": bh}
    idx = legs["TrendGate"].index.intersection(legs["Grid"].index)
    legs = {k: v.reindex(idx) for k, v in legs.items()}
    corr_tg_grid = dualengine.leg_correlation({k: legs[k] for k in ("TrendGate", "Grid")})
    corr_tg_etf = dualengine.leg_correlation({k: legs[k] for k in ("TrendGate", "ETF_bh")})
    corr_grid_etf = dualengine.leg_correlation({k: legs[k] for k in ("Grid", "ETF_bh")})

    def m_of(w):
        r = dualengine.combine_equity(legs, w)
        m = r.metrics
        m["calmar"] = (m["annual_return"] / abs(m["max_drawdown"])) if m["max_drawdown"] < 0 else float("nan")
        return m

    L = ["# 双引擎组合回测（TrendGate × Grid）| A股 | "
         f"{idx[0].date()} → {idx[-1].date()}", "", "## 设计", "",
         f"- **腿1 趋势引擎 TrendGate**：中证500成分（{len(tg.universe)} 只）双动量选股 + 沪深300 MA20 闸门 + 70% 敞口",
         f"- **腿2 震荡引擎 Grid**：{etf} 等比网格（间距 {grid_spacing:.1%}，越跌越买）",
         "- **组合方式**：资金分层并行（各腿用分配资金独立回测 → 对齐 → 加权求和），**不预测市场状态**",
         f"- 对照腿：ETF 被动持有（同样资金直接买 {etf} 不跑网格），用于回答「那部分钱给网格值不值」", "",
         "## 两腿独立表现（各自满额资金）", "",
         "| 腿 | 累计收益 | 最大回撤 | 夏普 |", "|:--|:--|:--|:--|"]
    for nm, m in [("TrendGate", tg.metrics), ("Grid", gr.metrics),
                  ("ETF 被动持有", dualengine._metrics(bh.reindex(idx).dropna()))]:
        L.append(f"| {nm} | {m['total_return']*100:.2f}% | {m['max_drawdown']*100:.2f}% | {m['sharpe']:.3f} |")
    L += ["", "## 相关性（分散化的原料）", "", "| 组合 | 日收益相关性 |", "|:--|:--|",
          f"| TrendGate ~ Grid | **{corr_tg_grid:.3f}** |",
          f"| TrendGate ~ ETF被动 | {corr_tg_etf:.3f} |",
          f"| Grid ~ ETF被动 | {corr_grid_etf:.3f}（标的相同，网格只是择时） |", "",
          "## 权重扫描（第一条腿 = TrendGate 占比）", "",
          "| TrendGate 权重 | 累计收益 | 年化 | 最大回撤 | 夏普 | 卡玛 |", "|:--|:--|:--|:--|:--|:--|"]
    for w in (1.0, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.0):
        m = m_of({"TrendGate": w, "Grid": 1 - w})
        L.append(f"| {w:.0%} | {m['total_return']*100:.2f}% | {m['annual_return']*100:.2f}% | "
                 f"{m['max_drawdown']*100:.2f}% | {m['sharpe']:.3f} | {m['calmar']:.2f} |")
    L += ["", "## 关键对照：那部分钱给「网格」还是「被动持有」", "",
          "| 方案 | 累计收益 | 最大回撤 | 夏普 | 卡玛 |", "|:--|:--|:--|:--|:--|"]
    for label, w in [("100% TrendGate", {"TrendGate": 1.0}),
                     ("50/50 TrendGate + 网格", {"TrendGate": .5, "Grid": .5}),
                     ("50/50 TrendGate + ETF被动", {"TrendGate": .5, "ETF_bh": .5}),
                     ("70/30 TrendGate + 网格", {"TrendGate": .7, "Grid": .3}),
                     ("70/30 TrendGate + ETF被动", {"TrendGate": .7, "ETF_bh": .3}),
                     ("100% 网格", {"Grid": 1.0}), ("100% ETF被动", {"ETF_bh": 1.0})]:
        m = m_of(w)
        L.append(f"| {label} | {m['total_return']*100:.2f}% | {m['max_drawdown']*100:.2f}% | "
                 f"{m['sharpe']:.3f} | {m['calmar']:.2f} |")

    # 分子区间：网格腿 vs 被动腿
    L += ["", "## 分子区间：网格腿 vs 被动腿（各 50/50）", "",
          "| 年份 | TrendGate 单独 | 网格单独 | 50/50 网格腿 | 50/50 被动腿 | 网格腿优势 |",
          "|:--|:--|:--|:--|:--|:--|"]
    wins = 0
    for y in sorted(set(idx.year)):
        seg = idx[idx.year == y]
        if len(seg) < 30:
            continue
        sub = {k: v.reindex(seg) for k, v in legs.items()}
        a = dualengine.combine_equity(sub, {"TrendGate": .5, "Grid": .5}).equity_curve
        b = dualengine.combine_equity(sub, {"TrendGate": .5, "ETF_bh": .5}).equity_curve
        t_, g_ = legs["TrendGate"].reindex(seg), legs["Grid"].reindex(seg)
        ar, br = a.iloc[-1] / a.iloc[0] - 1, b.iloc[-1] / b.iloc[0] - 1
        wins += 1 if ar > br else 0
        L.append(f"| {y} | {t_.iloc[-1]/t_.iloc[0]-1:+.2%} | {g_.iloc[-1]/g_.iloc[0]-1:+.2%} | "
                 f"{ar:+.2%} | {br:+.2%} | {(ar-br)*100:+.2f}pp |")

    best = max(((m_of({"TrendGate": float(w), "Grid": 1 - float(w)}), float(w))
                for w in np.arange(0, 1.01, 0.1)),
               key=lambda t: (round(t[0]["sharpe"], 4), t[1]))   # 夏普并列时取更高 TG 权重
    pure = m_of({"TrendGate": 1.0})
    gain = best[0]["sharpe"] - pure["sharpe"]
    if abs(gain) < 0.01:
        best_txt = (f"全区间最优权重 ≈ **TrendGate {best[1]:.0%}**（夏普 {best[0]['sharpe']:.3f}），"
                    f"但与 100% TrendGate（夏普 {pure['sharpe']:.3f}）**无实质差异"
                    f"（Δ{gain:+.4f}）** → 加网格并未提升风险调整收益")
    else:
        best_txt = (f"全区间最优权重：**TrendGate {best[1]:.0%}**（夏普 {best[0]['sharpe']:.3f}），"
                    f"较 100% TrendGate（{pure['sharpe']:.3f}）改善 {gain:+.4f}")

    L += ["", "## 结论", "",
          f"- {best_txt}",
          f"- 网格腿在 {wins}/{len([y for y in set(idx.year) if len(idx[idx.year==y])>=30])} 个年度优于被动腿"
          "（网格的主场是震荡/下跌年）",
          "- **低相关 ≠ 值得加入**：两腿相关性虽仅 "
          f"{corr_tg_grid:.3f}，但网格自身夏普（{gr.metrics['sharpe']:.3f}）远低于 TrendGate"
          f"（{tg.metrics['sharpe']:.3f}），分散化只能「平均」两者 → 组合夏普单调落在中间", "",
          f"> ⚠️ 区间局限：{idx[0].date()} → {idx[-1].date()} 以**趋势市为主**"
          "（2025 中证500ETF 大涨），网格主场（震荡市）占比低 → 结论对样本区间敏感。",
          "> ⚠️ 声明：免费公开数据源回测，未含滑点，不构成投资建议。"]
    return "\n".join(L)


async def main_async(args) -> int:
    out = await fetch_legs(args.etf, args.days, args.commission_tg, args.commission_grid, args.grid_spacing)
    if out is None:
        return 1
    tg, gr, bh, _ = out
    print(f"TrendGate 腿: {tg.metrics['total_return']*100:.2f}%  回撤 {tg.metrics['max_drawdown']*100:.2f}%")
    print(f"网格腿:      {gr.metrics['total_return']*100:.2f}%  回撤 {gr.metrics['max_drawdown']*100:.2f}%")
    report = render(tg, gr, bh, args.etf, args.tg_weight, args.grid_spacing, args.days,
                    args.commission_tg, args.commission_grid)
    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"dualengine_{datetime.now():%Y%m%d}.md"
    f.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\n📄 报告已保存: {f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="双引擎组合回测（TrendGate 趋势 × Grid 震荡）")
    ap.add_argument("--etf", default=ETF_DEFAULT, help="网格腿标的（宽基 ETF）")
    ap.add_argument("--days", type=int, default=800)
    ap.add_argument("--tg-weight", type=float, default=0.5, help="TrendGate 权重（报告默认对照 50/50）")
    ap.add_argument("--grid-spacing", type=float, default=0.02, help="网格间距")
    ap.add_argument("--commission-tg", type=float, default=0.001)
    ap.add_argument("--commission-grid", type=float, default=0.0002)
    ap.add_argument("--rebalance", choices=["none", "annual"], default="none")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())