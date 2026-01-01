<script setup lang="ts">
/**
 * Home - 首页/项目介绍
 * 静态页面，无 API 调用，适合 SEO 和防止爬虫触发数据库
 */
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores'
import { Button } from '@/components/ui/button'
import { 
  Sparkles, Tags, Search, Shield, Zap, 
  ArrowRight, Github, FolderOpen 
} from 'lucide-vue-next'

const userStore = useUserStore()

const features = [
  {
    icon: Sparkles,
    title: 'AI 智能标签',
    description: '基于视觉模型自动生成描述和标签',
    color: 'violet'
  },
  {
    icon: Search,
    title: '语义搜索',
    description: '通过自然语言描述找到相似图片',
    color: 'blue'
  },
  {
    icon: Tags,
    title: '标签管理',
    description: '分层标签体系，支持来源追踪',
    color: 'emerald'
  },
  {
    icon: Shield,
    title: '权限控制',
    description: '用户角色管理，API 密钥认证',
    color: 'amber'
  },
  {
    icon: Zap,
    title: '批量处理',
    description: '异步队列，支持批量分析和操作',
    color: 'rose'
  },
  {
    icon: FolderOpen,
    title: 'S3 存储',
    description: '支持本地和对象存储双模式',
    color: 'cyan'
  }
]
</script>

<template>
  <div class="min-h-screen bg-background">
    <!-- 顶部导航栏 -->
    <header class="fixed top-0 left-0 right-0 z-50 bg-background/80 backdrop-blur-lg border-b border-border">
      <div class="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
        <RouterLink to="/" class="flex items-center gap-2">
          <img src="/logo.png" alt="ImgTag" class="w-8 h-8 rounded-lg" />
          <span class="font-bold text-foreground">ImgTag</span>
        </RouterLink>
        
        <div class="flex items-center gap-2">
          <a 
            href="https://github.com/127Wzc/ImgTag" 
            target="_blank"
            class="flex items-center gap-2 px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition-colors"
          >
            <Github class="w-4 h-4" />
            <span class="hidden sm:inline">GitHub</span>
          </a>
          
          <template v-if="userStore.isLoggedIn">
            <RouterLink to="/dashboard">
              <Button size="sm" variant="outline" class="gap-1.5">
                <Zap class="w-4 h-4" />
                控制台
              </Button>
            </RouterLink>
          </template>
          <template v-else>
            <RouterLink to="/login">
              <Button size="sm" class="gap-1.5">
                登录
              </Button>
            </RouterLink>
          </template>
        </div>
      </div>
    </header>

    <!-- Hero Section -->
    <div class="relative overflow-hidden pt-14">
      <!-- 背景装饰 -->
      <div class="absolute inset-0 bg-gradient-to-br from-violet-500/5 via-transparent to-blue-500/5" />
      <div class="absolute top-20 left-10 w-72 h-72 bg-violet-500/10 rounded-full blur-3xl" />
      <div class="absolute bottom-20 right-10 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl" />
      
      <div class="relative max-w-6xl mx-auto px-6 py-20 lg:py-32">
        <div class="text-center">
          <!-- Logo -->
          <img src="/logo.png" alt="ImgTag" class="w-20 h-20 rounded-2xl shadow-xl mb-8" />
          
          <!-- Title -->
          <h1 class="text-4xl lg:text-6xl font-bold text-foreground mb-6">
            <span class="bg-gradient-to-r from-violet-500 to-purple-600 bg-clip-text text-transparent">ImgTag</span>
          </h1>
          
          <!-- Subtitle -->
          <p class="text-xl lg:text-2xl text-muted-foreground max-w-2xl mx-auto mb-8">
            智能图片标签管理系统<br class="hidden sm:block" />
            基于 AI 视觉模型的自动标签生成与向量搜索
          </p>
          
          <!-- CTA Buttons -->
          <div class="flex flex-col sm:flex-row items-center justify-center gap-4">
            <RouterLink to="/search">
              <Button size="lg" class="gap-2 bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700">
                <Search class="w-5 h-5" />
                开始探索
                <ArrowRight class="w-4 h-4" />
              </Button>
            </RouterLink>
            <template v-if="userStore.isLoggedIn">
              <RouterLink to="/dashboard">
                <Button variant="outline" size="lg" class="gap-2">
                  <Zap class="w-5 h-5" />
                  进入控制台
                </Button>
              </RouterLink>
            </template>
            <template v-else>
              <RouterLink to="/login">
                <Button variant="outline" size="lg" class="gap-2">
                  登录 / 注册
                </Button>
              </RouterLink>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- Features Section -->
    <div class="max-w-6xl mx-auto px-6 py-20">
      <h2 class="text-2xl lg:text-3xl font-bold text-center text-foreground mb-12">
        核心功能
      </h2>
      
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div 
          v-for="feature in features" 
          :key="feature.title"
          class="group p-6 bg-card border border-border rounded-2xl hover:border-primary/30 hover:shadow-lg transition-all duration-300"
        >
          <div 
            class="w-12 h-12 rounded-xl flex items-center justify-center mb-4 transition-transform group-hover:scale-110"
            :class="`bg-${feature.color}-500/10`"
          >
            <component 
              :is="feature.icon" 
              class="w-6 h-6"
              :class="`text-${feature.color}-500`"
            />
          </div>
          <h3 class="text-lg font-semibold text-foreground mb-2">{{ feature.title }}</h3>
          <p class="text-sm text-muted-foreground">{{ feature.description }}</p>
        </div>
      </div>
    </div>

    <!-- Tech Stack Section -->
    <div class="border-t border-border">
      <div class="max-w-6xl mx-auto px-6 py-16">
        <h2 class="text-xl font-semibold text-center text-foreground mb-8">技术栈</h2>
        <div class="flex flex-wrap items-center justify-center gap-4 text-sm text-muted-foreground">
          <span class="px-4 py-2 bg-muted/50 rounded-full">Vue 3</span>
          <span class="px-4 py-2 bg-muted/50 rounded-full">FastAPI</span>
          <span class="px-4 py-2 bg-muted/50 rounded-full">PostgreSQL</span>
          <span class="px-4 py-2 bg-muted/50 rounded-full">pgvector</span>
          <span class="px-4 py-2 bg-muted/50 rounded-full">Shadcn-Vue</span>
          <span class="px-4 py-2 bg-muted/50 rounded-full">Tailwind CSS</span>
          <span class="px-4 py-2 bg-muted/50 rounded-full">TanStack Query</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 动态颜色类 */
.bg-violet-500\/10 { background-color: rgb(139 92 246 / 0.1); }
.bg-blue-500\/10 { background-color: rgb(59 130 246 / 0.1); }
.bg-emerald-500\/10 { background-color: rgb(16 185 129 / 0.1); }
.bg-amber-500\/10 { background-color: rgb(245 158 11 / 0.1); }
.bg-rose-500\/10 { background-color: rgb(244 63 94 / 0.1); }
.bg-cyan-500\/10 { background-color: rgb(6 182 212 / 0.1); }

.text-violet-500 { color: rgb(139 92 246); }
.text-blue-500 { color: rgb(59 130 246); }
.text-emerald-500 { color: rgb(16 185 129); }
.text-amber-500 { color: rgb(245 158 11); }
.text-rose-500 { color: rgb(244 63 94); }
.text-cyan-500 { color: rgb(6 182 212); }
</style>
