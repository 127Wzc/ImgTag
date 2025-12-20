# ImgTag - 智能图片标签管理系统

基于 AI 视觉模型的图片标签自动生成与向量搜索系统。

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10+-green.svg)
![Vue](https://img.shields.io/badge/Vue-3-brightgreen.svg)

## ✨ 功能特性

### 🤖 AI 智能标签
- 支持 OpenAI、通义千问、Gemini 等视觉模型
- 自动分析图片生成描述和标签
- 可自定义分析提示词

### 🔍 语义向量搜索
- 基于文本描述的相似图片检索
- 混合搜索：向量相似度 + 标签权重
- 支持动态调整权重

### 📁 收藏夹管理
- 层级收藏夹（支持父子关系）
- 添加到收藏夹自动追加标签
- 随机图片 API（支持标签筛选）

### 🏷️ 标签系统
- 独立标签管理（同步、重命名、删除）
- 标签建议与搜索
- 标签使用统计

### ⚡ 异步任务
- 后台任务队列处理
- 批量向量化任务
- 任务状态追踪与清理

### 📦 其他功能
- 批量上传与 ZIP 压缩包导入
- 本地嵌入模型（无需 API）
- 现代化毛玻璃 UI 设计
- 深色模式支持

---

## 🏗️ 项目结构

```
ImgTag/
├── src/imgtag/          # Python 后端
│   ├── api/             # API 端点
│   ├── core/            # 核心配置
│   ├── db/              # 数据库操作
│   ├── schemas/         # Pydantic 模型
│   └── services/        # 业务服务 (视觉/嵌入/任务)
├── frontend/            # Vue 3 前端
│   ├── src/views/       # 页面组件
│   └── src/components/  # 公共组件
├── uploads/             # 图片存储目录
├── Dockerfile           # Docker 镜像
├── docker-compose.yml   # Docker Compose
└── pyproject.toml       # Python 项目配置
```

---

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 克隆项目
git clone https://github.com/your-repo/ImgTag.git
cd ImgTag

# 启动服务
docker-compose up -d

# 访问
# 前端: http://localhost:5173
# API:  http://localhost:8000/docs
```

### 方式二：本地开发

#### 环境要求
- Python 3.10+
- Node.js 18+
- PostgreSQL 15+ (需启用 pgvector 扩展)

#### 1. 配置数据库

```sql
CREATE DATABASE imgtag;
\c imgtag
CREATE EXTENSION vector;
```

#### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入数据库连接
```

```env
PG_CONNECTION_STRING=postgresql://user:password@localhost:5432/imgtag
```

#### 3. 启动后端

```bash
# 安装依赖
uv sync

# 使用本地嵌入模型（可选，约 90MB）
uv sync --extra local

# 启动服务
uv run uvicorn imgtag.main:app --reload --host 0.0.0.0
```

#### 4. 启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

访问 http://localhost:5173

---

## 📋 配置说明

通过 Web 界面「系统设置」页面管理所有配置：

### 视觉模型

| 配置项 | 说明 | 示例 |
|-------|------|------|
| API 地址 | OpenAI 兼容端点 | `https://api.openai.com/v1` |
| API 密钥 | 模型 API Key | `sk-xxx` |
| 模型名称 | 视觉模型 ID | `gpt-4o-mini` |

### 嵌入模型

**本地模型**（推荐）：
- 无需 API，完全离线
- 支持 `BAAI/bge-small-zh-v1.5`（约 90MB，512 维）

**在线 API**：
- 使用 OpenAI `text-embedding-3-small` 等 API

---

## 🔧 API 接口

| 端点 | 方法 | 说明 |
|------|-----|------|
| `/api/v1/images/upload` | POST | 上传图片 |
| `/api/v1/images/upload-zip` | POST | 上传 ZIP |
| `/api/v1/images/{id}` | GET/PUT/DELETE | 图片 CRUD |
| `/api/v1/search/similar` | POST | 语义搜索 |
| `/api/v1/collections/` | GET/POST | 收藏夹管理 |
| `/api/v1/collections/{id}/random` | GET | 随机图片 |
| `/api/v1/tags/` | GET | 标签列表 |
| `/api/v1/tasks/` | GET | 任务列表 |
| `/api/v1/queue/add` | POST | 添加到分析队列 |

完整文档：http://localhost:8000/docs

---

## 📦 技术栈

**后端**：
- FastAPI - Web 框架
- PostgreSQL + pgvector - 向量数据库
- OpenAI SDK - 模型调用
- Sentence Transformers - 本地嵌入

**前端**：
- Vue 3 + Composition API
- Element Plus - UI 组件
- Vite - 构建工具

---

## 🐳 Docker 部署

### 前提条件
需要已有 PostgreSQL 数据库（启用 pgvector 扩展）

### 使用 Docker Compose

1. 配置环境变量：
```bash
cp .env.example .env
# 编辑 .env 填入数据库连接
```

2. 启动服务：
```bash
docker-compose up -d
```

3. 访问：http://localhost:8000

### 单独构建运行

```bash
# 构建镜像
docker build -t imgtag .

# 运行（单端口同时提供 API 和前端）
docker run -d \
  -p 8000:8000 \
  -e PG_CONNECTION_STRING=postgresql://user:pass@host:5432/imgtag \
  -v ./uploads:/app/uploads \
  imgtag
```

### 环境变量

| 变量 | 说明 | 默认值 |
|-----|------|-------|
| `PG_CONNECTION_STRING` | PostgreSQL 连接字符串 | 必填 |
| `BASE_URL` | 服务地址 | `http://localhost:8000` |
| `UPLOAD_DIR` | 图片上传目录 | `./uploads` |

---

## 📄 License

MIT