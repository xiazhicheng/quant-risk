"""
阶段 2：持仓监控格式化器。
对应 SKILL.md 中「阶段 2：持仓监控（Holding）」模板。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field

from ._base import FormatValidationError, _validate, _format_num, _sign_pct


# ── Pydantic 模型 ───────────────────────────────────────────

class ChangePair(BaseModel):
    """前后对比对"""
    old: Any = Field(..., description="上次值")
    new: Any = Field(..., description="本次值")
    change: str = Field(..., description="变化方向")


class HoldingPosition(BaseModel):
    """当前持仓"""
    cost: Optional[float] = Field(None, description="持仓成本")
    current_price: Optional[float] = Field(None, description="当前价格")
    profit_loss: Optional[float] = Field(None, description="浮动盈亏")
    profit_pct: Optional[float] = Field(None, description="涨跌幅")
    position_pct: Optional[float] = Field(None, description="仓位占比(%)")
    max_limit: Optional[float] = Field(None, description="风控允许上限(%)")
    days: Optional[int] = Field(None, description="持仓天数")


class RiskTracking(BaseModel):
    """风险变化追踪"""
    pe: ChangePair
    dist_to_stop: ChangePair
    amount_trend: ChangePair
    outlook: ChangePair


class HotTracking(BaseModel):
    """热点变化追踪"""
    sector: ChangePair
    rel_to_market: ChangePair
    catalyst: ChangePair


class ExitCheck(BaseModel):
    """离场条件单项检查"""
    status: str = Field(..., description="安全/逼近/已触发 / 未到/接近/已触发")
    action: str = Field(..., description="操作提示")


class ExitConditions(BaseModel):
    """离场条件检查"""
    stop_loss: ExitCheck
    take_profit: ExitCheck
    profit_protection: ExitCheck
    fb_alert: ExitCheck


class ActionSuggestion(BaseModel):
    """操作建议"""
    hold_reason: Optional[str] = Field(None, description="继续持有理由")
    reduce_to: Optional[float] = Field(None, description="减仓至(%)")
    increase_to: Optional[float] = Field(None, description="增持至(%)")
    clear_condition: Optional[str] = Field(None, description="清仓触发条件")


class HoldingData(BaseModel):
    """持仓监控完整数据"""
    code: str
    name: str
    date: str
    position: HoldingPosition
    risk: RiskTracking
    hot: HotTracking
    exit: ExitConditions
    action: ActionSuggestion
    verdict: str = Field(..., description="结论: 持有/减仓/增持/清仓")
    next_observation: str = Field(..., description="下一步观察点")


# ── 渲染 ────────────────────────────────────────────────────

def _change_row(label: str, pair: ChangePair) -> str:
    return (f"| {label} | {_format_num(pair.old)} | {_format_num(pair.new)} | {pair.change} |")


def format_holding(data: dict[str, Any] | str) -> str:
    """校验 + 渲染持仓监控报告。"""
    if isinstance(data, str):
        data = json.loads(data)
    m = _validate(HoldingData, data)
    p = m.position
    r = m.risk
    h = m.hot
    e = m.exit
    a = m.action

    return f"""\
## 持仓风控检查 | {m.name}（{m.code}）— {m.date}

### 当前持仓

| 指标 | 值 |
|------|----|
| 持仓成本 | {_format_num(p.cost)} |
| 当前价格 | {_format_num(p.current_price)} |
| 浮动盈亏 | {_format_num(p.profit_loss)}（{_sign_pct(p.profit_pct)}%） |
| 当前仓位占比 | {_format_num(p.position_pct)}% |
| 风控允许上限 | {_format_num(p.max_limit)}% |
| 持仓天数 | {_format_num(p.days)} |

### 风险变化追踪

| 检查项 | 上次 | 本次 | 变化方向 |
|--------|------|------|---------|
{_change_row("PE", r.pe)}
{_change_row("价格距止损位", r.dist_to_stop)}
{_change_row("成交额趋势", r.amount_trend)}
{_change_row("行业景气度", r.outlook)}

### 热点变化追踪

| 检查项 | 上次 | 本次 | 变化方向 |
|--------|------|------|---------|
{_change_row("所属热点板块", h.sector)}
{_change_row("板块相对大盘", h.rel_to_market)}
{_change_row("近期催化剂", h.catalyst)}

### 离场条件检查

| 条件 | 状态 | 操作 |
|------|------|------|
| 未触发止损 | {e.stop_loss.status} | {e.stop_loss.action} |
| 未触发止盈 | {e.take_profit.status} | {e.take_profit.action} |
| 盈利保护线 | {e.profit_protection.status} | {e.profit_protection.action} |
| 基本面预警 | {e.fb_alert.status} | {e.fb_alert.action} |

### 操作建议

| 选项 | 建议 |
|------|------|
| 继续持有 | {_format_num(a.hold_reason)} |
| 减仓至 | {_format_num(a.reduce_to)}%（原为 {_format_num(p.position_pct)}%） |
| 增持至 | {_format_num(a.increase_to)}%（如适用） |
| 清仓离场 | {_format_num(a.clear_condition)} |

**结论**: {m.verdict}

**下一步观察点**: {m.next_observation}
"""
