import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, type MaybeRefOrGetter, toValue, type Ref } from 'vue'
import apiClient from '../client'
import type { ImageSubjectAssignment, SubjectResponse } from '@/types'

export interface SubjectsQueryParams {
  page: number
  size: number
  keyword?: string
  active_only?: boolean
}

/**
 * 主体词典列表（仅管理员）。
 * 通过 enabled 控制发起时机，普通用户查看图片时不请求完整词典。
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
        reanalyze: data.reanalyze ?? true,
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

export interface SubjectTemplate {
  id: number
  name: string
  content: string
  is_builtin: boolean
  is_active: boolean
}

export interface SubjectVersion {
  id: number
  subject_id: number
  state: 'history'
  definition: string
  recognition_notes: string
  edit_revision: number
  base_revision: number
  published_revision: number | null
  payload: Record<string, any>
  input_snapshot: Record<string, any>
  created_at: string
}

export function useSetImageSubjects() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (data: { image_id: number; subject_ids: number[]; primary_subject_id: number | null; reanalyze: boolean }) => {
      const { image_id, ...payload } = data
      const { data: result } = await apiClient.put(`/images/${image_id}/subjects`, payload)
      return result as { assignments: ImageSubjectAssignment[]; reanalyze_enqueued: boolean }
    },
    onSuccess: (_, vars) => {
      for (const key of [['image', vars.image_id], ['images'], ['my-images']]) {
        queryClient.invalidateQueries({ queryKey: key })
      }
    },
  })
}
