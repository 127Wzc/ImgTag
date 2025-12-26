<template>
  <el-config-provider :locale="zhCn">
    <div class="app-container" v-if="!isLoginPage">
      <!-- 移动端遮罩层 -->
      <div 
        class="sidebar-overlay" 
        :class="{ visible: mobileMenuOpen }" 
        @click="closeMobileMenu"
      ></div>
      
      <!-- 侧边栏 -->
      <aside class="sidebar" :class="{ collapsed: sidebarCollapsed, 'mobile-open': mobileMenuOpen }">
        <div class="logo">
          <el-icon :size="26"><PictureFilled /></el-icon>
          <span v-if="!sidebarCollapsed" class="logo-text">ImgTag</span>
          <!-- 移动端关闭按钮 -->
          <button class="mobile-close-btn" @click="closeMobileMenu">
            <el-icon :size="20"><Close /></el-icon>
          </button>
        </div>
        
        <nav class="sidebar-nav">
          <template v-for="(item, index) in menuItems" :key="item.path || item.divider">
            <!-- 分组分隔线 -->
            <div v-if="item.divider" class="nav-divider">
              <span v-if="!sidebarCollapsed" class="divider-label">{{ item.label }}</span>
              <div v-else class="divider-line"></div>
            </div>
            <!-- 菜单项 -->
            <router-link 
              v-else
              :to="item.path" 
              class="nav-item"
              :class="{ active: currentRoute === item.path }"
              @click="handleNavClick"
            >
              <el-icon :size="20"><component :is="item.icon" /></el-icon>
              <span v-if="!sidebarCollapsed">{{ item.label }}</span>
            </router-link>
          </template>
        </nav>
        
        <div class="sidebar-footer">
          <div class="theme-toggle" @click="toggleTheme" :title="theme === 'light' ? '切换到深色模式' : '切换到浅色模式'">
            <el-icon :size="20">
              <Sunny v-if="theme === 'dark'" />
              <Moon v-else />
            </el-icon>
            <span v-if="!sidebarCollapsed" class="theme-text">
              {{ theme === 'light' ? '深色模式' : '浅色模式' }}
            </span>
          </div>
          <div class="collapse-btn desktop-only" @click="sidebarCollapsed = !sidebarCollapsed">
            <el-icon :size="18">
              <ArrowLeft v-if="!sidebarCollapsed" />
              <ArrowRight v-else />
            </el-icon>
          </div>
        </div>
      </aside>

      <!-- 主内容区 -->
      <main class="main-content" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
        <header class="header">
          <div class="header-left">
            <!-- 移动端汉堡菜单按钮 -->
            <button class="hamburger-btn" @click="toggleMobileMenu">
              <el-icon :size="22"><Fold /></el-icon>
            </button>
            <h1 class="page-title">{{ pageTitle }}</h1>
          </div>
          <div class="header-right">
            <!-- 进行中的任务 -->
            <div v-if="processingTasks.length > 0" class="header-item tasks-indicator">
              <el-icon class="tasks-icon"><Loading class="is-loading" /></el-icon>
              <span class="tasks-text">
                <span class="tasks-count">{{ processingTasks.length }}</span>
                <span class="tasks-label">个任务进行中</span>
              </span>
              <el-popover
                placement="bottom-end"
                :width="320"
                trigger="hover"
                popper-class="tasks-popover"
              >
                <template #reference>
                  <el-icon class="tasks-arrow"><ArrowDown /></el-icon>
                </template>
                <div class="tasks-list">
                  <div class="tasks-list-header">
                    <span>进行中的任务</span>
                    <el-button 
                      text 
                      type="primary" 
                      size="small"
                      @click="router.push('/tasks')"
                    >
                      查看全部
                    </el-button>
                  </div>
                  <div class="tasks-list-content">
                    <div 
                      v-for="task in processingTasks" 
                      :key="task.id"
                      class="task-item"
                    >
                      <div class="task-info">
                        <div class="task-type">{{ getTaskTypeName(task.type) }}</div>
                        <div class="task-time">{{ formatTaskTime(task.created_at) }}</div>
                      </div>
                      <el-progress 
                        :percentage="0" 
                        :indeterminate="true"
                        :stroke-width="3"
                        style="margin-top: 8px;"
                      />
                    </div>
                    <div v-if="processingTasks.length === 0" class="tasks-empty">
                      <el-icon :size="32" color="var(--text-muted)"><Document /></el-icon>
                      <p>暂无进行中的任务</p>
                    </div>
                  </div>
                </div>
              </el-popover>
            </div>
            
            <!-- 健康状态 -->
            <div class="header-item health-indicator" :class="healthStatusClass">
              <el-icon class="health-icon">
                <SuccessFilled v-if="healthStatus === 'healthy'" />
                <CircleCloseFilled v-else-if="healthStatus === 'error'" />
                <Loading v-else class="is-loading" />
              </el-icon>
              <span class="health-text">
                {{ healthStatusText }}
              </span>
            </div>
            
            <!-- 用户状态 -->
            <div v-if="authStore.isLoggedIn" class="header-item user-info">
              <el-icon><User /></el-icon>
              <span class="user-name clickable" @click="router.push('/user-center')">
                {{ authStore.username }}
              </span>
              <el-tag v-if="authStore.isAdmin" size="small" type="warning">管理员</el-tag>
              <el-button text type="danger" size="small" @click="handleLogout">登出</el-button>
            </div>
            <router-link v-else to="/login" class="header-item login-btn">
              <el-icon><User /></el-icon>
              <span>登录</span>
            </router-link>
          </div>
        </header>
        
        <div class="content-wrapper">
          <router-view v-slot="{ Component }">
            <transition name="fade-slide" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
      </main>
    </div>
    
    <!-- 登录页单独渲染 -->
    <router-view v-else />
  </el-config-provider>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { healthCheck, getTasks } from '@/api'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()
