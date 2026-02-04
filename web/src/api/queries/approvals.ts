import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'
import apiClient from '../client'
import type { ApprovalListResponse } from '@/types'

export interface ApprovalsQueryParams {
  page: number
  size: number
  /** 逗号分隔的审批类型过滤，例如：suggest_image_update */
  types?: string
  /** 是否包含图片预览信息（减少 N+1 请求） */
  include_preview?: boolean
}

/**
 * 获取待审批建议列表（管理员）
 */
export function useApprovals(params: Ref<ApprovalsQueryParams>) {
  return useQuery({
    queryKey: computed(() => ['approvals', params.value]),
    queryFn: async () => {
      const { data } = await apiClient.get<ApprovalListResponse>('/approvals', {
        params: params.value,
      })
      return data
    },
  })
}

/**
 * 通过审批（管理员）
 */
export function useApproveApproval() {
  const queryClient = useQueryClient()

  return useMutation({
    meta: { successMessage: '已通过', toastError: true },
    mutationFn: async ({ id, comment }: { id: number; comment?: string }) => {
      const { data } = await apiClient.post(`/approvals/${id}/approve`, {
        comment: comment ?? null,
      })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}

/**
 * 拒绝审批（管理员）
 */
export function useRejectApproval() {
  const queryClient = useQueryClient()

  return useMutation({
    meta: { successMessage: '已拒绝', toastError: true },
    mutationFn: async ({ id, comment }: { id: number; comment?: string }) => {
      const { data } = await apiClient.post(`/approvals/${id}/reject`, {
        comment: comment ?? null,
      })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}
