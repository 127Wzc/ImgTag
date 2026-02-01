/**
 * 用户权限枚举（位掩码）
 * 与后端 Permission 枚举保持一致
 *
 * 安全说明：权限码本身是公开的，这不是安全隐患。
 * 真正的安全保障在于后端每次 API 请求都从数据库验证用户的实际权限值。
 */

export const Permission = {
    /** 上传图片 */
    UPLOAD_IMAGE: 1 << 0, // 1

    /** 新建标签（预留） */
    CREATE_TAGS: 1 << 1, // 2

    /** AI 分析（预留） */
    AI_ANALYZE: 1 << 2, // 4

    /** 智能搜索（预留） */
    AI_SEARCH: 1 << 3, // 8
} as const

export type PermissionType = (typeof Permission)[keyof typeof Permission]

/**
 * 检查用户是否拥有指定权限
 * @param userPermissions 用户的权限位掩码
 * @param required 需要检查的权限
 * @returns 如果用户拥有指定权限返回 true
 */
export function hasPermission(
    userPermissions: number,
    required: PermissionType
): boolean {
    return (userPermissions & required) === required
}

/**
 * 权限名称映射（用于 UI 显示）
 */
export const PermissionNames: Record<PermissionType, string> = {
    [Permission.UPLOAD_IMAGE]: '上传图片',
    [Permission.CREATE_TAGS]: '新建标签',
    [Permission.AI_ANALYZE]: 'AI 分析',
    [Permission.AI_SEARCH]: '智能搜索',
}

/**
 * 获取所有权限列表（用于管理界面）
 */
export function getAllPermissions(): Array<{
    value: PermissionType
    name: string
}> {
    return Object.entries(Permission).map(([key, value]) => ({
        value: value as PermissionType,
        name: PermissionNames[value as PermissionType] || key,
    }))
}
