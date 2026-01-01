<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useUserStore, useThemeStore } from '@/stores'
import { Button } from '@/components/ui/button'
import { Moon, Sun, LogIn, ArrowLeft, Menu, X, FolderOpen, Sparkles } from 'lucide-vue-next'

defineProps<{
  showBack?: boolean
}>()

const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()

// 移动端菜单
const mobileMenuOpen = ref(false)
</script>

<template>
  <header class="fixed top-0 left-0 right-0 z-50 bg-background/80 backdrop-blur-md border-b border-border">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between h-14 sm:h-16">
        <!-- 左侧：返回/Logo -->
        <div class="flex items-center gap-2 sm:gap-4">
          <RouterLink v-if="showBack" to="/">
            <Button variant="ghost" size="icon" class="text-muted-foreground w-8 h-8 sm:w-9 sm:h-9">
              <ArrowLeft class="w-4 h-4 sm:w-5 sm:h-5" />
            </Button>
          </RouterLink>
          <RouterLink to="/" class="flex items-center gap-2">
            <img src="/logo.png" alt="ImgTag" class="w-8 h-8 sm:w-9 sm:h-9 rounded-xl" />
            <span class="text-lg sm:text-xl font-bold bg-gradient-to-r from-foreground to-muted-foreground bg-clip-text text-transparent">
              ImgTag
            </span>
          </RouterLink>
        </div>

        <!-- 中间导航 (桌面端) - 使用分段控制器风格 -->
        <nav class="hidden md:flex items-center">
          <div class="flex items-center bg-muted/50 rounded-full p-1">
            <RouterLink 
              to="/search?mode=gallery" 
              class="flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-full transition-all"
              :class="route.query.mode !== 'smart'
                ? 'bg-background text-foreground shadow-sm' 
                : 'text-muted-foreground hover:text-foreground'"
            >
              <FolderOpen class="w-4 h-4" />
              图库浏览
            </RouterLink>
            <RouterLink 
              to="/search?mode=smart" 
              class="flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-full transition-all"
              :class="route.query.mode === 'smart' 
                ? 'bg-gradient-to-r from-violet-500 to-purple-600 text-white shadow-sm' 
                : 'text-muted-foreground hover:text-foreground'"
            >
              <Sparkles class="w-4 h-4" />
              智能搜索
            </RouterLink>
          </div>
        </nav>

        <!-- 右侧操作 -->
        <div class="flex items-center gap-1 sm:gap-2">
          <Button 
            variant="ghost" 
            size="icon" 
            @click="themeStore.toggleDark()"
            class="text-muted-foreground w-8 h-8 sm:w-9 sm:h-9"
          >
            <Moon v-if="themeStore.isDark" class="w-4 h-4 sm:w-5 sm:h-5" />
            <Sun v-else class="w-4 h-4 sm:w-5 sm:h-5" />
          </Button>

          <!-- 未登录时显示登录按钮 -->
          <template v-if="!userStore.isLoggedIn">
            <RouterLink to="/login" class="hidden sm:block">
              <Button variant="default" size="sm" class="gap-2">
                <LogIn class="w-4 h-4" />
                登录
              </Button>
            </RouterLink>
          </template>

          <!-- 移动端菜单按钮 -->
          <Button 
            variant="ghost" 
            size="icon" 
            class="md:hidden text-muted-foreground w-8 h-8"
            @click="mobileMenuOpen = !mobileMenuOpen"
          >
            <X v-if="mobileMenuOpen" class="w-5 h-5" />
            <Menu v-else class="w-5 h-5" />
          </Button>
        </div>
      </div>
    </div>

    <!-- 移动端下拉菜单 -->
    <Transition name="slide-down">
      <div 
        v-if="mobileMenuOpen"
        class="md:hidden border-t border-border bg-background/95 backdrop-blur-lg"
      >
        <nav class="px-4 py-3 space-y-1">
          <!-- 分段控制器风格的导航 -->
          <div class="flex items-center bg-muted/50 rounded-xl p-1 mb-3">
            <RouterLink 
              to="/search?mode=gallery" 
              class="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium rounded-lg transition-all"
              :class="route.query.mode !== 'smart' 
                ? 'bg-background text-foreground shadow-sm' 
                : 'text-muted-foreground'"
              @click="mobileMenuOpen = false"
            >
              <FolderOpen class="w-4 h-4" />
              图库浏览
            </RouterLink>
            <RouterLink 
              to="/search?mode=smart" 
              class="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium rounded-lg transition-all"
              :class="route.query.mode === 'smart' 
                ? 'bg-gradient-to-r from-violet-500 to-purple-600 text-white shadow-sm' 
                : 'text-muted-foreground'"
              @click="mobileMenuOpen = false"
            >
              <Sparkles class="w-4 h-4" />
              智能搜索
            </RouterLink>
          </div>
          
          <div class="pt-2 border-t border-border">
            <!-- 登录用户显示"我的图库"入口 -->
            <template v-if="userStore.isLoggedIn">
              <RouterLink 
                to="/my-files" 
                class="flex items-center justify-between px-4 py-3 text-primary font-medium hover:bg-accent rounded-lg"
                @click="mobileMenuOpen = false"
              >
                <span class="flex items-center gap-2">
                  <FolderOpen class="w-4 h-4" />
                  我的图库
                </span>
              </RouterLink>
            </template>
            <!-- 未登录显示登录 -->
            <template v-else>
              <RouterLink 
                to="/login" 
                class="flex items-center gap-2 px-4 py-3 text-primary font-medium hover:bg-accent rounded-lg"
                @click="mobileMenuOpen = false"
              >
                <LogIn class="w-4 h-4" />
                登录
              </RouterLink>
            </template>
          </div>
        </nav>
      </div>
    </Transition>
  </header>
</template>

<style scoped>
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.2s ease;
}
.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
