"""
阶段 1：投前审查格式化器。
对应 SKILL.md 中「阶段 1：投前审查（Pre-trade）」模板。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field

from ._base import FormatValidationError, _validate, _format_num, _sign_pct


# ── Pydantic 模型 ───────────────────────────────────────────

class ChanTech(BaseModel):
    """缠论技术面数据"""
    trend_type: str = Field(..., description="走势类型: 趋势/盘整/单边")
    zhongshu_count: int = Field(..., ge=0, description="中枢数量")
    zj: Optional[float] = Field(None, description="中枢下沿")
    zg: Optional[float] = Field(None, description="中枢上沿")
    position: str = Field(..., description="相对中枢位置: 上方/内部/下方")
    distance_pct: Optional[float] = Field(None, description="距中枢百分比")
    top_fx: int = Field(..., ge=0, description="顶分型数量")
    bottom_fx: int = Field(..., ge=0, description="底分型数量")
    bi_count: int = Field(..., ge=0, description="笔数量")
    last_bi_dir: str = Field(..., description="最近一笔方向")
    back_chi: str = Field(..., description="背驰信号: 无/顶背驰(强/弱)/底背驰(强/弱)")
    signal: str = Field(..., description="买卖点信号")
    chan_score: int = Field(..., ge=1, le=5, description="缠论评分")
    chan_verdict: str = Field(..., description="缠论结论: 偏多/中性/偏空")


class FbDimension(BaseModel):
    """基本面单维度评分"""
    score: int = Field(..., ge=1, le=5)
    reason: str = Field(..., description="评分依据")


class FbScore(BaseModel):
    """基本面五维评分"""
    industry_outlook: FbDimension
    competitive: FbDimension
    profitability: FbDimension
    financial_health: FbDimension
    growth: FbDimension


class HotMatch(BaseModel):
    """热点匹配数据"""
    sector: str
    in_mainstream: str = Field(..., description="是否处于主线: 是/否")
    catalyst: str
    rotation_position: str = Field(..., description="领涨/跟涨/补涨/退潮")


class ThreeDAssessment(BaseModel):
    """三维综合评估"""
    hot_score: int = Field(..., ge=1, le=5)
    hot_dir: str = Field(..., description="向上/平稳/向下")
    fb_score: int = Field(..., ge=1, le=5)
    fb_dir: str = Field(..., description="向上/平稳/向下")
    ch_score: int = Field(..., ge=1, le=5)
    ch_dir: str = Field(..., description="偏多/中性/偏空")
    overall: str = Field(..., description="三维共振/分歧判断")


class PreTradeData(BaseModel):
    """投前审查完整数据"""
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票中文名")
    date: str = Field(..., description="报告日期")
    price: float = Field(..., description="现价")
    change_pct: float = Field(..., description="涨跌幅")
    pe: Optional[float] = Field(None, description="PE")
    mcap: Optional[float] = Field(None, description="市值(亿)")
    amount: Optional[float] = Field(None, description="成交额")
    turnover: Optional[float] = Field(None, description="换手率(%)")
    industry: str = Field(..., description="行业")
    support: Optional[float] = Field(None, description="支撑位")
    resistance: Optional[float] = Field(None, description="压力位")

    chan: ChanTech
    fb: FbScore
    risk_level: str = Field(..., description="综合风险等级: 低/中/较高/高")
    hot: HotMatch
    three_d: ThreeDAssessment
    max_position: Optional[float] = Field(None, description="建议仓位上限(%)")
    stop_loss: Optional[float] = Field(None, description="止损触发价")
    stop_loss_pct: Optional[float] = Field(None, description="止损百分比")
    tp1: Optional[float] = Field(None, description="止盈一档")
    tp1_pct: Optional[float] = Field(None, description="止盈一档百分比")
    tp2: Optional[float] = Field(None, description="止盈二档")
    tp2_pct: Optional[float] = Field(None, description="止盈二档百分比")
    holding_period: str = Field(..., description="持仓周期: 短期/中期/长期")
    max_drawdown: Optional[float] = Field(None, description="最大容忍回撤(%)")

    verdict: str = Field(..., description="审查结论: 买入/观望/拒绝")
    reason: str = Field(..., description="核心理由")
    avoid_conditions: str = Field(..., description="必须回避的条件")


# ── 渲染 ────────────────────────────────────────────────────

def _fb_star(score: int) -> str:
    return "★★★" if score >= 4 else ("★★" if score == 3 else "★")


def _fb_verdict_row(dim: FbDimension) -> str:
    """返回 评分|依据，不含行首管道符"""
    return f"**{dim.score}/5** | {dim.reason}"


def format_pretrade(data: dict[str, Any] | str) -> str:
    """校验 + 渲染投前审查报告。"""
    if isinstance(data, str):
        data = json.loads(data)
    m = _validate(PreTradeData, data)

    chan = m.chan
    fb = m.fb
    hot = m.hot
    td = m.three_d

    return f"""\
