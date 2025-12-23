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
- **标签来源追踪**：区分 AI 生成和用户手动添加的标签

### 🔍 语义向量搜索
- 基于文本描述的相似图片检索
- 混合搜索：向量相似度 + 标签权重
- 支持动态调整权重

### 📁 收藏夹管理
- 层级收藏夹（支持父子关系）
- 添加到收藏夹自动追加标签
- 随机图片 API（支持标签筛选）

### 🏷️ 标签系统
- **规范化关联表设计**：标签存储于独立关联表
- 标签来源区分（AI/用户）
- 标签建议与搜索
- 标签使用统计

### 👥 用户认证
- 用户注册与登录（JWT 认证）
- 管理员审批新用户
- 角色权限控制（admin/user）
- **用户管理界面**：管理员可创建/禁用/删除用户、修改密码
- **个人中心**：修改密码、生成个人 API 密钥
- 默认管理员账号：`admin` / `admin`

**权限矩阵：**

| 操作 | 游客 | 登录用户 | 管理员 |
|-----|:----:|:-------:|:-----:|
| 仪表盘/图片查询/搜索 | ✅ | ✅ | ✅ |
| 上传/删除/更新图片 | ❌ | ✅ | ✅ |
| 收藏夹操作 | ❌ | ✅ | ✅ |
| 任务队列操作 | ❌ | ✅ | ✅ |
| 系统配置 | ❌ | ❌ | ✅ |
| 标签管理（重命名/删除） | ❌ | ❌ | ✅ |
| 向量管理 | ❌ | ❌ | ✅ |
| 用户管理/审批 | ❌ | ❌ | ✅ |

### ⚡ 批量操作
- 批量图片选择
- 批量删除、批量打标签
- 批量加入收藏夹
- 批量 AI 分析（异步队列）
- **批量 API**：单次请求处理多图片

### 📦 其他功能
- 批量上传与 ZIP 压缩包导入
- 本地嵌入模型（无需 API）
- 现代化毛玻璃 UI 设计
- 深色模式支持
- **启动时自动恢复未完成任务**
- **数据备份与恢复**：导出/导入数据库记录（JSON 格式）
- **重复图片检测**：基于文件 MD5 哈希检测并筛选重复图片
- **动态模型选择**：从 API 实时获取可用模型列表

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
├── web/                  # Vue 3 前端
│   ├── src/views/       # 页面组件
│   └── src/components/  # 公共组件
├── uploads/             # 图片存储目录
├── Dockerfile           # Docker 镜像
├── docker-compose.yml   # Docker Compose
└── pyproject.toml       # Python 项目配置
```

## 🗄️ 数据库结构

```
images              # 图片表
├── id, image_url, description, embedding, file_hash, ...

tags                # 标签表
├── id, name, source, usage_count, parent_id

image_tags          # 图片-标签关联表（核心）
├── image_id, tag_id, source(ai/user), added_by, added_at

users               # 用户表
├── id, username, password_hash, role, status, api_key

collections         # 收藏夹表
├── id, name, user_id, parent_id

tasks               # 任务表
├── id, task_type, status, payload, result
```

**关键设计：**
- 标签使用关联表 `image_tags` 存储，支持追踪来源和操作人
- `image_tags.source` 区分 AI 生成 (`ai`) 和用户添加 (`user`)
- 用户注册需管理员审批（`users.status`）

---

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 克隆项目
git clone https://github.com/your-repo/ImgTag.git
cd ImgTag

# 启动服务
docker-compose up -d

# 访问：http://localhost:8000（单端口同时提供 API 和前端）
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
cd web
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

## 🔧 内部 API

内部 API 使用 JWT 认证（Web 界面自动处理），供前端页面调用。

### 主要端点

| 模块 | 路径前缀 | 说明 |
|------|---------|------|
| 图片管理 | `/api/v1/images` | 上传、CRUD、批量操作 |
| 搜索 | `/api/v1/search` | 语义相似度搜索 |
| 收藏夹 | `/api/v1/collections` | 收藏夹管理 |
| 标签 | `/api/v1/tags` | 标签列表、管理 |
| 任务队列 | `/api/v1/queue` | 分析任务管理 |
| 认证 | `/api/v1/auth` | 登录、注册、用户管理 |
| 系统 | `/api/v1/system` | 备份、导入、重复检测 |

📖 **完整文档**：http://localhost:8000/docs

---

## 🔌 外部 API

供第三方系统接入的 API，使用个人 API 密钥认证。

### 快速开始

1. 在 **个人中心**（点击右上角用户名）生成 API 密钥
2. 调用 API 时携带密钥（Header 或参数方式）

### 接口列表

| 端点 | 说明 |
|------|------|
| `GET /api/v1/random` | 获取随机图片 |
| `POST /api/v1/add-image` | 通过 URL 添加图片 |
| `GET /api/v1/image/{id}` | 获取图片详情 |
| `GET /api/v1/search` | 搜索图片 |

### 示例

```bash
# 获取随机图片
curl "http://localhost:8000/api/v1/random?api_key=YOUR_KEY&count=1"

# 添加图片
curl -X POST "http://localhost:8000/api/v1/add-image?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"image_url": "https://example.com/image.jpg"}'

# 搜索图片（关键词需 URL 编码）
curl "http://localhost:8000/api/v1/search?api_key=YOUR_KEY&keyword=%E5%88%9D%E9%9F%B3&limit=10"
```

📖 **完整文档**：[docs/EXTERNAL_API.md](docs/EXTERNAL_API.md)

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