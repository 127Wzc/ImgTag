# 多阶段构建：前端 + 后端合并为单一镜像
# ============================================================
# 前端构建阶段
# 使用 --platform=linux/amd64 强制在 x86 上构建（避免 QEMU 模拟）
# 前端产物是平台无关的静态文件
# ============================================================
FROM --platform=linux/amd64 node:20-alpine AS web-builder

WORKDIR /app/web
COPY web/package.json web/pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install --frozen-lockfile
COPY web/ .
RUN pnpm build

# ============================================================
# Python 依赖安装阶段
# ============================================================
FROM python:3.11-slim AS python-builder

WORKDIR /app

# 安装编译依赖（仅在构建阶段需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

# -----------------------------------------------------------
# 核心依赖
FROM python-builder AS deps-core
RUN uv sync --no-dev && rm -rf /root/.cache

# -----------------------------------------------------------
# 完整依赖（含 ONNX）
FROM python-builder AS deps-full
RUN uv sync --extra local --no-dev && rm -rf /root/.cache

# ============================================================
# 最终运行时镜像（精简版基础）
# ============================================================
FROM python:3.11-slim AS runtime-base

WORKDIR /app

# 仅安装运行时依赖（不含编译工具）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 复制后端代码和配置
COPY src/ ./src/
COPY alembic.ini ./

RUN mkdir -p /app/uploads

ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# -----------------------------------------------------------
# slim: 精简版（在线 API）
FROM runtime-base AS slim
COPY --from=deps-core /app/.venv /app/.venv
COPY --from=web-builder /app/web/dist ./static
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" STATIC_DIR=/app/static
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["sh", "-c", "alembic upgrade head && uvicorn imgtag.main:app --host 0.0.0.0 --port 8000"]

# -----------------------------------------------------------
# full: 完整版（本地 ONNX 嵌入）
FROM runtime-base AS full
COPY --from=deps-full /app/.venv /app/.venv
COPY --from=web-builder /app/web/dist ./static
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" STATIC_DIR=/app/static
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["sh", "-c", "alembic upgrade head && uvicorn imgtag.main:app --host 0.0.0.0 --port 8000"]

# -----------------------------------------------------------
# slim-backend: 纯后端精简版
FROM runtime-base AS slim-backend
COPY --from=deps-core /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "alembic upgrade head && uvicorn imgtag.main:app --host 0.0.0.0 --port 8000"]

# -----------------------------------------------------------
# full-backend: 纯后端完整版
FROM runtime-base AS full-backend
COPY --from=deps-full /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "alembic upgrade head && uvicorn imgtag.main:app --host 0.0.0.0 --port 8000"]
