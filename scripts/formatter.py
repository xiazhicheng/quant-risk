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
    fb_w: float = Field(..., ge=0, le=50, description="基本面加权得分 0-50")
    hot_w: float = Field(..., ge=0, le=20, description="热点加权得分(技术面子分)")
    ch_w: float = Field(..., ge=0, le=30, description="缠论加权得分(技术面子分) 0-30")
    total: float = Field(..., ge=0, le=100, description="总分 0-100")
    advice: str = Field(..., description="建议")


class FbDetail(BaseModel):
    score: float = Field(..., ge=1, le=5)
    score_w: float = Field(..., ge=0, le=50, description="基本面加权得分 0-50")
    debug: str = Field(default="", description="基本面计算明细")
    pe: Any = Field(default="?", description="PE")
    revenue_yoy: Any = Field(default="?", description="营收增速")
    net_profit_yoy: Any = Field(default="?", description="净利增速")
    roe: Any = Field(default="?", description="ROE")
    gross_margin: Any = Field(default="?", description="毛利率")
    debt_ratio: Any = Field(default="?", description="负债率")
    # 六维评分（2026-07-22 重构）
    dim1_score: Any = Field(default="?", description="生意质量 1-10")
    dim2_score: Any = Field(default="?", description="护城河 1-10")
    dim3_score: Any = Field(default="?", description="管理层 1-10")
    dim4_score: Any = Field(default="?", description="最大风险 1-10")
    dim5_score: Any = Field(default="?", description="文明趋势 1-10")
    dim6_score: Any = Field(default="?", description="估值 1-10")
    dim1_debug: str = Field(default="", description="生意质量评分明细")
    dim2_debug: str = Field(default="", description="护城河评分明细")
    dim3_debug: str = Field(default="", description="管理层评分明细")
    dim4_debug: str = Field(default="", description="最大风险评分明细")
    dim5_debug: str = Field(default="", description="文明趋势评分明细")
    dim6_debug: str = Field(default="", description="估值评分明细")
    dim1_conclusion: str = Field(default="", description="生意质量定性结论")
    dim2_conclusion: str = Field(default="", description="护城河定性结论")
    dim3_conclusion: str = Field(default="", description="管理层定性结论")
    dim4_conclusion: str = Field(default="", description="最大风险定性结论")
    dim5_conclusion: str = Field(default="", description="文明趋势定性结论")
    dim6_conclusion: str = Field(default="", description="估值定性结论")
    dim1_confidence: str = Field(default="", description="生意质量信心度")
    dim2_confidence: str = Field(default="", description="护城河信心度")
    dim3_confidence: str = Field(default="", description="管理层信心度")
    dim4_confidence: str = Field(default="", description="最大风险信心度")
    dim5_confidence: str = Field(default="", description="文明趋势信心度")
    dim6_confidence: str = Field(default="", description="估值信心度")
    # 大师质疑扣分（2026-07-23 新增）
    dim1_penalty: Any = Field(default=None, description="生意质量扣分")
    dim2_penalty: Any = Field(default=None, description="护城河扣分")
    dim3_penalty: Any = Field(default=None, description="管理层扣分")
    dim4_penalty: Any = Field(default=None, description="最大风险扣分")
    dim5_penalty: Any = Field(default=None, description="文明趋势扣分")
    dim6_penalty: Any = Field(default=None, description="估值扣分")
    dim1_penalty_reason: str = Field(default="", description="生意质量扣分原因")
    dim2_penalty_reason: str = Field(default="", description="护城河扣分原因")
    dim3_penalty_reason: str = Field(default="", description="管理层扣分原因")
    dim4_penalty_reason: str = Field(default="", description="最大风险扣分原因")
    dim5_penalty_reason: str = Field(default="", description="文明趋势扣分原因")
    dim6_penalty_reason: str = Field(default="", description="估值扣分原因")
    # 其他大师质疑（非归属大师对该维度的质疑）
    dim1_other_masters: str = Field(default="", description="生意质量其他大师质疑")
    dim2_other_masters: str = Field(default="", description="护城河其他大师质疑")
    dim3_other_masters: str = Field(default="", description="管理层其他大师质疑")
    dim4_other_masters: str = Field(default="", description="最大风险其他大师质疑")
    dim5_other_masters: str = Field(default="", description="文明趋势其他大师质疑")
    dim6_other_masters: str = Field(default="", description="估值其他大师质疑")
    # 大师答疑（归属大师针对其他大师质疑的回答）
    dim1_master_answer: str = Field(default="", description="生意质量大师答疑")
    dim2_master_answer: str = Field(default="", description="护城河大师答疑")
    dim3_master_answer: str = Field(default="", description="管理层大师答疑")
    dim4_master_answer: str = Field(default="", description="最大风险大师答疑")
    dim5_master_answer: str = Field(default="", description="文明趋势大师答疑")
    dim6_master_answer: str = Field(default="", description="估值大师答疑")
    # 芒格式逆向检验
    reverse_test: str = Field(default="", description="芒格式逆向检验文本")
    # 质量筛选问题
    quality_issues: list = Field(default_factory=list, description="质量筛选问题列表")
    # 信息丰富度评级
    info_richness: str = Field(default="?", description="信息丰富度评级 A/B/C")
    info_richness_detail: str = Field(default="", description="信息丰富度详情")


class HotDetail(BaseModel):
    score: float = Field(..., ge=1, le=5)
    score_w: float = Field(..., ge=0, le=20, description="热点加权得分(技术面子分)")
    desc: str = Field(..., description="热点描述")
    flow_5d: Any = Field(default="?", description="近5日主力净流入(元)")
    flow_1d: Any = Field(default="?", description="最近1日主力净流入(元)")
    flow_days: Any = Field(default=0, description="资金流覆盖天数")
    sector_rank: Any = Field(default="?", description="板块排名")
    sector_5d_pct: Any = Field(default="?", description="板块5日涨幅")
    vol_ratio: Any = Field(default="?", description="5日量比")
    vol_desc: str = Field(default="", description="量能描述")
    pct_5d: Any = Field(default="?", description="个股5日涨幅")
    pct_desc: str = Field(default="", description="涨幅描述")
    relative_strength: Any = Field(default="?", description="相对板块强弱")


class ChanDetail(BaseModel):
    score: float = Field(..., ge=1, le=5)
    score_w: float = Field(..., ge=0, le=30, description="缠论加权得分(技术面子分) 0-30")
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
	"score_header": "| 排名 | 标的 | 板块 | 📊六维评分(60分) | 🔧缠论(20分) | 🔥热点(20分) | 总分(100分) | 建议 |\n|:----:|------|:----:|:----------:|:----------:|:----------:|:-----:|------|",
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
"score_label": "三维评分 TOP10",
		        "score_header": "| 排名 | 标的 | 板块 | 📊六维评分(60分) | 🔧缠论(20分) | 🔥热点(20分) | 总分(100分) | 建议 |\n|:----:|------|:----:|:----------:|:----------:|:----------:|:-----:|------|",
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
        "score_header": "| Rank | Stock | Sector | 6D Score(60pt) | Chan(20pt) | Hot(20pt) | Total(100pt) | Advice |\n|:----:|------|:----:|:---------------:|:------------:|:----------:|:-----:|------|",
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

### TOP10 推荐标的（基本面分析）

{top10_mermaid}

### 各股分析（基本面分析）

{detail_rows}

---

## 定价与择时

### 定价建议

{summary_header}
{summary_rows}

### 择时判断（基本面分析 + 技术面择时）

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

{funnel_section}

	{cross_validation_section}
	
		> 📡 **数据来源**: 六维评分→东财（单一源⚠️）；行情→腾讯（单一源⚠️）；日K线→腾讯主✅+新浪备✅；基本面→东财（单一源⚠️）。多源数据存在差异时已在交叉验证段标注。标注⚠️的字段仅依赖单一数据源，未做偏差≤1%交叉验证。
	
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


def _render_funnel_section(funnel: dict) -> str:
    """渲染行业漏斗筛选段落"""
    if not funnel or not funnel.get("industry"):
        return ""
    industry = funnel["industry"]
    scan_count = funnel.get("scan_count", 0)
    after_filter = funnel.get("after_filter", 0)
    after_veto = funnel.get("after_veto", 0)
    elim_count = scan_count - after_filter if scan_count > after_filter else 0
    veto_count = after_filter - after_veto if after_filter > after_veto else 0

    return (
        "\n### ① 行业漏斗筛选\n"
        f"\n**行业**: {industry}\n"
        "\n"
        "| 层数 | 阶段 | 标的数 | 变化 |\n"
        "|:----:|:----|:-----:|:----|\n"
        f"| 第一层 | 全市场扫描 | {scan_count} | — |\n"
        f"| 第二层 | 中观过滤（市值≥50亿，股价≥1元） | {after_filter} | -{elim_count} |\n"
        f"| 第三层 | 基本面一票否决 | {after_veto} | -{veto_count} |\n"
        f"| 第四层 | 六维评分排名 → 终选 | 3-10 | — |\n"
        "\n"
    )


