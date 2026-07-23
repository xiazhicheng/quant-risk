#!/usr/bin/env python3
"""
产业链渲染器 — 从结构化数据生成 Mermaid 产业链全景图

使用方式:
- LLM 按 ai-berkshire industry-research SOP 生成 Mermaid 文本
- 调用 render_mermaid_raw(mermaid_text) 直接渲染
- 或使用 render_chain_block(mermaid, industry, bottleneck, vs_leader) 渲染完整区块

注: 产业链数据为 LLM 临时中间产物，不持久化到文件系统。
"""


def render_mermaid_raw(mermaid_text: str) -> str:
    """
    直接渲染 LLM 生成的 Mermaid 文本。

    参数
    ----
    mermaid_text : str
        LLM 生成的 Mermaid 代码块内容（不含 ```mermaid 包围）

    返回
    ----
    str
        带 mermaid 代码块标记的完整 Markdown 文本
    """
    lines = ["```mermaid", mermaid_text.strip(), "```"]
    return "\n".join(lines)


def render_chain_block(
    mermaid_text: str,
    industry: str = "",
    bottleneck: str = "",
    vs_leader: str = "",
) -> str:
    """
    渲染完整的产业链区块：行业名称 + Mermaid 图 + 卡脖子 + 竞品对标。

    参数
    ----
    mermaid_text : str
        LLM 生成的 Mermaid 代码内容（不含 ```mermaid 包围）
    industry : str
        行业名称
    bottleneck : str
        卡脖子环节描述
    vs_leader : str
        竞品对标描述

    返回
    ----
    str
        完整的 Markdown 文本
    """
    lines = []
    if industry:
        lines.append(f"**{industry}**")
        lines.append("")
    lines.append(render_mermaid_raw(mermaid_text))
    lines.append("")

    if bottleneck or vs_leader:
        if bottleneck:
            lines.append(f"> **卡脖子**: {bottleneck}")
        if vs_leader:
            lines.append(f"> **竞品对标**: {vs_leader}")
        lines.append("")

    return "\n".join(lines)


def has_chain_data(mermaid_text: str | None) -> bool:
    """检查是否有产业链数据。"""
    return bool(mermaid_text and mermaid_text.strip())
