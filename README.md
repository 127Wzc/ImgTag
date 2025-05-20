# ImgTag 图像向量搜索系统

一个基于向量数据库的图像标签和描述搜索系统，使用 BAAI/bge-small-zh-v1.5 模型生成中文文本的向量表示。

## 项目结构

```
ImgTag/
├── config.py               # 配置文件
├── logging_config.py       # 日志配置
├── text_embedding.py       # 文本向量嵌入工具
├── pg_vector_operations.py # PostgreSQL向量数据库操作
├── vector_search_example.py # 向量搜索示例
└── README.md               # 项目说明
```

## 功能特点

- 使用 BAAI/bge-small-zh-v1.5 模型生成中文文本向量
- 支持文本描述和标签的组合向量生成
- 基于 PostgreSQL pgvector 扩展的向量数据库存储
- 支持标签搜索和向量相似度搜索
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
在项目根目录创建 `.env` 文件，添加数据库连接信息：
```
PG_CONNECTION_STRING=postgres://username:password@hostname:port/database?sslmode=require
```

4. 创建数据库表
```bash
psql -U your_username -d your_database -f create_tables.sql
```

## 使用方法

### 运行示例程序

```bash
python vector_search_example.py
```

示例程序将：
1. 检查数据库中是否已有足够的示例数据
2. 如果数据不足，生成示例数据
3. 执行标签搜索和向量相似度搜索
4. 显示搜索结果和性能统计

### 在自己的项目中使用

```python
from text_embedding import TextEmbedding
from pg_vector_operations import PGVectorDB

# 初始化文本向量化工具
text_embedding = TextEmbedding()

# 生成文本向量
text = "这是一段需要转换为向量的中文文本"
embedding = text_embedding.get_embedding(text)

# 生成文本+标签组合向量
tags = ["自然", "风景"]
combined_embedding = text_embedding.get_embedding_combined(text, tags)

# 数据库操作
db = PGVectorDB()

# 插入图像记录
db.insert_image(
    image_url="https://example.com/image.jpg",
    tags=["自然", "风景", "山脉"],
    embedding=combined_embedding,
    description="美丽的自然风景照片"
)

# 标签搜索
results = db.search_by_tags(["自然", "风景"])

# 向量相似度搜索
similar_results = db.search_similar_vectors(combined_embedding)
```

## 性能优化

系统已内置性能监控，所有关键操作都会记录执行时间。可以通过查看日志了解系统性能，并针对性进行优化。

## 许可证

MIT 