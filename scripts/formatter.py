#!/usr/bin/env python3
"""
输出格式化器 — 将裸 JSON 数据渲染为 SKILL.md 规定的选股报告模板。

设计原则:
  - 模型只负责产出裸数据（dict/JSON）
  - 格式校验由 Pydantic 强制执行
  - 格式渲染由 format_output() 完成，改格式只改本文件

校验失败行为:
  如果 Pydantic 校验不通过，抛出 FormatValidationError，
  调用方应将该 error 信息回传给 LLM，让其修正 JSON 后重试。

用法:
    from scripts.formatter import format_output, FormatValidationError

    try:
        report = format_output(raw_data)          # raw_data 是 dict 或 JSON 字符串
    except FormatValidationError as e:
        # 把 e.message 传给 LLM 让它重新输出
        llm_retry(e.message)
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── 错误类型 ────────────────────────────────────────────────

class FormatValidationError(Exception):
    """裸数据格式校验失败，调用方应将 message 回传给 LLM 重试。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message  # 直接传给 LLM 的完整说明


# ── Pydantic 模型 ───────────────────────────────────────────

class SectorItem(BaseModel):
    sector: str = Field(..., description="板块名称")
    count: int = Field(..., description="扫描只数")
    pct: float = Field(..., description="今日涨跌幅百分比")
    up: int = Field(..., description="上涨只数")
    dn: int = Field(..., description="下跌只数")


class EliminatedItem(BaseModel):
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    reason: str = Field(..., description="剔除原因")


class VetoedItem(BaseModel):
    """基本面一票否决的标的"""
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    reason: str = Field(..., description="否决原因")


class Top10Item(BaseModel):
    rank: int = Field(..., ge=1, le=10, description="排名")
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    sector: str = Field(..., description="板块")
    fb: float = Field(..., ge=1, le=5, description="基本面评分 1-5")
    hot: float = Field(..., ge=1, le=5, description="热点评分 1-5")
    ch: float = Field(..., ge=1, le=5, description="缠论评分 1-5")
    fb_w: float = Field(..., ge=0, le=60, description="基本面加权得分 0-60")
    hot_w: float = Field(..., ge=0, le=20, description="热点加权得分(技术面子分)")
    ch_w: float = Field(..., ge=0, le=20, description="缠论加权得分(技术面子分)")
    total: float = Field(..., ge=0, le=100, description="总分 0-100")
    strategy: str = Field(default="", description="策略匹配: 回调一买/突破三买/双策略共振")
    advice: str = Field(..., description="建议")


class FbDetail(BaseModel):
    score: float = Field(..., ge=1, le=5)
    score_w: float = Field(..., ge=0, le=60, description="基本面加权得分 0-60")
    debug: str = Field(default="", description="基本面计算明细")
    pe: Any = Field(default="?", description="PE")
    revenue_yoy: Any = Field(default="?", description="营收增速")
    net_profit_yoy: Any = Field(default="?", description="净利增速")
    roe: Any = Field(default="?", description="ROE")
    gross_margin: Any = Field(default="?", description="毛利率")
    debt_ratio: Any = Field(default="?", description="负债率")


class HotDetail(BaseModel):
    score: float = Field(..., ge=1, le=5)
    score_w: float = Field(..., ge=0, le=20, description="热点加权得分(技术面子分)")
    desc: str = Field(..., description="热点描述")


class ChanDetail(BaseModel):
    score: float = Field(..., ge=1, le=5)
    score_w: float = Field(..., ge=0, le=20, description="缠论加权得分(技术面子分)")
    ma60: Any = Field(default="?", description="MA60")
    price: Any = Field(default="?", description="现价")
    macd_hist: Any = Field(default="?", description="MACD柱")
    signal: str = Field(default="", description="信号")
    ma_alignment: str = Field(default="", description="MA排列")
    ma_trend: str = Field(default="", description="MA趋势")
    mc: str = Field(default="", description="MACD交叉")
    ma_pos_summary: str = Field(default="", description="价格在MA上的位置")
    ma_cross_short: str = Field(default="", description="短期MA交叉")
    ma_cross_medium: str = Field(default="", description="中期MA交叉")
    # ── 多周期缠论深度分析（2026-07-21 新增） ──
    week_ma60: Any = Field(default="?", description="周K MA60")
    week_chan_verdict: str = Field(default="", description="周线缠论判定: 偏多/中性/偏空")
    day_ma5: Any = Field(default="?", description="日K MA5")
    day_bottom_fx: Any = Field(default="?", description="最近底分型价格")
    day_top_fx: Any = Field(default="?", description="最近顶分型价格")
    day_bottom_fx_date: str = Field("", description="最近底分型日期")
    day_last_bi_dir: str = Field(default="", description="最近笔方向: up/down")
    day_above_ma5: bool = Field(False, description="日K底分型后是否站上MA5")
    buy_sell_detail: str = Field("", description="买卖点详情(一买/二买/三买/卖点)")
    divergence_detail: str = Field("", description="背驰详情(顶背驰/底背驰/无)")
    chan_verdict: str = Field("", description="缠论综合结论: 偏多/中性/偏空")


