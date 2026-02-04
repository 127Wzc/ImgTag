<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useUserStore, useThemeStore } from '@/stores'
import { Button } from '@/components/ui/button'
import {
  FolderOpen,
  Settings,
  ListTodo,
  Tags,
  User,
  LogOut,
  Moon,
  Sun,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  ChevronUp,
  Activity,
  HardDrive,
  Search,
  Inbox
} from 'lucide-vue-next'

const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()

// 导航项定义
const coreItems = computed(() => [
  {
    name: 'Dashboard',
    path: '/dashboard',
    icon: Activity,
    label: '仪表盘',
    requiresAuth: false
  },
  {
    name: 'MyFiles',
    path: '/my-files',
    icon: FolderOpen,
    label: '我的图库',
    requiresAuth: true
  },
  {
    name: 'Explore',
    path: '/search',
    icon: Search,
    label: '探索',
    requiresAuth: false
  },
])

const adminItems = computed(() => [
  { name: 'StorageEndpoints', path: '/storage-endpoints', icon: HardDrive, label: '存储端点' },
  { name: 'Tags', path: '/tags', icon: Tags, label: '标签管理' },
  { name: 'Approvals', path: '/approvals', icon: Inbox, label: '审批管理' },
  { name: 'Tasks', path: '/tasks', icon: ListTodo, label: '任务队列' },
  { name: 'Settings', path: '/settings', icon: Settings, label: '系统设置' },
])

const visibleCoreItems = computed(() =>
  coreItems.value.filter(item => {
    if (item.requiresAuth && !userStore.isLoggedIn) return false
    return true
  })
)

const visibleAdminItems = computed(() =>
  userStore.isAdmin ? adminItems.value : []
)

function isActive(path: string) {
  // 简单前缀匹配，解决子路由高亮问题
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function handleLogout() {
  userStore.logout()
  window.location.href = '/'
}

const showUserMenu = ref(false)

function toggleUserMenu() {
  showUserMenu.value = !showUserMenu.value
}

function handleUserMenuClickOutside(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.user-menu-container')) {
    showUserMenu.value = false
  }
}

watch(showUserMenu, (show) => {
  if (show) {
    document.addEventListener('click', handleUserMenuClickOutside)
  } else {
    document.removeEventListener('click', handleUserMenuClickOutside)
  }
})

function closeMobileMenu() {
  themeStore.mobileMenuOpen = false
}

function handleNavClick() {
  if (window.innerWidth < 1024) {
    closeMobileMenu()
  }
}
</script>

