import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { MutationCache, QueryCache, QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import 'vue-sonner/style.css'

import App from './App.vue'
import router from './router'
import { initAnalytics } from './analytics'
import './index.css'
import { notifyError, notifySuccess } from '@/utils/notify'

const app = createApp(App)

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      const meta = (query?.meta as any) || {}
      if (meta?.silentError) return
      notifyError(error)
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      const meta = (mutation.options.meta as any) || {}
      if (meta?.silentError) return
      if (typeof meta?.errorMessage === 'string' && meta.errorMessage.trim()) {
        notifyError(meta.errorMessage, { once: true })
        return
      }
      notifyError(error)
    },
    onSuccess: (_data, _variables, _context, mutation) => {
      const meta = (mutation.options.meta as any) || {}
      if (meta?.silentSuccess) return
      if (typeof meta?.successMessage === 'string' && meta.successMessage.trim()) {
        notifySuccess(meta.successMessage, { once: true })
      }
    },
  }),
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

// 未捕获的 Promise 异常兜底提示（避免“请求失败但无提示”）
window.addEventListener('unhandledrejection', (event) => {
  notifyError(event.reason)
})

// 插件注册
app.use(createPinia())
app.use(VueQueryPlugin, { queryClient })
app.use(router)

// 初始化分析追踪
initAnalytics()

app.mount('#app')