class DetailItem(BaseModel):
    rank: int = Field(..., ge=1)
    code: str
    name: str
    price: Any = Field(default="?")
    pct: Any = Field(default="?", description="涨跌幅")
    advice: str
    stop_loss: Any
    take_profit: Any = Field(default="?", description="目标价")
    total: Any = Field(default="?", description="总分")
    vol_5d_ratio: Optional[float] = Field(default=None, description="近5日成交额比（后5日/前5日）")
    pct_5d: Optional[float] = Field(default=None, description="近5日涨跌幅（%）")
    fb: FbDetail
    hot: HotDetail
    ch: ChanDetail
    # 策略信号（2026-07-21 新增）
    strategy: str = Field(default="", description="策略匹配")
    strategy_detail: str = Field(default="", description="策略匹配详情")
    strategy_stop_loss: float = Field(default=0.0, description="策略止损价")
    strategy_exit: str = Field(default="", description="策略离场条件")


class SummaryItem(BaseModel):
    code: str
    advice: str
    buy: Any
    stop_loss: Any
    take_profit: Any


class PortfolioTimingItem(BaseModel):
    """持仓标的择时判断"""
    code: str
    name: str
    entry_price: float = Field(..., description="买入成本价")
    current_price: float = Field(..., description="当前价")
    shares: int = Field(0, description="持仓数量")
    profit_pct: float = Field(0.0, description="盈亏百分比")
    # 基本面
    fb_debug: str = Field("", description="基本面计算明细")
    pe: Any = Field(default="?", description="PE")
    revenue_yoy: Any = Field(default="?", description="营收增速")
    net_profit_yoy: Any = Field(default="?", description="净利增速")
    roe: Any = Field(default="?", description="ROE")
    gross_margin: Any = Field(default="?", description="毛利率")
    debt_ratio: Any = Field(default="?", description="负债率")
    pb: Any = Field(default="?", description="PB")
    dividend_yield: Any = Field(default="?", description="股息率")
    # 缠论
    ma5: Any = Field(default="?", description="MA5")
    ma20: Any = Field(default="?", description="MA20")
    ma60: Any = Field(default="?", description="MA60")
    ma_alignment: str = Field("", description="MA排列")
    ma_trend: str = Field("", description="MA趋势")
    ma_pos_summary: str = Field("", description="价格在MA上的位置")
    ma_cross_short: str = Field("", description="短期MA交叉")
    ma_cross_medium: str = Field("", description="中期MA交叉")
    mc: str = Field("", description="MACD交叉")
    macd_hist: Any = Field(default="?", description="MACD柱值")
    signal: str = Field("", description="缠论信号")
    chan_verdict: str = Field("", description="缠论结论")
    # 深度缠论（2026-07-21 新增）
    week_ma60: Any = Field(default="?", description="周K MA60")
    week_chan_verdict: str = Field("", description="周线缠论判定")
    day_bottom_fx: Any = Field(default="?", description="最近底分型价格")
    day_bottom_fx_date: str = Field("", description="底分型日期")
    day_top_fx: Any = Field(default="?", description="最近顶分型价格")
    day_last_bi_dir: str = Field("", description="最近笔方向: up/down")
    buy_sell_detail: str = Field("", description="买卖点详情")
    divergence_detail: str = Field("", description="背驰详情")
    # 定价
    stop_loss: float = Field(0.0, description="止损价")
    take_profit: float = Field(0.0, description="目标价")
    advice: str = Field("持有", description="建议：持有/减仓/卖出/加仓")


