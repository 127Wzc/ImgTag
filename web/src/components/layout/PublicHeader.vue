<script setup lang="ts">
import { ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useUserStore, useThemeStore } from '@/stores'
import { Button } from '@/components/ui/button'
import { Moon, Sun, LogIn, ArrowLeft, Menu, X, FolderOpen, Sparkles, Plug } from 'lucide-vue-next'

defineProps<{ showBack?: boolean }>()
const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()
const mobileMenuOpen = ref(false)
const navigation = [
  { label: '图库浏览', to: '/search?mode=gallery', icon: FolderOpen, active: () => route.path === '/search' && route.query.mode !== 'smart' },
  { label: '智能搜索', to: '/search?mode=smart', icon: Sparkles, active: () => route.path === '/search' && route.query.mode === 'smart' },
  { label: '连接 MCP', to: '/connect', icon: Plug, active: () => route.path === '/connect' },
]
watch(() => route.fullPath, () => { mobileMenuOpen.value = false })
</script>

<template>
  <header class="fixed inset-x-0 top-0 z-50 border-b border-border bg-background/90 backdrop-blur-md">
    <div class="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:h-16 sm:px-6 lg:px-8">
      <div class="flex items-center gap-2 md:flex-1">
        <RouterLink v-if="showBack" to="/" aria-label="返回首页"><ArrowLeft class="h-4 w-4" /></RouterLink>
        <RouterLink to="/" class="flex items-center gap-2">
          <img src="/logo.png" alt="" class="h-8 w-8 rounded-xl sm:h-9 sm:w-9" />
          <span class="text-lg font-bold tracking-tight">ImgTag</span>
        </RouterLink>
      </div>
      <nav aria-label="主导航" class="hidden items-center gap-1 rounded-full bg-muted/50 p-1 md:flex">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" :aria-current="item.active() ? 'page' : undefined" class="flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors duration-150" :class="item.active() ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:bg-background/50 hover:text-foreground'">
          <component :is="item.icon" class="h-4 w-4" />{{ item.label }}
        </RouterLink>
      </nav>
      <div class="flex items-center justify-end gap-2 md:flex-1">
        <Button variant="ghost" size="icon" aria-label="切换主题" class="h-8 w-8 text-muted-foreground" @click="themeStore.toggleDark()"><Moon v-if="themeStore.isDark" class="h-4 w-4" /><Sun v-else class="h-4 w-4" /></Button>
        <Button as-child size="sm" variant="outline" class="hidden sm:inline-flex"><RouterLink :to="userStore.isLoggedIn ? '/dashboard' : '/login'">{{ userStore.isLoggedIn ? '控制台' : '登录' }}</RouterLink></Button>
        <Button variant="ghost" size="icon" aria-label="导航菜单" :aria-expanded="mobileMenuOpen" aria-controls="public-mobile-menu" class="h-8 w-8 md:hidden" @click="mobileMenuOpen = !mobileMenuOpen"><X v-if="mobileMenuOpen" class="h-5 w-5" /><Menu v-else class="h-5 w-5" /></Button>
      </div>
    </div>
    <Transition name="menu">
      <nav v-if="mobileMenuOpen" id="public-mobile-menu" aria-label="移动导航" class="border-t border-border bg-background px-4 py-3 md:hidden">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" :aria-current="item.active() ? 'page' : undefined" class="flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-colors" :class="item.active() ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:bg-muted/50'">
          <component :is="item.icon" class="h-4 w-4" />{{ item.label }}
        </RouterLink>
        <RouterLink :to="userStore.isLoggedIn ? '/dashboard' : '/login'" class="mt-2 flex items-center gap-3 border-t border-border px-3 pt-3 text-sm"><LogIn class="h-4 w-4" />{{ userStore.isLoggedIn ? '控制台' : '登录' }}</RouterLink>
      </nav>
    </Transition>
  </header>
</template>

<style scoped>
.menu-enter-active, .menu-leave-active { transition: opacity 150ms ease, transform 150ms ease; }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: translateY(-4px); }
@media (prefers-reduced-motion: reduce) {
  .menu-enter-active, .menu-leave-active { transition: none; }
}
</style>
