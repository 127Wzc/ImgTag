# 多阶段构建：前端 + 后端合并为单一镜像
# ============================================================
# 前端构建阶段
# 注意：在 CI 环境中，前端已经预先构建好并放在 web/dist 目录
# 此阶段仅在本地构建或 dist 目录不存在时实际执行构建
# ============================================================
FROM node:20-slim AS web-builder

WORKDIR /app/web

# 先复制预构建的 dist（如果存在）
COPY web/dist* ./dist/

# 如果 dist 不存在或为空，则执行构建
COPY web/package.json web/pnpm-lock.yaml ./
RUN if [ ! -d "dist" ] || [ -z "$(ls -A dist 2>/dev/null)" ]; then \
    npm install -g pnpm && pnpm install --frozen-lockfile; \
    fi

COPY web/ .
RUN if [ ! -d "dist" ] || [ -z "$(ls -A dist 2>/dev/null)" ]; then \
    pnpm build; \
    fi

# -----------------------------------------------------------
# Python 后端基础镜像
FROM python:3.11-slim AS base

WORKDIR /app

# 安装系统依赖（ca-certificates 用于 HTTPS 证书验证）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN pip install --no-cache-dir uv

# 复制项目配置
COPY pyproject.toml uv.lock ./

# -----------------------------------------------------------
# 精简版：仅支持在线 API 模式（约 500MB）
FROM base AS slim

# 只安装核心依赖（不含本地嵌入模型）
RUN uv sync --no-dev && \
    rm -rf /root/.cache

# 复制后端代码
COPY src/ ./src/
COPY alembic.ini ./

# 复制前端构建产物到 static 目录
COPY --from=web-builder /app/web/dist ./static

# 创建上传目录
RUN mkdir -p /app/uploads

# 环境变量
ENV PYTHONPATH=/app/src
ENV STATIC_DIR=/app/static

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 启动命令：先迁移再启动
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn imgtag.main:app --host 0.0.0.0 --port 8000"]

# -----------------------------------------------------------
# 完整版：支持本地 ONNX 嵌入模型（约 700MB）
FROM base AS full

# 安装包含本地嵌入模型的依赖（ONNX Runtime）
RUN uv sync --extra local --no-dev && \
    rm -rf /root/.cache

# 复制后端代码
COPY src/ ./src/
COPY alembic.ini ./

# 复制前端构建产物到 static 目录
COPY --from=web-builder /app/web/dist ./static

# 创建上传目录
RUN mkdir -p /app/uploads

# 环境变量
ENV PYTHONPATH=/app/src
ENV STATIC_DIR=/app/static

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 启动命令：先迁移再启动
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn imgtag.main:app --host 0.0.0.0 --port 8000"]

# -----------------------------------------------------------
# 纯后端精简版（无前端，用于前后端分离部署）
FROM base AS slim-backend

# 只安装核心依赖（不含本地嵌入模型）
RUN uv sync --no-dev && \
    rm -rf /root/.cache

# 复制后端代码
COPY src/ ./src/
COPY alembic.ini ./

# 创建上传目录
RUN mkdir -p /app/uploads

# 环境变量
ENV PYTHONPATH=/app/src

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 启动命令：先迁移再启动
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn imgtag.main:app --host 0.0.0.0 --port 8000"]

# -----------------------------------------------------------
# 纯后端完整版（无前端，含本地嵌入模型）
FROM base AS full-backend

# 安装包含本地嵌入模型的依赖（ONNX Runtime）
RUN uv sync --extra local --no-dev && \
    rm -rf /root/.cache

# 复制后端代码
COPY src/ ./src/
COPY alembic.ini ./

# 创建上传目录
RUN mkdir -p /app/uploads

# 环境变量
ENV PYTHONPATH=/app/src

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 启动命令：先迁移再启动
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn imgtag.main:app --host 0.0.0.0 --port 8000"]