const sidebarCollapsed = ref(false)

// 移动端菜单状态
const mobileMenuOpen = ref(false)
const isMobile = ref(false)

// 检测是否为移动端
const checkMobile = () => {
  isMobile.value = window.innerWidth <= 768
  // 在切换到桌面模式时关闭移动端菜单
  if (!isMobile.value) {
    mobileMenuOpen.value = false
  }
}

// 切换移动端菜单
const toggleMobileMenu = () => {
  mobileMenuOpen.value = !mobileMenuOpen.value
  // 防止背景滚动
  document.body.style.overflow = mobileMenuOpen.value ? 'hidden' : ''
}

// 关闭移动端菜单
const closeMobileMenu = () => {
  mobileMenuOpen.value = false
  document.body.style.overflow = ''
}

// 导航点击处理（移动端点击后关闭菜单）
const handleNavClick = () => {
  if (isMobile.value) {
    closeMobileMenu()
  }
}

// 是否登录页
const isLoginPage = computed(() => route.meta?.hideNav === true)

const theme = computed(() => appStore.theme)

const toggleTheme = () => {
  appStore.toggleTheme()
}

const menuItems = computed(() => {
  const items = []
  
  // 基础菜单项 - 所有用户可见
  items.push(
    { path: '/', label: '仪表盘', icon: 'HomeFilled' },
    { path: '/gallery', label: '图片库', icon: 'Picture' },
    { path: '/search', label: '智能搜索', icon: 'Search' },
  )
  
  // 登录用户可以看到更多功能
  if (authStore.isLoggedIn) {
    items.push(
      { divider: true, label: '功能菜单' },
      { path: '/upload', label: '上传图片', icon: 'Upload' },
      { path: '/tasks', label: '任务队列', icon: 'List' },
      { path: '/collections', label: '我的收藏', icon: 'Star' },
    )
  }
  
  // 管理员可以看到系统设置、标签管理和审批管理
  if (authStore.isAdmin) {
    items.push(
      { divider: true, label: '管理功能' },
      { path: '/settings', label: '系统设置', icon: 'Setting' },
      { path: '/tags', label: '标签管理', icon: 'CollectionTag' },
      { path: '/storage', label: '存储管理', icon: 'Box' },
      { path: '/approvals', label: '审批管理', icon: 'Check' },
    )
  }
  
  return items
})