def _render_cross_validation(cv_data: list) -> str:
    """渲染关键数据多源交叉验证记录。

    遵循 ai-berkshire financial-data.md 规范格式：
      - ≤1%: ✅ 一致
      - 1%~5%: ⚠️ 存在差异（注原因）
      - >5%: ❌ 重大差异（需核实）
      - 📊: 单一数据源，未交叉验证

    Args:
        cv_data: [{"code": str, "source_pair": str, "fields": [{"name":str,
                    "primary":float, "secondary":float, "deviation_pct":float,
                    "status":str, "secondary_source": str}],
                    "summary": {"total": int, "verified": int, "single_source": int,
                                "ok": int, "warn": int, "error": int, "error_msg": str}}]
    """
    if not cv_data:
        return ""

    has_data = [c for c in cv_data if c.get("fields")]
    if not has_data:
        return ""

    blocks = []
    for item in has_data:
        code = item["code"]
        summary = item["summary"]
        fields = item["fields"]

        verified_count = summary.get("verified", 0)
        single_count = summary.get("single_source", 0)
        ok = summary.get("ok", 0)
        warn = summary.get("warn", 0)
        error = summary.get("error", 0)

        # 标题行
        if error > 0:
            verdict = "❌"
        elif warn > 0:
            verdict = "⚠️"
        elif ok > 0:
            verdict = "✅"
        else:
            verdict = "📊"

        verified_str = f"✅{ok} ⚠️{warn} ❌{error}" if (ok + warn + error) > 0 else "—无交叉验证—"
        block = [f"**{code}** {verdict} | 数据{summary['total']}项（已交叉验证{verified_count}项）| {verified_str}"]

        for f in fields:
            name = f["name"]
            pv = f["primary"]
            sv = f["secondary"]
            dev = f["deviation_pct"]
            status = f["status"]
            src = f.get("secondary_source", "")

            if status == "📊":
                # 单一数据源
                block.append(f"  - {name}：{pv}% 📊（{src}）")
            elif status == "✅":
                block.append(f"  - {name}：{pv}% {status}（vs {src} {sv}%，偏差{dev}%）")
            elif status == "⚠️":
                block.append(f"  - {name}：{pv}%（东财）vs {sv}%（{src}）{status}（偏差{dev}%，可能存在会计口径差异）")
            else:
                block.append(f"  - {name}：{pv}%（东财）vs {sv}%（{src}）{status}（偏差{dev}%，重大差异，需核实原始财报）")

        blocks.append("\n".join(block))

    return (
        "\n### ③ 关键数据多源交叉验证\n"
        "\n"
        "> 数据来源：东财 GMAININDICATOR（主）+ 腾讯行情/Yahoo（副）\n"
        "> 📊 = 单一数据源（未交叉验证）| ✅ = 偏差≤1% | ⚠️ = 偏差1%~5% | ❌ = 偏差>5%\n"
        "\n"
        + "\n\n".join(blocks)
        + "\n"
    )


def _render_top10_rows(top10: list[Top10Item]) -> str:
    return "\n".join(
        f"| ⭐{t.rank} | **{t.code} {t.name}** | {t.sector} | {t.fb_w:.1f} | {t.ch_w:.1f} | {t.hot_w:.1f} | "
        f"**{t.total:.1f}** | {t.advice} |"
        for t in top10
    )


def _calc_pct_change(price, stop_loss):
    """计算止损相对当前价的百分比变化"""
    if isinstance(price, (int, float)) and isinstance(stop_loss, (int, float)) and price:
        return (stop_loss - price) / price * 100
    return 0.0


def _render_mirror_test(d: DetailItem, price_unit: str = "港元") -> str:
    """镜子测试：5句话说清楚为什么买。

    如果说不完整5句，标注"镜子测试未通过"。
    """
    fb = d.fb
    lines = []
    price = d.price

    # 第1句：买入理由（生意本质）
    if fb.roe and fb.roe != "?":
        try:
            roe_v = float(fb.roe)
            if roe_v > 30:
                lines.append(f"1. 这门生意ROE {fb.roe}%，资本回报效率极高，说明是好生意")
            elif roe_v > 15:
                lines.append(f"1. 这门生意ROE {fb.roe}%，资本回报效率良好，说明是合格的生意")
            elif roe_v > 0:
                lines.append(f"1. 这门生意ROE {fb.roe}%偏低，需确认商业模式是否可持续")
        except (ValueError, TypeError):
            pass
    elif fb.gross_margin and fb.gross_margin != "?":
        try:
            gm_v = float(fb.gross_margin)
            if gm_v > 60:
                lines.append(f"1. 毛利率 {fb.gross_margin}%，有极强的定价权，这是好生意的标志")
            elif gm_v > 40:
                lines.append(f"1. 毛利率 {fb.gross_margin}%，有一定定价权，生意模式尚可")
            else:
                lines.append(f"1. 毛利率 {fb.gross_margin}%，定价权一般")
        except (ValueError, TypeError):
            pass

    # 第2句：估值/安全边际
    if fb.pe and fb.pe != "?":
        try:
            pe_v = float(fb.pe)
            if 0 < pe_v < 15:
                lines.append(f"2. 当前PE {fb.pe}，估值偏低，有一定的安全边际")
            elif pe_v < 25:
                lines.append(f"2. 当前PE {fb.pe}，估值合理，安全边际一般")
            else:
                lines.append(f"2. 当前PE {fb.pe}，估值偏高，需确认增长能否消化估值")
        except (ValueError, TypeError):
            pass

    # 第3句：护城河/竞争壁垒
    if fb.roe and fb.roe != "?":
        try:
            roe_v = float(fb.roe)
            if roe_v > 15:
                lines.append(f"3. ROE {fb.roe}%持续高水平，说明有竞争壁垒，对手难以复制")
        except (ValueError, TypeError):
            pass
    if len(lines) < 3 and fb.net_profit_yoy and fb.net_profit_yoy != "?":
        try:
            ny_v = float(fb.net_profit_yoy)
            if ny_v > 20:
                lines.append(f"3. 净利增长 {fb.net_profit_yoy}%，盈利在加速，护城河在变宽")
            elif ny_v > 0:
                lines.append(f"3. 净利增长 {fb.net_profit_yoy}%，盈利在增长，但速度一般")
        except (ValueError, TypeError):
            pass

    # 第4句：确定性/长期
    if fb.debt_ratio and fb.debt_ratio != "?":
        try:
            dr_v = float(fb.debt_ratio)
            if dr_v < 30:
                lines.append(f"4. 负债率仅 {fb.debt_ratio}%，财务结构稳健，10年后大概率还在")
            elif dr_v < 50:
                lines.append(f"4. 负债率 {fb.debt_ratio}%，杠杆适中，长期风险可控")
            else:
                lines.append(f"4. 负债率 {fb.debt_ratio}%偏高，长期确定性存疑")
        except (ValueError, TypeError):
            pass

    # 第5句：下行风险控制
    stop_loss = d.stop_loss
    if stop_loss and float(stop_loss) > 0:
        try:
            loss_pct = (float(stop_loss) - float(d.price)) / float(d.price) * 100
            if loss_pct < -15:
                lines.append(f"5. 止损设在 {_fmt_num_safe(stop_loss)}（下行 {loss_pct:.1f}%），风险可控但波动较大")
            else:
                lines.append(f"5. 止损设在 {_fmt_num_safe(stop_loss)}（下行 {loss_pct:.1f}%），风险可控")
        except (ValueError, TypeError):
            pass

    # 生成镜子测试结果
    header = f"**镜子测试**：以{_fmt_num_safe(price)}{price_unit}买入{d.name}，因为：\n"
    body = "\n".join(lines[:5]) if lines else "（数据不足，无法生成镜子测试）"

    if len(lines) >= 5:
        return f"{header}{body}\n✅ 镜子测试通过——5句话说清楚了"
    elif len(lines) >= 3:
        return f"{header}{body}\n\n⚠️ 镜子测试边缘——仅{len(lines)}句，能说清楚但不够完整"
    else:
        return f"{header}{body}\n\n❌ 镜子测试未通过——仅{len(lines)}句，说不清楚为什么买，建议谨慎"


def _stars(n) -> str:
    """将1-5分映射为★符号"""
    if n is None or n == "?" or n == "":
        return "—"
    try:
        r = round(float(n))
        return "★" * max(1, min(5, r))
    except (ValueError, TypeError):
        return "—"


