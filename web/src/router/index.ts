import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores'

// 路由配置
const routes: RouteRecordRaw[] = [
    {
        path: '/',
        name: 'Home',
        component: () => import('@/pages/Home.vue'),
        meta: { title: '首页', hideNav: true },
    },
    {
        path: '/dashboard',
        name: 'Dashboard',
        component: () => import('@/pages/Dashboard.vue'),
        meta: { title: '仪表盘' },
    },
    {
        // Gallery 重定向到 Search
        path: '/gallery',
        redirect: '/search?mode=gallery',
    },
    {
        path: '/my-files',
        name: 'MyFiles',
        component: () => import('@/pages/MyFiles.vue'),
        meta: { title: '我的图库', requiresAuth: true },
    },
    {
        path: '/upload',
        name: 'Upload',
        component: () => import('@/pages/Upload.vue'),
        meta: { title: '上传', requiresAuth: true },
    },
    {
        path: '/search',
        name: 'Search',
        component: () => import('@/pages/Search.vue'),
        meta: { title: '图片探索' },
    },
    {
        path: '/tasks',
        name: 'Tasks',
        component: () => import('@/pages/Tasks.vue'),
        meta: { title: '任务队列', requiresAuth: true },
    },
    {
        path: '/settings',
        name: 'Settings',
        component: () => import('@/pages/Settings.vue'),
        meta: { title: '系统设置', requiresAdmin: true },
    },
    {
        path: '/login',
        name: 'Login',
        component: () => import('@/pages/Login.vue'),
        meta: { title: '登录', hideNav: true, guest: true },
    },
    {
        path: '/approvals',
        name: 'Approvals',
        component: () => import('@/pages/Approvals.vue'),
        meta: { title: '审批管理', requiresAdmin: true },
    },
    {
        path: '/collections',
        name: 'Collections',
        component: () => import('@/pages/Collections.vue'),
        meta: { title: '收藏夹', requiresAuth: true },
    },
    {
        path: '/tags',
        name: 'Tags',
        component: () => import('@/pages/Tags.vue'),
        meta: { title: '标签管理', requiresAdmin: true },
    },
    {
        path: '/user-center',
        name: 'UserCenter',
        component: () => import('@/pages/UserCenter.vue'),
        meta: { title: '用户中心', requiresAuth: true },
    },
    {
        path: '/storage',
        name: 'Storage',
        component: () => import('@/pages/StorageManagement.vue'),
        meta: { title: '存储管理', requiresAdmin: true },
    },
    {
        path: '/storage-endpoints',
        name: 'StorageEndpoints',
        component: () => import('@/pages/StorageEndpoints.vue'),
        meta: { title: '存储端点', requiresAdmin: true },
    },
    // 404 页面
    {
        path: '/:pathMatch(.*)*',
        name: 'NotFound',
        component: () => import('@/pages/NotFound.vue'),
        meta: { title: '页面未找到', hideNav: true },
    },
]

const router = createRouter({
    history: createWebHistory(),
    routes,
})

// 路由守卫
router.beforeEach((to, _from, next) => {
    // 更新页面标题
    document.title = to.meta.title
        ? `${to.meta.title} - ImgTag`
        : 'ImgTag'

    // 权限检查 - 使用延迟获取 store 避免 Pinia 未初始化
    const userStore = useUserStore()
    const isLoggedIn = userStore.isLoggedIn
    const isAdmin = userStore.isAdmin

    // 需要管理员权限
    if (to.meta.requiresAdmin) {
        if (!isLoggedIn) {
            return next({ name: 'Login', query: { redirect: to.fullPath } })
        }
        if (!isAdmin) {
            return next({ name: 'Dashboard' })
        }
    }

    // 需要登录
    if (to.meta.requiresAuth) {
        if (!isLoggedIn) {
            return next({ name: 'Login', query: { redirect: to.fullPath } })
        }
    }

    // 已登录用户访问登录页，跳转仪表盘
    if (to.meta.guest && isLoggedIn) {
        return next({ name: 'Dashboard' })
    }

    next()
})

// 类型扩展
declare module 'vue-router' {
    interface RouteMeta {
        title?: string
        requiresAuth?: boolean
        requiresAdmin?: boolean
        hideNav?: boolean
        guest?: boolean
    }
}

export default router
