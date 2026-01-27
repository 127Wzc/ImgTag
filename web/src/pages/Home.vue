<script setup lang="ts">
/**
 * Home - 现代化重设计版
 * 采用 Linear/Vercel 风格：深色极简、网格背景、微光动效、Bento Grid 布局
 */
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores'
import { Button } from '@/components/ui/button'
import {
  Sparkles, Search, Shield, Zap,
  ArrowRight, Github, Database
} from 'lucide-vue-next'
import { ref, computed } from 'vue'

const userStore = useUserStore()

// 鼠标位置追踪，用于卡片 Spotlight 效果
const wrapperRef = ref<HTMLElement | null>(null)
const mouse = ref({ x: 0, y: 0 })

function handleMouseMove(event: MouseEvent) {
  if (wrapperRef.value) {
    const rect = wrapperRef.value.getBoundingClientRect()
    mouse.value = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    }
  }
}

const features = [
  {
    icon: Sparkles,
    title: 'AI 视觉理解',
    description: '集成先进的多模态视觉模型，自动为图片生成精准描述与语义标签，让机器真正"看懂"图片。',
    class: 'lg:col-span-2 lg:row-span-2',
    gradient: 'from-violet-500/20 via-purple-500/5 to-transparent'
  },
  {
    icon: Search,
    title: '自然语言搜索',
    description: '打破关键词限制，使用"雨中的红色跑车"等自然语言描述即可毫秒级检索目标图片。',
    class: 'lg:col-span-1 lg:row-span-1',
    gradient: 'from-blue-500/20 via-cyan-500/5 to-transparent'
  },
  {
    icon: Database,
    title: '混合存储架构',
    description: '无缝支持本地文件系统与 S3 兼容对象存储，灵活适应各类部署环境。',
    class: 'lg:col-span-1 lg:row-span-1',
    gradient: 'from-emerald-500/20 via-teal-500/5 to-transparent'
  },
  {
    icon: Zap,
    title: '高性能批处理',
    description: '基于异步消息队列架构，支持数万级图片的快速导入与后台分析，互不阻塞。',
    class: 'lg:col-span-2 lg:row-span-1',
    gradient: 'from-amber-500/20 via-orange-500/5 to-transparent'
  },
  {
    icon: Shield,
    title: '细粒度权限',
    description: '完善的 RBAC 角色控制与 API 密钥管理体系。',
    class: 'lg:col-span-1 lg:row-span-1',
    gradient: 'from-rose-500/20 via-red-500/5 to-transparent'
  }
]

// 动态画廊逻辑
import { useImages } from '@/api/queries'
import type { ImageResponse } from '@/types'

const galleryParams = ref({
  page: 1,
  size: 30, // 获取足够多的图片以供滚动
})

const { data: galleryData } = useImages(galleryParams)

const images = computed(() => (galleryData.value?.data || []) as ImageResponse[])

const showGallery = computed(() => {
  return images.value.length >= 6
})

// 将图片分为两行
const galleryRow1 = computed(() => images.value.slice(0, Math.ceil(images.value.length / 2)))
const galleryRow2 = computed(() => images.value.slice(Math.ceil(images.value.length / 2)))

</script>

