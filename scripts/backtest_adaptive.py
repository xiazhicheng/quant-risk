#!/usr/bin/env python
"""自适应策略切换回测 CLI —— 检验「先判断震荡/趋势，再切换网格/趋势」是否成立。

用法:
  uv run scripts/backtest_adaptive.py 002340
  uv run scripts/backtest_adaptive.py 300308 --lookback 120 --step 20

输出三部分:
  ① 滚动判定的**预测力**（判定 trend 后，未来一段的 |IR| 是否真的更高）
  ② 自适应切换 vs 纯网格 / 纯趋势 / buy&hold
  ③ 切换次数与震荡占比
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import adaptive, data
from quantrisk.rotation import _metrics


async def fetch(code: str, days: int):
    if len(code) == 5:
        rows = await data.hk_kline_async(code, "day", count=days)
        market = "港股"
    else:
        rows = await data.cn_stock_kline_tencent_async(code, days=days)
        market = "A股"
    await data.close_async_session()
    if not rows:
        return None, market
    df = pd.DataFrame.from_records(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index(), market


def render(code: str, market: str, df: pd.DataFrame, cfg: adaptive.AdaptiveConfig,
           pp: dict, res: adaptive.AdaptiveResult) -> str:
    m = res.metrics
    gm, tm = _metrics(res.legs["grid_only"]), _metrics(res.legs["trend_only"])
    bh = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)
    best_single = max(gm["total_return"], tm["total_return"])
    gap = m["total_return"] - best_single
    L = [f"# 自适应策略切换回测 | {code}（{market}） | {df.index[0].date()} → {df.index[-1].date()}", "",
         "## 检验的问题", "",
         "> 「先判断是震荡型还是趋势型，然后分别用网格或趋势门控」——这个设想可行吗？", "",
         "两个前提必须先解决：① **趋势门控不能套单股**（TrendGate 是组合策略，需 500 只池子排名选前 10），",
         "单股版只能降级为「单股趋势跟随」；② **类型判定必须滚动**（用全区间数据判类型＝前视偏差）。", "",
         "## ① 滚动判定的预测力", "",
         f"- 判定窗口 {cfg.lookback} 日 / 判定频率 {cfg.step} 日 / 阈值 震荡≤{cfg.ir_choppy} 趋势≥{cfg.ir_trend}",
         f"- 判定次数：{pp.get('n_trend', 0) + pp.get('n_choppy', 0)}（trend {pp.get('n_trend', 0)} / choppy {pp.get('n_choppy', 0)}）", "",
         "| 判定为 | 随后 20 日平均 \\|IR\\| | 随后 20 日平均收益 |", "|:--|:--|:--|",
         f"| trend（趋势） | {pp.get('trend_fwd_ir', float('nan')):.2f} | {pp.get('trend_fwd_ret', float('nan'))*100:+.2f}% |",
         f"| choppy（震荡） | {pp.get('choppy_fwd_ir', float('nan')):.2f} | {pp.get('choppy_fwd_ret', float('nan'))*100:+.2f}% |",
         "",
         f"> **判定有没有预测力？** trend 后 |IR| 比 choppy 后 "
         f"{'更高 → 有预测力' if pp.get('trend_fwd_ir', 0) > pp.get('choppy_fwd_ir', 0) else '**更低 → 无预测力（判反了）**'}"
         f"（差值 {pp.get('trend_fwd_ir', 0) - pp.get('choppy_fwd_ir', 0):+.2f}）", "",
         "## ② 自适应切换 vs 单一子策略", "",
         "| 方案 | 累计收益 | 最大回撤 | 夏普 |", "|:--|:--|:--|:--|",
         f"| **自适应切换** | **{m['total_return']*100:.2f}%** | {m['max_drawdown']*100:.2f}% | {m['sharpe']:.3f} |",
         f"| 纯网格（全程） | {gm['total_return']*100:.2f}% | {gm['max_drawdown']*100:.2f}% | {gm['sharpe']:.3f} |",
         f"| 纯趋势跟随（全程） | {tm['total_return']*100:.2f}% | {tm['max_drawdown']*100:.2f}% | {tm['sharpe']:.3f} |",
         f"| buy&hold | {bh*100:.2f}% | {_metrics(df['close'])['max_drawdown']*100:.2f}% | — |", "",
         f"- 自适应 vs **最优单一策略**（{best_single*100:.2f}%）：**{gap*100:+.2f}pp** "
         f"→ {'✅ 切换有价值' if gap > 0 else '❌ **切换不如直接选一个用到底**'}",
         f"- 切换次数：{res.n_switches}（每次扣 {cfg.switch_cost*100:.2f}% 摩擦 → 约 {res.n_switches*cfg.switch_cost*100:.2f}%）",
         f"- 震荡状态占比：{m.get('choppy_days_ratio', 0)*100:.0f}%", "",
         "## 结论", ""]
    if gap > 0:
        L.append(f"- 本标的上自适应切换优于最优单一策略 {gap*100:+.2f}pp，可继续观察")
    else:
        L.append(f"- ⚠️ **本标的自适应切换跑输最优单一策略 {gap*100:.2f}pp**："
                 "判定滞后（等窗口确认趋势时行情已走大半）+ 切换摩擦 + 两头挨打")
    L += ["- **更根本的问题**：`analyze_fit.py` 的 IR/ER 是**事后指标**（用全区间数据算）——",
          "  「事后知道该用哪个策略」不等于「事前能判断出来」。本回测用滚动（无前视）判定后，",
          "  预测力与切换收益双双落空。", "",
          "> ⚠️ 实现口径：切换用**收益拼接**近似（切换日按新子策略日收益计 + 摩擦成本），",
          "> 未模拟两策略间真实仓位转移，故自适应结果为**上界估计**（实际只会更差）。",
          "> ⚠️ 声明：基于公开数据回测，不构成投资建议。"]
    return "\n".join(L)


async def main_async(args) -> int:
    df, market = await fetch(args.code, args.days)
    if df is None or df.empty:
        print(f"❌ {args.code} 无数据", file=sys.stderr)
        return 1
    cfg = adaptive.AdaptiveConfig(lookback=args.lookback, step=args.step,
                                  grid_spacing=args.spacing, trend_ma=args.trend_ma,
                                  commission=args.commission)
    pp = adaptive.regime_predictive_power(df["close"], cfg, horizon=20)
    res = adaptive.adaptive_backtest(df, cfg)
    report = render(args.code, market, df, cfg, pp, res)
    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"adaptive_{args.code}_{datetime.now():%Y%m%d}.md"
    f.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 报告已保存: {f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="自适应策略切换回测（震荡→网格 / 趋势→跟随）")
    ap.add_argument("code", help="股票代码（A股 6 位 / 港股 5 位）")
    ap.add_argument("--days", type=int, default=800)
    ap.add_argument("--lookback", type=int, default=120, help="类型判定窗口")
    ap.add_argument("--step", type=int, default=20, help="判定频率")
    ap.add_argument("--spacing", type=float, default=0.02, help="网格间距")
    ap.add_argument("--trend-ma", type=int, default=20, help="趋势子策略均线")
    ap.add_argument("--commission", type=float, default=0.001)
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())