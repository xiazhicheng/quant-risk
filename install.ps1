# quant-risk 一键安装（Windows PowerShell）
# 自动安装 uv + Python 3.12 + 轻量依赖（默认不含 Semantica 重型 AI 栈，约几十 MB）
# 需要完整 Semantica 影子裁决（约 2.5GB）时：uv sync --extra semantica
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

# 2. 安装依赖（uv 自动解析 Python 版本并托管；semantica 为可选 extra）
Write-Host "正在安装依赖（轻量版，首次约几十 MB，请耐心等待）..." -ForegroundColor Yellow
uv sync

# 3. 首次运行自检（纯导入，不依赖网络）
Write-Host "正在自检..." -ForegroundColor Yellow
uv run python -c "from scripts.quantrisk import data, swing; print('冒烟通过')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "自检失败：依赖安装不完整，请重试 install.ps1 或运行 'uv sync' 后联系排查。" -ForegroundColor Red
    exit 1
}
Write-Host "自检通过" -ForegroundColor Green

Write-Host "`n安装完成！开始使用：" -ForegroundColor Green
Write-Host "   uv run scripts/daily_run.py" -ForegroundColor White
Write-Host "   uv run scripts/analyze.py 600388"
Write-Host "`n提示：数据源为免费公开接口，无需 API Key；报告大量 BLOCK 属数据源限流（正常），非安装故障；"
Write-Host "完整 Semantica 影子裁决（约 2.5GB）：uv sync --extra semantica" -ForegroundColor Gray
