/**
 * 权限检查 Composable
 * 提供统一的权限检查和友好的错误提示
 */
import { computed } from 'vue'
import { useUserStore } from '@/stores'
import { Permission, PermissionNames, type PermissionType } from '@/constants/permissions'
import { toast } from 'vue-sonner'

export function usePermission() {
  const userStore = useUserStore()

  /**
   * 检查用户是否拥有指定权限
   */
  const hasPermission = (permission: PermissionType): boolean => {
    return userStore.checkPermission(permission)
  }

  /**
   * 检查权限并在无权限时显示友好提示
   * @param permission 需要检查的权限
   * @param action 操作名称（可选，用于自定义提示）
   * @returns 是否有权限
   */
  const checkPermissionWithToast = (
    permission: PermissionType,
    action?: string
  ): boolean => {
    if (hasPermission(permission)) {
      return true
    }

    const permissionName = action || PermissionNames[permission] || '该操作'
    toast.error(`暂无${permissionName}权限`, {
      description: '请联系管理员开通权限后再试'
    })
    return false
  }

  /**
   * 创建一个需要权限检查的操作处理器
   * @param permission 需要的权限
   * @param callback 有权限时执行的回调
   * @param action 操作名称（可选）
   */
  const withPermission = <TArgs extends unknown[]>(
    permission: PermissionType,
    callback: (...args: TArgs) => void,
    action?: string
  ): ((...args: TArgs) => void) => {
    return (...args: TArgs) => {
      if (!checkPermissionWithToast(permission, action)) return
      callback(...args)
    }
  }

  /**
   * 创建一个需要权限检查、且需要返回值的处理器
   * @returns 有权限时返回 callback 结果；无权限时返回 undefined
   */
  const withPermissionValue = <T extends (...args: any[]) => any>(
    permission: PermissionType,
    callback: T,
    action?: string
  ): ((...args: Parameters<T>) => ReturnType<T> | undefined) => {
    return (...args: Parameters<T>) => {
      if (!checkPermissionWithToast(permission, action)) return undefined
      return callback(...args)
    }
  }

  // 常用权限检查
  const canUpload = computed(() => hasPermission(Permission.UPLOAD_IMAGE))
  const canCreateTags = computed(() => hasPermission(Permission.CREATE_TAGS))
  const canUseAIAnalyze = computed(() => hasPermission(Permission.AI_ANALYZE))

  return {
    hasPermission,
    checkPermissionWithToast,
    withPermission,
    withPermissionValue,
    // 常用权限
    canUpload,
    canCreateTags,
    canUseAIAnalyze,
  }
}
