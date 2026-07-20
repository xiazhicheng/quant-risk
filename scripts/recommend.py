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
    from scripts.quantrisk.recommend_hk import hk_recommend_pipeline
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

    # 检查是否真的有值得推荐的标的
    top10 = raw_data.get("top10", [])
    if top10:
        top_score = top10[0].get("total", 0) if isinstance(top10[0], dict) else getattr(top10[0], "total", 0)
        top_advice = top10[0].get("advice", "") if isinstance(top10[0], dict) else getattr(top10[0], "advice", "")
    else:
        top_score = 0
        top_advice = ""

    market_label = {"hk": "港股", "cn": "A股", "us": "美股"}.get(market, "未知市场")
    eliminated = raw_data.get("eliminated", [])
    passed_cnt = raw_data.get("passed_count", 0)

    if top_score < 22 or top_advice == "回避":
        # 没有合适的推荐标的，诚实告知
        print(f"## {market_label}选股推荐 | {raw_data.get('date', '')}")
        print()
        print("### ❌ 当前无可推荐标的")
        print()
        reasons = []
        reasons.append(f"本次扫描共评估了 **{passed_cnt}** 只标的")
        if eliminated:
            reasons.append(f"其中 **{len(eliminated)}** 只因市值/股价/PE等硬约束被剔除")
        reasons.append(f"通过过滤的候选标的中，**最高评分仅 {top_score}/50**，低于推荐阈值（22分）")
        reasons.append("")

        # 展示评分较低的根因分析
        score_breakdown = []
        for i, item in enumerate(top10[:3]):
            if isinstance(item, dict):
                code, name = item.get("code", "?"), item.get("name", "?")
                fb, hot, ch = item.get("fb", 0), item.get("hot", 0), item.get("ch", 0)
                total = item.get("total", 0)
            else:
                code, name = getattr(item, "code", "?"), getattr(item, "name", "?")
                fb, hot, ch = getattr(item, "fb", 0), getattr(item, "hot", 0), getattr(item, "ch", 0)
                total = getattr(item, "total", 0)
            score_breakdown.append(f"  {i+1}. **{name}（{code}）** — 总分 {total} = 基本面{fb}×5 + 热点{hot}×3 + 缠论{ch}×2")

        if score_breakdown:
            reasons.append("评分最高的标的：")
            reasons.extend(score_breakdown)
            reasons.append("")

        # 分析各维度薄弱原因
        weak_spots = []
        avg_fb = sum((item.get("fb", 0) if isinstance(item, dict) else getattr(item, "fb", 0)) for item in top10[:5]) / max(len(top10[:5]), 1)
        avg_hot = sum((item.get("hot", 0) if isinstance(item, dict) else getattr(item, "hot", 0)) for item in top10[:5]) / max(len(top10[:5]), 1)
        avg_ch = sum((item.get("ch", 0) if isinstance(item, dict) else getattr(item, "ch", 0)) for item in top10[:5]) / max(len(top10[:5]), 1)

        if avg_fb < 3:
            weak_spots.append(f"📊 **基本面偏弱**（平均 {avg_fb:.1f}/5）— 估值偏高或盈利质量不佳")
        if avg_hot < 3:
            weak_spots.append(f"🔥 **热点不足**（平均 {avg_hot:.1f}/5）— 当前不在市场主线")
        if avg_ch < 3:
            weak_spots.append(f"🔧 **缠论信号偏空**（平均 {avg_ch:.1f}/5）— 技术结构未企稳")

        if weak_spots:
            reasons.append("评分偏低原因分析：")
            reasons.extend(weak_spots)
            reasons.append("")

        reasons.append("**结论**：当前市场环境下，没有符合筛选标准的推荐标的。建议等待市场情绪改善或基本面催化因素出现后再评估。")

        print("\n".join(reasons))
        print()
        print("> ⚠️ 声明：以上分析仅基于公开市场数据，不构成投资建议。")
        await close_async_session()
        await close_tickflow()
        return

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
