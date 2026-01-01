# ImgTag 系统架构

本文档详细介绍 ImgTag 的技术架构和核心模块设计。

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Vue 3)                       │
│   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────────┐   │
│   │ Gallery │ │ Upload  │ │ Search  │ │ Settings/Admin  │   │
│   └─────────┘ └─────────┘ └─────────┘ └─────────────────┘   │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP/WebSocket
┌────────────────────────────▼────────────────────────────────┐
│                   Backend (FastAPI)                         │
│   ┌──────────┐ ┌───────────┐ ┌────────────┐ ┌───────────┐   │
│   │ Auth API │ │ Image API │ │ Search API │ │ Admin API │   │
│   └──────────┘ └───────────┘ └────────────┘ └───────────┘   │
│   ┌──────────────────────────────────────────────────────┐  │
│   │                   Service Layer                      │  │
│   │  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐   │  │
│   │  │ Vision  │ │Embedding │ │ Storage │ │TaskQueue │   │  │
│   │  │ Service │ │ Service  │ │ Service │ │ Service  │   │  │
│   │  └─────────┘ └──────────┘ └─────────┘ └──────────┘   │  │
│   └──────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                    Data Layer                               │
│   ┌──────────────────┐        ┌──────────────────────────┐  │
│   │  PostgreSQL      │        │  Storage Endpoints       │  │
│   │  + pgvector      │        │  Local / S3 兼容存储    │  │
│   └──────────────────┘        └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | Vue 3 + TypeScript | SPA 单页应用 |
| **UI** | Tailwind CSS + shadcn/vue | 组件库 |
| **后端** | FastAPI + SQLAlchemy 2.0 | 异步 Python Web 框架 |
| **数据库** | PostgreSQL + pgvector | 向量存储与搜索 |
| **AI 模型** | OpenAI / Gemini | 视觉分析 |
| **嵌入模型** | ONNX Runtime / API | 文本向量化 |
| **存储** | Local + S3 兼容 | 多端点存储 |

---

## 核心模块

### 1. AI 视觉分析 (Vision Service)

自动分析图片内容，生成标签和描述。

**支持的模型提供商：** OpenAI 兼容 API

- OpenAI GPT-4 Vision
- Google Gemini Pro Vision

**工作流程：**
```
图片上传 → 加入任务队列 → Vision API 分析 → 生成标签+描述 → 更新数据库
```

### 2. 向量搜索 (Embedding Service)

基于文本语义的相似图片检索。

**向量生成：**
- 本地模式：ONNX Runtime + bge-small-zh-v1.5
- 在线模式：OpenAI / 通义千问 Embedding API

**搜索算法：**
- pgvector 余弦相似度
- 支持向量 + 标签混合搜索
- 可配置权重比例

### 3. 多端点存储 (Storage Service)

灵活的分布式存储方案。

**端点类型：**
| 类型 | 说明 |
|------|------|
| Local | 本地文件系统 |
| S3 | S3 兼容存储（AWS S3、RustFS 等）|

**端点角色：**
| 角色 | 用途 |
|------|------|
| Primary | 主存储，可上传/读取 |
| Backup | 备份端点，自动同步 |

**读取策略：**
1. 按 `read_priority` 优先级选择
2. 相同优先级按 `read_weight` 负载均衡
3. 自动跳过不健康端点

### 4. 任务队列 (Task Queue Service)

异步处理 AI 分析任务。

**特性：**
- 可配置并发数
- 支持回调通知
- 失败重试机制
- 智能跳过：手动指定标签时只生成向量

---

## 数据模型

### 核心表

| 表名 | 说明 |
|------|------|
| `images` | 图片元数据 + 向量 |
| `tags` | 标签定义 |
| `image_tags` | 图片-标签关联 |
| `image_locations` | 图片存储位置 |
| `storage_endpoints` | 存储端点配置 |
| `users` | 用户账户 |
| `collections` | 收藏夹 |

### 向量存储

使用 pgvector 扩展存储 768 维向量：

```sql
ALTER TABLE images ADD COLUMN embedding vector(768);
CREATE INDEX ON images USING ivfflat (embedding vector_cosine_ops);
```

---

## API 设计

### 内部 API (JWT 认证)

| 模块 | 路径 | 说明 |
|------|------|------|
| 认证 | `/api/v1/auth/*` | 登录/注册/Token |
| 图片 | `/api/v1/images/*` | CRUD + 上传 |
| 搜索 | `/api/v1/search/*` | 向量搜索 |
| 标签 | `/api/v1/tags/*` | 标签管理 |
| 存储 | `/api/v1/storage/*` | 端点管理 |

### 外部 API (API Key 认证)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/external/images` | POST | 添加图片 |
| `/api/v1/external/images/{id}` | GET | 获取详情 |
| `/api/v1/external/images/random` | GET | 随机图片 |
| `/api/v1/external/images/search` | GET | 搜索图片 |

详见 [外部 API 文档](external-api.md)

---

## 部署架构

### Docker 全栈部署

```
┌─────────────────────────────────┐
│     Docker Container (5173)     │
│  ┌───────────┐ ┌─────────────┐  │
│  │  Nginx    │→│  FastAPI    │  │
│  │ (静态+代理)│ │  (API)      │  │
│  └───────────┘ └─────────────┘  │
└─────────────────────────────────┘
              ↓
┌─────────────────────────────────┐
│      PostgreSQL + pgvector      │
└─────────────────────────────────┘
```

### 前后端分离部署

```
┌─────────────┐     ┌─────────────┐
│  CDN/Vercel │     │ Docker API  │
│  (Frontend) │ ──→ │ (Backend)   │
│    :443     │     │   :8000     │
└─────────────┘     └─────────────┘
```

---

## 相关文档

- [项目结构](project-structure.md)
- [数据库管理](database.md)
- [外部 API](external-api.md)
- [前端部署](frontend-deploy.md)