class SelectionReport(BaseModel):
    """选股推荐报告完整数据模型。"""
    date: str = Field(..., description="报告日期，格式 YYYY-MM-DD")
    sectors: list[SectorItem] = Field(..., min_length=1, description="板块扫描数据")
    eliminated: list[EliminatedItem] = Field(default_factory=list, description="被剔除标的")
    vetoed: list[VetoedItem] = Field(default_factory=list, description="基本面一票否决的标的")
    passed_count: int = Field(..., ge=0, description="通过过滤的标的数量")
    top10: list[Top10Item] = Field(..., min_length=1, max_length=10, description="TOP10 排名")
    details: list[DetailItem] = Field(..., min_length=1, max_length=10, description="各股详细分析")
    summary: list[SummaryItem] = Field(..., min_length=1, max_length=10, description="综合建议")

    @field_validator("top10")
    @classmethod
    def _top10_rank_order(cls, v: list[Top10Item]) -> list[Top10Item]:
        ranks = [i.rank for i in v]
        if ranks != sorted(ranks):
            raise ValueError(f"top10.rank 必须按 1,2,3... 升序排列，实际: {ranks}")
        return v

    @field_validator("details")
    @classmethod
    def _details_rank_order(cls, v: list[DetailItem]) -> list[DetailItem]:
        ranks = [i.rank for i in v]
        if ranks != sorted(ranks):
            raise ValueError(f"details.rank 必须升序排列，实际: {ranks}")
        return v


# ── 校验 ────────────────────────────────────────────────────

def validate(data: dict[str, Any]) -> SelectionReport:
    """
    校验裸数据，返回 Pydantic 模型实例。
    校验失败抛出 FormatValidationError，message 可直接传给 LLM。
    """
    try:
        return SelectionReport.model_validate(data)
    except Exception as exc:
        # 把 pydantic 错误转为清晰的中文诊断
        lines = [f"JSON 格式校验失败："]
        for e in exc.errors():
            loc = " → ".join(str(x) for x in e["loc"])
            msg = e.get("msg", "")
            inp = e.get("input")
            lines.append(f"  - 字段 '{loc}': {msg}")
            if inp is not None:
                lines.append(f"    实际值: {inp}")
        raise FormatValidationError("\n".join(lines))


# ── 模板 ────────────────────────────────────────────

MARKET_CONFIG = {
    "hk": {
        "title": "港股选股推荐",
        "scan_label": "全市场扫描（8 板块）",
        "scan_header": "| 板块 | 扫描只数 | 今日表现 |\n|------|:-------:|---------|",
        "elim_label": "中观过滤（剔除明细）",
        "elim_header": "| 剔除标的 | 原因 |\n|---------|------|",
        "passed_label": "通过过滤",
        "score_label": "三维评分 TOP10",
"score_header": "| 排名 | 标的 | 板块 | 基本面(60分) | 技术面(40分) | 总分(100分) | 策略 | 建议 |\n|:----:|------|:----:|:----------:|:----------:|:-----:|:---:|------|",
	        "detail_label": "各股详细分析",
	        "summary_label": "综合建议",
	        "summary_header": "| 标的 | 建议 | 入场区间 | 止损 | 目标 |\n|:----|:----:|:--------:|:----:|:----:|",
	        "price_unit": "港元",
	    },
	    "cn": {
	        "title": "A股选股推荐",
	        "scan_label": "全市场扫描（行业板块）",
	        "scan_header": "| 板块 | 扫描只数 | 今日表现 |\n|------|:-------:|---------|",
	        "elim_label": "中观过滤（剔除明细）",
	        "elim_header": "| 剔除标的 | 原因 |\n|---------|------|",
	        "passed_label": "通过过滤",
	        "score_label": "二维评分 TOP10",
	        "score_header": "| 排名 | 标的 | 板块 | 基本面(60分) | 技术面(40分) | 总分(100分) | 策略 | 建议 |\n|:----:|------|:----:|:----------:|:----------:|:-----:|:---:|------|",
        "detail_label": "各股详细分析",
        "summary_label": "综合建议",
        "summary_header": "| 标的 | 建议 | 入场区间 | 止损 | 目标 |\n|:----|:----:|:--------:|:----:|:----:|",
        "price_unit": "元",
    },
    "us": {
        "title": "US Stock Selection",
        "scan_label": "Full Market Scan (Sectors)",
        "scan_header": "| Sector | Count | Today |\n|--------|:-----:|-------|",
        "elim_label": "Filter Detail",
        "elim_header": "| Eliminated | Reason |\n|------------|--------|",
        "passed_label": "passed filter",
        "score_label": "3D Scoring TOP10",
        "score_header": "| Rank | Stock | Sector | Fundamental(60pt) | Technical(40pt) | Total(100pt) | Strategy | Advice |\n|:----:|------|:----:|:---------------:|:--------------:|:-----:|:------:|------|",
        "detail_label": "Detailed Analysis",
        "summary_label": "Summary",
        "summary_header": "| Stock | Advice | Entry | Stop Loss | Target |\n|:-----|:------:|:------:|:---------:|:------:|",
        "price_unit": "USD",
    },
}


def _get_config(market: str = "hk") -> dict:
    return MARKET_CONFIG.get(market, MARKET_CONFIG["hk"])


