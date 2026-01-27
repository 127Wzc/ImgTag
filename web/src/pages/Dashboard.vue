<script setup lang="ts">
/**
 * Dashboard - 仪表盘页面 (Linear Style)
 * 极简数据可视化，Bento Grid 布局
 */
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useDashboardStats, useTagsByLevel } from '@/api/queries'
import { useUserStore } from '@/stores'
import { Loader2, Search, ArrowRight, Activity, Database, Clock, Server, Layers, Hash, Image as ImageIcon } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

const userStore = useUserStore()

// API 查询
const { data: stats, isLoading: statsLoading } = useDashboardStats()

// 标签查询
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
    .slice(0, 6)
)
const topResolutions = computed(() =>
  (resolutionsData.value || [])
    .filter(t => (t.usage_count ?? 0) > 0)
    .sort((a, b) => (b.usage_count ?? 0) - (a.usage_count ?? 0))
    .slice(0, 6)
)
const topTags = computed(() =>
  (tagsData.value || [])
    .filter(t => (t.usage_count ?? 0) > 0)
    .sort((a, b) => (b.usage_count ?? 0) - (a.usage_count ?? 0))
    .slice(0, 12)
)

const isLoading = computed(() => statsLoading.value && !stats.value)

// 计算分析进度百分比
const analysisProgress = computed(() => {
  if (!stats.value?.images?.total) return 0
  return Math.round((stats.value.images.analyzed / stats.value.images.total) * 100)
})

// 格式化数字
function formatNumber(num: number) {
  return new Intl.NumberFormat('en-US').format(num)
}
</script>

