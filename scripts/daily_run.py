#!/usr/bin/env python3
"""每日收盘工作流入口（Phase 1，无 LLM 依赖）。

用法:
    uv run scripts/daily_run.py                     # A股+港股
    uv run scripts/daily_run.py --markets cn        # 仅 A股
    uv run scripts/daily_run.py --markets cn,hk --min-stocks 300 --rule-engine shadow
    uv run scripts/daily_run.py --no-backtest       # 不记录 TOP10 回测 jsonl

产物:
    report/recommend-{cn,hk}-YYYYMMDD-daily.md      每日信号报告
    report/snapshots/{cn,hk}-YYYYMMDD.json          冻结快照（walk-forward 基建）
    report/decision_outbox.sqlite3                  决策凭证（pipeline 内落库）
    report/swing_backtest.jsonl                     TOP10 回测记录（backtest_swing --report 消费）

边界: 固定 research 运行模式，不接 live；单市场失败不中断另一市场。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.quantrisk.daily import (render_daily_summary, run_daily,
                                     trendgate_signal, render_strategy_signals)
from scripts.quantrisk.data import close_async_session, close_tickflow


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="每日收盘工作流（A股+港股，无 LLM 依赖）")
    ap.add_argument("--markets", default="cn,hk", help="市场，逗号分隔（cn/hk），默认 cn,hk")
    ap.add_argument("--min-stocks", type=int, default=300, help="候选池规模（默认 300，龙头优先）")
    ap.add_argument("--rule-engine", default="shadow", choices=("python", "shadow", "semantica"),
                    help="规则引擎（默认 shadow：Python 主裁决 + Semantica 影子对比）")
    ap.add_argument("--no-backtest", action="store_true", help="不记录 TOP10 到 swing_backtest.jsonl")
    ap.add_argument("--snapshot-dir", default="report/snapshots", help="冻结快照输出目录")
    ap.add_argument("--gate-ma", type=int, default=30,
                    help="TrendGate 闸门均线周期（默认 30：A股/港股均采用激进档 MA30）")
    ap.add_argument("--gate-modes", default="cn=index,hk=index",
                    help="各市场闸门类型，逗号分隔（cn=index|stock,hk=index|stock；"
                         "默认 cn=index,hk=index；港股个股闸门用 hk=stock）")
    return ap.parse_args()


async def main() -> None:
    args = parse_args()
    result = await run_daily(
        markets=args.markets, min_stocks=args.min_stocks, rule_engine=args.rule_engine,
        snapshot_dir=Path(args.snapshot_dir), record_backtest=not args.no_backtest)
    print(render_daily_summary(result))

    # ── 策略层信号（TrendGate：闸门状态 + 双动量 TOP10，best-effort 不阻断）──
    markets = tuple(m.strip() for m in args.markets.split(",") if m.strip())
    gate_modes = {}
    for pair in str(args.gate_modes).split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            gate_modes[k.strip()] = v.strip()
    signals = []
    for m in markets:
        try:
            sig = await trendgate_signal(m, gate_ma=args.gate_ma,
                                         gate_mode=gate_modes.get(m, "index"))
            signals.append(sig)
        except Exception as exc:
            signals.append({"market": m, "label": m, "error": f"{type(exc).__name__}: {exc}"})
    if markets:
        sig_md = render_strategy_signals(signals)
        sig_file = Path("report") / f"strategy-signals-{date.today():%Y%m%d}.md"
        sig_file.parent.mkdir(parents=True, exist_ok=True)
        sig_file.write_text(sig_md, encoding="utf-8")
        print("\n" + sig_md)
        print(f"\n📄 策略信号已保存: {sig_file}")
    await close_async_session()
    await close_tickflow()
    failed = [m for m, v in (result.get("markets") or {}).items() if v.get("error")]
    if failed:
        print(f"⚠️ 失败市场：{', '.join(failed)}（其余市场产物已落盘）")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
