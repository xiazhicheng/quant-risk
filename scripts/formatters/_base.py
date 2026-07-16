"""
共享基础：Pydantic 校验异常 + 渲染工具函数。
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError


# ── 错误类型 ────────────────────────────────────────────────

class FormatValidationError(Exception):
    """裸数据格式校验失败，调用方应将 message 回传给 LLM 重试。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ── 统一校验入口 ────────────────────────────────────────────

def _validate(model: type[BaseModel], data: dict[str, Any]) -> BaseModel:
    """校验裸数据，返回 Pydantic 模型实例；失败抛 FormatValidationError。"""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        lines = ["JSON 格式校验失败："]
        for e in exc.errors():
            loc = " → ".join(str(x) for x in e["loc"])
            msg = e.get("msg", "")
            inp = e.get("input")
            lines.append(f"  - 字段 '{loc}': {msg}")
            if inp is not None:
                lines.append(f"    实际值: {inp}")
        raise FormatValidationError("\n".join(lines))


# ── 渲染辅助 ────────────────────────────────────────────────

def _format_num(v: Any, fmt: str = "{}") -> str:
    """安全格式化数值，None / 空值返回 -"""
    if v is None or v == "" or v == "-":
        return "-"
    return fmt.format(v)


def _sign_pct(v: Any) -> str:
    """涨跌幅带正负号"""
    if v is None or v == "" or v == "-":
        return "-"
    try:
        f = float(v)
        sign = "+" if f >= 0 else ""
        return f"{sign}{f}"
    except (ValueError, TypeError):
        return str(v)
