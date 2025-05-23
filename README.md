# ImgTag 图像向量搜索系统API

一个基于向量数据库的图像标签和描述搜索系统API，使用 BAAI/bge-small-zh-v1.5 模型生成中文文本的向量表示，并通过FastAPI提供RESTful API服务。

## 项目结构

```
ImgTag/
├── app/                    # 应用程序包
│   ├── api/                # API相关代码
│   │   ├── endpoints/      # API端点
│   │   │   ├── images.py   # 图像相关API
│   │   │   ├── search.py   # 搜索相关API
│   │   │   └── system.py   # 系统相关API
│   │   └── api_v1.py       # API路由注册
│   ├── core/               # 核心配置
│   │   ├── config.py       # 配置设置
│   │   └── logging_config.py # 日志配置
│   ├── db/                 # 数据库操作
│   │   └── pg_vector.py    # PostgreSQL向量数据库操作
│   ├── models/             # 数据模型
│   │   └── image.py        # 图像数据模型
│   └── services/           # 服务
│       └── text_embedding.py # 文本向量嵌入服务
├── main.py                 # 应用入口点
├── requirements.txt        # 项目依赖
└── .env.example            # 环境变量示例
```

## 功能特点

- RESTful API设计，采用FastAPI框架
- 使用 BAAI/bge-small-zh-v1.5 模型生成中文文本向量
- 支持文本描述和标签的组合向量生成
- 基于 PostgreSQL pgvector 扩展的向量数据库存储
- 支持标签搜索和向量相似度搜索
- 完整的API文档（Swagger和ReDoc）
- 完整的日志记录和性能监控

## 安装说明

### 前提条件

- Python 3.8+
- PostgreSQL 数据库（已安装 pgvector 扩展）

### 安装步骤

1. 克隆仓库
```bash
git clone https://github.com/yourusername/ImgTag.git
cd ImgTag
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置数据库连接
将 `.env.example` 文件复制为 `.env`，并修改数据库连接信息：
```
PG_CONNECTION_STRING=postgres://username:password@hostname:port/database
```

## 使用方法

### 启动API服务

```bash
python main.py
```

服务将在 http://localhost:8000 启动，可以通过以下URL访问API文档：
- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc

### API端点

API服务提供以下主要端点：

**图像操作**
- `POST /api/v1/images/`：创建图像记录
- `POST /api/v1/images/search/tags/`：通过标签搜索图像
- `PUT /api/v1/images/{image_id}/tags/`：更新图像标签

**搜索操作**
- `POST /api/v1/search/similar/`：相似度搜索

**系统操作**
- `GET /api/v1/system/status/`：获取系统状态
- `GET /api/v1/system/health/`：健康检查

### API使用示例

以下是使用cURL工具的API使用示例：

**创建图像记录**
```bash
curl -X 'POST' \
  'http://localhost:8000/api/v1/images/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "image_url": "https://example.com/image1.jpg",
  "tags": ["自然", "山脉", "日落"],
  "description": "壮丽的自然风景，包括高耸的山脉和美丽的日落景观"
}'
```

**通过标签搜索图像**
```bash
curl -X 'POST' \
  'http://localhost:8000/api/v1/images/search/tags/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "tags": ["自然", "山脉"],
  "limit": 5
}'
```

**相似度搜索**
```bash
curl -X 'POST' \
  'http://localhost:8000/api/v1/search/similar/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "美丽的自然风景和高山",
  "tags": ["自然", "风景"],
  "limit": 5,
  "threshold": 0.7
}'
```

**获取系统状态**
```bash
curl -X 'GET' \
  'http://localhost:8000/api/v1/system/status/' \
  -H 'accept: application/json'
```

## 部署

### Docker部署
通过Docker部署，可以创建Dockerfile和docker-compose.yml文件。

### 服务器部署
可以使用Gunicorn结合Uvicorn作为生产环境部署：

```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
```

## 性能优化

系统已内置性能监控，所有关键操作都会记录执行时间。可以通过查看日志了解系统性能，并针对性进行优化。

## 许可证

MIT 