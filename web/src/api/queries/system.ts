/**
 * System API Queries
 * Dashboard statistics and system status
 */
import { useQuery } from '@tanstack/vue-query'
import apiClient from '../client'

// Types
export interface DashboardStats {
    images: {
        total: number
        pending: number
        analyzed: number
    }
    today: {
        uploaded: number
        analyzed: number
    }
    queue: {
        total: number
        processing: number
        pending: number
        running: boolean
    }
    system: {
        vision_model: string
        embedding_model: string
        embedding_dimensions: number
        version: string
    }
}

// Query: Dashboard Stats（进入页面时请求一次，不自动刷新）
export function useDashboardStats() {
    return useQuery({
        queryKey: ['dashboard'],
        queryFn: async () => {
            const response = await apiClient.get<DashboardStats>('/system/dashboard')
            return response.data
        },
    })
}
