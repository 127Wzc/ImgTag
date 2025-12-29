<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useUserStore, useThemeStore } from '@/stores'
import { Button } from '@/components/ui/button'
import {
  FolderOpen,
  Settings,
  CheckSquare,
  Tags,
  User,
  LogOut,
  Moon,
  Sun,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  Sparkles,
  Image,
  ChevronUp,
  Activity,
  HardDrive,
} from 'lucide-vue-next'

const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()

// 导航项定义 - 按逻辑分组
// 核心功能区（所有登录用户可见）
const coreItems = computed(() => [
  { 
    name: 'Dashboard', 
    path: '/dashboard', 
    icon: Activity, 
    label: '仪表盘',
    requiresAuth: false  // 公开可用
  },
  { 
    name: 'MyFiles', 
    path: '/my-files', 
    icon: FolderOpen, 
    label: '我的图库',
    highlight: true,
    requiresAuth: true 
  },
  { 
    name: 'Explore', 
    path: '/search', 
    icon: Sparkles, 
    label: '图片探索',
    requiresAuth: false  // 公开可用
  },
])

// 管理功能区（仅管理员可见）
const adminItems = computed(() => [
  { name: 'StorageEndpoints', path: '/storage-endpoints', icon: HardDrive, label: '存储端点' },
  { name: 'Tags', path: '/tags', icon: Tags, label: '标签管理' },
  { name: 'Approvals', path: '/approvals', icon: CheckSquare, label: '审批管理' },
  { name: 'Settings', path: '/settings', icon: Settings, label: '系统设置' },
])

// 过滤可见项
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
  return route.path === path
}

function handleLogout() {
  userStore.logout()
  window.location.href = '/'
}

// 用户菜单下拉
const showUserMenu = ref(false)

function toggleUserMenu() {
  showUserMenu.value = !showUserMenu.value
}

