"""
风控格式化器包 — 统一导出所有模板的 format_* 函数和 FormatValidationError。

导入方式:
    from scripts.formatters import (
        FormatValidationError,
        format_pretrade,   # 阶段 1 投前审查
        format_holding,    # 阶段 2 持仓监控
        format_alert,      # 阶段 3 预警触发
        format_disposal,   # 阶段 4 处置决策
    )
"""
from __future__ import annotations

from ._base import FormatValidationError
from ._pretrade import format_pretrade
from ._holding import format_holding
from ._alert import format_alert
from ._disposal import format_disposal

__all__ = [
    "FormatValidationError",
    "format_pretrade",
    "format_holding",
    "format_alert",
    "format_disposal",
]
