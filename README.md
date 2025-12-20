# ImgTag - 智能图片标签管理系统

基于 AI 视觉模型的图片标签自动生成与向量搜索系统。

## ✨ 功能特性

- 🤖 **AI 自动打标签** - 支持 OpenAI、通义千问、Gemini 等视觉模型
- 🔍 **语义向量搜索** - 基于文本描述的相似图片检索
- 📦 **批量处理** - 支持批量上传后队列化分析
- 🏠 **本地嵌入模型** - 支持 bge-small-zh 等本地模型，无需 API
- 🎨 **现代化界面** - Vue 3 + Element Plus 构建
- ⚙️ **灵活配置** - 数据库化配置管理

## 🏗️ 项目结构

```
ImgTag/
├── src/imgtag/          # Python 后端源码
│   ├── api/             # API 端点
│   ├── core/            # 核心配置
│   ├── db/              # 数据库操作
│   ├── schemas/         # Pydantic 模型
│   └── services/        # 业务服务
├── frontend/            # Vue 前端
│   ├── src/
│   │   ├── views/       # 页面组件
│   │   ├── api/         # API 封装
│   │   └── assets/      # 静态资源
│   └── package.json
├── pyproject.toml       # Python 项目配置
└── .env                 # 环境变量
```

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- PostgreSQL 15+ (需安装 pgvector 扩展)

### 1. 克隆项目

```bash
git clone https://github.com/your-repo/ImgTag.git
cd ImgTag
```

### 2. 配置数据库

创建 PostgreSQL 数据库并启用 pgvector 扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入数据库连接
```

`.env` 文件内容：

```
PG_CONNECTION_STRING=postgresql://user:password@host:5432/imgtag
```

### 4. 启动后端

```bash
# 安装依赖
uv sync

# 如需使用本地嵌入模型（约 700MB）
uv sync --extra local

# 启动服务
uv run uvicorn imgtag.main:app --reload
```

### 5. 启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

访问 http://localhost:5173

## 📋 配置说明

所有配置都通过 Web 界面的「设置」页面管理：

### 视觉模型

| 配置项 | 说明 |
|-------|------|
| API 地址 | OpenAI 兼容的 API 端点 |
| API 密钥 | 模型 API Key |
| 模型名称 | 如 gpt-4o-mini、qwen-vl-plus |

### 嵌入模型

支持两种模式：

**本地模型**（推荐）：
- 无需 API，完全离线运行
- 支持 bge-small-zh-v1.5（~90MB，512维）
- 首次使用自动下载

**在线 API**：
- 使用 OpenAI text-embedding 等 API
- 需配置 API 密钥

### 队列配置

| 配置项 | 说明 | 默认值 |
|-------|------|-------|
| 最大并发数 | 批量分析的并发线程 | 2 |

## 🔧 API 接口

后端提供 RESTful API：

- `POST /api/v1/images/upload` - 上传图片
- `GET /api/v1/images/{id}` - 获取图片详情
- `PUT /api/v1/images/{id}` - 更新图片信息
- `DELETE /api/v1/images/{id}` - 删除图片
- `POST /api/v1/search/similar` - 语义搜索
- `POST /api/v1/queue/add` - 添加到分析队列
- `GET /api/v1/queue/status` - 获取队列状态

完整 API 文档访问：http://localhost:8000/docs

## 📦 技术栈

**后端**：
- FastAPI - Web 框架
- PostgreSQL + pgvector - 向量数据库
- OpenAI SDK - 模型调用
- Sentence Transformers - 本地嵌入

**前端**：
- Vue 3 - 框架
- Element Plus - UI 组件
- Pinia - 状态管理
- Vite - 构建工具

## 📄 License

MIT