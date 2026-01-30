import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'

import App from './App.vue'
import router from './router'
import { initAnalytics } from './analytics'
import './index.css'

const app = createApp(App)

// 插件注册
app.use(createPinia())
app.use(VueQueryPlugin)
app.use(router)

// 初始化分析追踪
initAnalytics()

app.mount('#app')
