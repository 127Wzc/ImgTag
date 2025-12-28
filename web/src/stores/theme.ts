import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useDark, useToggle } from '@vueuse/core'

export const useThemeStore = defineStore('theme', () => {
    // 暗色模式
    const isDark = useDark()
    const toggleDark = useToggle(isDark)

    // 侧边栏折叠状态
    const sidebarCollapsed = ref(false)

    function toggleSidebar() {
        sidebarCollapsed.value = !sidebarCollapsed.value
    }

    // 移动端菜单状态
    const mobileMenuOpen = ref(false)

    return {
        isDark,
        toggleDark,
        sidebarCollapsed,
        toggleSidebar,
        mobileMenuOpen,
    }
})