SECTOR_ORDER = [
    "互联网/IT", "金融/保险/券商", "能源/资源/矿业", "通信/运营商",
    "消费/食品/零售", "医药/生物科技", "制造/工业/半导体", "公用事业/基建/交运",
]

FB_VERDICT = {
    5: "基本面优秀。", 4: "基本面良好。", 3: "基本面稳健。",
    2: "基本面需关注。", 1: "基本面较差。",
}
FB_VERDICT_RANGE = [
    (4.5, 5.01, "基本面优秀。"),
    (4.0, 4.5, "基本面良好。"),
    (3.0, 4.0, "基本面稳健。"),
    (2.0, 3.0, "基本面需关注。"),
    (1.0, 2.0, "基本面较差。"),
]

CHAN_VERDICT = {
    5: "结构最佳", 4: "结构向好", 3: "结构中性",
    2: "结构需谨慎", 1: "结构偏空",
}
CHAN_VERDICT_RANGE = [
    (4.5, 5.01, "结构最佳"),
    (4.0, 4.5, "结构向好"),
    (3.0, 4.0, "结构中性"),
    (2.0, 3.0, "结构需谨慎"),
    (1.0, 2.0, "结构偏空"),
]

TEMPLATE = """\
## {title} | {date}

---

## 推荐结论

### TOP10 推荐标的

{score_header}
{top10_rows}

### 推荐逻辑

{detail_rows}

---

## 定价与择时

### 定价建议

{summary_header}
{summary_rows}

### 择时判断

{timing_rows}

{portfolio_timing_rows}

---

## 筛选过程

### ① 全市场扫描

{scan_header}
{sector_rows}

### ② 中观过滤

{elim_header}
{elim_rows}

候选池 {passed_count} 只通过过滤。

{vetoed_section}

> ⚠️ 声明：以上分析仅基于公开市场数据，不构成投资建议。
"""


# ── 渲染辅助 ────────────────────────────────────────────────

def _render_sector_rows(sectors: list[SectorItem]) -> str:
    # 按固定顺序排列
    order_idx = {name: i for i, name in enumerate(SECTOR_ORDER)}
    ordered = sorted(
        sectors,
        key=lambda s: order_idx.get(s.sector, 999),
    )
    return "\n".join(
        f"| {s.sector} | {s.count} | {'+' if s.pct >= 0 else ''}{s.pct:.2f}%（涨{s.up}跌{s.dn}） |"
        for s in ordered
    )


def _render_elim_rows(eliminated: list[EliminatedItem]) -> str:
    if not eliminated:
        return "| - | 无剔除 |"
    return "\n".join(f"| {e.code} {e.name} | {e.reason} |" for e in eliminated)


def _render_vetoed_section(vetoed: list[VetoedItem]) -> str:
    """渲染基本面一票否决段落"""
    if not vetoed:
        return ""
    return (
        "\n### ②.5 基本面一票否决（基本面不合格，直接淘汰）\n"
        "\n"
        "| 否决标的 | 原因 |\n"
        "|---------|------|\n"
        + "\n".join(f"| {v.code} {v.name} | {v.reason} |" for v in vetoed)
        + "\n"
    )


def _render_top10_rows(top10: list[Top10Item]) -> str:
    return "\n".join(
        f"| ⭐{t.rank} | **{t.code} {t.name}** | {t.sector} | {t.fb_w:.1f} | {t.hot_w + t.ch_w:.1f} | "
        f"**{t.total:.1f}** | {t.strategy or '—'} | {t.advice} |"
        for t in top10
    )


def _calc_pct_change(price, stop_loss):
    """计算止损相对当前价的百分比变化"""
    if isinstance(price, (int, float)) and isinstance(stop_loss, (int, float)) and price:
        return (stop_loss - price) / price * 100
    return 0.0


def _render_strategy_tag(d: DetailItem) -> str:
    """渲染策略标签段落（有信号时简洁展示，无信号时跳过）"""
    if not d.strategy or d.strategy == "暂无策略信号":
        return ""
    lines = ["\n\n**策略匹配**: " + d.strategy + " ✅"]
    if d.strategy_detail:
        parts = d.strategy_detail.split("|")
        for p in parts[:3]:
            p = p.strip()
            if p:
                lines.append(f"  - {p}")
    if d.strategy_stop_loss:
        lines.append(f"  - 止损: {d.strategy_stop_loss} | 离场: {d.strategy_exit}")
    return "\n".join(lines)


