# 用户权限系统

ImgTag 使用位掩码（Bitmask）做细粒度权限控制；**前端仅用于 UX**，安全性以**后端校验**为准。

## 角色与数据来源

- `admin`：绕过权限检查（视为拥有全部权限）
- `user`：由数据库字段 `users.permissions` 控制
- 外部 API（API Key）同样会返回/携带 `permissions`，用于一致的权限判断

## 权限位定义（当前 4 个）

| 权限位 | 权限名 | 说明 | 值 |
|--------|--------|------|-----|
| `1 << 0` | `UPLOAD_IMAGE` | 上传图片 | 1 |
| `1 << 1` | `CREATE_TAGS` | 新建标签 | 2 |
| `1 << 2` | `AI_ANALYZE` | AI 分析 | 4 |
| `1 << 3` | `SUGGEST_CHANGES` | 提交修改建议（修改他人图片元信息） | 8 |

组合示例：`3=上传+新建标签`，`5=上传+AI分析`，`15=全部权限`。

## 默认权限

- 新注册用户默认 `permissions = 15`（开启所有当前权限）
- 管理员创建用户：未显式传 `permissions` 时同样默认 15

升级说明：
- 通过 Alembic 迁移会对存量普通用户做补齐：`permissions |= 8`

补充说明：
- 后端权限是**实时**的：每次请求都会通过 `Token -> users` 查询拿到最新 `permissions`
- 前端会缓存 `user` 信息用于 UI（登录态刷新时会拉取 `/auth/me`）；若你在后台改了权限，建议刷新页面/重新登录

策略建议：
- `SUGGEST_CHANGES` 会引入“审批工作量/滥用提交”的成本（尽管不会直接落地数据），在公开部署场景建议按需开启（例如仅给可信成员开启）。
- 如需关闭某用户的建议权限，可在管理员接口将其 `permissions` 去掉对应位（`8`）。

## 主分类 / 分辨率（重要约束）

- 主分类（`level=0`）与分辨率（`level=1`）属于**系统标签**：创建/修改/删除仅管理员可做（后续可在后台管理）
- 主分类的**赋值/调整**按“谁上传谁管理”：普通用户只能改自己上传的图片；管理员不受限制
- 分辨率标签当前不支持由用户修改（由系统根据图片宽高自动生成/绑定）
- 因 `tags.name` 全局唯一：普通标签（`level=2`）的新增/绑定逻辑会拒绝使用已被主分类/分辨率占用的名字

## 后端：权限校验与友好提示

- 路由依赖（最常用）：`src/imgtag/api/endpoints/auth.py` 的 `require_permission(Permission.X)`
  - 失败会返回 403，并使用统一文案：`src/imgtag/core/permissions.py` 的 `permission_denied_detail()`
- 复杂场景封装（避免重复 & fail-fast）：`src/imgtag/api/permission_guards.py`
  - `ensure_permission(user, Permission.X)`：统一抛 403
  - `ensure_create_tags_if_missing(session, user, tag_names)`：仅当标签不存在且会“隐式创建”时才要求 `CREATE_TAGS`

建议：涉及上传/落库/触发异步任务时，先 **fail-fast** 校验权限，再进行存储/事务副作用。

## 前端：统一的权限检查 Composable

`web/src/composables/usePermission.ts` 提供：

- `checkPermissionWithToast(permission, action?)`：无权限时 toast 提示具体缺少的权限
- `withPermission(permission, callback, action?)`：仅用于副作用型操作（回调返回 `void`）
- `withPermissionValue(permission, callback, action?)`：需要返回值时使用（无权限返回 `undefined`）

示例：

```ts
const { withPermission, withPermissionValue } = usePermission()

const openUpload = withPermission(Permission.UPLOAD_IMAGE, () => {
  showUploadDialog.value = true
}, '上传图片')

const maybeId = withPermissionValue(Permission.CREATE_TAGS, () => createTag(), '新建标签')
```

## 管理员接口（修改权限）

```http
PUT /api/v1/auth/users/{user_id}
Authorization: Bearer <admin_token>
Content-Type: application/json

{ "permissions": 15 }
```

常用值：`0`（全禁用）、`1`（仅上传）、`15`（全部）。

## 新增权限（扩展）

1. `src/imgtag/core/permissions.py` 增加新的 bit + `PERMISSION_NAMES`
2. `web/src/constants/permissions.ts` 同步常量与显示名
3. 后端端点加 `require_permission()` 或 `permission_guards` 封装
4. 更新本文档的表格与默认值说明
