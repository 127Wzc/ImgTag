import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse } from 'axios'

/**
 * Axios 实例配置
 * - 自动注入 JWT Token
 * - 处理 401 跳转登录
 * - 统一错误处理
 */
const apiClient: AxiosInstance = axios.create({
    baseURL: '/api/v1',
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
