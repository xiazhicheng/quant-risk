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


class Top10Item(BaseModel):
    rank: int = Field(..., ge=1, le=10, description="排名")
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    sector: str = Field(..., description="板块")
    fb: int = Field(..., ge=1, le=5, description="基本面评分 1-5")
    hot: int = Field(..., ge=1, le=5, description="热点评分 1-5")
    ch: int = Field(..., ge=1, le=5, description="缠论评分 1-5")
    total: int = Field(..., ge=0, le=50, description="总分")
    advice: str = Field(..., description="建议")


class FbDetail(BaseModel):
    score: int = Field(..., ge=1, le=5)
    pe: Any = Field(default="?", description="PE")
    revenue_yoy: Any = Field(default="?", description="营收增速")
    net_profit_yoy: Any = Field(default="?", description="净利增速")
    roe: Any = Field(default="?", description="ROE")
    gross_margin: Any = Field(default="?", description="毛利率")
    debt_ratio: Any = Field(default="?", description="负债率")


class HotDetail(BaseModel):
    score: int = Field(..., ge=1, le=5)
    desc: str = Field(..., description="热点描述")


class ChanDetail(BaseModel):
    score: int = Field(..., ge=1, le=5)
    ma60: Any = Field(default="?", description="MA60")
    price: Any = Field(default="?", description="现价")
    macd_hist: Any = Field(default="?", description="MACD柱")
    signal: str = Field(default="", description="信号")


class DetailItem(BaseModel):
    rank: int = Field(..., ge=1)
    code: str
    name: str
    price: Any = Field(default="?")
    pct: Any = Field(default="?", description="涨跌幅")
    advice: str
    stop_loss: Any
    fb: FbDetail
    hot: HotDetail
    ch: ChanDetail


class SummaryItem(BaseModel):
    code: str
    advice: str
    buy: Any
    stop_loss: Any
    take_profit: Any


class SelectionReport(BaseModel):
    """选股推荐报告完整数据模型。"""
    date: str = Field(..., description="报告日期，格式 YYYY-MM-DD")
    sectors: list[SectorItem] = Field(..., min_length=1, description="板块扫描数据")
    eliminated: list[EliminatedItem] = Field(default_factory=list, description="被剔除标的")
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


# ── 模板 ────────────────────────────────────────────────────

SECTOR_ORDER = [
    "互联网/IT", "金融/保险/券商", "能源/资源/矿业", "通信/运营商",
    "消费/食品/零售", "医药/生物科技", "制造/工业/半导体", "公用事业/基建/交运",
]

FB_VERDICT = {
    5: "基本面优秀。", 4: "基本面良好。", 3: "基本面稳健。",
    2: "基本面需关注。", 1: "基本面较差。",
}

CHAN_VERDICT = {
    5: "结构最佳", 4: "结构向好", 3: "结构中性",
    2: "结构需谨慎", 1: "结构偏空",
}

TEMPLATE = """\
## 港股选股推荐 | {date}

### ① 全市场扫描（8 板块）

| 板块 | 扫描只数 | 今日表现 |
|------|:-------:|---------|
{sector_rows}

### ② 中观过滤（剔除明细）

| 剔除标的 | 原因 |
|---------|------|
{elim_rows}

候选池 {passed_count} 只通过过滤。

### ③ 三维评分 TOP10

| 排名 | 标的 | 板块 | 基本面(×5) | 热点(×3) | 缠论(×2) | 总分 | 建议 |
|:----:|------|:----:|:----------:|:--------:|:--------:|:----:|------|
{top10_rows}

### ⭐ 各股详细分析

{detail_rows}

### 综合建议

| 标的 | 建议 | 入场区间 | 止损 | 目标 |
|:----|:----:|:--------:|:----:|:----:|
{summary_rows}

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


def _render_top10_rows(top10: list[Top10Item]) -> str:
    return "\n".join(
        f"| ⭐{t.rank} | **{t.code} {t.name}** | {t.sector} | {t.fb} | {t.hot} | {t.ch} | "
        f"**{t.total}** | {t.advice} |"
        for t in top10
    )


def _render_detail_block(d: DetailItem) -> str:
    pct = d.pct
    sign = "+" if isinstance(pct, (int, float)) and pct >= 0 else ""
    pct_str = f"{sign}{pct}" if isinstance(pct, (int, float)) else str(pct)

    fb = d.fb
    hot = d.hot
    ch = d.ch

    fb_desc = FB_VERDICT.get(fb.score, "基本面稳健。")
    ch_desc = CHAN_VERDICT.get(ch.score, "结构中性。")

    return f"""\
#### {d.rank}. {d.name}（{d.code}）— {d.price} 港元 | {pct_str}%

| 维度 | 评分 | 依据 |
|:----:|:----:|------|
| 📊 **基本面** | **{fb.score}/5** | PE={fb.pe} / 营收={fb.revenue_yoy}% / 净利={fb.net_profit_yoy}% / ROE={fb.roe}% / 毛利率={fb.gross_margin}% / 负债率={fb.debt_ratio}%。{fb_desc} |
| 🔥 **热点** | **{hot.score}/5** | {hot.desc} |
| 🔧 **缠论** | **{ch.score}/5** | MA60={ch.ma60} / 现价={ch.price} / MACD柱={ch.macd_hist} / {ch.signal}。{ch_desc} |

**建议**：{d.advice}。止损 {d.stop_loss}。
"""


def _render_detail_rows(details: list[DetailItem]) -> str:
    return "\n".join(_render_detail_block(d) for d in details)


def _render_summary_rows(summary: list[SummaryItem]) -> str:
    return "\n".join(
        f"| {s.code} | {s.advice} | {s.buy} | {s.stop_loss} | {s.take_profit} |"
        for s in summary
    )


# ── 主入口 ───────────────────────────────────────────────────

def format_output(data: dict[str, Any] | str) -> str:
    """
    校验 + 渲染裸数据，返回标准 markdown 报告。

    调用方使用模式：
        try:
            report = format_output(raw_data)
        except FormatValidationError as e:
            llm_retry(e.message)   # 把错误信息传给 LLM 修正
    """
    if isinstance(data, str):
        data = json.loads(data)

    model: SelectionReport = validate(data)

    return TEMPLATE.format(
        date=model.date,
        sector_rows=_render_sector_rows(model.sectors),
        elim_rows=_render_elim_rows(model.eliminated),
        passed_count=model.passed_count,
        top10_rows=_render_top10_rows(model.top10),
        detail_rows=_render_detail_rows(model.details),
        summary_rows=_render_summary_rows(model.summary),
    )
