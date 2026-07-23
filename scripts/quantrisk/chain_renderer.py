#!/usr/bin/env python3
"""
产业链渲染器 — 从结构化 YAML 生成 Mermaid 产业链全景图

数据格式参考 ai-berkshire industry-research SOP:
- research/chain/{code}.yaml → load_chain_data()
- render_mermaid(data) → Mermaid graph TB 字符串
- render_chain_block(data) → 完整输出（mermaid + 卡脖子 + 竞品对标）

调用方无需接触硬编码字符串，直接从 YAML 加载渲染。
"""
import os
import yaml

# ── 产业链数据目录 ──
# 项目根目录下 research/chain/ 目录
_CHAIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "research",
    "chain",
)


def _resolve_chain_dir() -> str:
    """返回规范化后的产业链数据目录路径。"""
    return os.path.normpath(_CHAIN_DIR)


def load_chain_data(code: str) -> dict | None:
    """
    加载指定股票的产业链 YAML 数据。

    参数
    ----
    code : str
        股票代码，如 "02460"、"03888"

    返回
    ----
    dict | None
        YAML 解析后的字典，未找到文件时返回 None
    """
    chain_dir = _resolve_chain_dir()
    path = os.path.join(chain_dir, f"{code}.yaml")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def render_mermaid(data: dict) -> str:
    """
    从产业链 YAML 数据生成 Mermaid graph TB 字符串。

    支持:
    - subgraph 分组（上游/中游/下游/终端/竞争格局）
    - 节点标签 + note（emoji 状态标记）
    - 连接关系（实线 --> | 虚线 -.- →）

    参数
    ----
    data : dict
        load_chain_data() 返回的字典

    返回
    ----
    str
        Mermaid graph TB 文本
    """
    lines = ["graph TB"]

    # 渲染每个子图（chain 列表）
    for group in data.get("chain", []):
        name = group.get("name", "unnamed")
        lines.append(f"    subgraph {name}")
        for node in group.get("nodes", []):
            node_id = node.get("id", "")
            label = node.get("label", node_id)
            note = node.get("note", "")
            text = f"{label}<br/>{note}" if note else label
            lines.append(f"        {node_id}[{text}]")
        lines.append("    end")

    # 渲染连接关系（edges 列表）
    for edge in data.get("edges", []):
        from_id = edge.get("from", "")
        to_ids = edge.get("to", "").split() if isinstance(edge.get("to"), str) else edge.get("to", [])
        label = edge.get("label", "")
        style = edge.get("style", "solid")

        arrow = "-.->" if style == "dashed" else "-->"
        label_part = f"| {label}|" if label else ""

        if len(to_ids) == 1:
            lines.append(f"    {from_id} {arrow}{label_part} {to_ids[0]}")
        else:
            # 多个目标节点: A --> B & C
            targets = " & ".join(to_ids)
            lines.append(f"    {from_id} {arrow}{label_part} {targets}")

    return "\n".join(lines)


def render_chain_block(data: dict) -> str:
    """
    渲染完整的产业链区块：Mermaid 图 + 卡脖子 + 竞品对标。

    参数
    ----
    data : dict
        load_chain_data() 返回的字典

    返回
    ----
    str
        完整的 Markdown 文本（含 mermaid 代码块）
    """
    industry = data.get("industry", "")
    mermaid = render_mermaid(data)

    lines = []
    if industry:
        lines.append(f"**{industry}**")
        lines.append("")
    lines.append("```mermaid")
    lines.append(mermaid)
    lines.append("```")
    lines.append("")

    bottleneck = data.get("bottleneck", "")
    vs_leader = data.get("vs_leader", "")
    if bottleneck or vs_leader:
        lines.append(f"> **卡脖子**: {bottleneck}")
        lines.append(f"> **竞品对标**: {vs_leader}")
        lines.append("")

    return "\n".join(lines)


def chain_available(code: str) -> bool:
    """快速检查某只股票是否有产业链数据。"""
    return load_chain_data(code) is not None


# ── CLI 测试入口 ──
if __name__ == "__main__":
    import sys

    code = sys.argv[1] if len(sys.argv) > 1 else "02460"
    data = load_chain_data(code)
    if data is None:
        print(f"[chain_renderer] 未找到 {code} 的产业链数据")
        sys.exit(0)

    print(f"=== {data.get('name', code)} ({data.get('industry', '?')}) ===\n")
    print(render_chain_block(data))