<template>
  <div class="min-h-screen bg-background text-foreground overflow-hidden selection:bg-primary/20 font-sans">
    <!-- 背景网格装饰 -->
    <div class="fixed inset-0 z-0 pointer-events-none">
      <div class="absolute inset-0 bg-[linear-gradient(to_right,rgba(128,128,128,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(128,128,128,0.05)_1px,transparent_1px)] bg-[size:24px_24px]"></div>
      <div class="absolute left-0 right-0 top-0 -z-10 m-auto h-[310px] w-[310px] rounded-full bg-primary/20 opacity-20 blur-[100px]"></div>
    </div>

    <!-- 顶部导航 -->
    <header class="sticky top-0 z-50 w-full border-b border-border/40 bg-background/80 backdrop-blur-md">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        <RouterLink to="/" class="flex items-center gap-2.5 group">
          <div class="relative w-8 h-8 rounded-lg overflow-hidden shadow-sm group-hover:shadow-md transition-all ring-1 ring-border/50">
            <img src="/logo.png" alt="ImgTag" class="w-full h-full object-cover" />
            <div class="absolute inset-0 bg-gradient-to-tr from-primary/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
          <span class="font-bold text-lg tracking-tight">ImgTag</span>
        </RouterLink>

        <nav class="flex items-center gap-3">
          <a
            href="https://github.com/127Wzc/ImgTag"
            target="_blank"
            class="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors hidden sm:block"
          >
            GitHub
          </a>
          <div class="h-4 w-px bg-border hidden sm:block" />
          <template v-if="userStore.isLoggedIn">
            <RouterLink to="/dashboard">
              <Button size="sm" variant="default" class="rounded-full px-5 shadow-sm shadow-primary/20">
                控制台
              </Button>
            </RouterLink>
          </template>
          <template v-else>
            <RouterLink to="/login">
              <Button size="sm" class="rounded-full px-5 shadow-sm shadow-primary/20">
                登录
              </Button>
            </RouterLink>
          </template>
        </nav>
      </div>
    </header>

    <main class="relative z-10">
      <!-- Hero Section -->
      <section class="relative pt-20 pb-32 lg:pt-32 lg:pb-40 overflow-hidden">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 text-center">
          <!-- 徽章 -->
          <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-muted/50 border border-border/50 text-xs font-medium text-muted-foreground mb-8 opacity-0 animate-enter">
            <span class="relative flex h-2 w-2">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
            </span>
            v0.1.4 现已发布
          </div>

          <!-- 标题 -->
          <h1 class="text-4xl sm:text-6xl lg:text-7xl font-bold tracking-tight text-foreground mb-6 max-w-4xl mx-auto opacity-0 animate-enter delay-100">
            用 <span class="text-transparent bg-clip-text bg-gradient-to-r from-primary to-violet-500">AI 视觉</span> <br class="hidden sm:block" />
            重塑你的图片资产库
          </h1>

          <!-- 副标题 -->
          <p class="text-lg sm:text-xl text-muted-foreground max-w-2xl mx-auto mb-10 leading-relaxed opacity-0 animate-enter delay-200">
            基于先进的多模态大模型，为海量图片自动生成语义标签。
            <br />
            支持自然语言搜索，让每一张图片都触手可及。
          </p>

          <!-- 按钮组 -->
          <div class="flex flex-col sm:flex-row items-center justify-center gap-4 opacity-0 animate-enter delay-300">
            <RouterLink to="/search">
              <Button size="lg" class="h-12 px-8 rounded-full text-base gap-2 shadow-lg shadow-primary/20 hover:shadow-primary/30 transition-all hover:scale-105 active:scale-95">
                <Search class="w-4 h-4" />
                立即体验
                <ArrowRight class="w-4 h-4" />
              </Button>
            </RouterLink>
            <a href="https://github.com/127Wzc/ImgTag" target="_blank">
              <Button variant="outline" size="lg" class="h-12 px-8 rounded-full text-base gap-2 bg-background/50 backdrop-blur-sm hover:bg-muted/50 transition-all">
                <Github class="w-4 h-4" />
                查看源码
              </Button>
            </a>
          </div>

          <!-- 动态画廊 (已登录且有图片) -->
          <div v-if="showGallery" class="mt-20 relative full-width-gallery opacity-0 animate-enter delay-500 duration-1000">
             <!-- 遮罩 -->
            <div class="absolute inset-y-0 left-0 w-32 bg-gradient-to-r from-background to-transparent z-10 pointer-events-none"></div>
            <div class="absolute inset-y-0 right-0 w-32 bg-gradient-to-l from-background to-transparent z-10 pointer-events-none"></div>

            <div class="flex flex-col gap-4 -rotate-1 scale-105 hover:scale-100 transition-transform duration-700">
              <!-- 第一行：向左滚动 -->
              <div class="marquee-container flex overflow-hidden w-full">
                <div class="marquee-content animate-marquee flex gap-4 min-w-max">
                  <div 
                    v-for="img in galleryRow1" 
                    :key="img.id" 
                    class="relative group w-64 h-48 flex-shrink-0 rounded-xl overflow-hidden border border-border/50 bg-muted/30"
                  >
                    <img :src="img.image_url" class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110" loading="lazy" />
                    <!-- Hover Info -->
                    <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-3">
                      <p class="text-white text-xs font-medium truncate">{{ img.description || 'Image #' + img.id }}</p>
                      <div class="flex gap-1 mt-1 flex-wrap">
                        <span v-for="tag in img.tags.slice(0, 2)" :key="tag.id" class="text-[10px] bg-white/20 text-white px-1.5 py-0.5 rounded backdrop-blur-sm">
                          {{ tag.name }}
                        </span>
                      </div>
                    </div>
                  </div>
                  <!-- Duplicate for smooth loop -->
                  <div 
                    v-for="img in galleryRow1" 
                    :key="`dup-${img.id}`" 
                    class="relative group w-64 h-48 flex-shrink-0 rounded-xl overflow-hidden border border-border/50 bg-muted/30"
                  >
                    <img :src="img.image_url" class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110" loading="lazy" />
                  </div>
                </div>
              </div>

              <!-- 第二行：向右滚动 -->
              <div class="marquee-container flex overflow-hidden w-full">
                <div class="marquee-content animate-marquee-reverse flex gap-4 min-w-max">
                  <div 
                    v-for="img in galleryRow2" 
                    :key="img.id" 
                    class="relative group w-64 h-48 flex-shrink-0 rounded-xl overflow-hidden border border-border/50 bg-muted/30"
                  >
                    <img :src="img.image_url" class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110" loading="lazy" />
                    <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-3">
                       <p class="text-white text-xs font-medium truncate">{{ img.description || 'Image #' + img.id }}</p>
                    </div>
                  </div>
                  <!-- Duplicate -->
                   <div 
                    v-for="img in galleryRow2" 
                    :key="`dup-${img.id}`" 
                    class="relative group w-64 h-48 flex-shrink-0 rounded-xl overflow-hidden border border-border/50 bg-muted/30"
                  >
                    <img :src="img.image_url" class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110" loading="lazy" />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 视觉展示区 - 模拟应用界面 (Fallback) -->
          <div v-else class="mt-20 relative max-w-5xl mx-auto opacity-0 animate-enter delay-500 duration-1000">
            <div class="absolute -inset-1 bg-gradient-to-r from-primary/30 to-violet-500/30 rounded-xl blur opacity-30"></div>
            <div class="relative rounded-xl border border-border/50 bg-card/80 backdrop-blur shadow-2xl overflow-hidden aspect-[16/9] sm:aspect-[2/1] group">
              <!-- 模拟 Header -->
              <div class="h-10 border-b border-border/50 bg-muted/30 flex items-center px-4 gap-2">
                <div class="flex gap-1.5">
                  <div class="w-3 h-3 rounded-full bg-red-500/20 border border-red-500/30"></div>
                  <div class="w-3 h-3 rounded-full bg-yellow-500/20 border border-yellow-500/30"></div>
                  <div class="w-3 h-3 rounded-full bg-green-500/20 border border-green-500/30"></div>
                </div>
                <div class="ml-4 h-6 w-64 bg-muted/50 rounded-md flex items-center px-2">
                  <span class="text-[10px] text-muted-foreground">imgtag.app / search</span>
                </div>
              </div>
              <!-- 模拟内容 -->
              <div class="p-6 grid grid-cols-3 sm:grid-cols-4 gap-4 opacity-50 grayscale group-hover:grayscale-0 group-hover:opacity-100 transition-all duration-700">
                <!-- 模拟图片卡片 -->
                <div v-for="i in 8" :key="i" class="aspect-[4/3] rounded-lg bg-muted/50 border border-border/50 relative overflow-hidden">
                  <div class="absolute inset-0 bg-gradient-to-br from-muted/50 to-muted/20"></div>
                  <div class="absolute bottom-2 left-2 right-2 h-2 bg-primary/10 rounded-full w-2/3"></div>
                </div>
              </div>

              <!-- 浮动搜索框模拟 -->
              <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div class="bg-background/90 backdrop-blur-xl border border-border p-4 rounded-2xl shadow-2xl flex items-center gap-3 w-[280px] sm:w-[400px] transform translate-y-4 group-hover:translate-y-0 transition-transform duration-500">
                  <Search class="w-5 h-5 text-primary" />
                  <div class="h-4 bg-muted w-32 rounded-full"></div>
                  <div class="ml-auto flex gap-1">
                     <span class="text-[10px] bg-muted px-1.5 py-0.5 rounded text-muted-foreground">⌘ K</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Bento Grid Features -->
      <section
        ref="wrapperRef"
        @mousemove="handleMouseMove"
        class="py-24 sm:py-32 relative"
      >
        <div class="max-w-7xl mx-auto px-4 sm:px-6">
          <div class="text-center mb-16">
            <h2 class="text-3xl font-bold tracking-tight mb-4">全流程智能化管理</h2>
            <p class="text-muted-foreground max-w-2xl mx-auto">
              从上传到检索，AI 驱动每一个环节，让图片管理变得前所未有的简单。
            </p>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 lg:gap-6 auto-rows-fr">
            <div
              v-for="feature in features"
              :key="feature.title"
              :class="[
                'group relative rounded-3xl border border-border/50 bg-card/50 p-6 sm:p-8 overflow-hidden transition-all hover:border-primary/20 hover:shadow-lg',
                feature.class
              ]"
            >
              <!-- Spotlight Gradient -->
              <div
                class="pointer-events-none absolute -inset-px opacity-0 transition-opacity duration-300 group-hover:opacity-100"
                :style="{
                  background: `radial-gradient(600px circle at ${mouse.x}px ${mouse.y}px, rgba(var(--primary-rgb), 0.06), transparent 40%)`
                }"
              />

              <!-- 背景装饰 -->
              <div class="absolute top-0 right-0 -mt-4 -mr-4 w-24 h-24 rounded-full blur-3xl opacity-20 transition-opacity group-hover:opacity-40"
                :class="`bg-gradient-to-br ${feature.gradient}`"
              ></div>

              <div class="relative z-10 h-full flex flex-col">
                <div class="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-muted/50 border border-border/50 group-hover:scale-110 transition-transform duration-300 group-hover:bg-primary/10 group-hover:text-primary">
                  <component :is="feature.icon" class="h-6 w-6" />
                </div>

                <h3 class="text-xl font-semibold mb-2 group-hover:text-primary transition-colors">
                  {{ feature.title }}
                </h3>

                <p class="text-muted-foreground leading-relaxed text-sm sm:text-base flex-grow">
                  {{ feature.description }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Footer -->
      <footer class="border-t border-border/40 py-12 bg-muted/20">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col md:flex-row items-center justify-between gap-6">
          <div class="flex items-center gap-2">
            <img src="/logo.png" alt="ImgTag" class="w-6 h-6 grayscale opacity-50" />
            <span class="text-sm text-muted-foreground">© 2025 ImgTag. Open Source.</span>
          </div>

          <div class="flex items-center gap-6 text-sm text-muted-foreground">
            <a href="https://github.com/127Wzc/ImgTag/blob/main/README.md" class="hover:text-foreground transition-colors">文档</a>
            <a href="https://github.com/127Wzc/ImgTag/blob/main/docs/external-api.md" class="hover:text-foreground transition-colors">外部API</a>
            <a href="https://github.com/127Wzc/ImgTag" class="hover:text-foreground transition-colors">GitHub</a>
          </div>
        </div>
      </footer>
    </main>
  </div>
</template>

<style scoped>
/* 自定义进入动画 */
@keyframes enter {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-enter {
  animation: enter 0.6s ease-out forwards;
}

.delay-100 { animation-delay: 100ms; }
.delay-200 { animation-delay: 200ms; }
.delay-300 { animation-delay: 300ms; }
.delay-500 { animation-delay: 500ms; }

/* Marquee Animations */
@keyframes marquee {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}

@keyframes marquee-reverse {
  0% { transform: translateX(-50%); }
  100% { transform: translateX(0); }
}

@keyframes marquee-reverse {
  0% { transform: translateX(-50%); }
  100% { transform: translateX(0); }
}

.marquee-container {
  mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
}

.animate-marquee {
  animation: marquee 40s linear infinite;
}

.animate-marquee-reverse {
  animation: marquee-reverse 45s linear infinite;
}

.marquee-content:hover {
  animation-play-state: paused;
}

/* 确保背景网格在暗黑模式下更明显 */
.dark .bg-grid-white\/5 {
  mask-image: linear-gradient(to bottom, transparent, 10%, white, 90%, transparent);
}

/* 定义 Spotlight 需要的 RGB 变量，这里做个 fallback */
:root {
  --primary-rgb: 124, 58, 237; /* Violet-600 approx */
}
</style>
