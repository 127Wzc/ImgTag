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

### 旧库字段补齐

生产环境从 `0006_mcp_hardening` 直接升级到 `0007_subject_workflow`。

0007 创建多主体当前关联、主体提炼模板、图片与主体的历史表、识别备注和封面字段，并直接使用最终的历史状态默认值。已有主体描述保留为当前资料；用户自定义提示词不覆盖。缺少 `image_subjects.synced_primary_tag_id` 的旧 0005 库也会补齐字段及 `ON DELETE SET NULL` 外键，不推断历史标签归属。

应用启动时自动执行迁移，也可运行 `uv run alembic upgrade head`。本地已执行过开发迁移的库，必须先核实实际字段、外键、索引和默认值与合并后的 0007 一致，再将版本标识修正为 `0007_subject_workflow`；不要对这种库重新执行 0007 的建表步骤。
迁移验证应同时核对实际表结构与模型字段，不能只检查版本号和数据行数。
PostgreSQL 回归测试使用隔离 schema 并回滚：

```bash
IMGTAG_TEST_POSTGRES=1 uv run pytest tests/subjects/test_postgres.py -q
```

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

## 异常向量检测与修复

管理员可在“系统设置 → 系统维护 → 异常向量检测”分页查看有非空描述或可用标签，但向量缺失、全零/无效或维度与当前配置不符的图片。可用标签包含分类与普通标签，不包含分辨率标签；没有这些内容的图片不列为异常。

点击单张图片的“重建向量”后，任务队列使用当前描述和标签重新生成搜索向量，不调用视觉分析。页面展示重建状态，成功后重新检测并刷新列表，失败可查看任务后重试。检测只检查向量的结构有效性，不能判断维度相同的旧向量是否来自其他模型，或其语义是否与图片内容一致。

配置维度与数据库维度不一致时，需先在“向量嵌入”设置中处理维度配置，单张重建不会调整数据库结构或清空其他图片的向量。

## 连接池与同步参数

以下环境变量适用于 PostgreSQL。每个应用进程独立维护连接池，默认最多 5 个连接；
多进程、多副本部署时，连接上限按各进程的 `DB_POOL_SIZE + DB_MAX_OVERFLOW` 累加。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DB_POOL_SIZE` | 5 | 连接池容量，至少 1 |
| `DB_MAX_OVERFLOW` | 0 | 额外连接上限，0 表示不扩容 |
| `DB_POOL_TIMEOUT` | 30 | 等待可用连接的超时秒数 |
| `DB_POOL_RECYCLE` | 600 | 连接借出时超过此年龄则重建，单位秒 |
| `DB_POOL_PRE_PING` | true | 借出前检查连接健康 |
| `STORAGE_SYNC_CONCURRENCY` | 2 | 同时运行的手动同步批次数 |
| `STORAGE_SYNC_DB_MAX_ATTEMPTS` | 5 | 临时数据库异常最大尝试次数，包含首次 |
| `STORAGE_SYNC_DB_RETRY_DELAY` | 2 | 初始退避秒数，逐次翻倍，基础等待最多 30 秒，另加随机抖动 |

Compose 示例支持在其 `.env` 文件中设置上述参数。修改后重新创建容器生效：

```bash
docker compose up -d --force-recreate imgtag
```
