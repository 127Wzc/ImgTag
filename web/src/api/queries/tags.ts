import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, unref, type MaybeRef } from 'vue'
import apiClient from '../client'
import type { Tag } from '@/types'

interface TagStats {
    categories: number
    resolutions: number
    normal_tags: number
    total: number
}

/**
 * 获取标签统计（各级别数量）
 */
export function useTagStats() {
    return useQuery({
        queryKey: ['tags', 'stats'],
        queryFn: async () => {
            const { data } = await apiClient.get<TagStats>('/tags/stats')
            return data
        },
        staleTime: 60 * 1000,
    })
}

/**
 * 获取指定级别的标签（响应式）
 */
export function useTagsByLevel(level: MaybeRef<number>, limit = 200) {
    return useQuery({
        queryKey: computed(() => ['tags', 'level', unref(level), limit]),
        queryFn: async () => {
            const { data } = await apiClient.get<Tag[]>('/tags/', {
                params: { level: unref(level), limit }
            })
            return data
        },
        staleTime: 5 * 60 * 1000,
    })
}

/**
 * 获取所有标签
 */
export function useTags(limit = 200) {
    return useQuery({
        queryKey: ['tags', 'all', limit],
        queryFn: async () => {
            const { data } = await apiClient.get<Tag[]>('/tags/', {
                params: { limit }
            })
            return data
        },
        staleTime: 5 * 60 * 1000,
    })
}

/**
 * 搜索标签（支持关键字模糊匹配）
 */
export function useSearchTags(keyword: MaybeRef<string>, level?: MaybeRef<number | null>, limit = 50) {
    return useQuery({
        queryKey: computed(() => ['tags', 'search', unref(keyword), unref(level), limit]),
        queryFn: async () => {
            const params: Record<string, any> = { limit }
            const kw = unref(keyword)
            const lv = unref(level)
            if (kw) params.keyword = kw
            if (lv !== null && lv !== undefined) params.level = lv

            const { data } = await apiClient.get<Tag[]>('/tags/', { params })
            return data
        },
        enabled: computed(() => {
            const kw = unref(keyword)
            return kw.length > 0
        }),
        staleTime: 30 * 1000,
    })
}

/**
 * 获取主分类标签 (level=0)
 */
export function useCategories() {
    return useQuery({
        queryKey: ['tags', 'categories'],
        queryFn: async () => {
            const { data } = await apiClient.get<Tag[]>('/tags/', {
                params: { level: 0, limit: 100 }
            })
            return data
        },
        staleTime: 5 * 60 * 1000,
    })
}

/**
 * 获取分辨率标签 (level=1)
 */
export function useResolutions() {
    return useQuery({
        queryKey: ['tags', 'resolutions'],
        queryFn: async () => {
            const { data } = await apiClient.get<Tag[]>('/tags/', {
                params: { level: 1, limit: 100 }
            })
            return data
        },
        staleTime: 5 * 60 * 1000,
    })
}

/**
 * 创建标签
 */
export function useCreateTag() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (tag: { name: string; level?: number; source?: string }) => {
            const { data } = await apiClient.post('/tags/', null, {
                params: {
                    name: tag.name,
                    level: tag.level ?? 2,
                    source: tag.source ?? 'user'
                }
            })
            return data
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tags'] })
        },
    })
}

export interface ResolvedTag {
    id: number
    name: string
    level: number
    source: string
    is_new: boolean
}

/**
 * 解析标签：查询已存在标签或创建新标签
 * 用于编辑图片时添加标签，返回标签 ID 供缓存
 */
export function useResolveTag() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (params: { name: string; level?: number }): Promise<ResolvedTag> => {
            const { data } = await apiClient.post('/tags/resolve', null, {
                params: {
                    name: params.name,
                    level: params.level ?? 2,
                }
            })
            return data
        },
        onSuccess: (data) => {
            // 如果是新创建的标签，刷新标签列表
            if (data.is_new) {
                queryClient.invalidateQueries({ queryKey: ['tags'] })
            }
        },
    })
}

/**
 * 更新标签（按 ID）
 * 支持更新 name, code, prompt
 */
export function useRenameTag() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async ({ id, name, code, prompt }: {
            id: number;
            name?: string;
            code?: string | null;
            prompt?: string | null;
        }) => {
            const payload: Record<string, any> = {}
            if (name !== undefined) payload.name = name
            if (code !== undefined) payload.code = code
            if (prompt !== undefined) payload.prompt = prompt

            const { data } = await apiClient.put(`/tags/id/${id}`, payload)
            return data
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tags'] })
        },
    })
}

/**
 * 删除标签（按 ID）
 */
export function useDeleteTag() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (tagId: number) => {
            const { data } = await apiClient.delete(`/tags/id/${tagId}`)
            return data
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tags'] })
        },
    })
}

/**
 * 同步标签使用次数
 */
export function useUpdateTagCounts() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async () => {
            await apiClient.post('/tags/sync')
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tags'] })
        },
    })
}
