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
        component: () => import('@/views/Upload.vue')
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
        component: () => import('@/views/Settings.vue')
    }
]

const router = createRouter({
    history: createWebHistory(),
    routes
})

export default router