const currentRoute = computed(() => route.path)

const pageTitle = computed(() => {
  const item = menuItems.value.find(m => m.path === route.path)
  return item?.label || 'ImgTag'
})

// 健康状态
const healthStatus = ref('checking') // checking, healthy, error
const healthStatusClass = computed(() => healthStatus.value)
const healthStatusText = computed(() => {
  const map = {
    checking: '检查中...',
    healthy: '服务正常',
    error: '服务异常'
  }
  return map[healthStatus.value] || '未知'
})

// 进行中的任务
const processingTasks = ref([])

// 获取健康状态
const checkHealth = async () => {
  try {
    const result = await healthCheck()
    healthStatus.value = result.status === 'healthy' ? 'healthy' : 'error'
  } catch (e) {
    healthStatus.value = 'error'
  }
}

// 获取进行中的任务
const fetchProcessingTasks = async () => {
  try {
    const res = await getTasks({ 
      limit: 5, 
      status: 'processing' 
    })
    processingTasks.value = res.tasks || []
  } catch (e) {
    console.error('获取进行中任务失败:', e)
    processingTasks.value = []
  }
}

// 任务类型名称映射
const getTaskTypeName = (type) => {
  const map = {
    'add_to_collection': '添加到收藏夹',
    'vectorize_batch': '批量向量化',
    'analyze_image': '图片分析'
  }
  return map[type] || type
}

// 格式化任务时间
const formatTaskTime = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now - date) / 1000) // 秒
  
  if (diff < 60) return `${diff}秒前`
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return date.toLocaleDateString()
}

// 登出处理
const handleLogout = async () => {
  await authStore.logout()
  router.push('/login')
}

// 定时刷新
let healthTimer = null
let tasksTimer = null

onMounted(async () => {
  // 初始化主题
  appStore.initTheme()
  
  // 初始化认证状态
  await authStore.init()
  
  // 初始化移动端检测
  checkMobile()
  window.addEventListener('resize', checkMobile)
  
  checkHealth()
  fetchProcessingTasks()
  
  // 每30秒刷新健康状态
  healthTimer = setInterval(checkHealth, 30000)
  // 每30秒刷新进行中的任务（仅用于导航栏徽章显示）
  tasksTimer = setInterval(fetchProcessingTasks, 30000)
})

onUnmounted(() => {
  if (healthTimer) clearInterval(healthTimer)
  if (tasksTimer) clearInterval(tasksTimer)
  window.removeEventListener('resize', checkMobile)
  document.body.style.overflow = ''
})
</script>

<style scoped>
.app-container {
  display: flex;
  min-height: 100vh;
  position: relative;
  z-index: 1;
}

/* 环境光效果 */
/* Removed ambient glow */
.app-container::before,
.app-container::after {
  display: none;
}

/* 侧边栏 - 深色毛玻璃 */
.sidebar {
  width: 240px;
  background: var(--bg-sidebar);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  display: flex;
  flex-direction: column;
  transition: width 0.3s ease, background var(--transition-normal);
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  z-index: 100;
  border-right: 1px solid var(--border-color);
}

.sidebar.collapsed {
  width: 72px;
}

/* Logo - Clean */
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-primary);
  /* border-bottom: 1px solid var(--border-color-light); */
  position: relative;
  margin-bottom: 12px;
}

.logo-text {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.5px;
  color: var(--text-primary);
}

.sidebar-nav {
  flex: 1;
  padding: 20px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  margin: 2px 12px;
  border-radius: 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s ease;
}

.nav-item:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-primary);
}

.nav-item.active {
  background: rgba(0, 113, 227, 0.1);
  color: var(--primary-color);
}

.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 14px;
}

/* 菜单分组分隔线 */
.nav-divider {
  margin: 12px 12px 6px 12px;
  padding: 0 16px;
}

.divider-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
}

.divider-line {
  height: 1px;
  background: var(--border-color-light);
  margin: 8px 0;
}

.sidebar.collapsed .nav-divider {
  padding: 0 8px;
}

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color-light);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.theme-toggle {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  color: var(--text-sidebar-muted);
  cursor: pointer;
  transition: all 0.25s ease;
  margin: 2px 12px;
}

