import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'
import apiClient from '../client'
import type { Task, TaskListResponse } from '@/types'

/**
 * 获取任务列表
 */
export function useTasks(params: Ref<{
    status?: string
    page?: number
    size?: number
}>) {
    return useQuery({
        queryKey: computed(() => ['tasks', params.value]),
        queryFn: async () => {
            const searchParams = new URLSearchParams()
            if (params.value.status) searchParams.append('status', params.value.status)
            if (params.value.page) searchParams.append('page', String(params.value.page))
            if (params.value.size) searchParams.append('size', String(params.value.size))

            const { data } = await apiClient.get<TaskListResponse>(`/tasks/?${searchParams}`)
            return data
        },
        refetchInterval: 5000, // 每5秒自动刷新
    })
}

/**
 * 获取单个任务详情
 */
export function useTask(id: Ref<string | null>) {
    return useQuery({
        queryKey: ['task', id],
        queryFn: async () => {
            if (!id.value) return null
            const { data } = await apiClient.get<Task>(`/tasks/${id.value}`)
            return data
        },
        enabled: computed(() => id.value !== null),
    })
}

/**
 * 重试失败的任务
 */
export function useRetryTask() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (taskId: string) => {
            const { data } = await apiClient.post(`/tasks/${taskId}/retry`)
            return data
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tasks'] })
        },
    })
}

/**
 * 取消任务
 */
export function useCancelTask() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (taskId: string) => {
            const { data } = await apiClient.post(`/tasks/${taskId}/cancel`)
            return data
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tasks'] })
        },
    })
}

/**
 * 清理已完成的任务
 */
export function useClearCompletedTasks() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async () => {
            const { data } = await apiClient.delete('/tasks/completed')
            return data
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tasks'] })
        },
    })
}
