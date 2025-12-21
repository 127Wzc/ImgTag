import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as apiLogin, getCurrentUser, logout as apiLogout } from '@/api'

export const useAuthStore = defineStore('auth', () => {
    // 状态
    const token = ref(localStorage.getItem('token') || null)
    const user = ref(null)
    const isLoading = ref(false)
    const error = ref(null)

    // 计算属性
    const isLoggedIn = computed(() => !!token.value)
    const isAdmin = computed(() => user.value?.role === 'admin')
    const username = computed(() => user.value?.username || '')

    // 设置 token
    function setToken(newToken) {
        token.value = newToken
        if (newToken) {
            localStorage.setItem('token', newToken)
        } else {
            localStorage.removeItem('token')
        }
    }

    // 登录
    async function login(usernameInput, password) {
        isLoading.value = true
        error.value = null

        try {
            const result = await apiLogin(usernameInput, password)
            setToken(result.access_token)
            await fetchCurrentUser()
            return true
        } catch (e) {
            error.value = e.message
            return false
        } finally {
            isLoading.value = false
        }
    }

    // 登出
    async function logout() {
        try {
            await apiLogout()
        } catch (e) {
            // 忽略登出错误
        } finally {
            setToken(null)
            user.value = null
        }
    }

    // 获取当前用户信息
    async function fetchCurrentUser() {
        if (!token.value) return null

        try {
            user.value = await getCurrentUser()
            return user.value
        } catch (e) {
            // Token 无效，清除
            setToken(null)
            user.value = null
            return null
        }
    }

    // 初始化（检查已有 token）
    async function init() {
        if (token.value) {
            await fetchCurrentUser()
        }
    }

    return {
        token,
        user,
        isLoading,
        error,
        isLoggedIn,
        isAdmin,
        username,
        login,
        logout,
        fetchCurrentUser,
        init
    }
})
