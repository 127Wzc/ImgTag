<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores'
import apiClient from '@/api/client'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const isLogin = ref(true)
const loading = ref(false)
const error = ref('')
const allowRegister = ref(false)
const configLoading = ref(true)

// 表单数据
const loginForm = ref({
  username: '',
  password: '',
})
const registerForm = ref({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
})

// 获取公开配置
async function fetchPublicConfig() {
  try {
    const { data } = await apiClient.get('/auth/public-config')
    allowRegister.value = data.allow_register === true || data.allow_register === 'true'
  } catch {
    allowRegister.value = false
  } finally {
    configLoading.value = false
  }
}

onMounted(() => {
  fetchPublicConfig()
})

async function handleLogin() {
  if (!loginForm.value.username || !loginForm.value.password) {
    error.value = '请输入用户名和密码'
    return
  }
  
  loading.value = true
  error.value = ''
  
  try {
    await userStore.login(loginForm.value.username, loginForm.value.password)
    const redirect = route.query.redirect as string
    router.push(redirect || '/')
  } catch (e: any) {
    error.value = e.response?.data?.detail || '登录失败'
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  if (registerForm.value.password !== registerForm.value.confirmPassword) {
    error.value = '两次输入的密码不一致'
    return
  }
  
  loading.value = true
  error.value = ''
  
  try {
    await userStore.register(
      registerForm.value.username,
      registerForm.value.password,
      registerForm.value.email || undefined
    )
    // 注册成功，切换到登录
    isLogin.value = true
    error.value = ''
    loginForm.value.username = registerForm.value.username
  } catch (e: any) {
    error.value = e.response?.data?.detail || '注册失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-background p-4">
    <div class="w-full max-w-md space-y-8">
      <!-- Logo -->
      <div class="text-center">
        <img src="/logo.png" alt="ImgTag" class="w-16 h-16 mx-auto rounded-2xl mb-4" />
        <h1 class="text-4xl font-bold text-primary">ImgTag</h1>
        <p class="mt-2 text-muted-foreground">智能图片标签图床</p>
      </div>

      <!-- 登录/注册表单卡片 -->
      <div class="bg-card border border-border rounded-xl p-8 shadow-lg">
        <!-- Tab 切换（仅允许注册时显示） -->
        <div v-if="allowRegister && !configLoading" class="flex mb-6 bg-muted rounded-lg p-1">
          <button
            @click="isLogin = true"
            class="flex-1 py-2 px-4 rounded-md text-sm font-medium transition"
            :class="isLogin ? 'bg-background text-foreground shadow' : 'text-muted-foreground'"
          >
            登录
          </button>
          <button
            @click="isLogin = false"
            class="flex-1 py-2 px-4 rounded-md text-sm font-medium transition"
            :class="!isLogin ? 'bg-background text-foreground shadow' : 'text-muted-foreground'"
          >
            注册
          </button>
        </div>

        <!-- 仅登录时的标题 -->
        <h2 v-if="!allowRegister && !configLoading" class="text-xl font-semibold text-foreground mb-6 text-center">
          登录
        </h2>

        <!-- 错误提示 -->
        <div v-if="error" class="mb-4 p-3 bg-destructive/10 text-destructive text-sm rounded-lg">
          {{ error }}
        </div>

        <!-- 登录表单 -->
        <form v-if="isLogin || !allowRegister" @submit.prevent="handleLogin" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-foreground mb-1.5">
              用户名
            </label>
            <input
              v-model="loginForm.username"
              type="text"
              class="w-full px-4 py-2.5 bg-background border border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="请输入用户名"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-foreground mb-1.5">
              密码
            </label>
            <input
              v-model="loginForm.password"
              type="password"
              class="w-full px-4 py-2.5 bg-background border border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="请输入密码"
            />
          </div>
          <button
            type="submit"
            :disabled="loading"
            class="w-full py-2.5 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 transition disabled:opacity-50"
          >
            {{ loading ? '登录中...' : '登录' }}
          </button>
        </form>

        <!-- 注册表单（仅允许注册时） -->
        <form v-else-if="allowRegister" @submit.prevent="handleRegister" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-foreground mb-1.5">
              用户名
            </label>
            <input
              v-model="registerForm.username"
              type="text"
              class="w-full px-4 py-2.5 bg-background border border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="请输入用户名"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-foreground mb-1.5">
              邮箱 <span class="text-muted-foreground">(可选)</span>
            </label>
            <input
              v-model="registerForm.email"
              type="email"
              class="w-full px-4 py-2.5 bg-background border border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="请输入邮箱"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-foreground mb-1.5">
              密码
            </label>
            <input
              v-model="registerForm.password"
              type="password"
              class="w-full px-4 py-2.5 bg-background border border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="请输入密码"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-foreground mb-1.5">
              确认密码
            </label>
            <input
              v-model="registerForm.confirmPassword"
              type="password"
              class="w-full px-4 py-2.5 bg-background border border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="请再次输入密码"
            />
          </div>
          <button
            type="submit"
            :disabled="loading"
            class="w-full py-2.5 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 transition disabled:opacity-50"
          >
            {{ loading ? '注册中...' : '注册' }}
          </button>
        </form>
      </div>

      <!-- 返回首页链接 -->
      <div class="text-center">
        <RouterLink to="/" class="text-sm text-muted-foreground hover:text-foreground transition">
          返回首页
        </RouterLink>
      </div>
    </div>
  </div>
</template>
