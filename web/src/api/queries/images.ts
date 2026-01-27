import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'
import apiClient from '../client'
import type { ImageResponse, ImageSearchResponse, ImageSearchRequest, UploadAnalyzeResponse } from '@/types'

/**
 * 获取图片列表
 */
export function useImages(params: Ref<ImageSearchRequest>) {
    return useQuery({
        queryKey: computed(() => ['images', params.value]),
        queryFn: async () => {
            const { data } = await apiClient.post<ImageSearchResponse>('/images/search', params.value)
            return data
        },
    })
}

/**
 * 获取当前用户上传的图片列表
 */
export function useMyImages(params: Ref<ImageSearchRequest>) {
    return useQuery({
        queryKey: computed(() => ['my-images', params.value]),
        queryFn: async () => {
            const { data } = await apiClient.post<ImageSearchResponse>('/images/my', params.value)
            return data
        },
    })
}

/**
 * 获取单张图片详情
 */
export function useImage(id: Ref<number | null>) {
    return useQuery({
        queryKey: computed(() => ['image', id.value]),
        queryFn: async () => {
            if (!id.value) return null
            const { data } = await apiClient.get<ImageResponse>(`/images/${id.value}`)
            return data
        },
        enabled: computed(() => id.value !== null),
    })
}

/**
 * 上传选项接口
 */
export interface UploadOptions {
    file: File
    autoAnalyze?: boolean
    skipAnalyze?: boolean
    categoryId?: number
    tags?: string
    description?: string
    endpointId?: number  // 目标存储端点 ID
    isPublic?: boolean   // 是否公开
}

/**
 * 上传并分析图片
 */
export function useUploadImage() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (options: UploadOptions) => {
            const formData = new FormData()
            formData.append('file', options.file)
            formData.append('auto_analyze', String(options.autoAnalyze ?? true))
            formData.append('skip_analyze', String(options.skipAnalyze ?? false))
            if (options.categoryId) {
                formData.append('category_id', String(options.categoryId))
            }
            if (options.tags) {
                formData.append('tags', options.tags)
            }
            if (options.description) {
                formData.append('description', options.description)
            }
            if (options.endpointId) {
                formData.append('endpoint_id', String(options.endpointId))
            }
            if (options.isPublic !== undefined) {
                formData.append('is_public', String(options.isPublic))
            }

            const { data } = await apiClient.post<UploadAnalyzeResponse>('/images/upload', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            })
            return data
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['images'] })
        },
    })
}

/**
 * ZIP 上传选项
 */
export interface ZipUploadOptions {
    file: File
    categoryId?: number
}

/**
 * 上传 ZIP 压缩包
 */
export function useUploadZip() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (options: ZipUploadOptions) => {
            const formData = new FormData()
            formData.append('file', options.file)
            if (options.categoryId) {
                formData.append('category_id', String(options.categoryId))
            }

            const { data } = await apiClient.post<{
                message: string
                uploaded_count: number
                uploaded_ids: number[]
                failed_count: number
                failed_files: string[]
            }>('/images/upload-zip', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            })
            return data
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['images'] })
        },
    })
}

/**
 * URL 上传选项
 */
export interface UrlUploadOptions {
    imageUrl: string
    autoAnalyze?: boolean
    categoryId?: number
    tags?: string[]
    description?: string
}

/**
 * 从 URL 添加图片
 */
export function useUploadFromUrl() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (options: UrlUploadOptions) => {
            const { data } = await apiClient.post<UploadAnalyzeResponse>('/images/analyze-url', {
                image_url: options.imageUrl,
                auto_analyze: options.autoAnalyze ?? true,
                category_id: options.categoryId ?? null,
                tags: options.tags ?? [],
                description: options.description ?? '',
            })
            return data
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['images'] })
        },
    })
}

/**
 * 批量上传图片
 */
export function useBatchUpload() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (files: File[]) => {
            const results: UploadAnalyzeResponse[] = []
            for (const file of files) {
                const formData = new FormData()
                formData.append('file', file)
                formData.append('auto_analyze', 'true')

                const { data } = await apiClient.post<UploadAnalyzeResponse>('/images/upload', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                })
                results.push(data)
            }
            return results
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['images'] })
        },
    })
}

/**
 * 删除图片
 */
export function useDeleteImage() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (id: number) => {
            await apiClient.delete(`/images/${id}`)
            return id
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['images'] })
        },
    })
}

/**
 * 更新图片信息
 */
export function useUpdateImage() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async ({ id, data }: {
            id: number
            data: {
                tags?: string[]           // 废弃：按标签名更新
                tag_ids?: number[]        // 新流程：按标签 ID 更新
                description?: string
            }
        }) => {
            const { data: result } = await apiClient.put<ImageResponse>(`/images/${id}`, data)
            return result
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['image', variables.id] })
            queryClient.invalidateQueries({ queryKey: ['images'] })
        },
    })
}

/**
 * 为图片添加单个标签（支持 ID 或名称）
 */
export function useAddImageTag() {
    return useMutation({
        mutationFn: async ({ imageId, tagId, tagName }: {
            imageId: number
            tagId?: number
            tagName?: string
        }) => {
            const params = new URLSearchParams()
            if (tagId) params.set('tag_id', tagId.toString())
            if (tagName) params.set('tag_name', tagName)

            const { data } = await apiClient.post<{
                message: string
                tag_id: number
                tag_name: string
                is_new: boolean
            }>(`/images/${imageId}/tags?${params.toString()}`)
            return data
        },
    })
}

/**
 * 从图片删除单个标签
 */
export function useRemoveImageTag() {
    return useMutation({
        mutationFn: async ({ imageId, tagId }: { imageId: number; tagId: number }) => {
            const { data } = await apiClient.delete<{ message: string; tag_id: number }>(
                `/images/${imageId}/tags/${tagId}`
            )
            return data
        },
    })
}

