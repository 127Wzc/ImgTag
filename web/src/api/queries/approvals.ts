import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'
import apiClient from '../client'
import type { ApprovalListResponse } from '@/types'

export interface ApprovalsQueryParams {
  page: number
  size: number
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

