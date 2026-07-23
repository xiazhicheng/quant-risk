#!/usr/bin/env python3
"""股价异动快速归因 — 10 分钟回答"发生了什么？"

借鉴 ai-berkshire news-pulse.md 设计思路，轻量化实现。

用法:
    uv run scripts/news_pulse.py 02460              # 默认14天回溯
    uv run scripts/news_pulse.py 01308 --days 7      # 指定回溯天数
    uv run scripts/news_pulse.py 06693 --threshold 5 # 指定异动阈值(%)

输出:
    1. 一句话归因 + 性质判断
    2. 量价异动数据
    3. 行业板块对比
    4. 公告/新闻检查
    5. 行动建议
"""
import argparse
import asyncio
import sys
import warnings
from datetime import datetime, timedelta
from typing import Any

warnings.filterwarnings("ignore", message=".*Unclosed.*")
warnings.filterwarnings("ignore", message=".*Server disconnected.*")
sys.path.insert(0, ".")

from scripts.quantrisk.data import (
    hk_stock_quote_tencent_async, stock_kline_yahoo_async,
    hk_industry_ranking_async, stock_news,
)


def _sf(v) -> float:
    """安全转浮点"""
    if v is None: return 0.0
    try: return float(v)
    except (ValueError, TypeError): return 0.0


def _fmt_price(v) -> str:
    """格式化价格"""
    if v is None or v == "?" or v == "": return "—"
    return f"{_sf(v):.2f}"


def _fmt_pct(v) -> str:
    """格式化涨跌幅"""
    if v is None or v == "?" or v == "": return "—"
    v = _sf(v)
    return f"{v:+.2f}%"


