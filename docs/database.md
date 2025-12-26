# 数据库管理指南

## 首次初始化

### 1. 配置连接
编辑 `.env` 文件，设置 PostgreSQL 连接：
```env
PG_CONNECTION_STRING=postgresql://user:password@localhost:5432/imgtag
```

### 2. 执行迁移
```bash
# 创建所有表
uv run alembic upgrade head
```

### 3. 验证
```bash
uv run python scripts/test_db_init.py
```

---

## 修改数据库结构

### 步骤
1. **修改 ORM 模型**：编辑 `src/imgtag/models/*.py`
2. **生成迁移脚本**：
   ```bash
   uv run alembic revision --autogenerate -m "描述你的更改"
   ```
3. **检查生成的脚本**：`src/imgtag/alembic/versions/` 下的新文件
4. **执行迁移**：
   ```bash
   uv run alembic upgrade head
   ```

### 回滚
```bash
# 回退一个版本
uv run alembic downgrade -1

# 回退到指定版本
uv run alembic downgrade <revision_id>
```

---

## 常用命令

| 命令 | 说明 |
|------|------|
| `uv run alembic upgrade head` | 升级到最新 |
| `uv run alembic downgrade -1` | 回退一版 |
| `uv run alembic current` | 查看当前版本 |
| `uv run alembic history` | 查看迁移历史 |
| `uv run alembic stamp head` | 标记现有库为最新（跳过迁移） |

---

## 生产部署

### Docker 启动时自动迁移
在 `docker-compose.yml` 或启动脚本中：
```bash
uv run alembic upgrade head && uv run python -m uvicorn imgtag.main:app
```

### 已有数据库首次接入 Alembic
```bash
# 标记为已迁移（不执行任何 DDL）
uv run alembic stamp head
```
