<template>
  <el-config-provider :locale="zhCn">
    <div class="app-container">
      <!-- 侧边栏 -->
      <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div class="logo">
          <el-icon :size="26"><PictureFilled /></el-icon>
          <span v-if="!sidebarCollapsed" class="logo-text">ImgTag</span>
        </div>
        
        <nav class="sidebar-nav">
          <router-link 
            v-for="item in menuItems" 
            :key="item.path"
            :to="item.path" 
            class="nav-item"
            :class="{ active: currentRoute === item.path }"
          >
            <el-icon :size="20"><component :is="item.icon" /></el-icon>
            <span v-if="!sidebarCollapsed">{{ item.label }}</span>
          </router-link>
        </nav>
        
        <div class="sidebar-footer">
          <div class="collapse-btn" @click="sidebarCollapsed = !sidebarCollapsed">
            <el-icon :size="18">
              <ArrowLeft v-if="!sidebarCollapsed" />
              <ArrowRight v-else />
            </el-icon>
          </div>
        </div>
      </aside>

      <!-- 主内容区 -->
      <main class="main-content">
        <header class="header">
          <div class="header-left">
            <h1 class="page-title">{{ pageTitle }}</h1>
          </div>
          <div class="header-right">
            <el-tag type="success" effect="light" round>
              <el-icon class="status-icon"><SuccessFilled /></el-icon>
              运行中
            </el-tag>
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
  </el-config-provider>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

const route = useRoute()
const sidebarCollapsed = ref(false)

const menuItems = [
  { path: '/', label: '仪表盘', icon: 'HomeFilled' },
  { path: '/gallery', label: '图片库', icon: 'Picture' },
  { path: '/upload', label: '上传图片', icon: 'Upload' },
  { path: '/search', label: '智能搜索', icon: 'Search' },
  { path: '/tasks', label: '任务队列', icon: 'List' },
  { path: '/settings', label: '系统设置', icon: 'Setting' },
]

const currentRoute = computed(() => route.path)

const pageTitle = computed(() => {
  const item = menuItems.find(m => m.path === route.path)
  return item?.label || 'ImgTag'
})
</script>

<style scoped>
.app-container {
  display: flex;
  min-height: 100vh;
  background: var(--bg-primary);
  position: relative;
}

/* 环境光效果 */
.app-container::before {
  content: '';
  position: fixed;
  top: -200px;
  right: -200px;
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.06) 0%, transparent 70%);
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
}

.app-container::after {
  content: '';
  position: fixed;
  bottom: -200px;
  left: -200px;
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, rgba(212, 165, 116, 0.05) 0%, transparent 70%);
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
}

/* 侧边栏 - 深色毛玻璃 */
.sidebar {
  width: 240px;
  background: linear-gradient(180deg, #0f0d13 0%, #1a1625 50%, #2d2640 100%);
  display: flex;
  flex-direction: column;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  z-index: 100;
  border-right: 1px solid rgba(139, 92, 246, 0.1);
  box-shadow: 4px 0 24px rgba(0, 0, 0, 0.15);
}

.sidebar.collapsed {
  width: 72px;
}

.logo {
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: white;
  border-bottom: 1px solid rgba(139, 92, 246, 0.15);
  position: relative;
}

/* 金色微光效果 */
.logo::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 20%;
  right: 20%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(212, 165, 116, 0.5), transparent);
}

.logo-text {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 1px;
  background: linear-gradient(135deg, #fff 0%, #d4a574 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
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
  gap: 14px;
  padding: 14px 18px;
  border-radius: 14px;
  color: rgba(255, 255, 255, 0.6);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.nav-item:hover {
  background: rgba(139, 92, 246, 0.15);
  color: rgba(255, 255, 255, 0.9);
}

.nav-item.active {
  background: linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%);
  color: white;
  box-shadow: 0 4px 16px rgba(139, 92, 246, 0.4), 0 0 40px rgba(139, 92, 246, 0.15);
}

/* 活动项金色点缀 */
.nav-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 24px;
  background: linear-gradient(180deg, #d4a574 0%, #e8c9a4 100%);
  border-radius: 0 3px 3px 0;
  box-shadow: 0 0 12px rgba(212, 165, 116, 0.5);
}

.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 14px;
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid rgba(139, 92, 246, 0.1);
}

.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  transition: all 0.25s ease;
}

.collapse-btn:hover {
  background: rgba(139, 92, 246, 0.15);
  color: white;
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
}

.sidebar.collapsed + .main-content,
.sidebar.collapsed ~ .main-content {
  margin-left: 72px;
}

/* 头部 - 毛玻璃效果 */
.header {
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 36px;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(139, 92, 246, 0.08);
  position: sticky;
  top: 0;
  z-index: 50;
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
  gap: 16px;
}

.status-icon {
  margin-right: 4px;
}

.content-wrapper {
  flex: 1;
  padding: 32px 36px;
  overflow-y: auto;
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
</style>
