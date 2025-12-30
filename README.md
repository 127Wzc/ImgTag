# ImgTag - 智能图片标签管理系统

基于 AI 视觉模型的图片标签自动生成与向量搜索系统。

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10+-green.svg)
![Vue](https://img.shields.io/badge/Vue-3-brightgreen.svg)

## ✨ 功能特性

- 🤖 **AI 智能标签**：支持 OpenAI、通义千问、Gemini 等视觉模型自动分析图片
- 🔍 **语义向量搜索**：基于文本描述的相似图片检索
- 📁 **收藏夹管理**：层级收藏夹，自动追加标签
- 🏷️ **标签系统**：来源追踪（AI/用户）、使用统计
- 👥 **用户认证**：JWT 认证、管理员审批、角色权限
- ⚡ **批量操作**：批量上传、删除、打标签、AI 分析
- 📦 **其他**：ZIP 导入、本地嵌入模型、深色模式、重复检测

默认管理员账号：`admin` / `admin123`

---

## 🐳 Docker 部署

### 前提条件

需要已有 PostgreSQL 数据库（启用 pgvector 扩展）

### 快速启动

```bash
# 下载 docker-compose.yml
curl -O https://raw.githubusercontent.com/127Wzc/ImgTag/main/docker/docker-compose.yml

# 编辑 docker-compose.yml，填入数据库连接
# 启动服务
docker-compose up -d
```

访问：http://localhost:5173

### 镜像版本

| 标签 | 说明 | 体积 | 端口 |
|-----|------|-----|-----|
| `latest` | 全栈精简版（推荐） | ~380MB | **5173** → 前端+API 代理 |
| `latest-local` | 全栈 + 本地嵌入模型 | ~540MB | **5173** → 前端+API 代理 |
| `latest-backend` | 纯后端，前端托管 CDN | ~280MB | **8000** → 仅 API |
| `latest-backend-local` | 纯后端 + 本地模型 | ~440MB | **8000** → 仅 API |

> **精简版**：使用在线 API（OpenAI 等）生成向量  
> **完整版**：内置本地 ONNX 嵌入模型，无需外部 API

### 内存需求

| 版本 | 最低内存 | 推荐内存 |
|-----|---------|---------|
| 精简版 (`latest`) | 256MB | 512MB |
| 本地模型版 (`latest-local`) | **512MB** | **1GB** |

**为什么本地模型版需要更多内存？**

- ONNX Runtime 引擎：~150MB
- 嵌入模型（bge-small-zh）：~90MB 加载到内存
- Tokenizer 词表：~50MB
- 推理时临时张量：~50-100MB

模型大小直接影响内存占用：`bge-small` (~90MB) vs `bge-base` (~300MB)。默认使用 `bge-small-zh-v1.5`，兼顾精度和资源消耗。

### 环境变量

| 变量 | 说明 | 默认值 |
|-----|------|-------|
| `PG_CONNECTION_STRING` | PostgreSQL 连接字符串 | 必填 |
| `BASE_URL` | 服务地址 | `http://localhost:5173` |
| `UPLOAD_DIR` | 图片上传目录 | `./uploads` |

### 前后端分离部署

如需将前端托管到 CDN（Cloudflare Pages / Vercel / Netlify）：

1. 使用 `-backend` 镜像运行后端 API（端口 8000）
2. 参考 [前端部署指南](docs/frontend-deploy.md)

---

## 🚀 本地开发

### 环境要求
- Python 3.10+
- Node.js 18+
- PostgreSQL 15+ (启用 pgvector)

### 启动后端

```bash
cp .env.example .env
# 编辑 .env 填入数据库连接

uv sync                    # 安装依赖
uv sync --extra local      # 可选：本地嵌入模型
uv run python -m uvicorn imgtag.main:app --reload --host 0.0.0.0 --port 8000
```

### 启动前端

```bash
cd web
pnpm install
pnpm dev
```

访问 http://localhost:5173（前端自动代理 `/api` 到后端 8000 端口）

---

## 📋 配置说明

通过 Web 界面「系统设置」页面管理配置：

| 模块 | 配置项 |
|------|-------|
| **视觉模型** | API 地址、API 密钥、模型名称 |
| **嵌入模型** | 本地模型（离线）或在线 API |
| **存储端点** | 多端点管理、S3 兼容存储、自动备份 |

---

## 🔌 API

| 类型 | 端点 | 说明 |
|------|------|------|
| 内部 | `/api/v1/*` | JWT 认证，供前端调用 |
| 外部 | `/api/v1/random` 等 | API Key 认证，供第三方接入 |

📖 **API 文档**：http://localhost:8000/docs  
📖 **外部 API 详情**：[docs/external-api.md](docs/external-api.md)

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| [项目结构](docs/project-structure.md) | 目录结构与技术栈 |
| [数据库管理](docs/database.md) | 迁移与数据库操作 |
| [外部 API](docs/external-api.md) | 第三方接入接口 |
| [前端部署](docs/frontend-deploy.md) | CDN 托管前端指南 |

---

## 📄 License

MIT