def _render_checklist(fb, mirror_test_text: str, d, summary_only: bool = False) -> str:
    """买入前 Checklist 六关评分。

    基于六维评分和镜子测试自动生成。
    六维评分每维满分10分，≥7分视为通过。
    """
    # ① 好生意 → dim1 生意质量
    biz_score = fb.dim1_score if fb.dim1_score and fb.dim1_score != "?" else "—"
    # ② 护城河 → dim2
    moat_score = fb.dim2_score if fb.dim2_score and fb.dim2_score != "?" else "—"
    # ③ 逆向风险 → dim4 最大风险
    risk_score = fb.dim4_score if fb.dim4_score and fb.dim4_score != "?" else "—"
    # ④ 长期确定性 → dim5 文明趋势
    certain_score = fb.dim5_score if fb.dim5_score and fb.dim5_score != "?" else "—"
    # ⑤ 估值 → dim6
    val_score = fb.dim6_score if fb.dim6_score and fb.dim6_score != "?" else "—"
    # ⑥ 镜子测试
    if "镜子测试通过" in mirror_test_text:
        mirror_result = "✅ 通过"
    elif "镜子测试边缘" in mirror_test_text:
        mirror_result = "⚠️ 边缘"
    else:
        mirror_result = "❌ 未通过"

    # 综合计分
    passed = 0
    if fb.dim1_score and fb.dim1_score != "?" and float(fb.dim1_score) >= 7.0: passed += 1
    if fb.dim2_score and fb.dim2_score != "?" and float(fb.dim2_score) >= 7.0: passed += 1
    if fb.dim4_score and fb.dim4_score != "?" and float(fb.dim4_score) >= 7.0: passed += 1
    if fb.dim5_score and fb.dim5_score != "?" and float(fb.dim5_score) >= 7.0: passed += 1
    if fb.dim6_score and fb.dim6_score != "?" and float(fb.dim6_score) >= 7.0: passed += 1
    if "镜子测试通过" in mirror_test_text: passed += 1

    if passed >= 5: verdict = f"✅通过（{passed}/6关）"
    elif passed >= 3: verdict = f"⚠️边缘（{passed}/6关）"
    else: verdict = f"❌未通过（{passed}/6关）"

    if summary_only:
        return verdict

    return (
        f"**📋 买入前 Checklist**\n"
        f"| 关卡 | 评分 | 数据支撑 |\n"
        f"|:----|:---:|:---------|\n"
        f"| ① 好生意(生意质量) | {biz_score}/10 | ROE/毛利率/净利率 |\n"
        f"| ② 护城河 | {moat_score}/10 | ROE/毛利率/股息率/负债率 |\n"
        f"| ③ 逆向风险(最大风险) | {risk_score}/10 | 负债率/营收增速/净利 |\n"
        f"| ④ 长期确定性(文明趋势) | {certain_score}/10 | 营收增速/净利率/负债率/ROE |\n"
        f"| ⑤ 估值 | {val_score}/10 | PE相对估值/股息率 |\n"
        f"| ⑤ 镜子测试 | {mirror_result} | 5句话说清楚 |\n"
        f"| ⑥ 质量筛选 | {quality_result} | 财务指标硬约束 |\n"
        f"**{verdict}**"
    )

