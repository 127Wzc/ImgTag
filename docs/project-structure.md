# 项目结构

```
ImgTag/
├── src/imgtag/              # Python 后端
│   ├── api/                 # API 端点
│   │   └── endpoints/       # 路由处理器
│   ├── core/                # 核心配置
│   ├── db/                  # 数据库
│   │   └── repositories/    # 数据访问层
│   ├── schemas/             # Pydantic 模型
│   └── services/            # 业务服务
├── web/                     # Vue 3 前端
│   ├── src/
│   │   ├── api/             # API 调用 (TanStack Query)
│   │   ├── components/      # 公共组件
│   │   │   ├── ui/          # Shadcn-Vue 基础组件
│   │   │   └── layout/      # 布局组件
│   │   ├── pages/           # 页面组件
│   │   ├── stores/          # Pinia 状态管理
│   │   └── types/           # TypeScript 类型
│   └── package.json
├── docs/                    # 文档
├── uploads/                 # 图片存储目录
├── docker/                  # Docker 相关文件
│   ├── Dockerfile           # Docker 镜像（多阶段构建）
│   └── docker-compose.yml   # Docker Compose 示例
└── pyproject.toml           # Python 项目配置
```

## 技术栈

**后端**：
- FastAPI - Web 框架
- PostgreSQL + pgvector - 向量数据库
- Sentence Transformers / ONNX - 本地嵌入模型

**前端**：
- Vue 3 + Composition API + TypeScript
- Shadcn-Vue + Radix Vue - UI 组件
- Tailwind CSS 4 - 样式系统
- TanStack Query - 数据获取
- Pinia - 状态管理
- Vite - 构建工具
