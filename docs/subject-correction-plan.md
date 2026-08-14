# 主体自动纠正方案（V1 框架先行）

## 1. 目标与范围

- 目标：解决“人物/地标/动物主体被反复误识别”问题，让人工纠正可持续生效。
- 策略：先上线完整流程与数据结构，识别器先用 `stub` 占位，后续平滑替换为真实识别器（如 `insightface`）。
- 范围：本期只做主体记忆与纠正链路，不改变现有图像分析主流程行为。

## 2. 设计原则

- 零回归：默认 `subject_matcher_backend=stub`，自动匹配结果为 `NO_MATCH`，不影响现有标签/描述产出。
- 人工优先：人工/审批确认的主体在重新分析时直接生效（注入提示词约束），且不会被自动匹配结果覆盖。
- 分层清晰：API 只做鉴权与编排；业务逻辑在 Service；数据访问在 Repository。
- 挂接标签体系：主体通过 `category_tag_id`（level=0 分类）与 `primary_tag_id`（level=2 普通标签）关联既有三级标签系统，不再单独维护 `subject_type`。
- 可审计：低置信命中走审批；人工纠正/审批通过可登记样本引用。

## 3. V1 交付内容

### 3.1 数据层

- 新增迁移：`src/imgtag/alembic/versions/0005_subject_memory.py`
- 新增模型：`src/imgtag/models/subject.py`
- 新增表：
  - `subjects`：主体词典（`name` 冗余自 `primary_tag`，标签改名时自动同步）
  - `subject_samples`：主体样本。V1 仅登记来源引用（`embedding_model=reference`，`embedding=NULL`），
    向量维度不锁定，待真实识别器确定向量空间后再通过迁移固定维度并建向量索引
  - `image_subjects`：图片主体结果（部分唯一索引保证单主主体；`state` 当前仅使用 `confirmed`）
- 别名字段（`alias_tag_ids` / `aliases`）：V1 仅维护数据（校验、改名同步、删除保护），
  暂不参与匹配与提示词；预留给后续识别器词表与别名约束
- 新增仓库：`src/imgtag/db/repositories/subject.py`
- 新增 Schema：`src/imgtag/schemas/subject.py`
- 扩展图片响应：`ImageResponse.subjects`（默认空数组）

### 3.2 配置项（默认）

在 `src/imgtag/core/config_defaults.py`（阈值对所有主体类型通用）：

- `subject_memory_enabled=true`
- `subject_auto_apply_high_conf=true`
- `subject_high_threshold=0.50`
- `subject_low_threshold=0.40`
- `subject_max_candidates=3`
- `subject_matcher_backend=stub`

### 3.3 服务与流程

- `subject_matcher_stub.py`：占位匹配器（始终无命中）
- `subject_memory_service.py`：主体判定层（高/低置信决策；提供 `build_subject_hint` 统一提示词口径）
- `subject_assignment_service.py`：主体设置、建议创建、审批落地
  - 来源优先级：`auto` 不得覆盖 `manual` / `approval`
  - 主体落地时同步图片标签：挂接新主体的 `primary_tag`（人工/审批 → `source=user`，
    自动 → `source=system`，均不会被 AI 重分析清除），移除旧主体的 `primary_tag`
  - 建议创建前做 pending 去重（同图片同类型仅保留一条待审批）
- `task_queue.py`：视觉分析前执行主体判定
  - 已有人工/审批确认主体 → 直接注入提示词约束，跳过自动匹配
  - `high_conf`：自动写入主主体（受来源优先级保护）
  - `low_conf`：自动创建主体建议审批（pending 去重）
  - `no_match`：继续原有流程
- `vision_service.py`：支持 `subject_hints`，用于约束描述和标签一致性

### 3.4 API 与审批

- 主体词典：
  - `GET /api/v1/subjects`（需登录：词典可能包含人名等敏感信息，不对匿名开放）
  - `POST /api/v1/subjects`（admin）
  - `PATCH /api/v1/subjects/{id}`（admin）
- 图片主体纠正：
  - `PUT /api/v1/images/{image_id}/subjects/primary`（owner/admin 直接改，落地后触发向量重建；
    可选 `reanalyze=true` 触发强制重新分析：跳过“已有描述+标签”短路，
    基于主体约束重新生成描述与标签，用于修正历史错误描述，消耗一次视觉分析调用）
  - `POST /api/v1/images/{image_id}/subjects/suggest`（普通用户提建议）
- 审批类型扩展：
  - `type = "suggest_subject_assignment"`
  - 审批通过后执行主体落地并触发向量重建
