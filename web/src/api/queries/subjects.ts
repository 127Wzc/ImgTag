import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, type MaybeRefOrGetter, toValue, type Ref } from 'vue'
import apiClient from '../client'
import type { SubjectResponse } from '@/types'

export interface SubjectsQueryParams {
  page: number
  size: number
  keyword?: string
  active_only?: boolean
}

/**
 * 主体词典列表（后端要求登录）。
 * 通过 enabled 控制发起时机，避免匿名状态下触发 401 被拦截器强制跳转登录页。
 */
export function useSubjects(
  params: Ref<SubjectsQueryParams>,
  enabled: MaybeRefOrGetter<boolean> = true,
) {
  return useQuery({
    queryKey: computed(() => ['subjects', params.value]),
    queryFn: async () => {
      const { data } = await apiClient.get<SubjectResponse[]>('/subjects/', {
        params: params.value,
      })
      return data
    },
    enabled: computed(() => toValue(enabled)),
  })
}

export function useCreateSubject() {
  const queryClient = useQueryClient()
  return useMutation({
    meta: { successMessage: '主体创建成功', toastError: true },
    mutationFn: async (data: {
      category_tag_id: number
      primary_tag_id: number
      alias_tag_ids?: number[]
      description?: string | null
    }) => {
      const { data: result } = await apiClient.post<SubjectResponse>('/subjects/', data)
      return result
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['subjects'] })
    },
  })
}

export function useUpdateSubject() {
  const queryClient = useQueryClient()
  return useMutation({
    meta: { successMessage: '主体已更新', toastError: true },
    mutationFn: async (data: {
      id: number
      category_tag_id?: number
      primary_tag_id?: number
      alias_tag_ids?: number[]
      description?: string | null
      is_active?: boolean
    }) => {
      const { id, ...payload } = data
      const { data: result } = await apiClient.patch<SubjectResponse>(`/subjects/${id}`, payload)
      return result
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['subjects'] })
    },
  })
}

export function useSetPrimarySubject() {
  const queryClient = useQueryClient()
  return useMutation({
    meta: { successMessage: '主体已更新', toastError: true },
    mutationFn: async (data: {
      image_id: number
      subject_id: number
      confidence?: number | null
      add_sample?: boolean
      reanalyze?: boolean
      comment?: string
    }) => {
      const { data: result } = await apiClient.put<{
        message: string
        assignment: {
          subject_id: number
          subject_name: string
          confidence: number | null
          source: string
          state: string
          is_primary: boolean
          changed: boolean
        }
        reanalyze_enqueued: boolean
      }>(`/images/${data.image_id}/subjects/primary`, {
        subject_id: data.subject_id,
        confidence: data.confidence ?? null,
        add_sample: data.add_sample ?? false,
        reanalyze: data.reanalyze ?? false,
        comment: data.comment ?? null,
      })
      return result
    },
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ['image', vars.image_id] })
      queryClient.invalidateQueries({ queryKey: ['images'] })
      queryClient.invalidateQueries({ queryKey: ['my-images'] })
    },
  })
}

export function useSuggestPrimarySubject() {
  const queryClient = useQueryClient()
  return useMutation({
    meta: { successMessage: '主体建议已提交，等待管理员审批', toastError: true },
    mutationFn: async (data: {
      image_id: number
      subject_id: number
      confidence?: number | null
      comment?: string
      add_sample?: boolean
    }) => {
      const { data: result } = await apiClient.post<{
        message: string
        approval_id: number
      }>(`/images/${data.image_id}/subjects/suggest`, {
        subject_id: data.subject_id,
        confidence: data.confidence ?? null,
        comment: data.comment ?? null,
        add_sample: data.add_sample ?? false,
      })
      return result
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}