<template>
  <div class="p-6 lg:p-10 max-w-[1600px] mx-auto space-y-8">
    <!-- Header -->
    <div class="flex items-center justify-between pb-6 border-b border-border/40">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">概览</h1>
        <p class="text-sm text-muted-foreground mt-1 font-mono text-xs opacity-70">
          系统状态: {{ stats?.queue?.running ? '在线' : '空闲' }}
        </p>
      </div>
      <div class="flex gap-3">
        <RouterLink to="/search">
          <Button variant="outline" size="sm" class="gap-2 h-9">
            <Search class="w-3.5 h-3.5" />
            搜索
          </Button>
        </RouterLink>
        <RouterLink v-if="userStore.isLoggedIn" to="/my-files">
          <Button size="sm" class="gap-2 h-9 bg-primary text-primary-foreground shadow-sm">
            我的文件
            <ArrowRight class="w-3.5 h-3.5" />
          </Button>
        </RouterLink>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="isLoading" class="flex items-center justify-center py-40">
      <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
    </div>

    <template v-else>
      <!-- Stats Grid -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <!-- Total Images -->
        <div class="p-5 rounded-xl border border-border/50 bg-card/50 hover:bg-card hover:border-border transition-all group">
          <div class="flex items-center justify-between mb-4">
            <span class="text-sm font-medium text-muted-foreground">图片总数</span>
            <ImageIcon class="w-4 h-4 text-muted-foreground group-hover:text-foreground transition-colors" />
          </div>
          <div class="text-3xl font-mono font-medium tracking-tighter">
            {{ formatNumber(stats?.images?.total ?? 0) }}
          </div>
        </div>

        <!-- Pending Analysis -->
        <div class="p-5 rounded-xl border border-border/50 bg-card/50 hover:bg-card hover:border-border transition-all group">
          <div class="flex items-center justify-between mb-4">
            <span class="text-sm font-medium text-muted-foreground">待处理</span>
            <Clock class="w-4 h-4 text-muted-foreground group-hover:text-amber-500 transition-colors" />
          </div>
          <div class="text-3xl font-mono font-medium tracking-tighter flex items-end gap-2">
            {{ formatNumber(stats?.images?.pending ?? 0) }}
            <span v-if="(stats?.images?.pending ?? 0) > 0" class="text-xs text-amber-500 mb-1 font-sans font-medium">处理中</span>
          </div>
        </div>

        <!-- Today Uploads -->
        <div class="p-5 rounded-xl border border-border/50 bg-card/50 hover:bg-card hover:border-border transition-all group">
          <div class="flex items-center justify-between mb-4">
            <span class="text-sm font-medium text-muted-foreground">今日上传</span>
            <Database class="w-4 h-4 text-muted-foreground group-hover:text-blue-500 transition-colors" />
          </div>
          <div class="text-3xl font-mono font-medium tracking-tighter text-blue-500">
            +{{ formatNumber(stats?.today?.uploaded ?? 0) }}
          </div>
        </div>

        <!-- Queue Status -->
        <div class="p-5 rounded-xl border border-border/50 bg-card/50 hover:bg-card hover:border-border transition-all group relative overflow-hidden">
          <div class="flex items-center justify-between mb-4 relative z-10">
            <span class="text-sm font-medium text-muted-foreground">队列状态</span>
            <div class="flex items-center gap-1.5">
              <span class="relative flex h-2 w-2">
                <span v-if="stats?.queue?.running" class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span class="relative inline-flex rounded-full h-2 w-2" :class="stats?.queue?.running ? 'bg-emerald-500' : 'bg-zinc-500'"></span>
              </span>
              <span class="text-xs font-mono" :class="stats?.queue?.running ? 'text-emerald-500' : 'text-muted-foreground'">
                {{ stats?.queue?.running ? '运行中' : '空闲' }}
              </span>
            </div>
          </div>
          <div class="relative z-10">
             <div class="text-3xl font-mono font-medium tracking-tighter">
                {{ stats?.queue?.processing ?? 0 }}
             </div>
             <div class="text-xs text-muted-foreground mt-1">活跃任务</div>
          </div>
          <!-- Background Decoration -->
          <Activity v-if="stats?.queue?.running" class="absolute -right-2 -bottom-2 w-24 h-24 text-emerald-500/5 stroke-[1]" />
        </div>
      </div>

      <!-- Analysis Progress (Full Width) -->
      <div class="p-6 rounded-xl border border-border/50 bg-card/30">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm font-medium">分析进度</h3>
          <span class="text-sm font-mono text-muted-foreground">{{ analysisProgress }}%</span>
        </div>
        <div class="h-1.5 w-full bg-secondary/50 rounded-full overflow-hidden">
          <div
            class="h-full bg-foreground rounded-full transition-all duration-1000 ease-out"
            :style="{ width: `${analysisProgress}%` }"
          />
        </div>
        <div class="mt-2 flex justify-between text-xs text-muted-foreground font-mono">
          <span>{{ formatNumber(stats?.images?.analyzed ?? 0) }} 已分析</span>
          <span>{{ formatNumber(stats?.images?.total ?? 0) }} 总计</span>
        </div>
      </div>

      <!-- Bottom Grid: Tags & Distributions -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Categories -->
        <div class="lg:col-span-1 p-6 rounded-xl border border-border/50 bg-card/30 flex flex-col">
          <div class="flex items-center gap-2 mb-6">
            <Layers class="w-4 h-4 text-muted-foreground" />
            <h3 class="text-sm font-medium">热门分类</h3>
          </div>
          <div class="space-y-3 flex-1">
            <div
              v-for="(cat, i) in topCategories"
              :key="cat.id"
              class="group flex items-center justify-between text-sm"
            >
              <div class="flex items-center gap-3">
                <span class="font-mono text-xs text-muted-foreground w-4">{{ i + 1 }}</span>
                <span class="text-foreground/80 group-hover:text-foreground transition-colors">{{ cat.name }}</span>
              </div>
              <div class="flex items-center gap-2">
                <div class="w-16 h-1 bg-secondary rounded-full overflow-hidden">
                   <div class="h-full bg-violet-500/50" :style="{ width: `${(cat.usage_count! / (topCategories[0]?.usage_count || 1)) * 100}%` }" />
                </div>
                <span class="font-mono text-xs text-muted-foreground w-8 text-right">{{ cat.usage_count }}</span>
              </div>
            </div>
            <div v-if="!topCategories.length" class="text-sm text-muted-foreground py-4">暂无数据</div>
          </div>
        </div>

        <!-- Resolutions -->
        <div class="lg:col-span-1 p-6 rounded-xl border border-border/50 bg-card/30 flex flex-col">
          <div class="flex items-center gap-2 mb-6">
            <Server class="w-4 h-4 text-muted-foreground" />
            <h3 class="text-sm font-medium">分辨率分布</h3>
          </div>
          <div class="space-y-3 flex-1">
            <div
              v-for="(res, i) in topResolutions"
              :key="res.id"
              class="group flex items-center justify-between text-sm"
            >
              <div class="flex items-center gap-3">
                <span class="font-mono text-xs text-muted-foreground w-4">{{ i + 1 }}</span>
                <span class="text-foreground/80 group-hover:text-foreground transition-colors">{{ res.name }}</span>
              </div>
              <span class="font-mono text-xs text-muted-foreground">{{ res.usage_count }}</span>
            </div>
            <div v-if="!topResolutions.length" class="text-sm text-muted-foreground py-4">暂无数据</div>
          </div>
        </div>

        <!-- Trending Tags -->
        <div class="lg:col-span-1 p-6 rounded-xl border border-border/50 bg-card/30 flex flex-col">
          <div class="flex items-center gap-2 mb-6">
            <Hash class="w-4 h-4 text-muted-foreground" />
            <h3 class="text-sm font-medium">热门标签</h3>
          </div>
          <div class="flex flex-wrap gap-2 content-start">
            <span
              v-for="tag in topTags"
              :key="tag.id"
              class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-border/50 bg-secondary/30 text-xs text-foreground/80 hover:bg-secondary/50 hover:text-foreground hover:border-border transition-all cursor-default"
            >
              {{ tag.name }}
              <span class="text-[10px] text-muted-foreground border-l border-border/50 pl-1.5 ml-0.5">{{ tag.usage_count }}</span>
            </span>
            <div v-if="!topTags.length" class="text-sm text-muted-foreground py-4 w-full">暂无数据</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
