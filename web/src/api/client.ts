import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse } from 'axios'
import { getRuntimeConfig } from '@/utils/runtime-config'

/**
 * Axios 实例配置
 * - 自动注入 JWT Token
 * - 处理 401 跳转登录
 * - 统一错误处理
 * 
 * VITE_API_BASE_URL: 只需配置域名，如 https://api.example.com
 */
const API_PREFIX = '/api/v1'
const baseUrl = getRuntimeConfig('VITE_API_BASE_URL')
const apiClient: AxiosInstance = axios.create({
    baseURL: baseUrl ? `${baseUrl.replace(/\/$/, '')}${API_PREFIX}` : API_PREFIX,
    timeout: 30000,
    headers: {
        'Content-Type': 'application/json',
    },
})

// 请求拦截器：注入 Token
apiClient.interceptors.request.use(
    (config: InternalAxiosRequestConfig) => {
        const token = localStorage.getItem('token')
        if (token && config.headers) {
            config.headers.Authorization = `Bearer ${token}`
        }
        return config
    },
    (error) => {
        return Promise.reject(error)
    }
)

// 响应拦截器：处理错误
apiClient.interceptors.response.use(
    (response: AxiosResponse) => {
        // 兼容后端统一错误格式：即使 HTTP 200，也可能返回 { success:false, error:{...} }
        const data = response.data as any
        if (data && typeof data === 'object' && data.success === false && data.error?.message) {
            const err: any = new Error(data.error.message)
            err.response = response
            return Promise.reject(err)
        }
        return response
    },
    (error) => {
        if (error.response?.status === 401) {
            // Token 过期或无效，清除并跳转登录
            localStorage.removeItem('token')
            localStorage.removeItem('user')
            // 如果不是在登录页，跳转到登录
            if (window.location.pathname !== '/login') {
                window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname)
            }
        }
        return Promise.reject(error)
    }
)

export default apiClient