.theme-toggle:hover {
  background: var(--bg-hover);
  color: var(--primary-color);
}

.theme-text {
  font-size: 14px;
  font-weight: 500;
}

.sidebar.collapsed .theme-toggle {
  justify-content: center;
  padding: 10px;
  margin: 2px;
}

.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  border-radius: 10px;
  color: var(--text-sidebar-muted);
  cursor: pointer;
  transition: all 0.25s ease;
  margin: 2px 12px;
}

.collapse-btn:hover {
  background: var(--bg-hover);
  color: var(--primary-color);
}

.sidebar.collapsed .collapse-btn {
  margin: 2px;
}

/* 主内容区 */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  margin-left: 240px;
  transition: margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  min-height: 100vh;
  position: relative;
  z-index: 1;
  background: transparent;
}

.sidebar.collapsed + .main-content,
.sidebar.collapsed ~ .main-content {
  margin-left: 72px;
}

/* 头部 - 毛玻璃效果 */
.header {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border-bottom: 1px solid var(--border-color-light);
  position: sticky;
  top: 0;
  z-index: 50;
  box-shadow: var(--shadow-sm);
  transition: background var(--transition-normal), border-color var(--transition-normal);
}

.page-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: -0.5px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 头部状态项 */
.header-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: var(--radius-lg);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color-light);
  transition: all var(--transition-fast);
  font-size: 13px;
  font-weight: 500;
  cursor: default;
}

.header-item:hover {
  background: var(--bg-hover);
  border-color: var(--border-color);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

/* 任务指示器 */
.tasks-indicator {
  color: var(--primary-color);
  cursor: pointer;
}

.tasks-icon {
  font-size: 18px;
  color: var(--primary-color);
}

.tasks-text {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.tasks-count {
  font-size: 16px;
  font-weight: 600;
  color: var(--primary-color);
}

.tasks-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.tasks-arrow {
  font-size: 12px;
  color: var(--text-muted);
  margin-left: 4px;
  cursor: pointer;
  transition: transform var(--transition-fast);
}

.tasks-indicator:hover .tasks-arrow {
  transform: translateY(2px);
}

/* 健康状态指示器 */
.health-indicator {
  color: var(--text-primary);
}

.health-indicator.healthy {
  color: var(--success-color);
  background: rgba(52, 199, 89, 0.1);
  border-color: rgba(52, 199, 89, 0.2);
}

.health-indicator.error {
  color: var(--danger-color);
  background: rgba(255, 59, 48, 0.1);
  border-color: rgba(255, 59, 48, 0.2);
}

.health-indicator.checking {
  color: var(--text-secondary);
}

.health-icon {
  font-size: 18px;
}

.health-text {
  font-size: 13px;
  white-space: nowrap;
}

/* 任务列表弹窗 */
:deep(.tasks-popover) {
  padding: 0 !important;
}

.tasks-list {
  max-height: 400px;
  overflow-y: auto;
}

.tasks-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color-light);
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.tasks-list-content {
  padding: 8px;
}

.task-item {
  padding: 12px;
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  margin-bottom: 8px;
  transition: all var(--transition-fast);
}

.task-item:hover {
  background: var(--bg-hover);
}

.task-item:last-child {
  margin-bottom: 0;
}

.task-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.task-type {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.task-time {
  font-size: 12px;
  color: var(--text-secondary);
}

.tasks-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  color: var(--text-muted);
}

.tasks-empty p {
  margin: 12px 0 0 0;
  font-size: 13px;
}

/* ===== 移动端响应式样式 ===== */

/* 移动端遮罩层 */
.sidebar-overlay {
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 99;
  opacity: 0;
  transition: opacity 0.3s ease;
}

.sidebar-overlay.visible {
  opacity: 1;
}

/* 汉堡菜单按钮 */
.hamburger-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border: none;
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  cursor: pointer;
  transition: all var(--transition-fast);
  margin-right: 12px;
  flex-shrink: 0;
}

.hamburger-btn:hover {
  background: var(--bg-hover);
  color: var(--primary-color);
}

