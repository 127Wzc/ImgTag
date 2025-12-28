<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './Sidebar.vue'
import FloatingUploadButton from './FloatingUploadButton.vue'
import { useUserStore, useThemeStore } from '@/stores'

const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()

// 公开页面（不需要侧边栏的页面）
const publicPages = ['/', '/gallery', '/search', '/login']

// 是否显示侧边栏布局
const showSidebar = computed(() => {
  // 明确需要隐藏导航的页面
  if (route.meta.hideNav) return false
  // 未登录时，公开页面不显示侧边栏
  if (!userStore.isLoggedIn && publicPages.includes(route.path)) return false
  // 其他情况显示侧边栏
  return true
})

// 路由变化时关闭移动端菜单
watch(() => route.path, () => {
  themeStore.mobileMenuOpen = false
})
</script>

<template>
  <div class="min-h-screen bg-background">
    <!-- 带侧边栏的布局（登录后） -->
    <template v-if="showSidebar">
      <Sidebar />
      <main 
        class="min-h-screen transition-all duration-300 pt-14 lg:pt-0"
        :class="themeStore.sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-56'"
      >
        <slot />
      </main>
    </template>

    <!-- 无侧边栏的简洁布局（公开页面） -->
    <template v-else>
      <slot />
    </template>

    <!-- 悬浮上传按钮（全局） -->
    <FloatingUploadButton />
  </div>
</template>

