import { defineStore } from 'pinia'
import { ref } from 'vue'
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
        fetchSystemStatus,
        fetchImages,
        setPage
    }
})