## 投前风控审查 | {m.name}（{m.code}）— {m.date}

### 基本信息

| 指标 | 值 |
|------|----|
| 现价/涨跌幅 | {m.price} / {_sign_pct(m.change_pct)}% |
| PE/市值 | {_format_num(m.pe)} / {_format_num(m.mcap)}亿 |
| 成交额/换手率 | {_format_num(m.amount)} / {_format_num(m.turnover)}% |
| 行业 | {m.industry} |
| 支撑/压力 | {_format_num(m.support)} / {_format_num(m.resistance)} |

### 缠论技术面

| 指标 | 值 |
|------|----|
| 走势类型 | {chan.trend_type}（{chan.zhongshu_count} 个中枢） |
| 最近中枢区间 | [{_format_num(chan.zj)} – {_format_num(chan.zg)}] |
| 当前相对中枢位置 | {chan.position}（距中枢 {_format_num(chan.distance_pct)}%） |
| 分型数量 | {chan.top_fx} 顶 / {chan.bottom_fx} 底 |
| 笔数量 | {chan.bi_count} 笔（最近一笔方向: {chan.last_bi_dir}） |
| 背驰信号 | {chan.back_chi} |
| 买卖点信号 | {chan.signal} |
| 缠论评分 | {chan.chan_score}（{chan.chan_verdict}） |

### 基本面评分

| 维度 | 评分(1-5) | 得分依据 |
|------|----------|---------|
| 行业景气度 | {_fb_verdict_row(fb.industry_outlook)}
| 竞争格局 | {_fb_verdict_row(fb.competitive)}
| 盈利质量 | {_fb_verdict_row(fb.profitability)}
| 财务健康 | {_fb_verdict_row(fb.financial_health)}
| 成长性 | {_fb_verdict_row(fb.growth)}

**综合风险等级**: {m.risk_level}

### 当前热点匹配

| 检查项 | 状态 |
|--------|------|
| 所属热点板块 | {hot.sector} |
| 是否处于当前主线 | {hot.in_mainstream} |
| 近期催化剂 | {hot.catalyst} |
| 板块轮动位置 | {hot.rotation_position} |

### 三维度综合评估

| 维度 | 评分 | 方向 |
|------|------|------|
| 🔥 热点 | {_fb_star(td.hot_score)} | {td.hot_dir} |
| 📊 基本面 | {_fb_star(td.fb_score)} | {td.fb_dir} |
| 🔧 缠论 | {_fb_star(td.ch_score)} | {td.ch_dir} |

**综合**: {td.overall}

### 预设风控参数

| 参数 | 值 |
|------|----|
| 建议仓位上限 | {_format_num(m.max_position)}% |
| 止损触发价 | {_format_num(m.stop_loss)}（-{_format_num(m.stop_loss_pct)}%，跌破则离场） |
| 止盈触发价（一档） | {_format_num(m.tp1)}（+{_format_num(m.tp1_pct)}%，减半仓） |
| 止盈触发价（二档） | {_format_num(m.tp2)}（+{_format_num(m.tp2_pct)}%，清仓） |
| 持仓周期建议 | {m.holding_period} |
| 最大容忍回撤 | {_format_num(m.max_drawdown)}% |

### 审查结论

| 维度 | 结论 |
|------|------|
| 风控结论 | **{m.verdict}** |
| 核心理由 | {m.reason} |
| 必须回避的条件 | {m.avoid_conditions} |
"""
