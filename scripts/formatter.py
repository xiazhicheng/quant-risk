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
"score_header": "| 排名 | 标的 | 板块 | 📊六维评分(60分) | 技术面(40分) | 总分(100分) | 建议 |\n|:----:|------|:----:|:----------:|:----------:|:-----:|------|",
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
	        "score_header": "| 排名 | 标的 | 板块 | 📊六维评分(60分) | 技术面(40分) | 总分(100分) | 建议 |\n|:----:|------|:----:|:----------:|:----------:|:-----:|------|",
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
        "score_header": "| Rank | Stock | Sector | 6D Score(60pt) | Technical(40pt) | Total(100pt) | Advice |\n|:----:|------|:----:|:---------------:|:--------------:|:-----:|------|",
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

### TOP10 推荐标的（六维评分）

{score_header}
{top10_rows}

### 各股分析（六维评分）

{detail_rows}

---

## 定价与择时

### 定价建议

{summary_header}
{summary_rows}

### 择时判断（六维评分 + 技术面择时）

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
	
	> 📡 **数据来源**: 六维评分数据来自东财/Yahoo，行情/技术面来自腾讯/新浪/Yahoo，缠论K线来自腾讯/新浪。多源数据存在差异时已在交叉验证段标注。
	
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
        f"| 第四层 | 四大师评分排名 → 终选 | 3-10 | — |\n"
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
        f"| ⭐{t.rank} | **{t.code} {t.name}** | {t.sector} | {t.fb_w:.1f} | {t.hot_w + t.ch_w:.1f} | "
        f"**{t.total:.1f}** | {t.advice} |"
        for t in top10
    )


def _calc_pct_change(price, stop_loss):
    """计算止损相对当前价的百分比变化"""
    if isinstance(price, (int, float)) and isinstance(stop_loss, (int, float)) and price:
        return (stop_loss - price) / price * 100
    return 0.0


def _render_conflict_analysis(
    dyp_v: str, buffett_v: str, munger_v: str, lilu_v: str,
    dyp_s: float, buffett_s: float, munger_s: float, lilu_s: float,
) -> Tuple[str, str]:
    """基于四大师独立裁决生成对抗分析 + 投票制合成结论。

    Args:
        dyp_v/buffett_v/munger_v/lilu_v: 裁决文本（✅ 通过/⚠️ 有条件通过/❓ 灰色地带/❌ 不通过）
        dyp_s/buffett_s/munger_s/lilu_s: 评分（1-5）

    Returns:
        (conflict_text, synthesis_text)
    """
    # 映射裁决为计分
    verdict_map = {
        "✅ 通过": 2,
        "⚠️ 有条件通过": 1,
        "❓ 灰色地带": 0,
        "❌ 不通过": -1,
    }
    names = [
        ("🏢 段永平", dyp_v, dyp_s, "商业模式"),
        ("🛡️ 巴菲特", buffett_v, buffett_s, "护城河/估值"),
        ("⚠️ 芒格", munger_v, munger_s, "逆向风险"),
        ("🔭 李录", lilu_v, lilu_s, "长期确定性"),
    ]

    # 统计投票
    votes = []
    for name, verdict, score, _ in names:
        v = verdict_map.get(verdict, 0)
        votes.append((name, verdict, v))

    passed = sum(1 for _, _, v in votes if v >= 2)
    cond_passed = sum(1 for _, _, v in votes if v == 1)
    grey = sum(1 for _, _, v in votes if v == 0)
    failed = sum(1 for _, _, v in votes if v < 0)

    # 生成对抗文本
    conflict_lines = []
    dyp_name = names[0][0]
    buffett_name = names[1][0]
    munger_name = names[2][0]
    lilu_name = names[3][0]

    # 找出通过和不通过的
    passed_names = [n for n, _, v in votes if v >= 2]
    cond_names = [n for n, _, v in votes if v == 1]
    failed_names = [n for n, _, v in votes if v < 0]
    grey_names = [n for n, _, v in votes if v == 0]

    if passed_names and failed_names:
        conflict_lines.append(
            f"{'、'.join(passed_names)}通过，但{'、'.join(failed_names)}不通过——存在根本性分歧"
        )
    if passed_names and cond_names:
        conflict_lines.append(
            f"{'、'.join(passed_names)}通过，{'、'.join(cond_names)}有条件通过"
        )
    if passed_names and not failed_names and not cond_names:
        conflict_lines.append(f"{'、'.join(passed_names)}一致通过，无分歧")
    if cond_names and not passed_names and not failed_names:
        conflict_lines.append(f"全部为有条件通过，需逐个确认条件是否满足")

    # 特定大师对抗模式
    dyp_vote = verdict_map.get(dyp_v, 0)
    buffett_vote = verdict_map.get(buffett_v, 0)
    munger_vote = verdict_map.get(munger_v, 0)
    lilu_vote = verdict_map.get(lilu_v, 0)

    if dyp_vote >= 2 and buffett_vote < 0:
        conflict_lines.append("段永平看好商业模式，但巴菲特认为估值偏贵——好生意≠好价格")
    elif dyp_vote < 0 and buffett_vote >= 2:
        conflict_lines.append("巴菲特认为估值便宜，但段永平对生意质量有保留——便宜≠好生意")

    if dyp_vote >= 2 and munger_vote <= 0:
        conflict_lines.append("段永平认可生意质量，但芒格认为风险不可忽视——增长vs风险的对抗")
    elif dyp_vote <= 0 and munger_vote >= 2:
        conflict_lines.append("芒格认为风险可控，但段永平对商业模式存疑")

    if buffett_vote >= 2 and munger_vote <= 0:
        conflict_lines.append("巴菲特认为估值有安全边际，但芒格提示风险")
    elif buffett_vote < 0 and munger_vote >= 2:
        conflict_lines.append("芒格判定风险低，但巴菲特认为估值缺乏安全边际")

    if lilu_vote >= 2 and buffett_vote < 0:
        conflict_lines.append("李录看好长期确定性，但巴菲特认为当前价格不具吸引力——长期vs短期的视角冲突")

    conflict_text = "；".join(conflict_lines) if conflict_lines else "四大师视角存在一定分歧，需结合自身风险偏好判断"

    # 生成合成结论
    synthesis = _render_synthesis(passed, cond_passed, grey, failed)

    return conflict_text, synthesis


