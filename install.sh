#!/usr/bin/env bash
# quant-risk 一键安装（macOS / Linux）
# 自动安装 uv + Python 3.12 + 全部依赖（含 Semantica，首次约 2.5GB AI 推理库）
# 用法：bash install.sh
set -euo pipefail

echo "🔧 quant-risk 安装程序（macOS / Linux）"

# 1. 检测 / 安装 uv
if ! command -v uv >/dev/null 2>&1; then
    echo "⏳ 未检测到 uv，正在安装（官方脚本，无需 sudo）..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "✅ uv 已存在：$(uv --version)"
fi

# 2. 确保 Python 3.12（uv 托管，无需系统 Python）
if ! uv python find '>=3.12,<3.13' >/dev/null 2>&1; then
    echo "⏳ 正在安装托管 Python 3.12..."
    uv python install 3.12
fi

# 3. 安装全部依赖
echo "⏳ 正在安装依赖（含 Semantica，首次下载约 2.5GB，请耐心等待）..."
uv sync

echo ""
echo "✅ 安装完成！开始使用："
echo "   uv run scripts/daily_run.py                     # 每日 A股+港股信号"
echo "   uv run scripts/recommend.py --market cn         # A股波段推荐"
echo "   uv run scripts/analyze.py 600388                # 单股波段分析"
echo ""
echo "（数据源为免费公开接口，无需任何 API Key）"
