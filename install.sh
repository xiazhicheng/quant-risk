#!/usr/bin/env bash
# quant-risk 一键安装（macOS / Linux）
# 自动安装 uv + Python 3.12 + 轻量依赖（默认不含 Semantica 重型 AI 栈，约几十 MB）
# 需要完整 Semantica 影子裁决（约 2.5GB）时：uv sync --extra semantica
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

# 2. 安装依赖（uv 自动解析 Python 版本并托管；semantica 为可选 extra）
echo "⏳ 正在安装依赖（轻量版，首次约几十 MB，请耐心等待）..."
uv sync

# 3. 首次运行自检（纯导入，不依赖网络）
echo "⏳ 正在自检..."
if uv run python -c "from scripts.quantrisk import data, swing; print('✅ 冒烟通过：依赖安装完整')" 2>/dev/null; then
    echo "✅ 自检通过"
else
    echo "❌ 自检失败：依赖安装不完整，请重试 install.sh 或运行 'uv sync' 后联系排查。"
    exit 1
fi

echo ""
echo "✅ 安装完成！开始使用："
echo "   uv run scripts/daily_run.py                     # 每日 A股+港股信号"
echo "   uv run scripts/analyze.py 600388                # 单股波段分析"
echo "   uv run scripts/recommend.py --market cn         # A股波段推荐"
echo ""
echo "💡 首次运行提示："
echo "   - 数据源为免费公开接口，无需任何 API Key"
echo "   - 如报告出现大量 BLOCK/数据缺失，是免费数据源限流（fail-closed 正常行为），"
echo "     稍后重跑即可，不是安装问题"
echo "   - 完整 Semantica 影子裁决（约 2.5GB，含 torch 等）：uv sync --extra semantica"