.hamburger-btn:active {
  transform: scale(0.95);
}

/* 移动端关闭按钮 */
.mobile-close-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: var(--bg-hover);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  margin-left: auto;
}

.mobile-close-btn:hover {
  background: var(--bg-hover);
  color: var(--primary-color);
}

/* 桌面端折叠按钮 */
.desktop-only {
  display: flex;
}

/* 响应式 - 768px 以下为移动端 */
@media (max-width: 768px) {
  /* 显示遮罩层 */
  .sidebar-overlay {
    display: block;
    pointer-events: none;
  }
  
  .sidebar-overlay.visible {
    pointer-events: auto;
  }

  /* 汉堡菜单按钮 */
  .hamburger-btn {
    display: flex;
  }
  
  /* 移动端关闭按钮 */
  .mobile-close-btn {
    display: flex;
  }
  
  /* 隐藏桌面端折叠按钮 */
  .desktop-only {
    display: none;
  }

  /* 侧边栏 - 移动端抽屉模式 */
  .sidebar {
    width: 280px;
    transform: translateX(-100%);
    box-shadow: var(--shadow-xl);
  }
  
  .sidebar.mobile-open {
    transform: translateX(0);
  }
  
  /* 侧边栏在移动端不需要折叠状态 */
  .sidebar.collapsed {
    width: 280px;
    transform: translateX(-100%);
  }
  
  .sidebar.collapsed.mobile-open {
    transform: translateX(0);
  }
  
  .sidebar.collapsed .nav-item span,
  .sidebar.collapsed .logo-text,
  .sidebar.collapsed .theme-text,
  .sidebar.collapsed .divider-label {
    display: inline;
  }
  
  .sidebar.collapsed .nav-item {
    justify-content: flex-start;
    padding: 10px 16px;
  }
  
  .sidebar.collapsed .divider-line {
    display: none;
  }
  
  .sidebar.collapsed .nav-divider {
    padding: 0 16px;
  }

  /* 主内容区全宽 */
  .main-content {
    margin-left: 0 !important;
  }
  
  /* Header 适配 */
  .header {
    padding: 0 16px;
    min-height: 56px;
  }
  
  .header-left {
    display: flex;
    align-items: center;
  }
  
  .page-title {
    font-size: 18px;
  }
  
  .header-right {
    gap: 8px;
  }
  
  .header-item {
    padding: 6px 10px;
    font-size: 12px;
  }
  
  .tasks-label,
  .health-text {
    display: none;
  }
  
  .tasks-count {
    font-size: 14px;
  }
  
  /* 用户信息适配 */
  .user-info .user-name {
    max-width: 60px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .user-info .el-tag {
    display: none;
  }
  
  /* 内容区padding适配 */
  .content-wrapper {
    padding: 16px;
  }
  
  /* Logo区域适配 */
  .logo {
    justify-content: flex-start;
    padding: 0 20px;
  }
}

/* 更小屏幕适配 */
@media (max-width: 480px) {
  .header {
    padding: 0 12px;
  }
  
  .hamburger-btn {
    width: 36px;
    height: 36px;
    margin-right: 8px;
  }
  
  .page-title {
    font-size: 16px;
  }
  
  .header-item {
    padding: 6px 8px;
  }
  
  .content-wrapper {
    padding: 12px;
  }
  
  .sidebar {
    width: 260px;
  }
  
  .sidebar.collapsed {
    width: 260px;
  }
}

.content-wrapper {
  flex: 1;
  padding: 32px 36px;
  overflow-y: auto;
  position: relative;
  z-index: 1;
}

/* 页面切换动画 */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(12px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-12px);
}

/* 用户信息 */
.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-name {
  font-weight: 500;
  color: var(--text-primary);
}

.user-name.clickable {
  cursor: pointer;
  transition: color 0.2s ease;
}

.user-name.clickable:hover {
  color: var(--primary-color);
}

.login-btn {
  text-decoration: none;
  color: var(--primary-color);
  cursor: pointer;
}

.login-btn:hover {
  background: rgba(0, 113, 227, 0.1);
}
</style>
