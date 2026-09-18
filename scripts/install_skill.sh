#!/usr/bin/env bash
# quant-risk Skill 一键安装（macOS / Linux）
# 用法（远程 curl，下载即用）：
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.sh)"
# 或本地仓库内： bash scripts/install_skill.sh
# 默认安装到 ~/.claude/skills/quant-risk（Claude Code）
# 其他客户端：--dest ~/.codex/skills/quant-risk（Codex）| --dest ~/.agents/skills/quant-risk（ZCode）
set -euo pipefail

DEST="${1:-$HOME/.claude/skills/quant-risk}"
REPO_URL="https://github.com/xiazhicheng/quant-risk.git"
TMP_DIR=""

# 若当前不在仓库内（curl | bash 场景），临时 clone
if [ ! -f "SKILL.md" ] || [ ! -d "scripts" ]; then
    echo "⏳ 当前目录不是 quant-risk 仓库，临时拉取..."
    TMP_DIR="$(mktemp -d)"
    git clone --depth 1 "$REPO_URL" "$TMP_DIR/quant-risk" 2>/dev/null
    cd "$TMP_DIR/quant-risk"
fi

mkdir -p "$DEST"
cp SKILL.md "$DEST/"
# 排除 __pycache__/测试缓存等，只带运行所需的 scripts/
tar --exclude='__pycache__' --exclude='.pytest_cache' -cf - scripts | tar -xf - -C "$DEST/"
[ -n "$TMP_DIR" ] && rm -rf "$TMP_DIR"

echo ""
echo "✅ 已安装 quant-risk Skill 到：$DEST"
echo ""
echo "下一步："
echo "  1. 重启 AI 客户端（Claude Code / Codex / ZCode）"
echo "  2. 对话中直接说「帮我分析 600388」或「推荐今日 A股+港股」"
echo "  3. 首次执行时 AI 会自动安装依赖（uv sync，几十 MB，约 1-3 分钟）"
echo ""
echo "💡 手动装依赖（可选）：cd $DEST && uv sync"
echo "   完整 Semantica 影子裁决（约 2.5GB）：uv sync --extra semantica"
