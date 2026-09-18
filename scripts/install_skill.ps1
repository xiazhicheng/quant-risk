# quant-risk Skill 一键安装（Windows PowerShell）
# 用法（远程执行，下载即用）：
#   irm https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.ps1 | iex
# 默认安装到 ~/.claude/skills/quant-risk（Claude Code）
# 其他客户端：$dest 改为 ~/.codex/skills/quant-risk（Codex）| ~/.agents/skills/quant-risk（ZCode）

$ErrorActionPreference = "Stop"
$dest = "$env:USERPROFILE\.claude\skills\quant-risk"
$repo = "https://github.com/xiazhicheng/quant-risk.git"
$tmp = Join-Path $env:TEMP "qr-skill-$(Get-Random)"

Write-Host "正在拉取 quant-risk Skill..." -ForegroundColor Yellow
git clone --depth 1 $repo $tmp 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "拉取失败：请确认已安装 git" -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item "$tmp\SKILL.md" $dest
Copy-Item "$tmp\scripts" "$dest\scripts" -Recurse -Exclude "__pycache__"
Remove-Item -Recurse -Force $tmp

Write-Host "`n✅ 已安装 quant-risk Skill 到：$dest" -ForegroundColor Green
Write-Host "`n下一步："
Write-Host "  1. 重启 AI 客户端（Claude Code / Codex / ZCode）"
Write-Host "  2. 对话中直接说「帮我分析 600388」或「推荐今日 A股+港股」"
Write-Host "  3. 首次执行时 AI 会自动安装依赖（uv sync，几十 MB，约 1-3 分钟）"
Write-Host "`n手动装依赖（可选）：cd $dest; uv sync   （完整 Semantica：uv sync --extra semantica）" -ForegroundColor Gray