def _render_detail_block(d: DetailItem, price_unit: str = "港元") -> str:
    pct = d.pct
    sign = "+" if isinstance(pct, (int, float)) and pct >= 0 else ""
    pct_str = f"{sign}{pct}" if isinstance(pct, (int, float)) else str(pct)

    fb = d.fb
    hot = d.hot
    ch = d.ch

    # 浮点区间判定
    fb_desc = next(
        (desc for lo, hi, desc in FB_VERDICT_RANGE if lo <= fb.score < hi),
        "基本面稳健。"
    )
    ch_desc = next(
        (desc for lo, hi, desc in CHAN_VERDICT_RANGE if lo <= ch.score < hi),
        "结构中性"
    )
    sl_pct = _calc_pct_change(d.price, d.stop_loss)

    # 构建基本面摘要（从 debug 提取关键指标，去掉计算链）
    fb_parts = []
    if fb.revenue_yoy and fb.revenue_yoy != "?":
        fb_parts.append(f"营收{fb.revenue_yoy}%")
    if fb.net_profit_yoy and fb.net_profit_yoy != "?":
        fb_parts.append(f"净利{fb.net_profit_yoy}%")
    if fb.roe and fb.roe != "?":
        fb_parts.append(f"ROE{fb.roe}%")
    if fb.gross_margin and fb.gross_margin != "?":
        fb_parts.append(f"毛利率{fb.gross_margin}%")
    if fb.debt_ratio and fb.debt_ratio != "?":
        fb_parts.append(f"负债率{fb.debt_ratio}%")
    if fb.pe and fb.pe != "?":
        fb_parts.append(f"PE{fb.pe}")
    fb_summary = "，".join(fb_parts) if fb_parts else "数据不足"

    # 构建缠论摘要
    ch_parts = []
    if ch.ma_alignment:
        ch_parts.append(f"{ch.ma_alignment}")
    if ch.ma60 and ch.ma60 != "?" and ch.price and ch.price != "?":
        try:
            pv60 = (float(ch.price) - float(ch.ma60)) / float(ch.ma60) * 100
            ch_parts.append(f"MA60={ch.ma60}，偏离{pv60:+.1f}%")
        except (ValueError, TypeError):
            ch_parts.append(f"MA60={ch.ma60}")
    if ch.macd_hist and ch.macd_hist != "?":
        ch_parts.append(f"MACD柱={ch.macd_hist}")
    if ch.signal:
        ch_parts.append(f"信号:{ch.signal}")
    ch_summary = "，".join(ch_parts) if ch_parts else "数据不足"

    # 深度缠论段落（周线大势 + 日K买卖点 + 笔结构）
    ch_deep = _render_chan_deep_section(ch)
    ch_deep_block = f"\n{ch_deep}" if ch_deep else ""

    # 择时结论
    if ch.score >= 4.5:
        timing_verdict = "当前可布局"
    elif ch.score >= 4.0:
        timing_verdict = "等待回调介入"
    elif ch.score >= 3.0:
        timing_verdict = "观望，等待企稳"
    else:
        timing_verdict = "暂不建议入场"

    return f"""\
#### {d.rank}. {d.name}（{d.code}）— {d.advice} ✅ | 总分 {d.total}/100

**结论**：{fb_desc}（{fb.score_w}/60） + 技术面 {round(hot.score_w + ch.score_w, 1)}/40 → **{timing_verdict}**

**论据**：
- 📊 **基本面 {fb.score_w}/60**：{fb_summary}
- 🔥 **热点(子分)** {hot.score}/5 ({hot.score_w}分)：{hot.desc}
- 🔧 **缠论(子分)** {ch.score}/5 ({ch.score_w}分)：{ch_summary}{ch_deep_block}

**定价**：入场 {d.price} → 止损 {d.stop_loss}（{sl_pct:.1f}%）→ 目标 {d.take_profit}{_render_strategy_tag(d)}
	"""


def _render_detail_rows(details: list[DetailItem], price_unit: str = "港元") -> str:
    return "\n".join(_render_detail_block(d, price_unit=price_unit) for d in details)


def _fmt_num_safe(v) -> str:
    """安全数值格式化"""
    if v is None or v == "?" or v == "":
        return "?"
    try:
        if isinstance(v, (int, float)):
            return str(round(v, 2))
        return str(v)
    except (ValueError, TypeError):
        return "?"


