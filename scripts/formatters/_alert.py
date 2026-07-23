"""
阶段 3：预警触发格式化器。
对应 SKILL.md 中「阶段 3：预警触发（Alert）」模板。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field

from ._base import FormatValidationError, _validate, _format_num, _sign_pct


# ── Pydantic 模型 ───────────────────────────────────────────

class TriggerDetails(BaseModel):
    """触发详情"""
    price: Optional[float] = Field(None, description="当前价格")
    change_pct: Optional[float] = Field(None, description="较入场涨跌幅")
    trigger_value: Optional[float] = Field(None, description="触发条件值")
    threshold: Optional[float] = Field(None, description="预设风控线")
    deviation: Optional[str] = Field(None, description="偏离幅度（可读字符串，如 -2.1%）")
    time: Optional[str] = Field(None, description="触发时间")


class EmergencyCheck(BaseModel):
    """紧急基本面检查"""
    latest_report_date: Optional[str] = Field(None, description="最新财报日期")
    unexpected_negative: str = Field(..., description="是否有未预期利空: 是/否（描述）")
    industry_risk: str = Field(..., description="行业系统性风险: 是/否")
    volume_abnormal: str = Field(..., description="成交量状态: 放量/缩量/正常")
    volume_ratio: Optional[str] = Field(None, description="较日均倍数（如 0.5x / 2.1）")


class DisposalOption(BaseModel):
    """处置选项"""
    recommended: str = Field(..., description="是否建议: 是/否")
    reason: str = Field(..., description="理由")
    detail: Optional[str] = Field(None, description="补充说明（如减至 x%）")


class DisposalSuggestions(BaseModel):
    """处置建议"""
    stop_loss: DisposalOption
    partial_reduce: DisposalOption
    hold_observe: DisposalOption
    reverse_add: DisposalOption


class AlertData(BaseModel):
    """预警触发完整数据"""
    code: str
    name: str
    date: str
    trigger_type: str = Field(..., description="触发条件类型")
    details: TriggerDetails
    emergency: EmergencyCheck
    disposal: DisposalSuggestions
    verdict: str = Field(..., description="结论: 立即止损/减仓观望/持有观察/加仓")
    priority: str = Field(..., description="执行优先级: 高/中/低")
    execution_timing: str = Field(..., description="建议执行时限: 立即/本日/本周")


# ── 渲染 ────────────────────────────────────────────────────

def format_alert(data: dict[str, Any] | str) -> str:
    """校验 + 渲染预警触发报告。"""
    if isinstance(data, str):
        data = json.loads(data)
    m = _validate(AlertData, data)
    d = m.details
    e = m.emergency
    ds = m.disposal

    return f"""\
## ⚠ 风控预警 | {m.name}（{m.code}）— {m.date}

### 触发条件

{m.trigger_type}

### 触发详情

| 指标 | 值 |
|------|----|
| 当前价格 | {_format_num(d.price)}（较入场 {_sign_pct(d.change_pct)}%） |
| 触发条件值 | {_format_num(d.trigger_value)} |
| 预设风控线 | {_format_num(d.threshold)} |
| 偏离幅度 | {_format_num(d.deviation)} |
| 时间 | {_format_num(d.time)} |

### 紧急基本面检查

| 检查项 | 状态 |
|--------|------|
| 最新财报日期 | {_format_num(e.latest_report_date)} |
| 近期是否有未预期利空 | {e.unexpected_negative} |
| 行业是否有系统性风险 | {e.industry_risk} |
| 成交量是否异常 | {e.volume_abnormal}（较日均 {_format_num(e.volume_ratio)}） |

### 处置建议

| 选项 | 是否建议 | 理由 |
|------|---------|------|
| 执行止损 | {ds.stop_loss.recommended} | {ds.stop_loss.reason} |
| 部分减仓 | {ds.partial_reduce.recommended} | {ds.partial_reduce.reason} |
| 继续持有观察 | {ds.hold_observe.recommended} | {ds.hold_observe.reason} |
| 反向加仓 | {ds.reverse_add.recommended} | {ds.reverse_add.reason} |

	**结论**: {m.verdict}
	
	**执行优先级**: {m.priority} — 建议 {m.execution_timing} 执行
	
	> 📡 **数据来源**: 行情数据来自腾讯/新浪，基本面数据来自东财/Yahoo。
	"""
