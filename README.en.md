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