def _render_synthesis(passed: int, cond_passed: int, grey: int, failed: int) -> str:
    """基于投票结果生成合成结论"""
    # 加权计分：通过=2, 有条件通过=1, 灰色地带=0, 不通过=-1
    total_score = passed * 2 + cond_passed * 1 + grey * 0 + failed * (-1)
    max_score = 8  # 4×2

    if total_score >= 6:
        return f"✅ 强烈推荐（{passed}/4大师通过，大师共识度高）"
    elif total_score >= 4:
        return f"✅ 推荐（{passed}/4大师通过，偏向买入）"
    elif total_score >= 2:
        extra = ""
        if cond_passed > 0:
            extra = f"，{cond_passed}位有条件通过需确认"
        return f"⚠️ 灰色地带（{passed}/4大师通过{extra}，分歧明显需谨慎）"
    elif total_score >= 0:
        return f"❌ 不推荐（{passed}/4大师通过，多数派反对）"
    else:
        return f"❌ 回避（{failed}/4大师不通过，无人认可）"


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


def _render_detail_block(d: DetailItem, price_unit: str = "港元") -> str:
    pct = d.pct
    sign = "+" if isinstance(pct, (int, float)) and pct >= 0 else ""
    pct_str = f"{sign}{pct}" if isinstance(pct, (int, float)) else str(pct)

    fb = d.fb
    hot = d.hot
    ch = d.ch

    sl_pct = _calc_pct_change(d.price, d.stop_loss)

    # ── 六维评分表 ──
    dim_labels = [
        ("生意质量", "段永平"),
        ("护城河", "巴菲特"),
        ("管理层", "段永平+巴菲特"),
        ("最大风险", "芒格"),
        ("文明趋势", "李录"),
        ("估值", "巴菲特+段永平"),
    ]
    dim_rows = []
    for i, (label, master) in enumerate(dim_labels, 1):
        score = getattr(fb, f"dim{i}_score", "?")
        conclusion = getattr(fb, f"dim{i}_conclusion", "")
        confidence = getattr(fb, f"dim{i}_confidence", "")
        debug = getattr(fb, f"dim{i}_debug", "")
        if score and score != "?":
            dim_rows.append(
                f"| {label}（{master}） | {conclusion} | {confidence} |"
            )
        else:
            dim_rows.append(
                f"| {label}（{master}） | 数据不足 | — |"
            )
    dim_table = "\n".join(dim_rows) if dim_rows else "数据不足"

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
#### {d.rank}. {d.name}（{d.code}）— {d.advice} ✅ | 总分 {d.total}/100 | 📊六维评分 {fb.score_w}/60
{ir_desc} 关键指标：{fb_summary}

**📊 六维评分**

| 维度 | 结论 | 信心度 |
|:----|:----|:------:|
{dim_table}
{disclaimer_text}
**🔧 技术面 {round(hot.score_w + ch.score_w, 1)}/40** → {timing_verdict}
| 维度 | 信号 | 数值 |
|:----|:----|:----:|
{tech_table}

📋 镜子测试 {mirror_summary} | 六关 {cl_text}{(' | ⚠️芒格式逆向检验 ' + reverse_summary) if reverse_summary else ''}

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
        lines.append(f"📊 六维评分：{' | '.join(dim_parts)}（{fb.score_w}/60分）")

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
        lines.append(f"🏢 四大师视角：{fb_summary}")

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