def _render_chan_deep_section(ch: "ChanDetail") -> str:
    """渲染深度缠论分析段落：周线大势 + 日K买卖点 + 笔结构。"""
    lines = []

    # ── 大势（周线） ──
    wk_parts = []
    if ch.week_ma60 and ch.week_ma60 != "?":
        wk_parts.append(f"MA60={_fmt_num_safe(ch.week_ma60)}")
    if ch.week_chan_verdict:
        wk_parts.append(f"{ch.week_chan_verdict}")
    if wk_parts:
        lines.append(f"  - **大势（周线）**：周K {', '.join(wk_parts)}")

    # ── 买卖点（日K） ──
    dk_parts = []
    if ch.day_bottom_fx and ch.day_bottom_fx != "?":
        date_str = f"（{ch.day_bottom_fx_date}）" if ch.day_bottom_fx_date else ""
        dk_parts.append(f"底分型={_fmt_num_safe(ch.day_bottom_fx)}{date_str}")
    if ch.day_ma5 and ch.day_ma5 != "?":
        if ch.day_above_ma5:
            dk_parts.append(f"✅ 站上 MA5={_fmt_num_safe(ch.day_ma5)}")
        else:
            dk_parts.append(f"❌ 未站上 MA5={_fmt_num_safe(ch.day_ma5)}")
    # 买卖点 / 背驰 — 非"无"才展示
    if ch.buy_sell_detail and ch.buy_sell_detail != "无":
        dk_parts.append(f"{ch.buy_sell_detail}")
    if ch.divergence_detail and ch.divergence_detail != "无":
        dk_parts.append(f"{ch.divergence_detail}")
    if dk_parts:
        lines.append(f"  - **买卖点（日K）**：{' / '.join(dk_parts)}")

    # ── 笔结构 ──
    bi_parts = []
    if ch.day_last_bi_dir:
        arrow = "↑" if ch.day_last_bi_dir == "up" else "↓" if ch.day_last_bi_dir == "down" else "?"
        bi_parts.append(f"最近笔 {arrow}")
    if ch.chan_verdict:
        bi_parts.append(f"{ch.chan_verdict}")
    if ch.day_top_fx and ch.day_top_fx != "?":
        bi_parts.append(f"顶分型={_fmt_num_safe(ch.day_top_fx)}")
    if bi_parts:
        lines.append(f"  - **笔结构**：{' / '.join(bi_parts)}")

    return "\n".join(lines) if lines else ""


def _render_timing_block(d: DetailItem, price_unit: str = "港元") -> str:
    ch = d.ch

    # 综合判断（结论先行）
    if ch.score >= 4.5:
        timing = "当前可布局"
    elif ch.score >= 4.0:
        timing = "等待回调至 MA60 附近介入"
    elif ch.score >= 3.0:
        timing = "观望，等待技术结构企稳"
    else:
        timing = "暂不建议入场"

    lines = [f"**{d.name}（{d.code}）** → 建议：**{timing}** ✅"]

    # 技术指标（论据在后）
    parts = []
    if ch.ma_alignment:
        ma_desc = f"{ch.ma_alignment}（{ch.ma_pos_summary}，{ch.ma_trend}）"
        if ch.ma60 and ch.ma60 != "?" and ch.price and ch.price != "?":
            try:
                pv60 = (float(ch.price) - float(ch.ma60)) / float(ch.ma60) * 100
                ma_desc += f"，MA60={ch.ma60}，偏离{pv60:+.1f}%"
            except (ValueError, TypeError):
                ma_desc += f"，MA60={ch.ma60}"
        parts.append(ma_desc)
    if ch.mc:
        parts.append(f"MACD：{ch.mc}，柱值 {ch.macd_hist}")
    if ch.ma_cross_short:
        parts.append(f"短期均线：{ch.ma_cross_short}")
    if ch.ma_cross_medium:
        parts.append(f"中期均线：{ch.ma_cross_medium}")

    # 缠论深度：大势(周线) + 笔 + 买卖点/背驰
    chan_deep_parts = []
    if ch.week_ma60 and ch.week_ma60 != "?":
        chan_deep_parts.append(f"大势：周K MA60={_fmt_num_safe(ch.week_ma60)}{f'，{ch.week_chan_verdict}' if ch.week_chan_verdict else ''}")
    if ch.day_last_bi_dir:
        arrow = "↑" if ch.day_last_bi_dir == "up" else "↓"
        chan_deep_parts.append(f"笔：{arrow}")
    if ch.day_bottom_fx and ch.day_bottom_fx != "?":
        date_str = f"({ch.day_bottom_fx_date})" if ch.day_bottom_fx_date else ""
        ma5_info = f" MA5={_fmt_num_safe(ch.day_ma5)}{'✅' if ch.day_above_ma5 else '❌'}" if ch.day_ma5 and ch.day_ma5 != "?" else ""
        chan_deep_parts.append(f"底分型={_fmt_num_safe(ch.day_bottom_fx)}{date_str}{ma5_info}")
    if ch.buy_sell_detail and ch.buy_sell_detail != "无":
        chan_deep_parts.append(f"买卖点：{ch.buy_sell_detail}")
    if ch.divergence_detail and ch.divergence_detail != "无":
        chan_deep_parts.append(f"背驰：{ch.divergence_detail}")
    if chan_deep_parts:
        parts.append("缠论：" + " | ".join(chan_deep_parts))

    # 近5日成交额变化+收盘价变化（替代资金流向）
    vr = d.vol_5d_ratio
    p5 = d.pct_5d
    if vr is not None:
        if vr > 2.0:
            vd = f"放巨量({vr:.1f}x)"
        elif vr > 1.5:
            vd = f"放量({vr:.1f}x)"
        elif vr < 0.5:
            vd = f"缩量({vr:.1f}x)"
        else:
            vd = f"量平({vr:.1f}x)"
        vol_part = f"5日成交额{vd}"
    else:
        vol_part = "5日成交额:无数据"

    if p5 is not None:
        pct_part = f"5日涨幅{p5:+.2f}%"
    else:
        pct_part = "5日涨幅:无数据"

    # 量价共振判断
    if vr is not None and p5 is not None:
        if p5 > 3 and vr > 1.2:
            resonance = "量价齐升✅"
        elif p5 < -3 and vr > 1.2:
            resonance = "放量下跌⚠️"
        else:
            resonance = ""
        if resonance:
            parts.append(f"{vol_part} | {pct_part} | {resonance}")
        else:
            parts.append(f"{vol_part} | {pct_part}")
    else:
        parts.append(f"{vol_part} | {pct_part}")

    if parts:
        lines.append("论据：" + " | ".join(parts))

    # 策略标签（仅在有信号时显示）
    if d.strategy and d.strategy != "暂无策略信号":
        sd = d.strategy_detail
        if sd:
            dir_line = sd.split("|")[0].strip() if "|" in sd else sd[:60]
            lines.append(f"策略：{d.strategy} | {dir_line}")
        else:
            lines.append(f"策略：{d.strategy}")

    return "\n".join(lines)


