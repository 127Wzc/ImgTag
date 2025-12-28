<script setup lang="ts">
/**
 * Dashboard - 仪表盘页面
 * 展示图片统计、今日数据、队列状态、标签统计
 */
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useDashboardStats, useTagsByLevel } from '@/api/queries'
import { useUserStore } from '@/stores'
import { Loader2, Image, ImagePlus, Sparkles, Clock, Activity, TrendingUp, FolderOpen, Tags, Folder, Box, Search } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

const userStore = useUserStore()

// API 查询（进入页面时请求一次）
const { data: stats, isLoading: statsLoading } = useDashboardStats()

// 标签查询（各级别）
const level0 = ref(0)
const level1 = ref(1)
const level2 = ref(2)
const { data: categoriesData } = useTagsByLevel(level0, 50)
const { data: resolutionsData } = useTagsByLevel(level1, 50)
const { data: tagsData } = useTagsByLevel(level2, 50)

// 处理标签数据：按 usage_count 倒序
const topCategories = computed(() => 
  (categoriesData.value || [])
    .filter(t => (t.usage_count ?? 0) > 0)
    .sort((a, b) => (b.usage_count ?? 0) - (a.usage_count ?? 0))
    .slice(0, 5)
)
const topResolutions = computed(() => 
  (resolutionsData.value || [])
    .filter(t => (t.usage_count ?? 0) > 0)
    .sort((a, b) => (b.usage_count ?? 0) - (a.usage_count ?? 0))
    .slice(0, 5)
)
const topTags = computed(() => 
  (tagsData.value || [])
    .filter(t => (t.usage_count ?? 0) > 0)
    .sort((a, b) => (b.usage_count ?? 0) - (a.usage_count ?? 0))
    .slice(0, 10)
)

const isLoading = computed(() => statsLoading.value && !stats.value)

// 计算分析进度百分比
const analysisProgress = computed(() => {
  if (!stats.value?.images?.total) return 0
  return Math.round((stats.value.images.analyzed / stats.value.images.total) * 100)
})

// 格式化数字
function formatNumber(num: number) {
  if (num >= 10000) return (num / 10000).toFixed(1) + '万'
  return num.toString()
}
</script>