def _safe_float(v):
    """安全地将值转为 float，失败返回 None"""
    if v is None or v == "?" or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _render_detail_block(d: DetailItem, price_unit: str = "港元") -> str:
    """个股深度分析报告 — 13 节结构化输出"""
    pct = d.pct
    sign = "+" if isinstance(pct, (int, float)) and pct >= 0 else ""
    pct_str = f"{sign}{pct}" if isinstance(pct, (int, float)) else str(pct)

    fb = d.fb
    hot = d.hot
    ch = d.ch
    sl_pct = _calc_pct_change(d.price, d.stop_loss)

    # ── 关键指标摘要 ──
    fb_parts = []
    for attr, label in [("revenue_yoy", "营收"), ("net_profit_yoy", "净利"),
                         ("roe", "ROE"), ("gross_margin", "毛利率"),
                         ("debt_ratio", "负债率"), ("pe", "PE")]:
        v = getattr(fb, attr, "?")
        if v != "?" and v is not None:
            fb_parts.append(f"{label}{v}%")
    fb_summary = "，".join(fb_parts) if fb_parts else "数据不足"

    ir_desc = ""
    if fb.info_richness and fb.info_richness != "?":
        ir_desc = f"📡 {fb.info_richness}"
        if fb.info_richness_detail:
            ir_desc += f"（{fb.info_richness_detail}）"

    # 择时结论
    if ch.score >= 4.5: timing_verdict = "当前可布局"
    elif ch.score >= 4.0: timing_verdict = "等待回调介入"
    elif ch.score >= 3.0: timing_verdict = "观望，等待企稳"
    else: timing_verdict = "暂不建议入场"

    # 镜子测试
    mirror_text = _render_mirror_test(d, price_unit)
    if "✅ 镜子测试通过" in mirror_text: mirror_summary = "✅通过"
    elif "⚠️ 镜子测试边缘" in mirror_text: mirror_summary = "⚠️边缘"
    else: mirror_summary = "❌未通过"

    cl_text = _render_checklist(fb, mirror_text, d, summary_only=True)

    # 逆向检验摘要
    reverse_summary = ""
    if fb.reverse_test:
        if "无明显死亡路径" in fb.reverse_test or "健康" in fb.reverse_test:
            reverse_summary = "✅无明显风险"
        elif "🔥" in fb.reverse_test:
            reverse_summary = "⚠️有风险"
        else:
            reverse_summary = "⚠️有风险"

    # 留白声明
    disclaimer_text = ""
    if fb.info_richness == "C级":
        disclaimer_text = f"\n⚠️ **留白声明**：该标的信息丰富度评级为C级（数据严重不足），置信度较低。\n"

    adv = d.advice
    adv_emoji = "🔴" if "止损" in adv else ("✅" if "持有" in adv else "🟢")

    return f"""\
#### {d.rank}. {d.name}（{d.code}）— {adv} ✅ | 总分 {d.total}/100
{ir_desc} 关键指标：{fb_summary}

---
### 一、公司概况

**基本信息**：{d.name}（{d.code}）| 现价：{d.price} {price_unit}
> 📡 数据来源: 腾讯行情

{_render_hot_journey(hot)}
> 📡 数据来源: 腾讯/新浪日K线数据

---
### 二、财务数据与分析

{_render_financial_timeline(fb)}
> 📡 数据来源: 东财 datacenter（GMAININDICATOR）

---
### 三、技术分析

**🔧 {round(ch.score_w, 1)}/20** | {timing_verdict}

{_render_tech_flowchart(ch, d)}
> 📡 数据来源: 腾讯/新浪日K线 → MA/MACD/缠论计算

---
### 四、市场情绪

{_render_hot_journey(hot)}
> 📡 数据来源: 腾讯/新浪日K线 → 量价情绪评分

---
### 五、挑刺分析

{_render_critique(fb)}
> 📡 数据来源: 东财基本面数据 + 芒格式逆向分析

---
### 六、投资哲学对照

**📋 核心检查清单**

| 检查项 | 结果 |
|:------|:----:|
| 好生意（ROE>15% or 毛利率>40%） | {'✅' if (fb.roe and _safe_float(fb.roe) and float(fb.roe)>15) or (fb.gross_margin and _safe_float(fb.gross_margin) and float(fb.gross_margin)>40) else '❌'} |
| 护城河（ROE持续>15%） | {'✅' if fb.roe and _safe_float(fb.roe) and float(fb.roe)>15 else '❌'} |
| 价格合理（PE<25） | {'✅' if fb.pe and _safe_float(fb.pe) and 0<float(fb.pe)<25 else '❌' if fb.pe and _safe_float(fb.pe) and float(fb.pe)>0 else '➖'} |
| 财务安全（负债率<60%） | {'✅' if fb.debt_ratio and _safe_float(fb.debt_ratio) and float(fb.debt_ratio)<60 else '❌'} |
| 增长确定（营收+净利正增长） | {'✅' if fb.revenue_yoy and fb.net_profit_yoy and _safe_float(fb.revenue_yoy) and _safe_float(fb.net_profit_yoy) and float(fb.revenue_yoy)>0 and float(fb.net_profit_yoy)>0 else '❌'} |
> 📡 数据来源: 东财 datacenter

**🧭 四象限定位**

{_render_quadrant(fb)}
> 📡 数据来源: 东财基本面数据

---
### 七、投资委员会辩论

{_render_master_debate(fb, ch, d)}
{disclaimer_text}
> 📡 数据来源: 东财 datacenter（六维评分模型）+ 腾讯行情（PE/市值）

---
### 八、图表参考

| # | 图表 | 说明 | 数据源 |
|:-:|:----|:----|:------|
| ① | 情绪面用户旅程图 | 板块/量能/价格/综合情绪评分 | 腾讯/新浪K线 |
| ② | 财务数据时间线 | 营收/净利/ROE/毛利率/负债率 | 东财 datacenter |
| ③ | 技术面流程图 | 趋势/缠论/价量/支撑 | 腾讯/新浪K线 |
| ④ | 一票否决时序图 | 逆向检验→镜子测试→操作建议 | 东财+腾讯 |
| ⑤ | 投资委员会辩论 | 多方/空方/风控/委员会主席三角色 | 东财+腾讯 |
				"""
    pct = d.pct
    sign = "+" if isinstance(pct, (int, float)) and pct >= 0 else ""
    pct_str = f"{sign}{pct}" if isinstance(pct, (int, float)) else str(pct)

    fb = d.fb
    hot = d.hot
    ch = d.ch

    sl_pct = _calc_pct_change(d.price, d.stop_loss)

    # ── 六维评分表（2026-07-22 六维框架） ──
    dim_configs = [
        ("生意质量（段永平）", 1),
        ("护城河（巴菲特）", 2),
        ("管理层（段永平+巴菲特）", 3),
        ("最大风险（芒格）", 4),
        ("文明趋势（李录）", 5),
        ("估值（巴菲特+段永平）", 6),
    ]

    dim_rows = []
    dim_header = "| 维度 | 评分 | 信心度 | 大师视角 | 其他大师质疑 | 大师答疑 |\n|:----|:---:|:------:|:--------|:----------:|:--------|"
    for label, idx in dim_configs:
        score = getattr(fb, f"dim{idx}_score", "?")
        confidence = getattr(fb, f"dim{idx}_confidence", "")
        conclusion = getattr(fb, f"dim{idx}_conclusion", "")
        other_masters = getattr(fb, f"dim{idx}_other_masters", "")
        master_answer = getattr(fb, f"dim{idx}_master_answer", "")
        penalty = getattr(fb, f"dim{idx}_penalty", None)
        penalty_reason = getattr(fb, f"dim{idx}_penalty_reason", "")
        if score != "?":
            score_display = f"{score}/10"
            if penalty is not None and penalty > 0:
                score_display += f" ↓-{penalty}"
                if penalty_reason:
                    conclusion = f"{conclusion} ⚠️ {penalty_reason}"
            dim_rows.append(f"| {label} | {score_display} | {confidence} | {conclusion} | {other_masters} | {master_answer} |")
        else:
            dim_rows.append(f"| {label} | 数据不足 | — | 数据不足 | 数据不足 | 数据不足 |")
    dim_table = dim_header + "\n" + "\n".join(dim_rows) if dim_rows else "数据不足"

    # ── 关键指标摘要 ──
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

    ir_desc = ""
    if fb.info_richness and fb.info_richness != "?":
        ir_desc = f"📡 {fb.info_richness}"
        if fb.info_richness_detail:
            ir_desc += f"（{fb.info_richness_detail}）"

    # ── 技术面结构化表格 ──
    tech_rows = []
    if ch.ma_alignment:
        ma_detail = ""
        if ch.ma60 and ch.ma60 != "?" and ch.price and ch.price != "?":
            try:
                pv60 = (float(ch.price) - float(ch.ma60)) / float(ch.ma60) * 100
                ma_detail = f"MA60={ch.ma60}，偏离{pv60:+.1f}%"
            except (ValueError, TypeError):
                ma_detail = f"MA60={ch.ma60}"
        tech_rows.append(f"| MA排列 | {ch.ma_alignment}（{ch.chan_verdict or ch.signal or '中性'}） | {ma_detail} |")
    if ch.mc:
        tech_rows.append(f"| MACD | {ch.mc}，柱值{'正' if float(ch.macd_hist or 0) >= 0 else '负'} | MACD柱={ch.macd_hist} |")
    if ch.day_last_bi_dir:
        arrow = "↑" if ch.day_last_bi_dir == "up" else "↓"
        bi_detail = ""
        if ch.day_bottom_fx and ch.day_bottom_fx != "?":
            date_str = f"({ch.day_bottom_fx_date})" if ch.day_bottom_fx_date else ""
            ma5_str = f"✅站上MA5" if ch.day_above_ma5 else "❌未站上MA5"
            bi_detail = f"底分型={ch.day_bottom_fx}{date_str} {ma5_str}"
        tech_rows.append(f"| 缠论笔 | 最近笔 {arrow} | {bi_detail} |")

    # 量价
    vr = d.vol_5d_ratio
    p5 = d.pct_5d
    vol_desc = f"量平({vr:.1f}x)" if vr else "量:无数据"
    if vr and vr > 1.5: vol_desc = f"放量({vr:.1f}x)"
    if vr and vr > 2.0: vol_desc = f"放巨量({vr:.1f}x)"
    if vr and vr < 0.5: vol_desc = f"缩量({vr:.1f}x)"
    pct_desc = f"5日涨幅{p5:+.2f}%" if p5 is not None else "5日涨幅:无数据"
    tech_rows.append(f"| 量价 | {vol_desc} | {pct_desc} |")

    tech_table = "\n".join(tech_rows) if tech_rows else ""

    # 择时结论
    if ch.score >= 4.5: timing_verdict = "当前可布局"
    elif ch.score >= 4.0: timing_verdict = "等待回调介入"
    elif ch.score >= 3.0: timing_verdict = "观望，等待企稳"
    else: timing_verdict = "暂不建议入场"

    # ── 镜子测试（一句总结） ──
    mirror_text = _render_mirror_test(d, price_unit)
    if "✅ 镜子测试通过" in mirror_text:
        mirror_summary = "✅通过"
    elif "⚠️ 镜子测试边缘" in mirror_text:
        mirror_summary = "⚠️边缘"
    else:
        mirror_summary = "❌未通过"

    # ── Checklist（一句总结） ──
    cl_text = _render_checklist(fb, mirror_text, d, summary_only=True)

    # ── 逆向检验（一句总结） ──
    reverse_summary = ""
    if fb.reverse_test:
        if "无明显死亡路径" in fb.reverse_test or "健康" in fb.reverse_test:
            reverse_summary = "✅无明显风险"
        elif "🔥" in fb.reverse_test:
            reverse_summary = "⚠️有风险"
        else:
            reverse_summary = "⚠️有风险"

    # ── 留白声明 ──
    disclaimer_text = ""
    if fb.info_richness == "C级":
        disclaimer_text = f"\n⚠️ **留白声明**：该标的信息丰富度评级为C级（数据严重不足），置信度较低。\n"

    return f"""\
#### {d.rank}. {d.name}（{d.code}）— {d.advice} ✅ | 总分 {d.total}/100 | 📊基本面分析 {fb.score_w}/60
{ir_desc} 关键指标：{fb_summary}

**📊 基本面分析**

{_render_master_debate(fb, ch, d)}
{disclaimer_text}
{_render_hot_journey(hot)}

**🔧 技术面 {round(ch.score_w, 1)}/20** → {timing_verdict}
{_render_tech_flowchart(ch, d)}

{_render_veto_sequence(d, mirror_text, cl_text, reverse_summary)}

**💰 定价**：入场 {d.price} → 止损 {d.stop_loss}（{sl_pct:.1f}%）→ 目标 {d.take_profit}
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


def _render_hot_journey(hot: HotDetail, market: str = "hk") -> str:
    """情绪面分析 → Mermaid User Journey 图"""
    hot_score_val = hot.score
    hot_score_7 = min(round(hot_score_val * 1.4, 1), 7)  # 1-5 → 1.4-7

    # 板块排名 → 反向映射（排名越靠前分数越高）
    sector_rank = hot.sector_rank
    if isinstance(sector_rank, (int, float)) and sector_rank != "?":
        rank_score = max(7 - (sector_rank - 1) * 1.0, 0.5)
    else:
        rank_score = 3.5

    # 板块5日涨幅
    sec_5d = hot.sector_5d_pct
    if isinstance(sec_5d, (int, float)) and sec_5d != "?":
        sec_score = min(max((sec_5d + 10) / 20 * 7, 0.5), 7)
    else:
        sec_score = 3.5

    # 量比情绪
    vol_r = hot.vol_ratio
    if isinstance(vol_r, (int, float)) and vol_r != "?":
        # 1.0x=3.5, 2.0x=5.5, 0.5x=1.5
        vol_score = min(max(vol_r * 3.5 - 0.5, 0.5), 7)
    else:
        vol_score = 3.5

    # 5日涨幅情绪
    p5 = hot.pct_5d
    if isinstance(p5, (int, float)) and p5 != "?":
        p5_score = min(max((p5 + 15) / 30 * 7, 0.5), 7)
    else:
        p5_score = 3.5

    # 相对强弱
    rel = hot.relative_strength
    if isinstance(rel, (int, float)) and rel != "?":
        rel_score = min(max((rel + 15) / 30 * 7, 0.5), 7)
    else:
        rel_score = 3.5

    # 格式化数值
    sr_str = f"第{sector_rank}名" if isinstance(sector_rank, (int, float)) else "?"
    sec_str = f"{sec_5d:+.1f}%" if isinstance(sec_5d, (int, float)) else "?"
    vol_str = f"{vol_r:.1f}x" if isinstance(vol_r, (int, float)) else "?"
    p5_str = f"{p5:+.1f}%" if isinstance(p5, (int, float)) else "?"
    rel_str = f"{rel:+.1f}%" if isinstance(rel, (int, float)) else "?"

    return f"""\
