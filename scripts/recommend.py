#!/usr/bin/env python3
"""
统一推荐脚本 — 跨市场选股推荐（港股 / A 股 / 美股）

用法:
    uv run scripts/recommend.py                     # 港股推荐（默认）
    uv run scripts/recommend.py --market cn         # A 股推荐
    uv run scripts/recommend.py --market us         # 美股推荐
    uv run scripts/recommend.py --market hk --json  # JSON 输出

三步强制流程:
  ① 全市场扫描（板块扫描）
  ② 中观硬约束过滤（市值/股价/PE）
  ③ 微观三维评分（基本面×5 + 热点×3 + 缠论×2）→ TOP10

依赖:
  - formatter.py（统一格式化）
  - quantrisk/recommender.py（共享过滤/评分逻辑）
  - quantrisk/recommend_hk.py（港股数据源）
  - quantrisk/recommend_cn.py（A 股数据源）
  - quantrisk/recommend_us.py（美股数据源）
"""
from __future__ import annotations

import asyncio, json, sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.formatter import format_output, FormatValidationError
from scripts.quantrisk.data import close_async_session, close_tickflow


# ═══════════════════════════════════════════════════════════════
# 市场适配器路由
# ═══════════════════════════════════════════════════════════════

async def run_hk_recommendation(min_stocks: int = 300) -> dict:
    """港股推荐流程"""
    from scripts.recommend_hk import hk_recommend_pipeline
    return await hk_recommend_pipeline(min_stocks=min_stocks)


async def run_cn_recommendation(min_stocks: int = 200) -> dict:
    """A 股推荐流程"""
    from scripts.quantrisk.recommend_cn import (
        fetch_cn_candidate_pool, cn_recommend_pipeline,
    )
    candidates = await fetch_cn_candidate_pool(min_stocks=min_stocks)
    if not candidates:
        print("❌ A 股候选池获取失败")
        return {}
    return await cn_recommend_pipeline(candidates)


async def run_us_recommendation() -> dict:
    """美股推荐流程"""
    from scripts.quantrisk.recommend_us import (
        get_us_candidate_pool, us_recommend_pipeline,
    )
    candidates = get_us_candidate_pool()
    return await us_recommend_pipeline(candidates)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def parse_args():
    """解析命令行参数"""
    market = "hk"
    json_mode = False
    min_stocks = 200

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--market" and i + 1 < len(args):
            market = args[i + 1].lower()
            i += 2
        elif arg == "--json":
            json_mode = True
            i += 1
        elif arg == "--min-stocks" and i + 1 < len(args):
            min_stocks = int(args[i + 1])
            i += 2
        elif arg == "--help":
            print(__doc__)
            sys.exit(0)
        else:
            i += 1

    if market not in ("hk", "cn", "us"):
        print(f"❌ 未知市场: {market}（可选: hk, cn, us）")
        sys.exit(1)

    return market, json_mode, min_stocks


async def main():
    market, json_mode, min_stocks = parse_args()

    # 路由到对应市场
    if market == "hk":
        print(f"🔍 港股推荐（候选池 {min_stocks}+ 只）...")
        raw_data = await run_hk_recommendation(min_stocks)

    elif market == "cn":
        print(f"🔍 A 股推荐（候选池 {min_stocks}+ 只）...")
        raw_data = await run_cn_recommendation(min_stocks)

    elif market == "us":
        print("🔍 美股推荐（S&P 500 核心）...")
        raw_data = await run_us_recommendation()

    if not raw_data:
        print("❌ 推荐流程执行失败")
        sys.exit(1)

    # 格式化输出
    try:
        report = format_output(raw_data, market=market)
        if not json_mode:
            print(report)
        else:
            print(json.dumps(raw_data, ensure_ascii=False, default=str, indent=2))
    except FormatValidationError as e:
        print(f"❌ 格式校验失败:\n{e.message}")
        sys.exit(1)
    finally:
        await close_async_session()
        await close_tickflow()


if __name__ == "__main__":
    asyncio.run(main())
