import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { getImages, getSystemStatus } from '@/api'

export const useAppStore = defineStore('app', () => {
    // 系统状态
    const systemStatus = ref(null)
    const isLoading = ref(false)
    const error = ref(null)

    // 图像数据
    const images = ref([])
    const totalImages = ref(0)
    const currentPage = ref(1)
    const pageSize = ref(20)

    // 主题管理
    const theme = ref(localStorage.getItem('theme') || 'dark') // light, dark

    // 初始化主题
    function initTheme() {
        const savedTheme = localStorage.getItem('theme')
        if (savedTheme) {
            theme.value = savedTheme
        } else {
            // 没有保存的主题，默认使用暗色
            theme.value = 'dark'
        }
        applyTheme(theme.value)
    }

    // 应用主题
    function applyTheme(newTheme) {
        const html = document.documentElement
        if (newTheme === 'dark') {
            html.classList.add('dark-theme')
            html.classList.remove('light-theme')
        } else {
            html.classList.add('light-theme')
            html.classList.remove('dark-theme')
        }
        localStorage.setItem('theme', newTheme)
    }

    // 切换主题
    function toggleTheme() {
        theme.value = theme.value === 'light' ? 'dark' : 'light'
        applyTheme(theme.value)
    }

    // 设置主题
    function setTheme(newTheme) {
        if (newTheme === 'light' || newTheme === 'dark') {
            theme.value = newTheme
            applyTheme(newTheme)
        }
    }

    // 监听主题变化
    watch(theme, (newTheme) => {
        applyTheme(newTheme)
    })

    // 获取系统状态
    async function fetchSystemStatus() {
        try {
            systemStatus.value = await getSystemStatus()
        } catch (e) {
            error.value = e.message
        }
    }

    // 获取图像列表
    async function fetchImages(params = {}) {
        isLoading.value = true
        error.value = null

        try {
            const result = await getImages({
                ...params,
                limit: pageSize.value,
                offset: (currentPage.value - 1) * pageSize.value
            })

            images.value = result.images
            totalImages.value = result.total
        } catch (e) {
            error.value = e.message
            images.value = []
            totalImages.value = 0
        } finally {
            isLoading.value = false
        }
    }

    // 设置当前页
    function setPage(page) {
        currentPage.value = page
    }

    return {
        systemStatus,
        isLoading,
        error,
        images,
        totalImages,
        currentPage,
        pageSize,
        theme,
        initTheme,
        toggleTheme,
        setTheme,
        fetchSystemStatus,
        fetchImages,
        setPage
    }
})
