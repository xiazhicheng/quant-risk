#!/usr/bin/env python
"""TrendGate 参数网格扫描：持仓数 × 调仓周期 × 闸门类型。

对同一份缓存行情遍历全部组合，输出可直接比较的指标表（累计/年化/回撤/夏普/
平均仓位/空仓率/成交笔数 + 分年与前后半段），用于回答「我的组合该设几只股票、
多少日调仓、闸门用个股还是指数」。

⚠️ 同一段历史上挑最优 = 样本内选择；结果必须配合 walkforward_gate.py 滚动验证
或分年/分段一致性一起看，不能只取单点最优。

用法:
  uv run scripts/scan_trendgate_grid.py --market cn
  uv run scripts/scan_trendgate_grid.py --market hk --pool hsi --max-dd 1.0
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import rotation
from quantrisk.rotation import _metrics
from quantrisk.trendgate import (HS300_SYMBOL, HSI_SYMBOL, TrendGateConfig,
                                 run_trendgate_backtest)


def _fmt_pct(x) -> str:
    return f"{x * 100:.2f}%" if x is not None else "—"


def _fmt_num(x) -> str:
    return f"{x:.3f}" if x is not None else "—"


async def _index_kline_async(symbol: str, days: int):
    from backtest_trendgate import _index_kline_async as _impl
    return await _impl(symbol, days)


def _segments(eq: pd.Series) -> dict[str, float]:
    """分年 + 前后半段收益（段内首日为基准）。"""
    out: dict[str, float] = {}
    for y in sorted({d.year for d in eq.index}):
        seg = eq[eq.index.year == y]
        if len(seg) >= 2 and seg.iloc[0] > 0:
            out[str(y)] = float(seg.iloc[-1] / seg.iloc[0] - 1)
    half = len(eq) // 2
    if half >= 2:
        out["前半段"] = float(eq.iloc[half - 1] / eq.iloc[0] - 1)
        out["后半段"] = float(eq.iloc[-1] / eq.iloc[half - 1] - 1)
    return out


async def _load(market: str, pool: str, days: int):
    use_hsi = market == "hk" and pool == "hsi"
    uni_key = "hk_hsi" if use_hsi else market
    hit = rotation.cache_matrix(f"{uni_key}_d{days}")
    universe = rotation.load_universe_cache(uni_key)
    if not (hit and universe):
        raise SystemExit(f"❌ 缓存缺失（{uni_key}_d{days}）——先跑 backtest_trendgate.py 生成")
    close, open_df = hit[0], hit[1]
    volume = hit[2] if len(hit) > 2 else None
    symbol = HS300_SYMBOL if market == "cn" else HSI_SYMBOL
    gate_index = await _index_kline_async(symbol, len(close))
    if gate_index is None:
        raise SystemExit(f"❌ 闸门指数 {symbol} 获取失败（fail-closed）")
    return universe, close, open_df, gate_index, volume


def _render(args, label, rows, dates) -> str:
    ranked = sorted(rows, key=lambda r: r["sharpe"], reverse=True)
    L = [f"# TrendGate 参数网格扫描（{label}）", "",
         f"区间：{dates[0]:%Y-%m-%d} → {dates[-1]:%Y-%m-%d}；{len(dates)} 交易日；"
         f"单边费用 {args.commission:.2%}；MA{args.gate_ma} 连续{args.confirm}日、敞口{args.exposure:.0%}。", "",
         f"执行口径：滑点 {args.slippage:.2%}/边、涨跌停检查 "
         f"{'关' if args.no_limit_check else ('开（A股 开盘涨停买不进/跌停卖不出）' if args.market == 'cn' else '不适用（港股无涨跌停）')}、"
         f"停牌检查 {'关' if args.no_halt_check else '开（成交量0/缺失不可成交）'}。", "",
         f"组合数：{len(rows)}（持仓数 {args.top_ns} × 调仓周期 {args.rebalance_days} × 闸门 {args.gates}）", ""]
    if args.max_dd < 1.0:
        L += [f"⚠️ 回撤约束：最大回撤必须 ≤ {args.max_dd:.0%}（超限组合标 ❌ 并从推荐中排除）。", ""]
    L += ["## 一、全部组合（按夏普降序）", "",
          "| 排名 | 持仓数 | 调仓周期 | 闸门 | 累计收益 | 年化 | 最大回撤 | 夏普 | 平均仓位 | 空仓率 | 成交笔数 | 约束 |",
          "|--:|--:|--:|:--|--:|--:|--:|--:|--:|--:|--:|:--|"]
    for i, r in enumerate(ranked, 1):
        ok = r["max_drawdown"] is None or r["max_drawdown"] >= -args.max_dd
        flag = "✅" if ok else "❌超回撤"
        L.append(f"| {i} | {r['top_n']} | {r['rebalance_days']}日 | "
                 f"{'个股' if r['gate'] == 'stock' else '指数'} | "
                 f"{_fmt_pct(r['total_return'])} | {_fmt_pct(r['annual_return'])} | "
                 f"{_fmt_pct(r['max_drawdown'])} | {_fmt_num(r['sharpe'])} | "
                 f"{_fmt_pct(r['avg_exposure'])} | {_fmt_pct(r['flat_ratio'])} | "
                 f"{r['fills']} | {flag} |")
    ok_rows = [r for r in ranked if r["max_drawdown"] is None or r["max_drawdown"] >= -args.max_dd]
    best_title = ("## 二、最优组合（夏普最高，且满足回撤约束）" if args.max_dd < 1.0
                  else "## 二、最优组合（夏普最高）")
    L += ["", best_title, ""]
    if ok_rows:
        best = ok_rows[0]
        L += [f"- **夏普最优**：持仓 {best['top_n']} 只 / 每 {best['rebalance_days']} 日调仓 / "
              f"{'个股' if best['gate'] == 'stock' else '指数'}闸门 → "
              f"{_fmt_pct(best['total_return'])} 累计、"
              f"{_fmt_pct(best['max_drawdown'])} 回撤、夏普 {_fmt_num(best['sharpe'])}"]
        by_ret = max(ok_rows, key=lambda r: r["total_return"] or -9)
        L += [f"- **收益最优**：持仓 {by_ret['top_n']} 只 / 每 {by_ret['rebalance_days']} 日调仓 / "
              f"{'个股' if by_ret['gate'] == 'stock' else '指数'}闸门 → "
              f"{_fmt_pct(by_ret['total_return'])} 累计、"
              f"{_fmt_pct(by_ret['max_drawdown'])} 回撤、夏普 {_fmt_num(by_ret['sharpe'])}"]
        by_dd = max(ok_rows, key=lambda r: r["max_drawdown"] or -9)
        L += [f"- **回撤最小**：持仓 {by_dd['top_n']} 只 / 每 {by_dd['rebalance_days']} 日调仓 / "
              f"{'个股' if by_dd['gate'] == 'stock' else '指数'}闸门 → "
              f"{_fmt_pct(by_dd['total_return'])} 累计、"
              f"{_fmt_pct(by_dd['max_drawdown'])} 回撤、夏普 {_fmt_num(by_dd['sharpe'])}"]
    else:
        L += ["- ⚠️ 无组合满足回撤约束"]
    L += ["", "## 三、分年与前后半段（各组合收益，检验稳定性）", "",
          "| 持仓数 | 周期 | 闸门 | " + " | ".join(sorted({k for r in rows for k in r["seg"]})) + " |",
          "|--:|--:|:--|" + "--:|" * len({k for r in rows for k in r["seg"]})]
    keys = sorted({k for r in rows for k in r["seg"]})
    for r in sorted(rows, key=lambda x: (x["top_n"], x["rebalance_days"], x["gate"])):
        L.append(f"| {r['top_n']} | {r['rebalance_days']}日 | "
                 f"{'个股' if r['gate'] == 'stock' else '指数'} | "
                 + " | ".join(_fmt_pct(r["seg"].get(k)) for k in keys) + " |")
    L += ["", "## 四、边界与风险", "",
          "- **样本内选择**：全部组合在同一段历史上比较，最优值是事后挑选，样本外必然打折；"
          "判断稳定性看第三节的分年/分段一致性，必要时用 `walkforward_gate.py` 做滚动验证。",
          "- 闸门指数与行情矩阵来自同一缓存；stock 闸门不依赖指数。",
          "- 成分池快照仍有幸存者/成分前视偏差；未模拟涨跌停、停牌、滑点与税费差异。",
          "- 仓位受 100 股整数倍与现金约束，小仓位（top_n 大、敞口低）时取整影响更明显。",
          ""]
    return "\n".join(L)


async def main_async(args) -> int:
    universe, close, open_df, gate_index, volume = await _load(args.market, args.pool, args.days)
    dates = list(close.index)
    top_ns = [int(x) for x in str(args.top_ns).split(",")]
    rbs = [int(x) for x in str(args.rebalance_days).split(",")]
    gates = [g.strip() for g in str(args.gates).split(",") if g.strip()]
    label = (f"{args.market} / {'恒指成分池' if args.pool == 'hsi' and args.market == 'hk' else args.pool}")

    rows = []
    for top_n in top_ns:
        for rb in rbs:
            for gate in gates:
                cfg = TrendGateConfig(
                    gate_mode=gate, top_n=top_n, rebalance_days=rb,
                    commission_rate=args.commission, gate_ma=args.gate_ma,
                    gate_confirm_days=args.confirm, max_exposure=args.exposure,
                    warmup_days=args.warmup, market=args.market,
                    slippage=args.slippage,
                    enforce_price_limits=not args.no_limit_check,
                    enforce_halts=not args.no_halt_check)
                r = run_trendgate_backtest(close, open_df,
                                           gate_index if gate == "index" else None, cfg, universe,
                                           volume_df=volume)
                m = r.metrics
                flat = float(r.holdings.sum(axis=1).eq(0).mean())
                rows.append({
                    "top_n": top_n, "rebalance_days": rb, "gate": gate,
                    "total_return": m.get("total_return"), "annual_return": m.get("annual_return"),
                    "max_drawdown": m.get("max_drawdown"), "sharpe": m.get("sharpe"),
                    "avg_exposure": m.get("average_exposure"), "flat_ratio": flat,
                    "fills": len(r.fills), "seg": _segments(r.equity_curve),
                })

    report = _render(args, label, rows, dates)
    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"gridscan_{args.market}_{datetime.now():%Y%m%d_%H%M}.md"
    out_file.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 报告已保存: {out_file}")
    from quantrisk import data
    await data.close_async_session()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="TrendGate 参数网格扫描（持仓数 × 调仓周期 × 闸门）")
    ap.add_argument("--market", choices=["cn", "hk"], required=True)
    ap.add_argument("--pool", choices=["amount", "hsi"], default="hsi")
    ap.add_argument("--top-ns", default="3,5,10")
    ap.add_argument("--rebalance-days", default="20,40,60", help="调仓周期（逗号分隔）")
    ap.add_argument("--gates", default="index,stock", help="闸门类型（逗号分隔）")
    ap.add_argument("--days", type=int, default=800)
    ap.add_argument("--gate-ma", type=int, default=30)
    ap.add_argument("--confirm", type=int, default=3)
    ap.add_argument("--exposure", type=float, default=0.7)
    ap.add_argument("--warmup", type=int, default=120)
    ap.add_argument("--commission", type=float, default=0.001)
    ap.add_argument("--slippage", type=float, default=0.0,
                    help="单边滑点（买价×(1+s)、卖价×(1-s)）")
    ap.add_argument("--no-limit-check", action="store_true", help="关闭涨跌停不可成交约束")
    ap.add_argument("--no-halt-check", action="store_true", help="关闭停牌不可成交约束")
    ap.add_argument("--max-dd", type=float, default=1.0, help="回撤约束（如 0.20 = ≤20%%，超限标 ❌）")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