```mermaid
journey
    title 🔥 情绪面分析 — {hot.desc.split('板块')[0] if '板块' in hot.desc else ''}
    section 板块情绪
      {sr_str}: {rank_score:.1f}: 板块
      {sec_str}: {sec_score:.1f}: 板块
    section 量能情绪
      {vol_str}: {vol_score:.1f}: 个股
    section 价格情绪
      {p5_str}: {p5_score:.1f}: 个股
      相对强弱{rel_str}: {rel_score:.1f}: 个股
    section 综合
      情绪评分 ({hot_score_val}/5): {hot_score_7:.1f}: 系统
```"""


def _render_master_debate(fb: FbDetail, ch: "ChanDetail" = None, d: "DetailItem" = None) -> str:
    """投资委员会辩论 — 多方/空方/风控/委员会主席 三角色"""
    pe = _safe_float(fb.pe)
    roe_val = _safe_float(fb.roe)
    rev = _safe_float(fb.revenue_yoy)
    net = _safe_float(fb.net_profit_yoy)
    dr = _safe_float(fb.debt_ratio)
    gm = _safe_float(fb.gross_margin)

    lines = []
    lines.append("```mermaid")
    lines.append("sequenceDiagram")
    lines.append("    participant 委员会主席")
    lines.append("    participant 多方")
    lines.append("    participant 空方")
    lines.append("    participant 风控")
    lines.append("    ")
    lines.append("")

    data_items = []
    if roe_val is not None: data_items.append(f"ROE={roe_val:.0f}")
    if gm is not None: data_items.append(f"毛利率={gm:.0f}")
    if rev is not None: data_items.append(f"营收+{rev:.0f}" if rev>0 else f"营收{rev:.0f}")
    if net is not None: data_items.append(f"净利+{net:.0f}" if net>0 else f"净利{net:.0f}")
    if dr is not None: data_items.append(f"负债率{dr:.0f}")
    if pe is not None and pe>0: data_items.append(f"PE={pe:.0f}")
    lines.append(f"    Note over 委员会主席: \U0001f4ca 标的数据全景")
    lines.append(f"    委员会主席->>委员会主席: {' | '.join(data_items[:6])}")
    lines.append("")

    # 多方陈词
    pro_args = []
    if roe_val is not None and roe_val > 15:
        pro_args.append(f"ROE {roe_val:.0f}% 远超15%及格线，资本回报效率极高")
    if gm is not None and gm > 40:
        pro_args.append(f"毛利率 {gm:.0f}% 高于40%，有强定价权")
    if rev is not None and rev > 5:
        pro_args.append(f"营收增长 {rev:.0f}%，主业在快速扩张")
    if net is not None and net > 20:
        pro_args.append(f"净利暴增 {net:.0f}%，盈利加速")
    if dr is not None and dr < 30:
        pro_args.append(f"负债率仅 {dr:.0f}%，财务极其稳健")
    if pe is not None and 0 < pe < 15:
        pro_args.append(f"PE {pe:.0f} 处于低估区间，有安全边际")

    lines.append("    Note over 多方,委员会主席: \U0001f535 多方陈述（看多逻辑）")
    if pro_args:
        for arg in pro_args[:3]:
            lines.append(f"    多方->>委员会主席: \U0001f4c8 {arg}")
    else:
        lines.append("    多方->>委员会主席: \u26a0\ufe0f 无明显正向驱动因素")
    lines.append("")

    # 空方驳斥
    con_args = []
    if roe_val is not None and roe_val < 10:
        con_args.append(f"ROE仅{roe_val:.0f}%，远低于15%，资本低效配置！")
    elif roe_val is not None and roe_val < 15:
        con_args.append(f"ROE {roe_val:.0f}% 低于15%，回报率不及格")
    if gm is not None and gm < 20:
        con_args.append(f"毛利率仅{gm:.0f}%，定价权薄弱！")
    if rev is not None and rev < 0:
        con_args.append(f"营收同比{rev:.0f}%，主业萎缩！")
    elif rev is not None and rev < 5:
        con_args.append(f"营收仅增长{rev:.0f}%，跑不赢通胀")
    if net is not None and net < 0:
        con_args.append(f"净利同比{net:.0f}%，盈利恶化！")
    if dr is not None and dr > 60:
        con_args.append(f"负债率{dr:.0f}%，杠杆过高！")
    if pe is not None and pe > 30:
        con_args.append(f"PE高达{pe:.0f}，严重高估！")

    lines.append("    Note over 空方,委员会主席: \U0001f534 空方驳斥（看空逻辑）")
    if con_args:
        for arg in con_args[:3]:
            lines.append(f"    空方->>委员会主席: \U0001f4c9 {arg}")
    else:
        lines.append("    空方->>委员会主席: \u2705 无明显负面因素")
    lines.append("")

    # ── 多轮动态辩论 ──
    # 构建辩论议题池（根据数据动态生成）
    debate_topics = []
    
    # 议题1：盈利能力
    if roe_val is not None:
        if roe_val > 25:
            debate_topics.append(("🔴", "盈利能力", 
                f"ROE高达{roe_val:.0f}%！全市场顶尖水平，这就是印钞机级别的生意！",
                f"ROE{roe_val:.0f}%确实亮眼，但高ROE能持续吗？历史上多少「印钞机」最后成了碎纸机？"))
        elif roe_val > 15:
            debate_topics.append(("🟡", "盈利能力",
                f"ROE {roe_val:.0f}%超过15%及格线，资本回报效率优秀。",
                f"ROE才{roe_val:.0f}%刚过及格线就吹？优秀企业ROE应该25%起步！"))
        elif roe_val < 10:
            debate_topics.append(("🔴", "盈利能力",
                f"ROE仅{roe_val:.0f}%，远低于15%！资本在低效空转，这是毁灭价值！",
                f"ROE{roe_val:.0f}%确实难看但看毛利率{gm:.0f}%，说明定价权没丢，ROE提升只是时间问题！"))
    
    # 议题2：成长性
    if rev is not None:
        if rev > 20:
            debate_topics.append(("🟢", "成长性",
                f"营收增长{rev:.0f}%！高速扩张中，这是成长股的魅力！",
                f"营收增长{rev:.0f}%看似漂亮，但高增长能持续吗？一旦增速放缓，市场会用脚投票！"))
        elif rev > 5:
            debate_topics.append(("🟡", "成长性",
                f"营收增长{rev:.0f}%，主业稳步扩张。",
                f"营收才增长{rev:.0f}%跑不赢GDP，这叫成长？这叫混日子！"))
        elif rev < -10:
            debate_topics.append(("🔴", "成长性",
                f"营收暴跌{rev:.0f}%！主业严重萎缩，这是要完的节奏！",
                f"营收下滑是事实，但看看同行都在跌，这是行业周期不是公司问题！"))
        elif rev < 0:
            debate_topics.append(("🔴", "成长性",
                f"营收同比{rev:.0f}%，负增长就是危险的信号！",
                f"营收微降但毛利率稳定，说明是在主动优化产品结构！"))
    
    # 议题3：财务安全
    if dr is not None:
        if dr > 70:
            debate_topics.append(("🔴", "财务安全",
                f"负债率{dr:.0f}%！这杠杆率，一旦加息就是灾难！",
                f"负债率虽高但利息保障倍数足够，而且低息环境还能持续！"))
        elif dr > 50:
            debate_topics.append(("🟡", "财务安全",
                f"负债率{dr:.0f}%，超过50%需关注。",
                f"负债率{dr:.0f}%确实偏高，但ROE{roe_val:.0f}%能覆盖利息成本，风险可控！"))
        elif dr < 30:
            debate_topics.append(("🟢", "财务安全",
                f"负债率仅{dr:.0f}%，零净负债，财务极其稳健！",
                f"零负债=零杠杆=低回报。保守不是优秀，是浪费资本！"))
    
    # 议题4：估值
    if pe is not None and pe > 0:
        if pe < 10:
            debate_topics.append(("🟢", "估值水平",
                f"PE仅{pe:.0f}倍！极度低估，市场明显定价错误！",
                f"PE{pe:.0f}倍低不是没理由的！市场比你我聪明，低PE的公司通常有你看不到的雷！"))
        elif pe < 15:
            debate_topics.append(("🟢", "估值水平",
                f"PE {pe:.0f}倍偏低，有足够安全边际！",
                f"PE{pe:.0f}倍只能说合理偏低，「足够安全边际」是骗自己的话！"))
        elif pe > 30:
            debate_topics.append(("🔴", "估值水平",
                f"PE高达{pe:.0f}倍！严重高估，任何利空都会引发暴跌！",
                f"PE高是因为市场看到了你看不到的增长潜力！嫌贵的人永远买不到好公司！"))

    # 议题5：技术面
    ma_bull = False
    ma_bear = False
    if ch is not None:
        if ch.chan_verdict and "\u504f\u591a" in ch.chan_verdict: ma_bull = True
        if ch.chan_verdict and "\u504f\u7a7a" in ch.chan_verdict: ma_bear = True
        if ch.ma_alignment and "\u591a\u5934" in ch.ma_alignment: ma_bull = True
    if d is not None: p5 = d.pct_5d
    else: p5 = None
    
    if ma_bull:
        debate_topics.append(("🟢", "技术面",
            "MA多头排列，周线月线全部向上，趋势就是最好的朋友！",
            "技术面滞后于基本面！等 MA 信号出来，聪明钱早就进场了！"))
    elif ma_bear:
        debate_topics.append(("🔴", "技术面",
            "MA空头排列，下降趋势明显，现在接飞刀会死得很惨！",
            "空头排列才是机会！等所有人都绝望了，真正的价值投资者才开始买入！"))
    else:
        debate_topics.append(("🟡", "技术面",
            "技术面中性，等待方向选择。",
            "技术面无方向就是最大不确定性，不确定性=风险！"))
    
    # 议题6：竞争格局（基于毛利率判断护城河）
    if gm is not None:
        if gm > 60:
            debate_topics.append(("🟢", "竞争格局",
                f"毛利率{gm:.0f}%远超60%，有极强的定价权！这就是护城河！",
                f"历史上有多少高毛利率的公司最后被颠覆了？诺基亚、柯达都曾是暴利！"))
        elif gm > 40:
            debate_topics.append(("🟡", "竞争格局",
                f"毛利率{gm:.0f}%高于40%，有一定定价权，竞争地位尚可。",
                f"毛利率{gm:.0f}%也就是行业平均，没有什么护城河，竞争对手随时可以杀进来！"))
        else:
            debate_topics.append(("🔴", "竞争格局",
                f"毛利率仅{gm:.0f}%，定价权薄弱！靠价格战活着的公司没有未来！",
                f"毛利率低但周转快，薄利多销也是一种商业模式！沃尔玛毛利率也不高！"))

    # 议题7：管理层能力（ROE作为管理层资本配置效率的代理指标）
    if roe_val is not None:
        if roe_val > 20:
            debate_topics.append(("🟢", "管理层能力",
                f"ROE{roe_val:.0f}%，资本配置效率极高，管理层值得信赖！",
                f"高ROE不一定是管理层优秀，也可能是行业红利！潮水退了才知道谁在裸泳！"))
        elif roe_val > 10:
            debate_topics.append(("🟡", "管理层能力",
                f"ROE{roe_val:.0f}%，资本配置能力中等，管理层合格。",
                f"ROE中规中矩，没有超额回报说明管理层只是平庸！"))
        else:
            debate_topics.append(("🔴", "管理层能力",
                f"ROE仅{roe_val:.0f}%，资本回报连理财都不如，管理层在毁灭价值！",
                f"ROE低可能是因为行业处于资本投入期，一旦产出开始，ROE会大幅跳升！"))

    # 议题8：未来趋势（营收增速方向）
    if rev is not None:
        if rev > 15:
            debate_topics.append(("🟢", "未来趋势",
                f"营收增长{rev:.0f}%，行业景气度向上，公司正处于上升通道！",
                f"高速增长不可持续！历史上高增长公司的增速回归均值是大概率事件！"))
        elif rev > 0:
            debate_topics.append(("🟡", "未来趋势",
                f"营收稳健增长，行业格局稳定，公司确定性较高。",
                f"稳健但不性感！没有加速增长的预期，估值就没有提升空间！"))
        else:
            debate_topics.append(("🔴", "未来趋势",
                f"营收持续下滑，行业可能正在被颠覆或被替代！",
                f"营收下滑但毛利率稳住了，说明公司在主动收缩聚焦核心业务！"))

    # ── 执行多轮辩论 ──
    round_num = 1
    for severity, topic, bull_arg, bear_arg in debate_topics:
        lines.append(f"    Note over 多方,空方: \u26a1 第{round_num}回合：{topic}辩论")
        # 多方进攻
        lines.append(f"    多方->>委员会主席: {bull_arg}")
        # 空方反击
        lines.append(f"    空方->>委员会主席: {bear_arg}")
        # 多方再反驳（第二轮交锋）
        if severity == "\U0001f7e2":  # 多方占优时，多方追加攻击
            lines.append(f"    多方->>委员会主席: 你这就是无视数据！事实胜于雄辩，数字不会说谎！")
        elif severity == "\U0001f534":  # 空方占优时，空方追加攻击
            lines.append(f"    空方->>委员会主席: 你这是在赌博！历史上多少好公司死在了「这次不一样」的幻觉里！")
        else:
            lines.append(f"    多方->>委员会主席: 你太悲观了！")
            lines.append(f"    空方->>委员会主席: 你太乐观了！市场专治各种不服！")
        lines.append("")
        round_num += 1
    
    # ── 自由辩论（基于具体数据） ──
    severity_score = 0
    for severity, _, _, _ in debate_topics:
        if severity == "\U0001f7e2": severity_score += 1
        elif severity == "\U0001f534": severity_score -= 1
    
    lines.append("    Note over 多方,空方: \U0001f4a5 自由辩论")
    # 多方结案陈词（引用具体数据）
    bull_close = ""
    if roe_val is not None: bull_close = f"ROE{roe_val:.0f}%"
    if pe is not None and pe < 15: bull_close += f"+PE{pe:.0f}倍低估" if bull_close else f"PE{pe:.0f}倍低估"
    if rev is not None and rev > 0: bull_close += f"+营收增长{rev:.0f}%" if bull_close else f"营收增长{rev:.0f}%"
    if dr is not None and dr < 30: bull_close += "+零净负债"
    lines.append(f"    多方->>委员会主席: {bull_close if bull_close else '数据优势明显'}，这组数据你还要无视吗？")
    
    # 空方结案陈词（引用具体风险）
    bear_close = ""
    if roe_val is not None and roe_val < 10: bear_close = f"ROE仅{roe_val:.0f}%"
    elif dr is not None and dr > 60: bear_close = f"负债率{dr:.0f}%"
    elif rev is not None and rev < 0: bear_close = f"营收负增长{rev:.0f}%"
    elif pe is not None and pe > 30: bear_close = f"PE{pe:.0f}倍透支未来"
    else: bear_close = "你忽视了尾部风险"
    lines.append(f"    空方->>委员会主席: {bear_close}！这些风险你选择视而不见？")
    
    if len(debate_topics) >= 3:
        lines.append(f"    多方->>委员会主席: 数据不会说谎！你拿一个具体风险来反驳我的每一个论点！")
        lines.append(f"    空方->>委员会主席: 市场不是算术题！低PE可以更低，高ROE可以崩塌，你的假设全是静态的！")
    lines.append("")

    # 风控评估
    lines.append("    Note over 风控,委员会主席: \U0001f6e1\ufe0f 风控评估")
    meltdown = False
    if rev is not None and rev < -20:
        lines.append(f"    风控->>委员会主席: \U0001f534 营收暴跌{rev:.0f}%，触发熔断！")
        meltdown = True
    if dr is not None and dr > 80:
        lines.append(f"    风控->>委员会主席: \U0001f534 负债率{dr:.0f}%超80%！")
        meltdown = True
    if roe_val is not None and roe_val < 0:
        lines.append(f"    风控->>委员会主席: \U0001f534 ROE为负！")
        meltdown = True
    if pe is not None and pe > 80:
        lines.append(f"    风控->>委员会主席: \U0001f534 PE{pe:.0f}超高估！")
        meltdown = True
    if not meltdown:
        lines.append("    风控->>委员会主席: \u2705 各项指标在安全阈值内")
        lines.append("    风控->>委员会主席: \u2795 最大风险来自行业波动，可设止损控制")
    lines.append("")

    # 委员会主席裁决
    sl_price = None
    tp_price = None
    if d is not None:
        sl_price = d.stop_loss
        tp_price = d.take_profit
    
    lines.append("    Note over 委员会主席: \u2696\ufe0f 委员会主席裁决")
    score = len(pro_args) - len(con_args) - (5 if meltdown else 0)
    
    # 方向
    if score >= 2:
        direction = "\U0001f7e2 买入"
        position = "30%"
    elif score >= -1:
        direction = "\U0001f7e1 持有"
        position = "10-20%（观察仓）"
    else:
        direction = "\U0001f534 卖出/回避"
        position = "0%（清仓）"
    
    # 风控
    if sl_price and sl_price != "?":
        risk_line = f"止损 {sl_price}"
    elif dr is not None and dr > 60:
        risk_line = "止损设于MA60下方5%"
    else:
        risk_line = "止损设于入场价下方8-10%"
    
    lines.append(f"    委员会主席->>委员会主席: \U0001f4cb 多方{len(pro_args)}项 vs 空方{len(con_args)}项")
    lines.append(f"    委员会主席->>委员会主席: \U0001f3af 方向：{direction}")
    lines.append(f"    委员会主席->>委员会主席: \U0001f4ca 仓位：{position}")
    lines.append(f"    委员会主席->>委员会主席: \U0001f6e1 风控：{risk_line}")

    lines.append("```")
    return "\n".join(lines)


def _render_tech_flowchart(ch: "ChanDetail", d: "DetailItem") -> str:
    """技术面分析 → Mermaid 流程图"""
    lines = []
    lines.append("```mermaid")
    lines.append("flowchart TB")

    # 趋势子图 — MA排列（用 day_ma5 + ma60）
    ni = 0
    ma_parts = []
    for ma_name, attr in [("MA5", "day_ma5"), ("MA60", "ma60")]:
        v = getattr(ch, attr, "?")
        if v != "?" and v is not None:
            try:
                fv = float(v)
                if ch.price and ch.price != "?":
                    direction = "🔺" if float(ch.price) > fv else "🔻"
                else:
                    direction = ""
                ma_parts.append(f'n{ni}["{ma_name} {fv:.2f}{direction}"]')
                ni += 1
            except (ValueError, TypeError):
                ma_parts.append(f'n{ni}["{ma_name} {v}"]')
                ni += 1
    if ma_parts:
        ma_chain = " --> ".join(ma_parts)
        lines.append("    subgraph 趋势")
        lines.append("        direction LR")
        lines.append(f"        {ma_chain}")
        lines.append("    end")

    # 缠论子图
    chan_parts = []
    if ch.day_last_bi_dir:
        arrow = "↑" if ch.day_last_bi_dir == "up" else "↓"
        chan_parts.append(f'n{ni}["笔{arrow}"]')
        ni += 1
    if hasattr(ch, 'buy_sell_detail') and ch.buy_sell_detail:
        if "中枢" in ch.buy_sell_detail:
            chan_parts.append(f'n{ni}["中枢"]')
            ni += 1
    if ch.day_bottom_fx and ch.day_bottom_fx != "?":
        ma5_str = "✅" if getattr(ch, "day_above_ma5", False) else ""
        chan_parts.append(f'n{ni}["底{ch.day_bottom_fx}{ma5_str}"]')
        ni += 1
    if ch.day_top_fx and ch.day_top_fx != "?":
        chan_parts.append(f'n{ni}["顶{ch.day_top_fx}"]')
        ni += 1
    if chan_parts:
        lines.append("    subgraph 缠论")
        lines.append("        direction LR")
        lines.append(f"        {' --> '.join(chan_parts)}")
        lines.append("    end")

    # 价量子图
    vol_parts = []
    vr = d.vol_5d_ratio
    if vr:
        if vr > 2.0: vol_desc = f"放巨量{vr:.1f}x"
        elif vr > 1.5: vol_desc = f"放量{vr:.1f}x"
        elif vr < 0.5: vol_desc = f"缩量{vr:.1f}x"
        else: vol_desc = f"量平{vr:.1f}x"
        vol_parts.append(f'n{ni}["{vol_desc}"]')
        ni += 1
    p5 = d.pct_5d
    if p5 is not None:
        vol_parts.append(f'n{ni}["{p5:+.1f}%"]')
        ni += 1
    if vol_parts:
        lines.append("    subgraph 价量")
        lines.append("        direction LR")
        lines.append(f"        {' --> '.join(vol_parts)}")
        lines.append("    end")

    # 支撑子图
    sl = d.stop_loss
    tp = d.take_profit
    if sl and sl != "?" and tp and tp != "?":
        lines.append("    subgraph 支撑")
        lines.append("        direction LR")
        lines.append(f'        n{ni}["损{sl}"]')
        ni += 1
        lines.append(f'        n{ni}["盈{tp}"]')
        lines.append(f'        n{ni-1} --> n{ni}')
        lines.append("    end")

    lines.append("```")
    return "\n".join(lines) if len(lines) > 4 else ""
    vr = d.vol_5d_ratio
    if vr:
        if vr > 2.0: vol_desc = f"放巨量{vr:.1f}x"
        elif vr > 1.5: vol_desc = f"放量{vr:.1f}x"
        elif vr < 0.5: vol_desc = f"缩量{vr:.1f}x"
        else: vol_desc = f"量平{vr:.1f}x"
        vol_parts.append(vol_desc)
    p5 = d.pct_5d
    if p5 is not None:
        vol_parts.append(f"{p5:+.1f}%")
    if vol_parts:
        lines.append("    subgraph 价量")
        lines.append("        direction LR")
        lines.append(f"        {' --> '.join(vol_parts)}")
        lines.append("    end")

    # 支撑子图
    sl = d.stop_loss
    tp = d.take_profit
    if sl and sl != "?" and tp and tp != "?":
        lines.append("    subgraph 支撑")
        lines.append("        direction LR")
        sl_str = f"损{sl}" if isinstance(sl, (int, float)) else str(sl)
        tp_str = f"盈{tp}" if isinstance(tp, (int, float)) else str(tp)
        lines.append(f"        {sl_str} --> {tp_str}")
        lines.append("    end")

    lines.append("```")
    return "\n".join(lines) if len(lines) > 4 else ""


def _render_veto_sequence(d: "DetailItem", mirror_text: str, cl_text: str, reverse_summary: str) -> str:
    """一票否决时序图（逆向检验+镜子测试+操作建议）"""
    lines = []
    lines.append("```mermaid")
    lines.append("sequenceDiagram")
    lines.append("    participant 逆向")
    lines.append("    participant 镜子")
    lines.append("    participant 结论")
    lines.append("")

    # 逆向检验
    fb = d.fb
    lines.append("    Note over 逆向,结论: ⚠️ 芒格式逆向检验")
    if fb.reverse_test:
        for line_text in fb.reverse_test.split("\n"):
            line_s = line_text.strip()
            if line_s.startswith("|") or not line_s:
                continue
            # 去掉行首的 emoji 标记
            line_s = line_s.lstrip("☠️⚠️🏭").strip()
            if len(line_s) > 80:
                line_s = line_s[:77] + "..."
            lines.append(f"    逆向->>逆向: ☠ {line_s}")
    else:
        lines.append("    逆向->>逆向: 数据不足")
    lines.append(f"    逆向->>结论: {reverse_summary}")

    # 镜子测试（展示5个具体问题，不截断太狠）
    lines.append("")
    lines.append("    Note over 镜子,结论: 📋 镜子测试（5句话说清楚为什么买）")
    mirror_lines = [l for l in mirror_text.split("\n") if l.strip().startswith(("1.", "2.", "3.", "4.", "5."))]
    for ml in mirror_lines[:5]:
        ml_clean = ml.strip()
        if len(ml_clean) > 65:
            ml_clean = ml_clean[:62] + "..."
        lines.append(f"    镜子->>镜子: {ml_clean}")
    mirror_verdict = "✅通过" if "✅" in mirror_text else ("⚠️边缘" if "⚠️" in mirror_text else "❌未通过")
    lines.append(f"    镜子->>结论: {mirror_verdict} | {cl_text}")

    # 操作建议
    lines.append("")
    lines.append("    Note over 结论: 🎯 操作建议")
    advice = d.advice
    if "止损" in advice:
        lines.append(f"    结论->>结论: 🔴 {advice}")
    elif "持有" in advice:
        lines.append(f"    结论->>结论: ✅ {advice}")
    elif "加仓" in advice:
        lines.append(f"    结论->>结论: 🟢 {advice}")
    else:
        lines.append(f"    结论->>结论: {advice}")

    lines.append("```")
    return "\n".join(lines)


def _render_financial_timeline(fb: "FbDetail") -> str:
    """财务数据与分析 → Mermaid 时间线图"""
    metrics = [
        ("营收增速", fb.revenue_yoy, "%", True),
        ("净利增速", fb.net_profit_yoy, "%", True),
        ("ROE", fb.roe, "%", False),
        ("毛利率", fb.gross_margin, "%", False),
        ("负债率", fb.debt_ratio, "%", False),
        ("PE", fb.pe, "", False),
    ]
    has_data = any(v != "?" and v is not None for _, v, _, _ in metrics)
    if not has_data:
        return "> **数据缺失**：财务数据不足，无法生成图表"

    lines = ["```mermaid", "flowchart LR"]
    cards = []
    for i, (label, val, unit, pct_sign) in enumerate(metrics):
        if val != "?" and val is not None:
            try:
                fv = float(val)
                if label == "负债率":
                    emoji = "🟢" if fv < 60 else "🔴" if fv > 80 else "🟡"
                elif label == "PE":
                    emoji = "🟢" if 0 < fv < 15 else "🟡" if fv < 25 else "🔴"
                elif label == "ROE":
                    emoji = "🟢" if fv > 15 else "🔴"
                elif label in ("营收增速", "净利增速"):
                    emoji = "🟢" if fv > 0 else "🔴"
                else:
                    emoji = "🟢" if fv > 0 else "🔴" if fv < 0 else "🟡"
                # 节点ID+引号标签，去掉%避免Mermaid问题
                val_str = f"{fv:.1f}"
                cards.append(f'm{i}["{emoji} {label} {val_str}"]')
            except (ValueError, TypeError):
                cards.append(f'm{i}[{label} {val}]')
    if cards:
        lines.append(f"    {' --> '.join(cards)}")
    lines.append("```")
    return "\n".join(lines)


def _render_valuation_chart(fb: "FbDetail") -> str:
    """估值判断 → Mermaid 流程图"""
    pe = fb.pe
    pe_str = f"{pe}" if pe != "?" and pe is not None else "数据缺失"

    lines = ["```mermaid", "flowchart TB"]
    lines.append(f'    PE["当前PE: {pe_str}"]')
    # 判断估值区间
    if pe != "?" and pe is not None:
        try:
            pe_v = float(pe)
            if pe_v < 15:
                zone = "偏低 ✅ 有安全边际"
            elif pe_v < 25:
                zone = "合理 ➖ 安全边际一般"
            elif pe_v < 40:
                zone = "偏高 ⚠️ 需增长支撑"
            else:
                zone = "过高 🔴 极度高估"
            lines.append(f'    zone["{zone}"]')
            lines.append(f"    PE --> zone")
        except (ValueError, TypeError):
            pass
    lines.append("```")
    return "\n".join(lines)


def _render_quadrant(fb: "FbDetail") -> str:
    """基于ROE和营收增速判断四象限位置"""
    roe = _safe_float(fb.roe)
    rev = _safe_float(fb.revenue_yoy)
    pe = _safe_float(fb.pe)

    quadrant = "数据不足"
    roe_high = roe is not None and roe > 15
    roe_low = roe is not None and roe <= 15
    rev_pos = rev is not None and rev > 0
    rev_neg = rev is not None and rev <= 0

    if roe_high and rev_pos:
        quadrant = "🟢 **明星** — 高ROE+正增长，巴菲特+李录都会喜欢"
    elif roe_high and rev_neg:
        quadrant = "🟡 **现金牛** — 高ROE但增长停滞，巴菲特喜欢但李录担心"
    elif roe_low and rev_pos:
        quadrant = "🔵 **成长股** — 低ROE但高增长，需判断ROE能否提升（段永平视角）"
    elif roe_low and rev_neg:
        quadrant = "🔴 **问题股** — 低ROE+负增长，芒格会说：远离"

    lines = [f"> **四象限定位**: {quadrant}"]
    if pe is not None and pe > 0:
        if pe < 15:
            lines.append(f"> **估值判断**: PE {pe:.1f}，偏低有安全边际（巴菲特：好价格）")
        elif pe < 25:
            lines.append(f"> **估值判断**: PE {pe:.1f}，合理（巴菲特：价格一般）")
        else:
            lines.append(f"> **估值判断**: PE {pe:.1f}，偏高（段永平：好生意也要好价格）")
    return "\n".join(lines)


def _render_critique(fb: "FbDetail") -> str:
    """从现有数据生成挑刺分析内容"""
    lines = []

    # 致命缺陷：从逆向检验中提取
    if fb.reverse_test and fb.reverse_test != "数据不足":
        lines.append("**☠️ 致命风险路径**")
        for rt in fb.reverse_test.split("\n"):
            rt = rt.strip()
            if rt and not rt.startswith("|") and len(rt) > 5:
                rt_clean = rt.lstrip("☠️⚠️🏭").strip()
                if len(rt_clean) > 60:
                    rt_clean = rt_clean[:57] + "..."
                lines.append(f"- ☠ {rt_clean}")
        lines.append("")

    # 反共识压力测试：基于财务数据提问
    questions = []
    pe = fb.pe
    roe = fb.roe
    rev = fb.revenue_yoy
    net = fb.net_profit_yoy
    dr = fb.debt_ratio
    gm = fb.gross_margin

    if roe != "?" and roe is not None:
        try:
            rv = float(roe)
            if rv < 10:
                questions.append(f"ROE仅{rv:.1f}%，远低于15%及格线——低ROE是否意味着管理层资本配置能力不足？如果长期无法提升，这还是一门好生意吗？")
        except: pass
    if rev != "?" and rev is not None:
        try:
            rv = float(rev)
            if rv < 0:
                questions.append(f"营收同比{rv:+.1f}%负增长——是行业周期下行还是市场份额流失？如果是结构性衰退，当前的估值便宜是陷阱还是机会？")
            elif rv < 5:
                questions.append(f"营收仅增长{rv:.1f}%，跑不赢通胀——公司是否处于成熟期天花板？如果没有新增长曲线，未来5年营收会持续萎缩吗？")
        except: pass
    if net != "?" and net is not None:
        try:
            nv = float(net)
            if nv > 200:
                questions.append(f"净利暴增{nv:.0f}%，是否来自一次性收益或会计调整？扣非后的真实盈利能力是多少？")
        except: pass
    if dr != "?" and dr is not None:
        try:
            dv = float(dr)
            if dv > 50:
                questions.append(f"负债率{dv:.1f}%偏高——如果利率上升或盈利下滑，偿债压力会多大？极端情况下能否撑过2年不盈利？")
        except: pass
    if pe != "?" and pe is not None:
        try:
            pv = float(pe)
            if pv < 5:
                questions.append(f"PE仅{pv:.1f}——低PE是市场定价错误还是价值陷阱？是否存在资产负债表上未暴露的风险？")
            elif pv > 30:
                questions.append(f"PE高达{pv:.1f}——高估值是否已透支未来3-5年的增长？如果增速不及预期，股价可能面临戴维斯双杀")
        except: pass
    if gm != "?" and gm is not None:
        try:
            gv = float(gm)
            if gv < 20:
                questions.append(f"毛利率仅{gv:.1f}%，定价权薄弱——如果原材料成本再上涨10%，是否会侵蚀全部利润？")
        except: pass

    if questions:
        lines.append("**❓ 反共识压力测试**")
        for q in questions[:4]:
            lines.append(f"- 🤔 {q}")
        lines.append("")

    if not lines:
        lines.append("> 数据不足，无法生成挑刺分析")

    return "\n".join(lines)
    """生成 LLM 待补全的章节占位符"""
    return f"""
