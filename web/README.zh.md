# ImgTag Web

Vue 3 + TypeScript + Vite 前端应用。

## 开发

```bash
pnpm install
pnpm dev
```

## 构建

```bash
pnpm build
```

## 配置

复制 `.env.example` 到 `.env`：

```bash
# 后端 API
VITE_API_BASE_URL=https://your-backend.example.com

# 分析统计（可选）
VITE_UMAMI_WEBSITE_ID=xxx
VITE_UMAMI_HOST=https://analytics.example.com
VITE_GA_MEASUREMENT_ID=G-XXXXXXXXXX
```

## 分析统计

基于 [analytics](https://getanalytics.io/) 的可扩展分析系统。

| 平台 | 环境变量 |
|------|----------|
| Umami | `VITE_UMAMI_WEBSITE_ID` + `VITE_UMAMI_HOST` |
| Google Analytics 4 | `VITE_GA_MEASUREMENT_ID` |

### 使用

```typescript
import { useAnalytics } from '@/composables/useAnalytics'

const { trackEvent } = useAnalytics()
trackEvent('image_upload', { source: 'button' })
```

特性：异步加载、自动页面追踪（Umami）、可扩展。
