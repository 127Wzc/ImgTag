# ImgTag 外部 API 参考

> 外部 API 用于第三方系统接入，支持 REST API、OpenAI Function Calling 和 MCP 协议。

## 目录

- [快速开始](#快速开始)
- [认证方式](#认证方式)
- [REST API](#rest-api)
  - [获取随机图片](#1-获取随机图片)
  - [添加图片](#2-添加图片)
  - [获取图片详情](#3-获取图片详情)
  - [搜索图片](#4-搜索图片)
- [AI 集成](#ai-集成)
  - [OpenAI Tools Schema](#openai-tools-schema)
  - [MCP 配置](#mcp-配置)
- [错误处理](#错误处理)

---

## 快速开始

```bash
# 获取随机图片
curl "http://your-domain/api/v1/external/images/random?api_key=YOUR_KEY&count=1"

# 搜索图片
curl "http://your-domain/api/v1/external/images/search?api_key=YOUR_KEY&keyword=风景"

# 添加图片
curl -X POST "http://your-domain/api/v1/external/images" \
  -H "api_key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"image_url": "https://example.com/image.jpg"}'
```

---

## 认证方式

> [!IMPORTANT]
> 所有 API 请求都需要携带 API 密钥。在「用户中心」生成密钥后，通过以下两种方式传递：

**方式一：Query 参数**
```
GET /api/v1/external/images/random?api_key=YOUR_API_KEY
```

**方式二：Header**
```
api_key: YOUR_API_KEY
```

---

## REST API

**Base URL**: `http://your-domain/api/v1/external`

| 端点 | 方法 | 说明 |
|------|------|------|
| `/images/random` | GET | 随机获取图片 |
| `/images` | POST | 添加图片（支持 AI 分析） |
| `/images/{id}` | GET | 获取图片详情 |
| `/images/search` | GET | 搜索图片 |

---

### 1. 获取随机图片

`GET /images/random`

#### 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `tags` | array | 否 | `[]` | 标签筛选（AND 关系） |
| `count` | int | 否 | `1` | 返回数量，最大 50 |

> 返回范围：公开图片 + 本人上传的图片（admin 无限制）。

#### 示例

```bash
curl "http://your-domain/api/v1/external/images/random?api_key=YOUR_KEY&tags=风景&count=3"
```

#### 响应

```json
{
  "images": [
    {
      "id": 123,
      "url": "https://oss.example.com/abc.jpg",
      "description": "美丽的日落风景",
      "tags": ["风景", "日落"]
    }
  ],
  "count": 1
}
```

---

### 2. 添加图片

`POST /images`

#### 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `image_url` | string | **是** | - | 图片 URL |
| `tags` | array | 否 | `[]` | 用户标签 |
| `description` | string | 否 | `""` | 图片描述 |
| `category_id` | int | 否 | - | 主分类 ID |
| `auto_analyze` | bool | 否 | `true` | 是否 AI 分析 |
| `callback_url` | string | 否 | - | 分析完成回调 URL |
| `is_public` | bool | 否 | `true` | 是否公开 |

> [!TIP]
> 同时提供 `tags` 和 `description` 时会跳过 AI 分析，只生成向量嵌入（更快）。

#### 示例

```bash
# AI 自动分析
curl -X POST "http://your-domain/api/v1/external/images" \
  -H "api_key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://example.com/image.jpg",
    "auto_analyze": true,
    "callback_url": "https://your-server.com/webhook"
  }'

# 跳过 AI 分析（手动提供标签）
curl -X POST "http://your-domain/api/v1/external/images" \
  -H "api_key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://example.com/image.jpg",
    "tags": ["风景", "日落"],
    "description": "美丽的海边日落"
  }'
```

#### 响应

```json
{
  "id": 123,
  "image_url": "https://oss.example.com/abc.jpg",
  "original_url": "https://example.com/image.jpg",
  "tags": [{"name": "风景", "source": "user"}],
  "description": "美丽的海边日落",
  "width": 1920,
  "height": 1080,
  "skip_analyze": false,
  "process_time": "0.85秒"
}
```

#### 回调通知

当指定 `callback_url` 时，AI 分析完成后会 POST 到该地址：

```json
{
  "image_id": 123,
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "image_url": "https://oss.example.com/abc.jpg",
  "tags": ["风景", "日出", "自然"],
  "description": "一张美丽的日出风景照片...",
  "error": null
}
```

---

### 3. 获取图片详情

`GET /images/{id}`

#### 示例

```bash
curl "http://your-domain/api/v1/external/images/123?api_key=YOUR_KEY"
```

#### 响应

```json
{
  "id": 123,
  "url": "https://oss.example.com/abc.jpg",
  "description": "图片描述",
  "tags": ["标签1", "标签2"],
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

### 4. 搜索图片

`GET /images/search`

#### 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `keyword` | string | 否 | - | 关键词搜索 |
| `tags` | array | 否 | `[]` | 标签筛选 |
| `page` | int | 否 | `1` | 页码 |
| `size` | int | 否 | `20` | 每页数量，最大 100 |

#### 示例

```bash
# 关键词搜索
curl "http://your-domain/api/v1/external/images/search?api_key=YOUR_KEY&keyword=风景&size=10"

# 标签筛选
curl "http://your-domain/api/v1/external/images/search?api_key=YOUR_KEY&tags=可爱&page=1"
```

#### 响应

```json
{
  "data": [
    {
      "id": 123,
      "image_url": "https://oss.example.com/abc.jpg",
      "description": "图片描述",
      "tags": ["可爱", "二次元"],
      "created_at": "2024-01-01T12:00:00Z"
    }
  ],
  "total": 100,
  "page": 1,
  "size": 20,
  "pages": 5,
  "has_next": true,
  "has_prev": false
}
```

---

## AI 集成

### OpenAI Tools Schema

支持 OpenAI / Claude / Gemini 等模型的 Function Calling。

<details>
<summary><b>📋 完整 Tools Schema（点击展开）</b></summary>

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_random_images",
        "description": "从图库中随机获取符合条件的图片。支持按标签筛选，标签之间是 AND 关系。",
        "parameters": {
          "type": "object",
          "properties": {
            "tags": {
              "type": "array",
              "items": {"type": "string"},
              "description": "标签筛选列表"
            },
            "count": {
              "type": "integer",
              "minimum": 1,
              "maximum": 50,
              "default": 1,
              "description": "返回图片数量"
            }
          }
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "add_image",
        "description": "从 URL 添加图片到图库，可选择是否进行 AI 自动分析。",
        "parameters": {
          "type": "object",
          "properties": {
            "image_url": {
              "type": "string",
              "format": "uri",
              "description": "图片 URL"
            },
            "tags": {
              "type": "array",
              "items": {"type": "string"},
              "description": "用户自定义标签"
            },
            "description": {
              "type": "string",
              "description": "图片描述"
            },
            "category_id": {
              "type": "integer",
              "description": "主分类 ID"
            },
            "auto_analyze": {
              "type": "boolean",
              "default": true,
              "description": "是否启用 AI 分析"
            },
            "callback_url": {
              "type": "string",
              "format": "uri",
              "description": "分析完成回调 URL"
            }
          },
          "required": ["image_url"]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "search_images",
        "description": "搜索图库中的图片，支持关键词和标签筛选。",
        "parameters": {
          "type": "object",
          "properties": {
            "keyword": {
              "type": "string",
              "description": "搜索关键词"
            },
            "tags": {
              "type": "array",
              "items": {"type": "string"},
              "description": "标签筛选列表"
            },
            "page": {
              "type": "integer",
              "minimum": 1,
              "default": 1,
              "description": "页码"
            },
            "size": {
              "type": "integer",
              "minimum": 1,
              "maximum": 100,
              "default": 20,
              "description": "每页数量"
            }
          }
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "get_image_detail",
        "description": "获取指定图片的详细信息。",
        "parameters": {
          "type": "object",
          "properties": {
            "image_id": {
              "type": "integer",
              "description": "图片 ID"
            }
          },
          "required": ["image_id"]
        }
      }
    }
  ]
}
```

</details>

#### 使用示例

```python
import json
import httpx
from openai import OpenAI

# 配置
IMGTAG_API_BASE = "http://your-domain/api/v1/external"
IMGTAG_API_KEY = "your-api-key"

client = OpenAI()

# 定义 tools（完整 schema 见上方折叠块）
tools = [...]

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "帮我搜索风景图片"}],
    tools=tools,
    tool_choice="auto"
)

# 处理 tool 调用
if response.choices[0].message.tool_calls:
    tool_call = response.choices[0].message.tool_calls[0]
    func_name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)
    
    # 调用 ImgTag API
    if func_name == "search_images":
        result = httpx.get(
            f"{IMGTAG_API_BASE}/images/search",
            params=args,
            headers={"api_key": IMGTAG_API_KEY}
        ).json()
```

---

### MCP 配置

ImgTag 内置 MCP Server，同时支持两代传输协议（共享同一套工具与权限逻辑）：

- **Streamable HTTP**（现行标准，推荐）：单端点 POST，无状态，兼容负载均衡与标准限流；
- **HTTP+SSE**（2024-11-05 旧协议，已被官方弃用）：保留给尚未升级的旧客户端。

| 端点 | 传输 | 认证 | 工具 | 数据可见性 |
|------|------|------|------|-----------|
| `POST /api/v1/mcp` | Streamable HTTP | 强制 API Key | 全部（写工具按用户权限过滤） | public + 本人上传；admin 无限制 |
| `POST /api/v1/mcp/public` | Streamable HTTP | API Key 可选 | 仅只读工具 | 匿名：仅 public；带 Key：public + 本人上传（工具仍只读） |
| `GET /api/v1/mcp/sse` | HTTP+SSE（兼容） | 强制 API Key | 同上全功能 | 同上 |
| `GET /api/v1/mcp/public/sse` | HTTP+SSE（兼容） | API Key 可选 | 同上只读 | 同上 |

**支持的 Tools：**
| Tool | 只读 | 说明 |
|------|------|------|
| `search_images` | 是 | 图库检索：不传条件随机抽取；tags 标签筛选（AND 硬过滤）；keyword 关键词搜索（语义向量 / 模糊匹配）；`sort=latest` 支持分页浏览 |
| `get_image_detail` | 是 | 获取图片详情（含可见性校验） |
| `add_image` | 否 | 从 URL 添加图片（支持 AI 分析），需要「上传图片」权限 |

**`search_images` 参数：**
| 参数 | 类型 / 默认 | 说明 |
|------|------------|------|
| `keyword` | string | 搜索词。不传时进入随机抽取模式 |
| `tags` | string[] | 标签名列表（AND 关系，所有模式下硬过滤） |
| `match` | `auto` / `semantic` / `fuzzy`，默认 `auto` | keyword 匹配方式：semantic=语义向量；fuzzy=描述/标签名子串；auto=优先语义、失败降级模糊 |
| `sort` | `auto` / `random` / `latest` / `relevance`，默认 `auto` | auto=有 keyword 按相关度、无 keyword 随机；latest=最新排序（唯一支持分页）；random 仅无 keyword 时有效 |
| `count` | int 1-50，默认 10 | 返回数量（latest 模式下为每页数量） |
| `page` | int ≥1，默认 1 | 页码，仅 `sort=latest` 时生效 |

**端点地址：**
```
推荐（Streamable HTTP）:
  全功能:   http://your-server:8000/api/v1/mcp?api_key=YOUR_KEY
  公共只读: http://your-server:8000/api/v1/mcp/public                    （匿名，仅公开图片）
  公共只读: http://your-server:8000/api/v1/mcp/public?api_key=YOUR_KEY   （公开 + 本人上传）

兼容（HTTP+SSE，已弃用，仅供旧客户端）:
  全功能:   http://your-server:8000/api/v1/mcp/sse?api_key=YOUR_KEY
  公共只读: http://your-server:8000/api/v1/mcp/public/sse
```

> 新客户端会自动探测传输协议：POST initialize 成功即 Streamable HTTP；失败（4xx）则回退旧 SSE。
> 旧 SSE 公共端点对匿名连接数设有上限（默认 20），超出返回 `429`；Streamable HTTP 无长连接，不受此限制。

#### 客户端配置

**方式一：直接 HTTP 连接（Cursor 等支持远程 MCP 的客户端）**

```json
{
  "mcpServers": {
    "imgtag": {
      "url": "http://your-server:8000/api/v1/mcp?api_key=YOUR_KEY"
    }
  }
}
```

> 接入公共只读端点时，将 `url` 换成 `/api/v1/mcp/public`，`api_key` 可省略（省略后仅能访问公开图片）。
> 仅支持旧协议的客户端可继续使用 `/api/v1/mcp/sse` 并声明 `"transport": "sse"`。

**方式二：使用 mcp-remote 代理（仅支持 stdio 的客户端，如部分版本 Claude Desktop）**

```bash
npx -y mcp-remote http://your-server:8000/api/v1/mcp?api_key=YOUR_KEY
```

Claude Desktop 配置（`~/.claude/claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "imgtag": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://your-server:8000/api/v1/mcp?api_key=YOUR_KEY"
      ]
    }
  }
}
```

---

## 错误处理

| 状态码 | 说明 |
|--------|------|
| `401` | 无效的 API 密钥 |
| `404` | 资源不存在 |
| `422` | 参数验证失败 |
| `500` | 服务器内部错误 |

**错误响应格式：**

```json
{
  "detail": "错误信息"
}
```