<template>
  <div class="p-6 lg:p-8 space-y-6">
    <!-- 页面标题 -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-foreground">仪表盘</h1>
        <p class="text-muted-foreground text-sm mt-1">数据概览与统计</p>
      </div>
      <!-- 根据登录状态显示不同按钮 -->
      <div class="flex items-center gap-2">
        <RouterLink to="/search">
          <Button variant="outline" class="gap-2">
            <Search class="w-4 h-4" />
            图片探索
          </Button>
        </RouterLink>
        <RouterLink v-if="userStore.isLoggedIn" to="/my-files">
          <Button class="gap-2">
            <FolderOpen class="w-4 h-4" />
            我的图库
          </Button>
        </RouterLink>
        <RouterLink v-else to="/login">
          <Button class="gap-2">
            登录
          </Button>
        </RouterLink>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="isLoading" class="flex items-center justify-center py-20">
      <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
    </div>

    <template v-else>
      <!-- 第一行：图片统计卡片 -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <!-- 图片总数 -->
        <div class="bg-gradient-to-br from-violet-500/10 to-purple-500/10 border border-violet-500/20 rounded-2xl p-5">
          <div class="flex items-center justify-between">
            <div class="w-10 h-10 bg-violet-500/20 rounded-xl flex items-center justify-center">
              <Image class="w-5 h-5 text-violet-500" />
            </div>
            <span class="text-xs font-medium text-violet-500 bg-violet-500/10 px-2 py-1 rounded-full">总计</span>
          </div>
          <div class="mt-4">
            <div class="text-3xl font-bold text-foreground">{{ formatNumber(stats?.images?.total ?? 0) }}</div>
            <div class="text-sm text-muted-foreground mt-1">图片总数</div>
          </div>
        </div>

        <!-- 待分析 -->
        <div class="bg-gradient-to-br from-amber-500/10 to-orange-500/10 border border-amber-500/20 rounded-2xl p-5">
          <div class="flex items-center justify-between">
            <div class="w-10 h-10 bg-amber-500/20 rounded-xl flex items-center justify-center">
              <Clock class="w-5 h-5 text-amber-500" />
            </div>
            <span class="text-xs font-medium text-amber-500 bg-amber-500/10 px-2 py-1 rounded-full">待处理</span>
          </div>
          <div class="mt-4">
            <div class="text-3xl font-bold text-foreground">{{ formatNumber(stats?.images?.pending ?? 0) }}</div>
            <div class="text-sm text-muted-foreground mt-1">待分析</div>
          </div>
        </div>

        <!-- 今日上传 -->
        <div class="bg-gradient-to-br from-blue-500/10 to-cyan-500/10 border border-blue-500/20 rounded-2xl p-5">
          <div class="flex items-center justify-between">
            <div class="w-10 h-10 bg-blue-500/20 rounded-xl flex items-center justify-center">
              <ImagePlus class="w-5 h-5 text-blue-500" />
            </div>
            <span class="text-xs font-medium text-blue-500 bg-blue-500/10 px-2 py-1 rounded-full">今日</span>
          </div>
          <div class="mt-4">
            <div class="text-3xl font-bold text-foreground">{{ stats?.today?.uploaded ?? 0 }}</div>
            <div class="text-sm text-muted-foreground mt-1">今日上传</div>
          </div>
        </div>

        <!-- 今日分析 -->
        <div class="bg-gradient-to-br from-emerald-500/10 to-green-500/10 border border-emerald-500/20 rounded-2xl p-5">
          <div class="flex items-center justify-between">
            <div class="w-10 h-10 bg-emerald-500/20 rounded-xl flex items-center justify-center">
              <Sparkles class="w-5 h-5 text-emerald-500" />
            </div>
            <span class="text-xs font-medium text-emerald-500 bg-emerald-500/10 px-2 py-1 rounded-full">今日</span>
          </div>
          <div class="mt-4">
            <div class="text-3xl font-bold text-foreground">{{ stats?.today?.analyzed ?? 0 }}</div>
            <div class="text-sm text-muted-foreground mt-1">今日分析</div>
          </div>
        </div>
      </div>

      <!-- 第二行：分析进度 & 队列状态 -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- 分析进度 -->
        <div class="bg-card border border-border rounded-2xl p-6">
          <div class="flex items-center justify-between mb-4">
            <h3 class="font-semibold text-foreground flex items-center gap-2">
              <TrendingUp class="w-4 h-4 text-primary" />
              分析进度
            </h3>
            <span class="text-2xl font-bold text-primary">{{ analysisProgress }}%</span>
          </div>
          <div class="h-3 bg-muted rounded-full overflow-hidden">
            <div 
              class="h-full bg-gradient-to-r from-primary to-purple-500 rounded-full transition-all duration-500"
              :style="{ width: `${analysisProgress}%` }"
            />
          </div>
          <div class="flex justify-between text-sm text-muted-foreground mt-3">
            <span>已分析 {{ formatNumber(stats?.images?.analyzed ?? 0) }}</span>
            <span>共 {{ formatNumber(stats?.images?.total ?? 0) }} 张</span>
          </div>
        </div>

        <!-- 队列状态 -->
        <div class="bg-card border border-border rounded-2xl p-6">
          <div class="flex items-center justify-between mb-4">
            <h3 class="font-semibold text-foreground flex items-center gap-2">
              <Activity class="w-4 h-4 text-primary" />
              分析队列
            </h3>
            <span 
              class="text-xs font-medium px-2.5 py-1 rounded-full"
              :class="stats?.queue?.running 
                ? 'text-emerald-500 bg-emerald-500/10' 
                : 'text-muted-foreground bg-muted'"
            >
              {{ stats?.queue?.running ? '运行中' : '已停止' }}
            </span>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div class="bg-muted/50 rounded-xl p-4 text-center">
              <div class="text-2xl font-bold text-foreground">{{ stats?.queue?.pending ?? 0 }}</div>
              <div class="text-xs text-muted-foreground mt-1">等待中</div>
            </div>
            <div class="bg-muted/50 rounded-xl p-4 text-center">
              <div class="text-2xl font-bold text-amber-500">{{ stats?.queue?.processing ?? 0 }}</div>
              <div class="text-xs text-muted-foreground mt-1">处理中</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 第三行：标签统计（紧凑横向布局） -->
      <div class="bg-card border border-border rounded-2xl p-6">
        <h3 class="font-semibold text-foreground flex items-center gap-2 mb-4">
          <Tags class="w-4 h-4 text-primary" />
          标签统计
        </h3>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <!-- 主分类 -->
          <div class="space-y-2">
            <div class="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Folder class="w-3.5 h-3.5 text-violet-500" />
              <span>主分类 Top 5</span>
            </div>
            <div v-if="topCategories.length" class="flex flex-wrap gap-2">
              <span 
                v-for="tag in topCategories" 
                :key="tag.id"
                class="inline-flex items-center gap-1 px-2.5 py-1 bg-violet-500/10 text-violet-500 rounded-full text-xs"
              >
                {{ tag.name }}
                <span class="font-semibold">{{ tag.usage_count }}</span>
              </span>
            </div>
            <div v-else class="text-xs text-muted-foreground">暂无数据</div>
          </div>

          <!-- 分辨率 -->
          <div class="space-y-2">
            <div class="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Box class="w-3.5 h-3.5 text-blue-500" />
              <span>分辨率 Top 5</span>
            </div>
            <div v-if="topResolutions.length" class="flex flex-wrap gap-2">
              <span 
                v-for="tag in topResolutions" 
                :key="tag.id"
                class="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-500/10 text-blue-500 rounded-full text-xs"
              >
                {{ tag.name }}
                <span class="font-semibold">{{ tag.usage_count }}</span>
              </span>
            </div>
            <div v-else class="text-xs text-muted-foreground">暂无数据</div>
          </div>

          <!-- 热门标签 -->
          <div class="space-y-2">
            <div class="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Tags class="w-3.5 h-3.5 text-emerald-500" />
              <span>热门标签 Top 10</span>
            </div>
            <div v-if="topTags.length" class="flex flex-wrap gap-2">
              <span 
                v-for="tag in topTags" 
                :key="tag.id"
                class="inline-flex items-center gap-1 px-2.5 py-1 bg-emerald-500/10 text-emerald-500 rounded-full text-xs"
              >
                {{ tag.name }}
                <span class="font-semibold">{{ tag.usage_count }}</span>
              </span>
            </div>
            <div v-else class="text-xs text-muted-foreground">暂无数据</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
