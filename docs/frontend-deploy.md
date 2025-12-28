# ImgTag 前端部署指南

本指南介绍如何将 ImgTag 前端独立部署到 CDN 平台（Cloudflare Pages、Vercel、Netlify）。

## 前提条件

- 已部署后端 API 服务（使用 `-backend` 或 `-backend-local` 镜像）
- 后端已配置 CORS 允许前端域名

## 环境变量

| 变量 | 说明 | 示例 |
|-----|------|------|
| `VITE_API_BASE_URL` | 后端地址（仅域名，不带路径） | `https://api.example.com` |

> 代码会自动追加 `/api/v1`，无需手动添加

---

## Cloudflare Pages

### 方式一：连接 Git 仓库

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. 进入 **Pages** → **Create a project** → **Connect to Git**
3. 选择仓库，配置构建设置：

| 设置项 | 值 |
|-------|-----|
| 根目录 | `web` |
| 构建命令 | `pnpm install && pnpm build` |
| 输出目录 | `dist` |

4. 添加环境变量：`VITE_API_BASE_URL = https://your-api.example.com`

### 方式二：直接上传

```bash
cd web
pnpm install
VITE_API_BASE_URL=https://your-api.example.com pnpm build
# 将 dist 目录上传到 Cloudflare Pages
```

---

## Vercel

### 方式一：一键部署

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/127Wzc/ImgTag&root-directory=web)

### 方式二：CLI 部署

```bash
cd web
pnpm install
npx vercel --prod
```

### 项目设置

| 设置项 | 值 |
|-------|-----|
| 根目录 | `web` |
| Framework Preset | Vite |
| 构建命令 | `pnpm build` |
| 输出目录 | `dist` |
| 环境变量 | `VITE_API_BASE_URL=https://your-api.example.com` |

---

## Netlify

### 方式一：连接 Git 仓库

1. 登录 [Netlify](https://app.netlify.com/)
2. **Add new site** → **Import an existing project**
3. 选择仓库，配置构建设置：

| 设置项 | 值 |
|-------|-----|
| Base directory | `web` |
| Build command | `pnpm install && pnpm build` |
| Publish directory | `web/dist` |

4. 添加环境变量：`VITE_API_BASE_URL`

### 方式二：使用配置文件

在 `web/` 目录创建 `netlify.toml`：

```toml
[build]
  base = "web"
  command = "pnpm install && pnpm build"
  publish = "dist"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

---

## 架构示意

```
用户浏览器
    │
    ├──→ CDN (前端静态页面)
    │     Cloudflare Pages / Vercel / Netlify
    │
    ├──→ S3 / R2 (图片存储，可选)
    │
    └──→ 你的服务器 (后端 API)
          使用 imgtag:latest-backend 镜像
```

---

## 常见问题

### Q: 环境变量不生效

Vite 环境变量必须以 `VITE_` 前缀开头，且需要**重新构建**才能生效。
