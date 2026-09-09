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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.quantrisk.daily import render_daily_summary, run_daily
from scripts.quantrisk.data import close_async_session, close_tickflow


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="每日收盘工作流（A股+港股，无 LLM 依赖）")
    ap.add_argument("--markets", default="cn,hk", help="市场，逗号分隔（cn/hk），默认 cn,hk")
    ap.add_argument("--min-stocks", type=int, default=300, help="候选池规模（默认 300，龙头优先）")
    ap.add_argument("--rule-engine", default="shadow", choices=("python", "shadow", "semantica"),
                    help="规则引擎（默认 shadow：Python 主裁决 + Semantica 影子对比）")
    ap.add_argument("--no-backtest", action="store_true", help="不记录 TOP10 到 swing_backtest.jsonl")
    ap.add_argument("--snapshot-dir", default="report/snapshots", help="冻结快照输出目录")
    return ap.parse_args()


async def main() -> None:
    args = parse_args()
    result = await run_daily(
        markets=args.markets, min_stocks=args.min_stocks, rule_engine=args.rule_engine,
        snapshot_dir=Path(args.snapshot_dir), record_backtest=not args.no_backtest)
    print(render_daily_summary(result))
    await close_async_session()
    await close_tickflow()
    failed = [m for m, v in (result.get("markets") or {}).items() if v.get("error")]
    if failed:
        print(f"⚠️ 失败市场：{', '.join(failed)}（其余市场产物已落盘）")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
