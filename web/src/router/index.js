import { createRouter, createWebHistory } from 'vue-router'

const routes = [
    {
        path: '/',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue')
    },
    {
        path: '/gallery',
        name: 'Gallery',
        component: () => import('@/views/Gallery.vue')
    },
    {
        path: '/upload',
        name: 'Upload',
        component: () => import('@/views/Upload.vue'),
        meta: { requiresAuth: true }  // 需要登录
    },
    {
        path: '/search',
        name: 'Search',
        component: () => import('@/views/Search.vue')
    },
    {
        path: '/tasks',
        name: 'Tasks',
        component: () => import('@/views/Tasks.vue')
    },
    {
        path: '/settings',
        name: 'Settings',
        component: () => import('@/views/Settings.vue'),
        meta: { requiresAdmin: true }  // 需要管理员
    },
    {
        path: '/login',
        name: 'Login',
        component: () => import('@/views/Login.vue'),
        meta: { hideNav: true, guest: true }
    },
    {
        path: '/approvals',
        name: 'Approvals',
        component: () => import('@/views/Approvals.vue'),
        meta: { requiresAdmin: true }  // 需要管理员
    },
    {
        path: '/collections',
        name: 'Collections',
        component: () => import('@/views/Collections.vue'),
        meta: { requiresAuth: true }  // 需要登录
    },
    {
        path: '/tags',
        name: 'Tags',
        component: () => import('@/views/Tags.vue'),
        meta: { requiresAdmin: true }  // 需要管理员
    },
    {
        path: '/user-center',
        name: 'UserCenter',
        component: () => import('@/views/UserCenter.vue'),
        meta: { requiresAuth: true }  // 需要登录
    }
]

const router = createRouter({
    history: createWebHistory(),
    routes
})

// 路由守卫
router.beforeEach((to, from, next) => {
    const token = localStorage.getItem('token')
    const isLoggedIn = !!token

    // 解析 token 获取角色（简单版本）
    let isAdmin = false
    if (token) {
        try {
            const payload = JSON.parse(atob(token.split('.')[1]))
            isAdmin = payload.role === 'admin'
        } catch (e) {
            // Token 解析失败
        }
    }

    // 需要管理员权限
    if (to.meta.requiresAdmin) {
        if (!isLoggedIn) {
            return next({ name: 'Login', query: { redirect: to.fullPath } })
        }
        if (!isAdmin) {
            alert('需要管理员权限')
            return next({ name: 'Dashboard' })
        }
    }

    // 需要登录
    if (to.meta.requiresAuth) {
        if (!isLoggedIn) {
            return next({ name: 'Login', query: { redirect: to.fullPath } })
        }
    }

    // 已登录用户访问登录页，跳转首页
    if (to.meta.guest && isLoggedIn) {
        return next({ name: 'Dashboard' })
    }

    next()
})

export default router