<!-- ===== 第{section_num}节：{title} ===== -->
> 📡 **LLM 待补全**：本节内容需联网检索后补充
> 建议搜索方向：
> - 业务线拆分与收入构成
> - 核心产品市占率与增长趋势
> - 行业竞争格局变化
> - 最新研报评级与目标价
<!-- ===== End ===== -->
"""


def _render_top10_mermaid(top10: list) -> str:
    """TOP10 推荐标的 → Mermaid 横向排名图"""
    lines = []
    lines.append("```mermaid")
    lines.append("flowchart LR")
    for t in top10[:5]:  # TOP5 展示
        sub_id = f"S{t.rank}"
        name_short = t.name[:6]
        lines.append(f"    subgraph {sub_id}_{name_short}_{t.total:.0f}点")
        lines.append("        direction TB")
        # 用箭头表示评分流向
        lines.append(f"        六维_{t.fb_w:.0f} --> 缠论_{t.ch_w:.0f} --> 热点_{t.hot_w:.0f}")
        lines.append("    end")
    if len(top10) > 5:
        lines.append(f"    S5 -->|TOP6-10略| S_end")
        lines.append(f"    S_end((...))")
    lines.append("```")
    return "\n".join(lines)


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
    fb = d.fb

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

    # 六维评分摘要
    dim_labels_short = ["生意质量", "护城河", "管理层", "最大风险", "文明趋势", "估值"]
    dim_parts = []
    for i, label in enumerate(dim_labels_short, 1):
        score = getattr(fb, f"dim{i}_score", "?")
        conf = getattr(fb, f"dim{i}_confidence", "")
        if score and score != "?":
            dim_parts.append(f"{label}{score}分")
    if dim_parts:
        lines.append(f"📊 基本面分析：{' | '.join(dim_parts)}（{fb.score_w}/60分）")

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

    # 真实资金流（近5日主力净流入）— 热点核心信号
    flow_5d = d.hot.flow_5d
    flow_1d = d.hot.flow_1d
    if isinstance(flow_5d, (int, float)) and abs(flow_5d) > 1e4:
        if isinstance(d.hot.flow_days, (int, float)) and d.hot.flow_days >= 2:
            flow_part = (f"近{int(d.hot.flow_days)}日主力净流入{flow_5d/1e8:+.2f}亿"
                         f" | 最近1日{flow_1d/1e8:+.2f}亿" if isinstance(flow_1d, (int, float)) and abs(flow_1d) > 1e4
                         else f"近{int(d.hot.flow_days)}日主力净流入{flow_5d/1e8:+.2f}亿")
        else:
            flow_part = f"今日主力净流入{flow_5d/1e8:+.2f}亿"
        parts.append(flow_part)

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
        lines.append(f"📊 六维视角：{fb_summary}")

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
        cross_validation_section=_render_cross_validation(data.get("cross_validation", [])),
        funnel_section=_render_funnel_section(data.get("funnel", {})),
        scan_label=cfg["scan_label"],
        scan_header=cfg["scan_header"],
        elim_label=cfg["elim_label"],
        elim_header=cfg["elim_header"],
        passed_label=cfg["passed_label"],
        detail_label=cfg["detail_label"],
        summary_label=cfg["summary_label"],
        summary_header=cfg["summary_header"],
        sector_rows=_render_sector_rows(model.sectors),
        elim_rows=_render_elim_rows(model.eliminated),
        vetoed_section=_render_vetoed_section(model.vetoed),
        passed_count=model.passed_count,
        top10_mermaid=_render_top10_mermaid(model.top10),
        detail_rows=_render_detail_rows(model.details, price_unit=cfg["price_unit"]),
        summary_rows=_render_summary_rows(model.summary),
        timing_rows=_render_timing_rows(model.details, price_unit=cfg["price_unit"]),
        portfolio_timing_rows=_render_portfolio_timing(
            [PortfolioTimingItem(**h) for h in data.get("portfolio_timing", [])],
            price_unit=cfg["price_unit"],
        ) if data.get("portfolio_timing") else "",
    )
