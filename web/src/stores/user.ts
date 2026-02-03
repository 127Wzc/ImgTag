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
    const lastFetchedAt = ref<number>(0)
    const isAutoRefreshBound = ref(false)
    let fetchPromise: Promise<void> | null = null

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
        await fetchCurrentUser({ force: true })
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
        lastFetchedAt.value = 0
        localStorage.removeItem('token')
        localStorage.removeItem('user')
    }

    async function fetchCurrentUser(options?: { force?: boolean; minIntervalMs?: number }): Promise<void> {
        if (!token.value) return

        const minIntervalMs = options?.minIntervalMs ?? 2 * 60 * 1000
        const now = Date.now()
        const shouldFetch = !!options?.force || now - lastFetchedAt.value >= minIntervalMs
        if (!shouldFetch) return

        if (fetchPromise) return fetchPromise

        fetchPromise = (async () => {
            try {
                const response = await apiClient.get('/auth/me')
                user.value = response.data
                localStorage.setItem('user', JSON.stringify(response.data))
                lastFetchedAt.value = Date.now()
            } catch (e: any) {
                const status = e?.response?.status
                // 仅在 token/账号确实无效时登出；网络抖动/后端错误不应强制清空登录态
                if (status === 401 || status === 403) {
                    logout()
                }
            } finally {
                fetchPromise = null
            }
        })()

        return fetchPromise
    }

    /**
     * 绑定“回到前台时刷新用户信息”的自动刷新逻辑（带节流）
     *
     * 触发时机：
     * - 页面从后台切回前台（visibilitychange -> visible）
     * - 浏览器窗口重新获得焦点（focus）
     *
     * 说明：
     * - 使用 localStorage 的 user 先渲染 UI
     * - 之后通过 /auth/me 刷新一次，确保权限/角色变更能较快生效
     */
    function bindAutoRefresh(options?: { minIntervalMs?: number }) {
        if (isAutoRefreshBound.value) return
        isAutoRefreshBound.value = true

        const minIntervalMs = options?.minIntervalMs ?? 2 * 60 * 1000

        const refreshIfNeeded = () => {
            if (!token.value) return
            void fetchCurrentUser({ minIntervalMs })
        }

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') refreshIfNeeded()
        })
        window.addEventListener('focus', refreshIfNeeded)

        // 启动后先同步一次（避免长期使用旧缓存）
        refreshIfNeeded()
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
        bindAutoRefresh,
    }
})
