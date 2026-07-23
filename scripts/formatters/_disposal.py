"""
阶段 4：处置决策格式化器。
对应 SKILL.md 中「阶段 4：处置决策（Disposal）」模板。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field

from ._base import FormatValidationError, _validate, _format_num, _sign_pct


# ── Pydantic 模型 ───────────────────────────────────────────

class CurrentState(BaseModel):
    """当前持仓状态"""
    shares: Optional[int] = Field(None, description="持仓量(股)")
    cost: Optional[float] = Field(None, description="持仓成本")
    price: Optional[float] = Field(None, description="现价")
    total_profit: Optional[float] = Field(None, description="浮动盈亏")
    profit_pct: Optional[float] = Field(None, description="盈亏百分比")
    position_pct: Optional[float] = Field(None, description="仓位占比(%)")
    sector_pct: Optional[float] = Field(None, description="板块配置占比(%)")


class PlanOption(BaseModel):
    """处置方案选项"""
    operation: str = Field(..., description="操作描述")
    impact: str = Field(..., description="预估影响")
    recommended: str = Field(..., description="是否推荐")


class PlanComparison(BaseModel):
    """处置方案对比"""
    a_one_shot: PlanOption = Field(..., description="A: 一次性清仓")
    b_batch: PlanOption = Field(..., description="B: 分批退出")
    c_reduce: PlanOption = Field(..., description="C: 减仓不空仓")
    d_swap: PlanOption = Field(..., description="D: 转仓")


class ExecutionPlan(BaseModel):
    """执行计划"""
    method: str = Field(..., description="方式: 市价/限价/条件单")
    deadline: str = Field(..., description="时限: 立即/本日/本周/两周内")
    batch_details: Optional[str] = Field(None, description="分批明细")


class DisposalData(BaseModel):
    """处置决策完整数据"""
    code: str
    name: str
    date: str
    reason: str = Field(..., description="处置原因")
    state: CurrentState
    plans: PlanComparison
    execution: ExecutionPlan
    reallocation: Optional[str] = Field(None, description="赎回资金再配置建议")
    lesson: Optional[str] = Field(None, description="经验记录")


# ── 渲染 ────────────────────────────────────────────────────

def _plan_row(label: str, plan: PlanOption) -> str:
    return f"| {label} | {plan.operation} | {plan.impact} | {plan.recommended} |"


def format_disposal(data: dict[str, Any] | str) -> str:
    """校验 + 渲染处置决策报告。"""
    if isinstance(data, str):
        data = json.loads(data)
    m = _validate(DisposalData, data)
    s = m.state
    p = m.plans
    ex = m.execution

    batch_line = (f"- **分批明细**: {ex.batch_details}" if ex.batch_details else "")

    return f"""\
## 处置方案 | {m.name}（{m.code}）— {m.date}

### 处置原因

{m.reason}

### 当前状态

| 指标 | 值 |
|------|----|
| 持仓量 | {_format_num(s.shares)} 股 |
| 持仓成本 | {_format_num(s.cost)} |
| 现价 | {_format_num(s.price)} |
| 浮动盈亏 | {_format_num(s.total_profit)}（{_sign_pct(s.profit_pct)}%） |
| 仓位占比 | {_format_num(s.position_pct)}% |
| 板块配置占比 | {_format_num(s.sector_pct)}% |

### 处置方案对比

| 方案 | 操作 | 预估影响 | 建议 |
|------|------|---------|------|
{_plan_row("A: 一次性清仓", p.a_one_shot)}
{_plan_row("B: 分批退出", p.b_batch)}
{_plan_row("C: 减仓不空仓", p.c_reduce)}
{_plan_row("D: 转仓", p.d_swap)}

### 执行计划

- **方式**: {ex.method}
- **时限**: {ex.deadline}
{batch_line}

### 赎回资金再配置建议

{_format_num(m.reallocation)}

	### 经验记录
	
	{_format_num(m.lesson)}
	
	> 📡 **数据来源**: 行情数据来自腾讯/新浪，基本面数据来自东财/Yahoo。
	"""