def _render_timing_rows(details: list[DetailItem], price_unit: str = "港元") -> str:
    return "\n\n".join(_render_timing_block(d, price_unit=price_unit) for d in details)


def _render_summary_rows(summary: list[SummaryItem]) -> str:
    return "\n".join(
        f"| {s.code} | {s.advice} | {s.buy} | {s.stop_loss} | {s.take_profit} |"
        for s in summary
    )


def _render_portfolio_timing(portfolio: list[PortfolioTimingItem], price_unit: str = "港元") -> str:
    """渲染持仓卖出择时分析（结论先行：建议→论据）"""
    if not portfolio:
        return ""
    blocks = []
    for h in portfolio:
        # ── 综合建议（结论先行） ──
        adv = h.advice
        extra = ""
        if adv == "卖出":
            extra = f"跌破MA60({h.ma60})确认，或基本面恶化无改善"
        elif adv == "减仓":
            extra = f"接近目标价{h.take_profit}，可分批止盈降低风险"
        elif adv == "持有":
            extra = f"跌破MA60({h.ma60})止损，或基本面恶化时重新评估"
        elif adv == "加仓":
            extra = f"回调至MA60({h.ma60})附近加仓，基本面确认改善后执行"

        lines = [f"#### {h.name}（{h.code}）"]
        lines.append(f"**建议**：**{adv}** — {extra}")
        lines.append(f"成本 {h.entry_price} {price_unit} → 现价 {h.current_price} {price_unit}（{h.profit_pct:+.1f}%），共 {h.shares} 股")

        # ── 盈亏状态 ──
        loss_pct = h.profit_pct
        if loss_pct < -20:
            loss_note = "深度亏损"
        elif loss_pct < -10:
            loss_note = "中度亏损"
        elif loss_pct < 0:
            loss_note = "轻度亏损"
        elif loss_pct < 10:
            loss_note = "微利"
        else:
            loss_note = "盈利良好"
        lines.append(f"💰 盈亏：{loss_pct:+.1f}%（{loss_note}）")

        # ── 基本面论据 ──
        fb_parts = []
        if h.pe and h.pe != "?":
            fb_parts.append(f"PE={h.pe}")
        if h.revenue_yoy and h.revenue_yoy != "?":
            fb_parts.append(f"营收={h.revenue_yoy}%")
        if h.net_profit_yoy and h.net_profit_yoy != "?":
            fb_parts.append(f"净利={h.net_profit_yoy}%")
        if h.roe and h.roe != "?":
            fb_parts.append(f"ROE={h.roe}%")
        if h.gross_margin and h.gross_margin != "?":
            fb_parts.append(f"毛利率={h.gross_margin}%")
        if h.debt_ratio and h.debt_ratio != "?":
            fb_parts.append(f"负债率={h.debt_ratio}%")
        if h.pb and h.pb != "?":
            fb_parts.append(f"PB={h.pb}")
        if h.dividend_yield and h.dividend_yield != "?":
            fb_parts.append(f"股息率={h.dividend_yield}%")
        fb_summary = " / ".join(fb_parts) if fb_parts else "数据不足"
        lines.append(f"📊 基本面：{fb_summary}")

        # ── 缠论论据 ──
        chan_parts = []
        if h.ma_alignment:
            chan_parts.append(f"MA排列：{h.ma_alignment}（{h.ma_pos_summary}，{h.ma_trend}）")
        if h.ma5 and h.ma5 != "?" and h.ma20 and h.ma20 != "?" and h.ma60 and h.ma60 != "?":
            chan_parts.append(f"MA5={h.ma5} / MA20={h.ma20} / MA60={h.ma60}")
        if h.ma_cross_short:
            chan_parts.append(f"短期均线：{h.ma_cross_short}")
        if h.ma_cross_medium:
            chan_parts.append(f"中期均线：{h.ma_cross_medium}")
        if h.mc:
            chan_parts.append(f"MACD：{h.mc}，柱值 {h.macd_hist}")
        if h.signal:
            chan_parts.append(f"信号：{h.signal}")
        if h.chan_verdict:
            chan_parts.append(f"结论：{h.chan_verdict}")
        # 深度缠论：周线大势 + 笔 + 买卖点/背驰
        if h.week_ma60 and h.week_ma60 != "?":
            chan_parts.append(f"大势：周K MA60={h.week_ma60}{f'，{h.week_chan_verdict}' if h.week_chan_verdict else ''}")
        if h.day_last_bi_dir:
            arrow = "↑" if h.day_last_bi_dir == "up" else "↓"
            chan_parts.append(f"最近笔：{arrow}")
        if h.day_bottom_fx and h.day_bottom_fx != "?":
            date_str = f"({h.day_bottom_fx_date})" if h.day_bottom_fx_date else ""
            ma5_info = f" MA5={h.ma5}{'✅' if h.buy_sell_detail and 'above' in h.buy_sell_detail else ''}" if h.ma5 and h.ma5 != "?" else ""
            chan_parts.append(f"底分型：{h.day_bottom_fx}{date_str}{ma5_info}")
        if h.buy_sell_detail:
            chan_parts.append(f"买卖点：{h.buy_sell_detail}")
        if h.divergence_detail:
            chan_parts.append(f"背驰：{h.divergence_detail}")
        lines.append(f"🔧 缠论：{'；'.join(chan_parts)}" if chan_parts else "🔧 缠论：数据不足")

        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ── 主入口 ───────────────────────────────────────────────────

