# Repository Guidelines

## 项目结构

- 后端：`src/imgtag/`（分层：`api/endpoints/` → `services/` → `db/repositories/` → `models/`；Schema 在 `schemas/`；配置/权限/异常在 `core/`）
- 迁移：`src/imgtag/alembic/versions/`（Alembic）
- 前端：`web/`（Vue 3 + TypeScript + Vite；页面 `web/src/pages/`；组件 `web/src/components/`；状态 `web/src/stores/`；请求 `web/src/api/queries/`）
- 文档与部署：`docs/`、`docker/`

## 本地开发命令

后端（Python 3.10+，使用 `uv`）：

```bash
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run python -m uvicorn imgtag.main:app --reload --port 8000
```

可选：安装本地嵌入模型依赖 `uv sync --extra local`。

前端（`pnpm` + Vite）：

```bash
cd web
pnpm install
pnpm dev
pnpm build  # vue-tsc + 生产构建
```

## 架构与编码规范（强约束）

- 默认使用中文进行协作沟通与注释；保持专业、直接。
- 严格分层：API Router 只做参数/权限/编排；业务在 Service；数据访问在 Repository；禁止在 `api/endpoints/` 写 SQL/复杂事务。
- 全链路异步：DB/S3/HTTP 必须 `async def`；CPU 密集型（图像处理/本地向量）放入 `run_in_executor`。
- SQLAlchemy 2.0 Async：禁用 `session.query`；使用 `select()/insert()/update()/delete()`；关联加载用 `selectinload` 预加载，避免 `MissingGreenlet` / N+1。
- Pydantic v2：区分输入/输出 Schema；使用 `model_dump()`；需要时使用 `ConfigDict(from_attributes=True)`。
- import 策略：默认顶层全局导入；仅重型/可选依赖（如 `transformers/onnxruntime/numpy`）或运行时循环依赖允许局部导入；顺序为标准库 → 第三方 → 本地模块。
- 错误处理：不允许静默失败；精确捕获 → 记录日志 → 抛出标准 HTTP 异常。

## 测试与验证

- 后端使用 `pytest` + `pytest-asyncio`：主体相关放 `tests/subjects/`（接口、提炼、关联、版本、匹配），图片分析相关放 `tests/analysis/`（接口、队列、历史管理）；其余模块保留在 `tests/` 根目录。
- 按功能归并用例，复用 fixture；不要为每次修复单独建文件，也不要通过导入其他测试模块来聚合。
- 日常测试使用模拟 HTTP 和本地内存库，不连接真实数据库、存储或模型。依赖运行服务的 `scripts/smoke_subject_flow.py` 仅供手工验证，不纳入自动回归。

```bash
uv run --frozen --no-sync pytest -q
uv run --frozen --no-sync pytest tests/subjects -q
uv run --frozen --no-sync pytest tests/analysis -q
IMGTAG_TEST_POSTGRES=1 uv run --frozen --no-sync pytest tests/subjects/test_postgres.py -q
```

- PostgreSQL 测试须显式启用，使用配置数据库中的隔离 schema，每个用例结束后回滚并检查清理；真实模型实验不纳入自动回归。
- pytest 使用 importlib 模式，缓存位于 `tmp/agent/cache/pytest/`；uv 缓存可通过 `UV_CACHE_DIR=tmp/agent/cache/uv` 指定。需要覆盖率时添加 `--cov=imgtag`。
- 前端未配置测试框架：涉及前端改动时运行 `pnpm --dir web build`，检查类型与生产构建。

## 提交 / PR / 发布

- Commit 信息使用 Conventional Commits：`feat:`, `fix:`, `docs:`, `refactor:`, `build:`, `release:`。
- PR：描述清楚变更与动机，关联 issue；临时 UI 验证截图先放 `tmp/agent/<日期>-<任务>/screenshots/`，精选用于正式说明的截图再放 `docs/screenshots/`。
- 版本与发布（GitHub Actions）：
  - 同一提交中同步更新 `pyproject.toml` 的 `version` 与 `web/package.json` 的 `version`
  - push 到 `main` 且 `pyproject.toml` 版本变化 → 自动创建 `vX.Y.Z` tag + GitHub Release
  - 推送 `v*` tag → 触发 Docker 镜像构建与推送（包含 `latest`/`latest-local`/`latest-backend` 等标签）

## 安全与配置

- 禁止提交密钥/令牌；新增环境变量时同步更新 `.env.example`。
- 本地运行需要 PostgreSQL 并启用 `pgvector`；细节参考 `docs/database.md`。

## 文档维护

- 仅将影响使用方式、数据结构与兼容性、权限、部署或长期维护的关键变动沉淀到正式文档；数据库结构变动须有对应 Alembic 迁移，更新说明应写清升级要求。
- 文档描述当前有效行为，在原有章节中压缩整合；避免重复说明同一规则，不按对话或开发顺序追加流水账，不保留已废弃方案与临时 UI 布局说明。
- 测试次数、运行时间、本地库修正、调试过程、一次性脚本及中间截图放任务临时目录。正式文档只保留必要操作、约束和兼容性说明。
- 变动不影响既有使用或维护方式时，不必新增文档条目；发布历史仅记录已发布版本的关键变化。

## Agent 临时产物

- 临时文件统一放 `tmp/agent/<日期>-<任务>/`：`tools/` 放一次性脚本和预览服务，`logs/` 放测试/构建日志和请求记录，`screenshots/` 放验证截图，`results/` 放原始输入输出及参考图，`reports/` 放临时报告。先创建目录，脚本默认输出也使用该目录。
- 不再写入 `/private/tmp/imgtag-*`、`docs/test-results/` 或把实验脚本放入 `scripts/`。`scripts/` 只保留长期维护的项目工具。
- `docs/screenshots/` 仅保留正式文档精选图，使用稳定名称并同步修改引用；中间截图留在临时目录。
- `tmp/` 已由 Git 和 Docker 忽略，不随仓库分发；不要放入需要长期恢复的数据库备份或上传原件。这些数据仍放 `data/`，数据库备份放 `data/backups/`。
- 应用自身的 `logs/`、依赖目录 `.venv/` 和 `node_modules/` 保持原位。验证结束后关闭 agent 自己创建的预览服务，不关闭用户服务。
- 日志不得输出密钥、完整数据库连接串或图片 Base64；含敏感输入的本地归档仅当前用户可读。

日志示例（按本次任务替换目录名）：

```bash
mkdir -p tmp/agent/2026-10-18-check/logs
UV_CACHE_DIR=tmp/agent/cache/uv uv run --frozen --no-sync pytest -q > tmp/agent/2026-10-18-check/logs/pytest.log 2>&1
pnpm --dir web build > tmp/agent/2026-10-18-check/logs/web-build.log 2>&1
```

已有主体实验归档在 `tmp/agent/2026-10-18-subject-workflow/`，整理清单与验证日志在 `tmp/agent/2026-10-18-cleanup/logs/`。历史一次性修改/迁移脚本仅供追溯，不重新执行；模型对照工具默认仅生成输入，`--live` 才调用模型。
