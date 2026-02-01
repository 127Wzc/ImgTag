import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '@/api/client'
import { Permission, hasPermission, type PermissionType } from '@/constants/permissions'

export interface User {
    id: number
    username: string
    email: string | null
    role: 'admin' | 'user'
    permissions: number
    api_key: string | null
}

export const useUserStore = defineStore('user', () => {
    // State
    const token = ref<string | null>(localStorage.getItem('token'))
    const user = ref<User | null>(null)

    // 从 localStorage 恢复用户信息
    const savedUser = localStorage.getItem('user')
    if (savedUser) {
        try {
            user.value = JSON.parse(savedUser)
        } catch {
            localStorage.removeItem('user')
        }
    }

    // Getters
    const isLoggedIn = computed(() => !!token.value && !!user.value)
    const isAdmin = computed(() => user.value?.role === 'admin')
    const username = computed(() => user.value?.username ?? '')

    /**
     * 检查用户是否拥有指定权限
     * Admin 角色自动拥有所有权限
     */
    const checkPermission = (permission: PermissionType): boolean => {
        if (user.value?.role === 'admin') return true
        return hasPermission(user.value?.permissions ?? 0, permission)
    }

    /**
     * 是否有上传权限
     */
    const canUpload = computed(() => checkPermission(Permission.UPLOAD_IMAGE))

    // Actions
    async function login(usernameOrEmail: string, password: string): Promise<void> {
        const response = await apiClient.post('/auth/login', {
            username: usernameOrEmail,
            password: password,
        })

        token.value = response.data.access_token
        localStorage.setItem('token', response.data.access_token)

        // 登录成功后获取用户详细信息
        await fetchCurrentUser()
    }

    async function register(username: string, password: string, email?: string): Promise<void> {
        await apiClient.post('/auth/register', {
            username,
            password,
            email: email || null,
        })
    }

    function logout(): void {
        token.value = null
        user.value = null
        localStorage.removeItem('token')
        localStorage.removeItem('user')
    }

    async function fetchCurrentUser(): Promise<void> {
        if (!token.value) return
        try {
            const response = await apiClient.get('/auth/me')
            user.value = response.data
            localStorage.setItem('user', JSON.stringify(response.data))
        } catch {
            logout()
        }
    }

    return {
        // State
        token,
        user,
        // Getters
        isLoggedIn,
        isAdmin,
        username,
        canUpload,
        // Methods
        checkPermission,
        // Actions
        login,
        register,
        logout,
        fetchCurrentUser,
    }
})