- 标签联动保护：
  - 删除被主体引用（主名称/分类/别名）的标签会被拦截并给出可读提示
  - 标签改名自动同步主体冗余名称

### 3.5 前端入口

- 类型扩展：`web/src/types/api.ts`
- 查询封装：`web/src/api/queries/subjects.ts`
- 主体管理页：`web/src/pages/Subjects.vue`（admin）
- 图片详情：`web/src/components/ImageDetailModal.vue`
  - 查看当前主体
  - 直接纠正（owner/admin）
  - 提交建议（普通用户）
- 审批页：`web/src/pages/Approvals.vue`
  - 支持展示/处理 `suggest_subject_assignment`

## 4. 数据流（V1）

1. 图片进入分析队列。
2. 队列先执行主体判定：
   - 已有人工/审批确认主体 → 直接作为提示词约束（人工纠正持续生效的关键闭环）
   - 否则执行自动匹配（当前 `stub` 默认 `NO_MATCH`）
3. 视觉分析与标签流程按原逻辑继续（主体挂接的标签为 user/system 来源，不会被 AI 重分析清除）。
4. 人工纠正入口：
   - owner/admin：直接写 `image_subjects` + 同步标签 + 向量重建；
     可选强制重新分析（`reanalyze`）以重新生成描述——不勾选时旧描述保持不变
   - 普通用户：写审批 `suggest_subject_assignment`，管理员通过后落地
5. 样本登记：仅人工直接纠正或审批通过时写入 `subject_samples`（V1 只记录来源图片引用，不写向量）。

## 5. 接口与数据结构

### 5.1 `ImageResponse` 增量字段

```json
{
  "subjects": [
    {
      "subject_id": 1,
      "subject_name": "示例主体",
      "confidence": 0.92,
      "state": "confirmed",
      "source": "manual",
      "is_primary": true
    }
  ]
}
```

### 5.2 主体建议审批 payload

```json
{
  "type": "suggest_subject_assignment",
  "payload": {
    "image_id": 123,
    "base_subject": {
      "subject_id": 1,
      "subject_name": "旧主体",
      "confidence": 0.6
    },
    "proposed_subject": {
      "subject_id": 2,
      "subject_name": "新主体"
    },
    "confidence": 0.45,
    "comment": "建议修正",
    "add_sample": true
  }
}
```

## 6. 验收标准

### 6.1 后端

- `subject_memory_service` 在 `stub` 下稳定返回 `no_match`（或按阈值处理 mock 返回）。
- 已有人工确认主体的图片重新分析时，提示词包含主体约束，且不执行自动匹配。
- `source=auto` 的落地不会覆盖 `manual` / `approval` 的主体。
- `PUT /images/{id}/subjects/primary` 权限正确、重复提交幂等、落地后同步标签并触发向量重建。
- `reanalyze=true` 时强制重新分析：跳过短路检查，提示词包含主体约束，旧描述被重新生成。
- `GET /subjects` 匿名访问返回 401；审批落地遇到可预期业务失败（如主体停用）返回 400。
- `POST /images/{id}/subjects/suggest` 可创建审批（pending 去重）并在通过后落地。
- 删除被主体引用的标签返回 400 且提示主体名称；标签改名同步主体名称。
- 原 `suggest_image_update` 无回归。

### 6.2 前端

- 图片详情可展示主体、直接纠正、提交建议。
- 审批页可区分并处理图片建议与主体建议。

### 6.3 构建与测试

- 后端：`uv run pytest`
- 前端：`pnpm build`

## 7. 下一阶段（接入真实识别器）

- 新增：`src/imgtag/services/subject_matcher_insightface.py`
- 通过配置切换：`subject_matcher_backend=insightface`
- 新增迁移：为 `subject_samples.embedding` 固定维度（如 512）并创建向量索引（ivfflat/HNSW，
  建议在有数据后创建或 REINDEX），按 `embedding_model` 过滤检索
- 将 V1 登记的 `reference` 样本批量回算真实向量
- 保持 API / DB / 前端不变，仅替换匹配实现
- 阈值策略保持：
  - 高置信自动应用（不覆盖人工结果）
  - 低置信走审批
  - 自动命中不直接回流样本（避免污染）

## 8. 运行与上线注意事项

- 先执行数据库迁移：`uv run alembic upgrade head`
- 默认可先开 `subject_memory_enabled=true` + `backend=stub`，验证全链路无回归
- 接入真实识别器前，建议先准备少量高质量主体样本并观察误报率/漏报率
