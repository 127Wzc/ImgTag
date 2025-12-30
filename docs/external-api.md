# ImgTag 外部 API 参考文档

外部 API 用于第三方系统接入，使用个人 API 密钥进行认证。

## 认证方式

在个人中心生成 API 密钥后，可通过以下两种方式传递：

```bash
# 方式一：Query 参数
curl "http://your-domain/api/v1/random?api_key=YOUR_API_KEY"

# 方式二：Header
curl -H "api_key: YOUR_API_KEY" "http://your-domain/api/v1/random"
```

---

## 接口列表

### 1. 获取随机图片

**GET** `/api/v1/random`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tags` | array | 否 | 标签筛选（AND 关系） |
| `count` | int | 否 | 返回数量，默认 1，最大 50 |
| `include_full_url` | bool | 否 | 是否拼接 base_url，默认 true |
| `api_key` | string | 否 | API 密钥 |

**响应示例：**
```json
{
  "images": [
    {
      "id": 123,
      "url": "https://example.com/uploads/image.jpg",
      "description": "图片描述",
      "tags": ["标签1", "标签2"]
    }
  ],
  "count": 1
}
```

---

### 2. 通过 URL 添加图片

**POST** `/api/v1/add-image`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image_url` | string | **是** | 图片 URL |
| `tags` | array | 否 | 初始标签列表 |
| `description` | string | 否 | 图片描述 |
| `category_id` | int | 否 | 主分类 ID |
| `endpoint_id` | int | 否 | 存储端点 ID（默认使用系统默认端点） |
| `auto_analyze` | bool | 否 | 是否自动 AI 分析，默认 true |
| `callback_url` | string | 否 | 分析完成后的回调 URL |

**请求示例：**
```bash
curl -X POST "http://your-domain/api/v1/add-image?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://example.com/image.jpg",
    "category_id": 1,
    "auto_analyze": true,
    "callback_url": "https://your-server.com/webhook/imgtag"
  }'
```

**响应示例：**
```json
{
  "id": 123,
  "image_url": "https://oss.example.com/123/abc.jpg",
  "original_url": "https://example.com/image.jpg",
  "tags": [{"name": "风景", "source": "user"}],
  "description": "",
  "width": 1920,
  "height": 1080,
  "process_time": "0.85秒"
}
```

> 图片会保存到系统默认端点（可通过 `endpoint_id` 指定），如有备份端点会自动同步。

#### 回调机制

当指定 `callback_url` 时，AI 分析完成后会 POST 到该地址：

```json
{
  "image_id": 123,
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "image_url": "https://oss.example.com/123/abc.jpg",
  "tags": ["风景", "日出", "自然"],
  "description": "一张美丽的日出风景照片...",
  "width": 1920,
  "height": 1080,
  "error": null
}
```

| 字段 | 说明 |
|------|------|
| `image_id` | 图片 ID |
| `task_id` | 任务 ID（用于追踪） |
| `success` | 分析是否成功 |
| `image_url` | 图片访问 URL |
| `tags` | AI 生成的标签列表 |
| `description` | AI 生成的图片描述 |
| `width` / `height` | 图片尺寸 |
| `error` | 失败时的错误信息（成功时为 null） |

---

### 3. 获取图片详情

**GET** `/api/v1/image/{image_id}`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image_id` | int | **是** | 图片 ID（路径参数） |
| `api_key` | string | 否 | API 密钥 |

**请求示例：**
```bash
curl "http://your-domain/api/v1/image/123?api_key=YOUR_KEY"
```

**响应示例：**
```json
{
  "id": 123,
  "url": "/uploads/abc123.jpg",
  "description": "图片描述",
  "tags": ["标签1", "标签2"],
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

### 4. 搜索图片

**GET** `/api/v1/search`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keyword` | string | 否 | 关键词搜索（描述） |
| `tags` | array | 否 | 标签筛选 |
| `limit` | int | 否 | 返回数量，默认 20，最大 100 |
| `offset` | int | 否 | 分页偏移，默认 0 |
| `api_key` | string | 否 | API 密钥 |

**请求示例：**
```bash
# 无参数搜索
curl "http://your-domain/api/v1/search?api_key=YOUR_KEY&limit=10"

# 关键词搜索（中文需 URL 编码）
curl "http://your-domain/api/v1/search?api_key=YOUR_KEY&keyword=%E5%88%9D%E9%9F%B3"

# 标签筛选
curl "http://your-domain/api/v1/search?api_key=YOUR_KEY&tags=%E5%8F%AF%E7%88%B1"
```

**响应示例：**
```json
{
  "images": [
    {
      "id": 123,
      "image_url": "/uploads/abc.jpg",
      "tags": ["可爱", "二次元"],
      "description": "图片描述",
      "source_type": "local",
      "original_url": null
    }
  ],
  "total": 100,
  "limit": 20,
  "offset": 0
}
```

---

## 错误响应

| 状态码 | 说明 |
|--------|------|
| 401 | 无效的 API 密钥 / 需要 API 密钥 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

错误响应格式：
```json
{
  "detail": "错误信息"
}
```