// 点击外部关闭
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
    class="fixed left-0 top-0 z-40 h-screen bg-sidebar border-r border-sidebar-border transition-all duration-300 hidden lg:block"
    :class="themeStore.sidebarCollapsed ? 'w-16' : 'w-56'"
  >
    <div class="flex flex-col h-full">
      <!-- Logo -->
      <div class="h-14 flex items-center justify-between px-3 border-b border-sidebar-border">
        <RouterLink to="/" class="flex items-center gap-2">
          <div class="w-8 h-8 bg-gradient-to-br from-primary to-violet-600 rounded-lg flex items-center justify-center shadow-lg shadow-primary/25">
            <Image class="w-4 h-4 text-white" />
          </div>
          <span 
            v-if="!themeStore.sidebarCollapsed" 
            class="text-base font-bold text-sidebar-foreground"
          >
            ImgTag
          </span>
        </RouterLink>
        <Button
          variant="ghost"
          size="icon"
          class="w-7 h-7 text-sidebar-foreground hover:bg-sidebar-accent"
          @click="themeStore.toggleSidebar"
        >
          <ChevronLeft v-if="!themeStore.sidebarCollapsed" class="w-4 h-4" />
          <ChevronRight v-else class="w-4 h-4" />
        </Button>
      </div>

      <!-- 导航菜单 -->
      <nav class="flex-1 px-2 py-3 space-y-1 overflow-y-auto">
        <!-- 核心功能 -->
        <template v-if="visibleCoreItems.length > 0">
          <RouterLink
            v-for="item in visibleCoreItems"
            :key="item.name"
            :to="item.path"
            class="group flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 relative"
            :class="[
              isActive(item.path)
                ? 'bg-primary/10 text-primary font-medium'
                : item.highlight
                  ? 'text-sidebar-foreground hover:bg-sidebar-accent'
                  : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground'
            ]"
          >
            <component 
              :is="item.icon" 
              class="w-5 h-5 shrink-0 transition-colors" 
              :class="isActive(item.path) ? 'text-primary' : ''"
            />
            <span v-if="!themeStore.sidebarCollapsed" class="flex-1">{{ item.label }}</span>
          </RouterLink>
        </template>

        <!-- 管理员分割线 -->
        <div v-if="visibleAdminItems.length > 0" class="my-3">
          <div class="flex items-center gap-2 px-3 py-1">
            <div class="flex-1 h-px bg-sidebar-border"></div>
            <span v-if="!themeStore.sidebarCollapsed" class="text-[10px] text-sidebar-foreground/40 uppercase tracking-wider">管理</span>
            <div class="flex-1 h-px bg-sidebar-border"></div>
          </div>
        </div>

        <!-- 管理员导航 -->
        <RouterLink
          v-for="item in visibleAdminItems"
          :key="item.name"
          :to="item.path"
          class="flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200"
          :class="[
            isActive(item.path)
              ? 'bg-primary/10 text-primary font-medium'
              : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground'
          ]"
        >
          <component 
            :is="item.icon" 
            class="w-5 h-5 shrink-0"
            :class="isActive(item.path) ? 'text-primary' : ''"
          />
          <span v-if="!themeStore.sidebarCollapsed">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <!-- 底部操作区 -->
      <div class="p-2 border-t border-sidebar-border space-y-1">
        <!-- 主题切换 -->
        <Button
          variant="ghost"
          class="w-full justify-start gap-3 text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground"
          :class="themeStore.sidebarCollapsed ? 'px-0 justify-center' : 'px-3'"
          @click="themeStore.toggleDark()"
        >
          <Moon v-if="themeStore.isDark" class="w-5 h-5" />
          <Sun v-else class="w-5 h-5" />
          <span v-if="!themeStore.sidebarCollapsed" class="text-sm">
            {{ themeStore.isDark ? '深色' : '浅色' }}
          </span>
        </Button>

        <!-- 用户中心/登录 -->
        <template v-if="userStore.isLoggedIn">
          <!-- 用户卡片 - 点击弹出菜单 -->
          <div class="relative user-menu-container">
            <button
              @click.stop="toggleUserMenu"
              class="w-full flex items-center gap-2 px-3 py-2 rounded-lg transition-colors cursor-pointer"
              :class="showUserMenu ? 'bg-sidebar-accent' : 'bg-sidebar-accent/50 hover:bg-sidebar-accent'"
            >
              <div class="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
                <User class="w-4 h-4 text-primary" />
              </div>
              <template v-if="!themeStore.sidebarCollapsed">
                <div class="flex-1 min-w-0 text-left">
                  <div class="text-sm font-medium text-sidebar-foreground truncate">{{ userStore.username }}</div>
                  <div class="text-xs text-sidebar-foreground/50">{{ userStore.isAdmin ? '管理员' : '用户' }}</div>
                </div>
                <ChevronUp class="w-4 h-4 text-sidebar-foreground/50 transition-transform" :class="showUserMenu ? '' : 'rotate-180'" />
              </template>
            </button>
            
            <!-- 下拉菜单 -->
            <Transition name="fade-up">
              <div 
                v-if="showUserMenu"
                class="absolute bottom-full left-0 right-0 mb-1 bg-popover border border-border rounded-lg shadow-lg overflow-hidden"
                :class="themeStore.sidebarCollapsed ? 'w-48 left-auto right-0' : ''"
              >
                <RouterLink
                  to="/user-center"
                  class="flex items-center gap-3 px-3 py-2.5 text-sm text-foreground hover:bg-accent transition-colors"
                  @click="showUserMenu = false"
                >
                  <User class="w-4 h-4" />
                  个人中心
                </RouterLink>
                <button
                  @click="handleLogout"
                  class="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-red-500 hover:bg-red-500/10 transition-colors"
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
            class="flex items-center gap-3 px-3 py-2 rounded-lg transition-colors text-primary hover:bg-primary/10"
            :class="themeStore.sidebarCollapsed && 'px-0 justify-center'"
          >
            <User class="w-5 h-5 shrink-0" />
            <span v-if="!themeStore.sidebarCollapsed" class="text-sm font-medium">登录</span>
          </RouterLink>
        </template>
      </div>
    </div>
  </aside>

  <!-- 移动端顶部栏 -->
  <header class="fixed top-0 left-0 right-0 z-50 h-14 bg-sidebar border-b border-sidebar-border flex items-center justify-between px-4 lg:hidden">
    <RouterLink to="/" class="flex items-center gap-2">
      <div class="w-8 h-8 bg-gradient-to-br from-primary to-violet-600 rounded-lg flex items-center justify-center">
        <Image class="w-4 h-4 text-white" />
      </div>
      <span class="text-base font-bold text-sidebar-foreground">ImgTag</span>
    </RouterLink>
    <Button
      variant="ghost"
      size="icon"
      class="text-sidebar-foreground"
      @click="themeStore.mobileMenuOpen = !themeStore.mobileMenuOpen"
    >
      <X v-if="themeStore.mobileMenuOpen" class="w-5 h-5" />
      <Menu v-else class="w-5 h-5" />
    </Button>
  </header>

  <!-- 移动端侧边栏遮罩 -->
  <Transition name="fade">
    <div 
      v-if="themeStore.mobileMenuOpen"
      class="fixed inset-0 z-40 bg-black/50 lg:hidden"
      @click="closeMobileMenu"
    />
  </Transition>

  <!-- 移动端侧边栏 -->
  <Transition name="slide">
    <aside
      v-if="themeStore.mobileMenuOpen"
      class="fixed left-0 top-14 z-50 w-64 h-[calc(100vh-3.5rem)] bg-sidebar border-r border-sidebar-border lg:hidden"
    >
      <div class="flex flex-col h-full">
        <!-- 导航菜单 -->
        <nav class="flex-1 px-2 py-3 space-y-1 overflow-y-auto">
          <template v-if="visibleCoreItems.length > 0">
            <RouterLink
              v-for="item in visibleCoreItems"
              :key="item.name"
              :to="item.path"
              class="flex items-center gap-3 px-3 py-2 rounded-lg transition-colors"
              :class="[
                isActive(item.path)
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-sidebar-foreground hover:bg-sidebar-accent'
              ]"
              @click="handleNavClick"
            >
              <component :is="item.icon" class="w-5 h-5 shrink-0" />
              <span class="flex-1">{{ item.label }}</span>
            </RouterLink>
          </template>

          <div v-if="visibleAdminItems.length > 0" class="my-3">
            <div class="flex items-center gap-2 px-3 py-1">
              <div class="flex-1 h-px bg-sidebar-border"></div>
              <span class="text-[10px] text-sidebar-foreground/40 uppercase tracking-wider">管理</span>
              <div class="flex-1 h-px bg-sidebar-border"></div>
            </div>
          </div>

          <RouterLink
            v-for="item in visibleAdminItems"
            :key="item.name"
            :to="item.path"
            class="flex items-center gap-3 px-3 py-2 rounded-lg transition-colors"
            :class="[
              isActive(item.path)
                ? 'bg-primary/10 text-primary font-medium'
                : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground'
            ]"
            @click="handleNavClick"
          >
            <component :is="item.icon" class="w-5 h-5 shrink-0" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>

        <!-- 底部操作区 -->
        <div class="p-2 border-t border-sidebar-border space-y-1">
          <Button
            variant="ghost"
            class="w-full justify-start gap-3 px-3 text-sidebar-foreground/70 hover:bg-sidebar-accent"
            @click="themeStore.toggleDark()"
          >
            <Moon v-if="themeStore.isDark" class="w-5 h-5" />
            <Sun v-else class="w-5 h-5" />
            <span class="text-sm">{{ themeStore.isDark ? '深色模式' : '浅色模式' }}</span>
          </Button>

          <template v-if="userStore.isLoggedIn">
            <!-- 移动端：用户信息卡片 -->
            <div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-sidebar-accent/50 mb-1">
              <div class="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center">
                <User class="w-4 h-4 text-primary" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium text-sidebar-foreground truncate">{{ userStore.username }}</div>
                <div class="text-xs text-sidebar-foreground/50">{{ userStore.isAdmin ? '管理员' : '用户' }}</div>
              </div>
            </div>
            <!-- 链接按钮 -->
            <RouterLink
              to="/user-center"
              class="flex items-center gap-3 px-3 py-2 rounded-lg text-sidebar-foreground hover:bg-sidebar-accent transition-colors"
              @click="handleNavClick"
            >
              <Settings class="w-4 h-4" />
              <span class="text-sm">个人中心</span>
            </RouterLink>
            <button
              @click="handleLogout"
              class="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-red-500 hover:bg-red-500/10 transition-colors"
            >
              <LogOut class="w-4 h-4" />
              <span class="text-sm">退出登录</span>
            </button>
          </template>
          <template v-else>
            <RouterLink
              to="/login"
              class="flex items-center gap-3 px-3 py-2 rounded-lg text-primary hover:bg-primary/10"
              @click="handleNavClick"
            >
              <User class="w-5 h-5 shrink-0" />
              <span class="text-sm font-medium">登录</span>
            </RouterLink>
          </template>
        </div>
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
  transition: all 0.15s ease;
}
.fade-up-enter-from,
.fade-up-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.2s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(-100%);
}
</style>
