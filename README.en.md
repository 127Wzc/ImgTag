<p align="center">
  <img src="docs/logo.png" alt="ImgTag" width="120" />
</p>

<h1 align="center">ImgTag</h1>

<p align="center">AI-Powered Image Tagging and Vector Search System</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License" /></a>
  <img src="https://img.shields.io/badge/Python-3.10+-green.svg" alt="Python" />
  <img src="https://img.shields.io/badge/Vue-3-brightgreen.svg" alt="Vue" />
</p>

<p align="center">
  <a href="README.md">中文</a> | English
</p>

## ✨ Features

- 🤖 **AI Smart Tagging** - Supports OpenAI, Gemini vision models (OpenAI-compatible API)
- 🔍 **Semantic Vector Search** - Find similar images by text description
- 💾 **Multi-Endpoint Storage** - Local + S3-compatible with auto backup
- 📁 **Collections** - Hierarchical folders with auto-tagging
- 🏷️ **Tag System** - Source tracking (AI/User), usage statistics
- 👥 **User Auth** - JWT authentication, admin approval, role-based access
- ⚡ **Batch Operations** - Bulk upload, delete, tag, and analyze

> Default admin: `admin` / `admin123`

---

<details>
<summary><b>📸 Screenshots (Click to expand)</b></summary>

### 🏠 Dashboard - Overview & Statistics

![Dashboard](docs/screenshots/dashboard.png)

Real-time display of total images, pending analysis queue, today's uploads/analysis stats. Tag usage Top rankings at a glance.

---

### 🖼️ My Files - Image Management & Filtering

![My Files](docs/screenshots/my-files.png)

Filter by category, resolution, keywords. Inline tag editing, batch selection for one-click tagging or deletion.

---

### 🔍 Image Detail - AI Description & Tags

![Image Detail](docs/screenshots/image-detail.png)

View AI-generated descriptions, tag sources (AI/User), image metadata. Copy image links and edit descriptions.

---

### ✨ Explore - Browse & Smart Search

![Explore](docs/screenshots/search.png)

Multi-dimensional search by tags and descriptions. Semantic search with natural language, vector similarity-based retrieval.

---

### 📤 Upload - Smart Analysis

![Upload](docs/screenshots/upload.png)

Drag & drop upload, ZIP batch import, URL fetch. Optional AI auto-analysis for tags and descriptions.

---

### 🏷️ Tag Management - Categories & Statistics

![Tags](docs/screenshots/tags.png)

Three-tier tag system: Main categories (Wallpaper/Meme etc.), Resolution (4K/2K etc.), Normal tags. Usage count and source tracking.

---

### 💾 Storage Endpoints - Multi-Endpoint Config

![Storage](docs/screenshots/storage.png)

Local storage and S3-compatible endpoints (MinIO, AWS S3, etc.). Configurable primary endpoint and backup sync (auto + scheduled). Multi-endpoint load balancing.

---

### ⚙️ Settings - AI Model Configuration

![Settings](docs/screenshots/settings.png)

Configure vision models (OpenAI, Gemini, etc.), embedding models, and system parameters.

</details>

---

## 🐳 Quick Deploy

**Prerequisites**: PostgreSQL database with pgvector extension

```bash
# Download config
curl -O https://raw.githubusercontent.com/127Wzc/ImgTag/main/docker/docker-compose.yml

# Edit docker-compose.yml to set database connection
# Start service
docker-compose up -d
```

Access: http://localhost:5173

### Docker Images

| Tag | Description | Port |
|-----|-------------|------|
| `latest` | Full-stack slim (recommended) | 5173 |
| `latest-local` | Full-stack + local embedding model | 5173 |
| `latest-backend` | Backend API only | 8000 |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `PG_CONNECTION_STRING` | PostgreSQL connection string (required) |

---

## 🚀 Local Development

```bash
# Backend
cp .env.example .env && vim .env  # Configure database
uv sync && uv run uvicorn imgtag.main:app --reload --port 8000

# Frontend
cd web && pnpm install && pnpm dev
```

Access: http://localhost:5173

---

## 📋 Configuration

Manage via Web UI "System Settings":

| Module | Options |
|--------|---------|
| Vision Model | API URL, API Key, Model Name |
| Embedding Model | Local model / Online API |
| Storage Endpoints | Multi-endpoint, S3-compatible, Auto-backup |
---

## 🔌 API

📖 [Swagger Docs](http://localhost:8000/docs) | [External API Reference](docs/external-api.md)

---

## � Decoupled Deployment

To host frontend on CDN (Vercel / Cloudflare Pages):

1. Deploy backend using `latest-backend` image (port 8000)
2. See [Frontend Deploy Guide](docs/frontend-deploy.md)

For technical details, see [Architecture](docs/architecture.md)

---

## 📄 License

[MIT](LICENSE)