<template>
  <!-- 桌面端侧边栏 -->
  <aside
    class="fixed left-0 top-0 z-40 h-screen bg-background border-r border-border/40 transition-all duration-300 hidden lg:flex flex-col"
    :class="themeStore.sidebarCollapsed ? 'w-16' : 'w-56'"
  >
    <!-- Logo 区域 -->
    <div class="h-14 flex items-center px-4 border-b border-border/40 shrink-0">
      <RouterLink to="/" class="flex items-center gap-3 overflow-hidden">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center shrink-0 border border-primary/10">
           <img src="/logo.png" alt="Logo" class="w-5 h-5 object-contain opacity-90" />
        </div>
        <span
          class="font-semibold text-base tracking-tight whitespace-nowrap transition-opacity duration-300"
          :class="themeStore.sidebarCollapsed ? 'opacity-0 w-0' : 'opacity-100'"
        >
          ImgTag
        </span>
      </RouterLink>
    </div>

    <!-- 导航菜单 -->
    <nav class="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto scrollbar-thin scrollbar-thumb-border/50 hover:scrollbar-thumb-border/80">
      <template v-if="visibleCoreItems.length > 0">
        <RouterLink
          v-for="item in visibleCoreItems"
          :key="item.name"
          :to="item.path"
          class="group flex items-center gap-3 px-3 py-2 rounded-md transition-all duration-200"
          :class="[
            isActive(item.path)
              ? 'bg-primary/10 text-primary font-medium shadow-sm shadow-primary/5'
              : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
          ]"
          :title="themeStore.sidebarCollapsed ? item.label : ''"
        >
          <component
            :is="item.icon"
            class="w-4.5 h-4.5 shrink-0 transition-colors"
            :class="isActive(item.path) ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground'"
          />
          <span
            class="text-sm whitespace-nowrap transition-all duration-300 origin-left"
            :class="themeStore.sidebarCollapsed ? 'opacity-0 scale-90 w-0 hidden' : 'opacity-100 scale-100'"
          >
            {{ item.label }}
          </span>
        </RouterLink>
      </template>

      <!-- 分割线 -->
      <div v-if="visibleAdminItems.length > 0 && !themeStore.sidebarCollapsed" class="my-4 px-3">
        <p class="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wider">管理</p>
      </div>
      <div v-else-if="visibleAdminItems.length > 0" class="my-2 border-t border-border/40 w-8 mx-auto"></div>

      <!-- 管理员导航 -->
      <RouterLink
        v-for="item in visibleAdminItems"
        :key="item.name"
        :to="item.path"
        class="group flex items-center gap-3 px-3 py-2 rounded-md transition-all duration-200"
        :class="[
          isActive(item.path)
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
        ]"
        :title="themeStore.sidebarCollapsed ? item.label : ''"
      >
        <component
          :is="item.icon"
          class="w-4.5 h-4.5 shrink-0"
        />
        <span
          class="text-sm whitespace-nowrap transition-all duration-300 origin-left"
          :class="themeStore.sidebarCollapsed ? 'opacity-0 scale-90 w-0 hidden' : 'opacity-100 scale-100'"
        >
          {{ item.label }}
        </span>
      </RouterLink>
    </nav>

    <!-- 底部操作区 -->
    <div class="p-3 border-t border-border/40 space-y-1 bg-background/50 backdrop-blur-sm">
      <!-- 收缩按钮 -->
      <button
        @click="themeStore.toggleSidebar"
        class="hidden lg:flex w-full items-center gap-3 px-3 py-2 rounded-md text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-colors group"
        :class="themeStore.sidebarCollapsed && 'justify-center px-0'"
      >
         <component :is="themeStore.sidebarCollapsed ? ChevronRight : ChevronLeft" class="w-4.5 h-4.5" />
         <span
            class="text-sm whitespace-nowrap transition-all duration-300"
            :class="themeStore.sidebarCollapsed ? 'hidden' : 'block'"
         >
           收起菜单
         </span>
      </button>

      <!-- 主题切换 -->
      <button
        @click="themeStore.toggleDark()"
        class="w-full flex items-center gap-3 px-3 py-2 rounded-md text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-colors group"
        :class="themeStore.sidebarCollapsed && 'justify-center px-0'"
      >
        <component :is="themeStore.isDark ? Moon : Sun" class="w-4.5 h-4.5 transition-transform group-hover:rotate-12" />
        <span
          class="text-sm whitespace-nowrap transition-all duration-300"
          :class="themeStore.sidebarCollapsed ? 'hidden' : 'block'"
        >
          {{ themeStore.isDark ? '深色模式' : '浅色模式' }}
        </span>
      </button>

      <!-- 用户菜单 -->
      <template v-if="userStore.isLoggedIn">
        <div class="relative user-menu-container pt-1">
          <button
            @click.stop="toggleUserMenu"
            class="w-full flex items-center gap-3 px-2 py-2 rounded-lg border border-transparent hover:bg-muted/50 hover:border-border/40 transition-all outline-none"
            :class="[
              showUserMenu ? 'bg-muted/50 border-border/40' : '',
              themeStore.sidebarCollapsed ? 'justify-center px-0' : ''
            ]"
          >
            <div class="w-7 h-7 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shrink-0 shadow-sm">
              <span class="text-[10px] font-bold text-white">{{ userStore.username.substring(0,2).toUpperCase() }}</span>
            </div>

            <div
              class="flex-1 min-w-0 text-left transition-all duration-300"
              :class="themeStore.sidebarCollapsed ? 'hidden' : 'block'"
            >
              <div class="text-xs font-medium text-foreground truncate">{{ userStore.username }}</div>
              <div class="text-[10px] text-muted-foreground truncate">{{ userStore.isAdmin ? '管理员' : '普通用户' }}</div>
            </div>

            <ChevronUp
              v-if="!themeStore.sidebarCollapsed"
              class="w-3.5 h-3.5 text-muted-foreground transition-transform duration-200"
              :class="showUserMenu ? '' : 'rotate-180'"
            />
          </button>

          <!-- 悬浮菜单 -->
          <Transition name="fade-up">
            <div
              v-if="showUserMenu"
              class="absolute bottom-full left-0 right-0 mb-2 bg-popover/95 backdrop-blur border border-border/50 rounded-xl shadow-xl overflow-hidden ring-1 ring-border/10 p-1"
              :class="themeStore.sidebarCollapsed ? 'w-48 left-0' : ''"
              style="min-width: 160px;"
            >
               <div class="px-3 py-2 border-b border-border/40 mb-1 lg:hidden">
                  <div class="font-medium text-sm">{{ userStore.username }}</div>
                  <div class="text-xs text-muted-foreground">{{ userStore.user?.email }}</div>
               </div>
              <RouterLink
                to="/user-center"
                class="flex items-center gap-2.5 px-3 py-2 text-sm text-foreground/80 hover:text-foreground hover:bg-muted/60 rounded-lg transition-colors"
                @click="showUserMenu = false"
              >
                <Settings class="w-4 h-4" />
                账号设置
              </RouterLink>
              <button
                @click="handleLogout"
                class="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-red-500 hover:bg-red-500/10 rounded-lg transition-colors mt-1"
              >
                <LogOut class="w-4 h-4" />
                退出登录
              </button>
            </div>
          </Transition>
        </div>
      </template>
      <template v-else>
        <RouterLink
          to="/login"
          class="flex items-center gap-3 px-3 py-2 rounded-md transition-colors text-primary hover:bg-primary/10 border border-primary/20 hover:border-primary/50"
          :class="themeStore.sidebarCollapsed && 'justify-center px-0'"
        >
          <User class="w-4.5 h-4.5 shrink-0" />
          <span v-if="!themeStore.sidebarCollapsed" class="text-sm font-medium">登录 / 注册</span>
        </RouterLink>
      </template>
    </div>
  </aside>

  <!-- 移动端顶部 Header -->
  <header class="fixed top-0 left-0 right-0 z-40 h-14 bg-background/80 backdrop-blur-md border-b border-border/40 flex items-center justify-between px-4 lg:hidden">
    <div class="flex items-center gap-3">
      <Button
        variant="ghost"
        size="icon"
        class="-ml-2 text-muted-foreground"
        @click="themeStore.mobileMenuOpen = !themeStore.mobileMenuOpen"
      >
        <Menu v-if="!themeStore.mobileMenuOpen" class="w-5 h-5" />
        <X v-else class="w-5 h-5" />
      </Button>
      <span class="text-base font-bold tracking-tight">ImgTag</span>
    </div>
    <div class="w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center border border-primary/10">
      <img src="/logo.png" alt="Logo" class="w-5 h-5 object-contain" />
    </div>
  </header>

  <!-- 移动端侧边栏遮罩 -->
  <Transition name="fade">
    <div
      v-if="themeStore.mobileMenuOpen"
      class="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm lg:hidden"
      @click="closeMobileMenu"
    />
  </Transition>

  <!-- 移动端侧边栏 -->
  <Transition name="slide">
    <aside
      v-if="themeStore.mobileMenuOpen"
      class="fixed inset-y-0 left-0 z-50 w-72 bg-background border-r border-border shadow-2xl lg:hidden flex flex-col"
    >
      <div class="h-14 flex items-center justify-between px-4 border-b border-border/40">
        <span class="font-bold text-lg">ImgTag</span>
        <Button variant="ghost" size="icon" @click="closeMobileMenu">
          <X class="w-5 h-5" />
        </Button>
      </div>

      <nav class="flex-1 px-4 py-6 space-y-1 overflow-y-auto">
        <RouterLink
          v-for="item in visibleCoreItems"
          :key="item.name"
          :to="item.path"
          class="flex items-center gap-3 px-3 py-3 rounded-lg transition-colors text-base"
          :class="[
            isActive(item.path)
              ? 'bg-primary/10 text-primary font-medium'
              : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
          ]"
          @click="handleNavClick"
        >
          <component :is="item.icon" class="w-5 h-5" />
          {{ item.label }}
        </RouterLink>

        <div v-if="visibleAdminItems.length > 0" class="my-6 px-3">
           <p class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">管理控制台</p>
        </div>

        <RouterLink
          v-for="item in visibleAdminItems"
          :key="item.name"
          :to="item.path"
          class="flex items-center gap-3 px-3 py-3 rounded-lg transition-colors text-base"
          :class="[
            isActive(item.path)
              ? 'bg-primary/10 text-primary font-medium'
              : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
          ]"
          @click="handleNavClick"
        >
          <component :is="item.icon" class="w-5 h-5" />
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="p-4 border-t border-border/40 space-y-2 bg-muted/20">
        <button
          @click="themeStore.toggleDark()"
          class="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-muted-foreground hover:bg-muted/50 transition-colors"
        >
          <component :is="themeStore.isDark ? Moon : Sun" class="w-5 h-5" />
          {{ themeStore.isDark ? '切换到浅色模式' : '切换到深色模式' }}
        </button>

        <template v-if="userStore.isLoggedIn">
           <button
              @click="handleLogout"
              class="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-red-500 hover:bg-red-500/10 transition-colors"
            >
              <LogOut class="w-5 h-5" />
              退出登录
            </button>
        </template>
        <template v-else>
            <RouterLink to="/login" class="block">
              <Button class="w-full" size="lg">登录 / 注册</Button>
            </RouterLink>
        </template>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.fade-up-enter-active,
.fade-up-leave-active {
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.fade-up-enter-from,
.fade-up-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.95);
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(-100%);
}
</style>