def format_output(data: dict[str, Any] | str, market: str = "hk") -> str:
    """
    校验 + 渲染裸数据，返回标准 markdown 报告。

    market: 'hk' | 'cn' | 'us' — 根据市场切换模板标题和币种

    调用方使用模式：
        try:
            report = format_output(raw_data, market="hk")
        except FormatValidationError as e:
            llm_retry(e.message)   # 把错误信息传给 LLM 修正
    """
    if isinstance(data, str):
        data = json.loads(data)

    model: SelectionReport = validate(data)
    cfg = _get_config(market)

    return TEMPLATE.format(
        title=cfg["title"],
        date=model.date,
        scan_label=cfg["scan_label"],
        scan_header=cfg["scan_header"],
        elim_label=cfg["elim_label"],
        elim_header=cfg["elim_header"],
        passed_label=cfg["passed_label"],
        score_label=cfg["score_label"],
        score_header=cfg["score_header"],
        detail_label=cfg["detail_label"],
        summary_label=cfg["summary_label"],
        summary_header=cfg["summary_header"],
        sector_rows=_render_sector_rows(model.sectors),
        elim_rows=_render_elim_rows(model.eliminated),
        vetoed_section=_render_vetoed_section(model.vetoed),
        passed_count=model.passed_count,
        top10_rows=_render_top10_rows(model.top10),
        detail_rows=_render_detail_rows(model.details, price_unit=cfg["price_unit"]),
        summary_rows=_render_summary_rows(model.summary),
        timing_rows=_render_timing_rows(model.details, price_unit=cfg["price_unit"]),
        portfolio_timing_rows=_render_portfolio_timing(
            [PortfolioTimingItem(**h) for h in data.get("portfolio_timing", [])],
            price_unit=cfg["price_unit"],
        ) if data.get("portfolio_timing") else "",
    )
