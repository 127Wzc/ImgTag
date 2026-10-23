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

### 搜索索引升级

`0008_search_indexes` 添加标签反向索引并删除两个历史 IVFFlat 索引，描述、标签和向量数据不变。迁移使用并发索引操作，建议低峰升级；中断后可重新执行。

HNSW 默认关闭，需要 pgvector 0.8 及以上版本、向量维度不超过 2000。管理员在“向量嵌入”中开启并保存后，首次手动构建，已有索引自动复用；高级设置支持强制重建。索引未就绪时使用精确搜索。关闭开关保留索引，向量写入仍会维护它。

构建和重建在线执行，需要数据库账号具有建索引权限；不调用模型，但会增加服务器负载，建议低峰操作。单次等锁超过 30 秒会停止维护，待相关长事务结束后可在页面重试；重试会清理失败残留的无效索引。搜索精度默认 40，实际值不低于每页数量，候选数量自动推导，无需重建索引即可调整。

智能搜索仅返回第一页，最多 50 张，`total` 是本次返回数量；HTTP 接口拒绝 `page>1` 或 `size>50`，MCP 语义搜索拒绝 `page>1`（默认返回 10 张）。普通图库及显式模糊搜索保留分页。主动选择的标签为 AND 筛选，语义阈值只约束向量分，标签命中可独立入选；纯筛选不调用模型。HNSW 结果可能与精确搜索不同。

搜索开关、精度和索引可用性每次合并为一次查询，配置保存后无需重启；索引大小、构建进度和维护错误仅在管理入口查询。

排查搜索性能时设置 `LOG_LEVEL=DEBUG` 并重启应用（Compose 需重新创建容器），在控制台或 `logs/api.log` 中按 `imgtag.search`、`trace` 查看各 `stage` 的 `elapsed_ms`、检索模式及返回数量。阶段耗时包含连接等待、SQL 执行和结果取回；`embedding`、`retrieval` 是包含内部阶段的汇总，不要与子阶段重复相加。`total` 从搜索处理函数开始计时，不含认证依赖和最终响应序列化。默认 INFO 不输出阶段日志，新增日志不记录搜索原文、向量和 SQL 参数。日志格式集中在 `core/logging_config.py`，应用与请求日志统一采用“时间 - 模块 - 等级 - 行为”格式；请求摘要为“请求完成: method=… path=… status=… client=… protocol=…”。性能日志合并至 `logs/api.log`，不再写入 `performance.log`。

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

## 敏感数据加密与密钥轮换

`IMGTAG_SECRET_KEY` 可在环境变量或 `.env` 配置，用于加密 S3 凭据。留空时沿用数据库密钥，新库自动生成独立密钥。

- **首次升级**：原来设置过自定义密钥的，先保留原值启动一次完成登记，再更换；原值丢失无法恢复。旧默认密钥自动兼容。
- **更换密钥**：备份数据库、停止全部实例，修改变量后统一启动。Docker Compose 需执行 `docker compose up -d --force-recreate imgtag`，仅重启容器不会更新环境变量。
- **启动行为**：密钥变化才重加密 S3 凭据，完成后提供服务；失败回滚并停止启动。

数据库备份包含解密所需密钥，请妥善保管。回退旧版应用需恢复升级前的数据库和密钥配置。

## 异常向量检测与修复

管理员可在“系统设置 → 系统维护 → 异常向量检测”分页查看有非空描述或可用标签，但向量缺失、全零/无效或维度与当前配置不符的图片。可用标签包含分类与普通标签，不包含分辨率标签；没有这些内容的图片不列为异常。

点击单张图片的“重建向量”后，任务队列使用当前描述和标签重新生成搜索向量，不调用视觉分析。页面展示重建状态，成功后重新检测并刷新列表，失败可查看任务后重试。检测只检查向量的结构有效性，不能判断维度相同的旧向量是否来自其他模型，或其语义是否与图片内容一致。

配置维度与数据库维度不一致时，需先在“向量嵌入”设置中处理维度配置，单张重建不会调整数据库结构或清空其他图片的向量。

调整维度会删除向量索引并清空旧向量（设为 `NULL`），回填后按需构建 HNSW。仅升级索引无需重新生成向量；更换模型即使维度相同，也需全库重建。

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
