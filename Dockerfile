# syntax=docker/dockerfile:1.7

# ============================================================
# python-base — 公共 Python 运行环境、uv 与 jemalloc 配置
# ============================================================
FROM python:3.13-slim AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    LD_PRELOAD=/usr/lib/libjemalloc.so.2 \
    MALLOC_CONF="narenas:2,background_thread:true" \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libjemalloc2 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/lib/*/libjemalloc.so.2 /usr/lib/libjemalloc.so.2

COPY --from=ghcr.io/astral-sh/uv:0.7.20 /uv /uvx /bin/

# ============================================================
# runtime-deps — 仅安装 Bot 运行时第三方依赖
# ============================================================
# 先安装运行时依赖，但不安装项目本身。
# 这样只有应用源码变化时，这一层仍然可以复用缓存。
FROM python-base AS runtime-deps

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# ============================================================
# dev-deps — 仅安装开发和迁移第三方依赖
# ============================================================
# 先安装开发和迁移依赖，但不安装项目本身。
# 最终 dev 阶段会在复制源码之后再安装当前项目。
FROM python-base AS dev-deps

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --extra dev --no-install-project

# ============================================================
# base — 安装项目源码，用于正常启动 Bot
# ============================================================
FROM runtime-deps AS base

COPY README.md LICENSE ./
COPY alembic.ini migrate.py ./
COPY alembic/ ./alembic/
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ============================================================
# dev — 安装项目源码和开发依赖，用于迁移数据库等
# ============================================================
FROM dev-deps AS dev

COPY README.md LICENSE ./
COPY alembic.ini migrate.py ./
COPY alembic/ ./alembic/
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --extra dev
