# 多阶段构建：前端 + 后端合并为单一镜像
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

# 安装依赖
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install --frozen-lockfile

# 构建前端
COPY frontend/ .
RUN pnpm build

# -----------------------------------------------------------
# Python 后端 + 前端静态文件
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN pip install uv

# 复制项目配置
COPY pyproject.toml uv.lock ./

# 安装 Python 依赖（包含本地嵌入模型支持）
RUN uv sync --extra local

# 复制后端代码
COPY src/ ./src/

# 复制前端构建产物到 static 目录
COPY --from=frontend-builder /app/frontend/dist ./static

# 创建上传目录
RUN mkdir -p /app/uploads

# 环境变量
ENV PYTHONPATH=/app/src
ENV STATIC_DIR=/app/static

# 暴露端口（单端口同时提供 API 和前端）
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 启动命令
CMD ["uv", "run", "uvicorn", "imgtag.main:app", "--host", "0.0.0.0", "--port", "8000"]
