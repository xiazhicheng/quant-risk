# quant-risk 一键安装（Windows PowerShell）
# 自动安装 uv + Python 3.12 + 全部依赖（含 Semantica，首次约 2.5GB AI 推理库）
# 用法：powershell -ExecutionPolicy Bypass -File install.ps1

Write-Host "quant-risk 安装程序 (Windows)" -ForegroundColor Cyan

# 1. 检测 / 安装 uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "未检测到 uv，正在安装（官方脚本）..." -ForegroundColor Yellow
    irm https://astral.sh/uv/install.ps1 | iex
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
} else {
    Write-Host "uv 已存在: $(uv --version)" -ForegroundColor Green
}

# 2. 确保 Python 3.12（uv 托管）
if (-not (uv python find '>=3.12,<3.13' 2>$null)) {
    Write-Host "正在安装托管 Python 3.12..." -ForegroundColor Yellow
    uv python install 3.12
}

# 3. 安装全部依赖
Write-Host "正在安装依赖（含 Semantica，首次下载约 2.5GB，请耐心等待）..." -ForegroundColor Yellow
uv sync

Write-Host "`n安装完成！开始使用：" -ForegroundColor Green
Write-Host "   uv run scripts/daily_run.py" -ForegroundColor White
Write-Host "   uv run scripts/recommend.py --market cn"
Write-Host "`n（数据源为免费公开接口，无需任何 API Key）"
