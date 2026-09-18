# quant-risk — A股+港股量化波段系统镜像
# 基础：python:3.12-slim + uv（官方托管）
# Semantica 为可选依赖（官方全量包，含 torch/transformers/faiss 等，镜像约 2.5GB）：
# 镜像显式 --extra semantica 保持完整影子裁决能力；本机开发可仅 uv sync 轻量安装
# 用法：docker run --rm -v $(pwd)/report:/app/report quant-risk daily --markets cn,hk

FROM python:3.12-slim

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

# uv 静态二进制（多架构：amd64/arm64）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 先只拷依赖清单，利用 uv 缓存层（改代码不重装依赖）
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --extra semantica

# 拷贝项目代码（.dockerignore 已排除 report/.venv/.git 等）
COPY . .

# 数据源为免费公开 HTTP 接口，容器内直接可用；report/ 由宿主机挂载持久化
ENTRYPOINT ["uv", "run", "--no-sync"]
CMD ["scripts/daily_run.py", "--markets", "cn,hk"]
