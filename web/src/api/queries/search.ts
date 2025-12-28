import { useQuery } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'
import apiClient from '../client'
import type { ImageSearchResponse, SimilarSearchResponse, SimilarSearchRequest } from '@/types'

/**
 * 关键词/标签搜索
 */
export function useSearch(params: Ref<{
    keyword?: string
    tags?: string[]
    category_id?: number
    resolution_id?: number
    limit?: number
    offset?: number
} | null>) {
    return useQuery({
        queryKey: ['search', params],
        queryFn: async () => {
            if (!params.value) return null

            const searchParams = new URLSearchParams()

            if (params.value.keyword) {
                searchParams.append('keyword', params.value.keyword)
            }
            if (params.value.tags?.length) {
                params.value.tags.forEach(tag => searchParams.append('tags', tag))
            }
            if (params.value.category_id) {
                searchParams.append('category_id', String(params.value.category_id))
            }
            if (params.value.resolution_id) {
                searchParams.append('resolution_id', String(params.value.resolution_id))
            }
            if (params.value.limit) {
                searchParams.append('limit', String(params.value.limit))
            }
            if (params.value.offset) {
                searchParams.append('offset', String(params.value.offset))
            }

            const { data } = await apiClient.get<ImageSearchResponse>(`/search/?${searchParams}`)
            return data
        },
        enabled: computed(() => params.value !== null),
    })
}

/**
 * 语义向量搜索
 */
export function useSimilarSearch(params: Ref<SimilarSearchRequest | null>) {
    return useQuery({
        queryKey: ['similar-search', params],
        queryFn: async () => {
            if (!params.value) return null
            const { data } = await apiClient.post<SimilarSearchResponse>('/images/smart-search', params.value)
            return data
        },
        enabled: computed(() => params.value !== null && !!params.value.text),
    })
}
