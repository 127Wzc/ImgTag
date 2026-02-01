# 用户权限系统

ImgTag 使用基于位掩码（Bitmask）的细粒度权限控制系统。

## 概述

- **Admin 角色**：自动拥有所有权限，绕过权限检查
- **User 角色**：通过 `permissions` 字段控制具体权限

## 权限定义

| 权限位 | 权限名 | 说明 | 值 |
|--------|--------|------|-----|
| `1 << 0` | `UPLOAD_IMAGE` | 允许上传图片 | 1 |
| `1 << 1` | `CREATE_TAGS` | 允许新建标签 | 2 (预留) |
| `1 << 2` | `AI_ANALYZE` | 允许 AI 分析 | 4 (预留) |
| `1 << 3` | `AI_SEARCH` | 允许智能搜索 | 8 (预留) |

## 默认权限

- 新注册用户默认 `permissions = 1`（仅上传权限）
- 管理员可通过用户管理接口修改用户权限

## 权限检查

### 后端

```python
from imgtag.api.endpoints.auth import require_permission
from imgtag.core.permissions import Permission

# 在路由端点使用
@router.post("/upload")
async def upload_image(
    user: dict = Depends(require_permission(Permission.UPLOAD_IMAGE)),
):
    # 只有拥有上传权限的用户才能访问
    ...
```

### 前端

```typescript
import { Permission, hasPermission } from '@/constants/permissions'

// 使用 Store getter
const userStore = useUserStore()
if (userStore.canUpload) {
  // 有上传权限
}

// 或直接检查
if (hasPermission(user.permissions, Permission.UPLOAD_IMAGE)) {
  // 有上传权限
}
```

## 权限组合

权限值可以组合，例如：

```python
# 同时拥有上传和新建标签权限
permissions = Permission.UPLOAD_IMAGE | Permission.CREATE_TAGS  # = 3
```

## 安全说明

权限码本身是公开的（开源项目），这**不构成安全隐患**：

1. **权限码只是标识符**：类似于 `role = "admin"` 中的 `"admin"` 字符串
2. **安全性由后端保证**：每次 API 请求都从数据库验证用户的实际权限值
3. **JWT 签名保护**：Token 无法被伪造（需要服务器的 `SECRET_KEY`）
4. **前端权限仅用于 UI**：前端读取权限只用于显示优化，不作为安全依据

## 管理员接口

修改用户权限：

```http
PUT /api/v1/auth/users/{user_id}
Content-Type: application/json
Authorization: Bearer <admin_token>

{
  "permissions": 1
}
```

| permissions 值 | 含义 |
|---------------|------|
| `0` | 禁止所有操作 |
| `1` | 仅上传 |
| `15` | 所有当前权限 |

## 扩展权限

如需添加新权限：

1. 在 `src/imgtag/core/permissions.py` 添加新的权限位
2. 在 `web/src/constants/permissions.ts` 添加对应常量
3. 在需要的路由端点使用 `require_permission()`
4. 在前端相应位置添加权限检查