async def news_pulse(code: str, days: int = 14, threshold: float = 0) -> str:
    """执行异动归因分析。

    Args:
        code: 股票代码（港股当前）
        days: 回溯天数
        threshold: 异动阈值（百分比），0=自动检测

    Returns:
        markdown 格式的归因报告
    """
    today = datetime.now()
    start_date = today - timedelta(days=days)

    # ── 1. 获取基础数据 ──
    quote = await hk_stock_quote_tencent_async(code)
    if not quote or not quote.get("price"):
        return f"## 异动归因：{code}\n\n❌ 无法获取行情数据，请检查股票代码。\n"

    name = quote.get("name", code)
    price = _sf(quote.get("price"))
    chg_pct = _sf(quote.get("change_pct"))
    volume = _sf(quote.get("volume_shares"))
    amount = _sf(quote.get("amount_100m"))
    high_52w = _sf(quote.get("high_52w"))
    low_52w = _sf(quote.get("low_52w"))
    pe = _sf(quote.get("pe"))
    pb = _sf(quote.get("pb"))
    mcap = _sf(quote.get("market_cap_100m"))

    # 校验52周高低（腾讯有时返回异常值）
    if high_52w > price * 100 or low_52w > price * 100:
        high_52w = 0
        low_52w = 0

    # ── 2. 获取K线数据（用于异动检测） ──
    symbol = f"{code}.HK"
    klines = await stock_kline_yahoo_async(symbol, "1d", "3mo")
    valid_kl = [k for k in klines if k.get("close") and k.get("volume")]

    # ── 3. 获取板块排名 ──
    industry_data = []
    try:
        industry_data = await hk_industry_ranking_async(20)
    except Exception:
        # 行业排名API不稳定，跳过不影响核心归因
        pass

    # ── 4. 获取最近新闻 ──
    news_items = await stock_news(name, count=8)
    # 过滤：标题含股票名或代码的新闻才保留
    keywords = [name, code]
    filtered_news = []
    for n in news_items:
        title = n.get("title", "")
        if any(kw.lower() in title.lower() for kw in keywords if len(kw) > 1):
            filtered_news.append(n)
    news_items = filtered_news[:5] if filtered_news else []

    # ── 5. 量价异动分析 ──
    price_data = []
    if valid_kl and len(valid_kl) >= days:
        recent = valid_kl[-days:]
        for i, k in enumerate(recent):
            close = _sf(k.get("close"))
            vol = int(_sf(k.get("volume")))
            chg = ((close / _sf(recent[i-1].get("close"))) - 1) * 100 if i > 0 else 0
            price_data.append({"date": k.get("date", ""), "close": close, "volume": vol, "chg": chg})

    # 检测异动日
    anomaly_days = []
    threshold_val = threshold if threshold > 0 else 3.0
    if price_data:
        pcts = [abs(d["chg"]) for d in price_data if d["chg"] != 0]
        avg_abs_chg = sum(pcts) / len(pcts) if pcts else 0
        threshold_val = threshold if threshold > 0 else max(avg_abs_chg * 2, 3.0)

        for d in price_data:
            if abs(d["chg"]) >= threshold_val:
                anomaly_days.append(d)

    # 近N日累计涨跌
    if len(price_data) >= 2:
        first_close = price_data[0]["close"]
        last_close = price_data[-1]["close"]
        period_chg = (last_close - first_close) / first_close * 100 if first_close else 0
        period_high = max(d["close"] for d in price_data)
        period_low = min(d["close"] for d in price_data)
    else:
        period_chg = chg_pct
        period_high = price
        period_low = price

    # 成交量变化
    if len(price_data) >= 10:
        half = len(price_data) // 2
        recent_avg_vol = sum(d["volume"] for d in price_data[half:]) / max(len(price_data) - half, 1)
        prev_avg_vol = sum(d["volume"] for d in price_data[:half]) / max(half, 1)
        vol_ratio = recent_avg_vol / prev_avg_vol if prev_avg_vol > 0 else 1.0
    else:
        vol_ratio = 1.0

    # ── 6. 性质判断 ──
    # 判断逻辑：异动幅度 + 成交量 + 板块对比 + 新闻
    is_anomaly = abs(period_chg) >= threshold_val or len(anomaly_days) >= 2

    # 板块对比（从hk_industry_ranking找该股票所在板块）
    sector_name = ""
    sector_chg = 0.0
    for sec in industry_data:
        sector_name = sec.get("sector", "")
        sector_chg = _sf(sec.get("change_pct"))
        # 粗略匹配：遍历该板块股票...（hk_industry_ranking没有个股列表，只能取板块整体）

    # 判断性质
    if not is_anomaly:
        nature = "📊 正常波动"
        nature_detail = "近{}日累计涨跌{:.2f}%，未触发异动阈值{:.1f}%，属于正常价格波动。".format(
            days, period_chg, threshold_val)
    elif abs(period_chg) > 8 and vol_ratio > 1.5 and news_items:
        nature = "🔴 价值事件"
        nature_detail = "大幅波动({:+.2f}%)+放量({:.1f}x)+有相关新闻，基本面可能发生变化，建议重审投资论文。".format(
            period_chg, vol_ratio)
    elif vol_ratio > 1.5 and not news_items:
        nature = "🟡 真因不明"
        nature_detail = "放量({:.1f}x)但无相关新闻，市场可能在提前反应未公开信息，警惕内幕抢跑。".format(vol_ratio)
    elif abs(period_chg) > 3 and vol_ratio < 1.2:
        nature = "🔵 情绪/技术波动"
        nature_detail = "波动({:+.2f}%)但量能无异常({:.1f}x)，可能是情绪/资金面驱动，基本面无变化。".format(
            period_chg, vol_ratio)
    else:
        nature = "🟠 混合型"
        nature_detail = "部分基本面因素+部分情绪放大，需进一步确认。".format(period_chg, vol_ratio)

    # ── 7. 构建报告 ──
    lines = [f"## 异动归因：{name}（{code}）"]

    # 一句话摘要
    one_liner = f"近{days}日{'涨' if period_chg >= 0 else '跌'}{abs(period_chg):.2f}%"
    if vol_ratio > 1.5:
        one_liner += f"，放量{vol_ratio:.1f}x"
    if anomaly_days:
        one_liner += f"，最大单日波动{max(abs(d['chg']) for d in anomaly_days):.2f}%"
    if not is_anomaly:
        one_liner += "，正常波动"
    lines.append(f"\n**一句话归因**：{one_liner}")
    lines.append(f"\n**性质**：{nature}")
    lines.append(f">{nature_detail}")

    # 基础数据
    lines.append(f"\n### 📊 基础数据")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|:----|:---|")
    lines.append(f"| 当前股价 | {_fmt_price(price)} |")
    lines.append(f"| 今日涨跌 | {_fmt_pct(chg_pct)} |")
    lines.append(f"| 近{days}日涨跌 | {_fmt_pct(period_chg)} |")
    lines.append(f"| 区间最高/最低 | {_fmt_price(period_high)} / {_fmt_price(period_low)} |")
    lines.append(f"| 成交量比(后/前半) | {vol_ratio:.2f}x |")
    lines.append(f"| 52周高/低 | {_fmt_price(high_52w)} / {_fmt_price(low_52w)} |")
    if pe: lines.append(f"| PE | {_fmt_price(pe)} |")
    if pb: lines.append(f"| PB | {_fmt_price(pb)} |")
    if mcap: lines.append(f"| 市值 | {mcap:.1f}亿 |")

    # 异动日检测
    if anomaly_days:
        lines.append(f"\n### ⚡ 异动日检测（阈值 ≥{threshold_val:.1f}%）")
        lines.append(f"| 日期 | 收盘价 | 涨跌幅 | 成交量 |")
        lines.append(f"|:----|:-----:|:-----:|:-----:|")
        for d in anomaly_days[:5]:
            lines.append(f"| {d['date']} | {_fmt_price(d['close'])} | {_fmt_pct(d['chg'])} | {d['volume']:,} |")

    # 行业板块对比
    valid_industry = [s for s in industry_data if s.get("sector") and s.get("change_pct")]
    if valid_industry:
        lines.append(f"\n### 🏭 行业板块表现")
        lines.append(f"| 板块 | 涨跌幅 |")
        lines.append(f"|:----|:-----:|")
        for sec in valid_industry[:10]:
            sec_name = sec.get("sector", "")
            sec_chg = _sf(sec.get("change_pct"))
            is_current = name in sec_name or any(
                keyword in sec_name for keyword in name[:2])
            marker = " ◀" if is_current else ""
            lines.append(f"| {sec_name}{marker} | {_fmt_pct(sec_chg)} |")

    # 最近新闻
    if news_items:
        lines.append(f"\n### 📰 最近新闻")
        for n in news_items[:5]:
            title = n.get("title", "")
            publisher = n.get("publisher", "")
            link = n.get("link", "")
            lines.append(f"- [{title}]({link}) _({publisher})_" if link else f"- {title}")
    else:
        lines.append(f"\n### 📰 最近新闻")
        lines.append(f"- 未找到相关新闻（当前新闻源覆盖有限，不代表真无事件）")

    # 行动建议
    lines.append(f"\n### 🎯 行动建议")
    if "价值事件" in nature:
        lines.append(f"- 🔴 建议触发深度分析：`uv run scripts/analyze.py {code}`")
        lines.append(f"- 📋 建议重审投资论文")
    elif "真因不明" in nature:
        lines.append(f"- ⚠️ 量价异常但无新闻，警惕内幕抢跑")
        lines.append(f"- 📋 建议观察1-3个交易日后再做判断")
    elif "情绪波动" in nature:
        lines.append(f"- 🔵 基本面无变化，可视为正常波动")
        lines.append(f"- 📋 无需特别操作")
    else:
        lines.append(f"- 📊 正常波动，无需操作")

    lines.append(f"\n---")
    lines.append(f"> 📡 数据来源：腾讯行情 | Yahoo新闻")
    lines.append(f"> ⚠️ 本报告为快速归因（非深度研究），数据截止 {today.strftime('%Y-%m-%d %H:%M')}")

    # 清理会话
    from scripts.quantrisk.data import close_async_session
    await close_async_session()

    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description="股价异动快速归因")
    parser.add_argument("code", help="股票代码（如 02460）")
    parser.add_argument("--days", type=int, default=14, help="回溯天数（默认14）")
    parser.add_argument("--threshold", type=float, default=0, help="异动阈值%（默认自动）")
    args = parser.parse_args()

    report = await news_pulse(args.code, args.days, args.threshold)
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
