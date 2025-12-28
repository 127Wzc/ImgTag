<script setup lang="ts">
import { ref, computed } from 'vue'
import { useTasks, useClearCompletedTasks, useRetryTask } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { 
  Loader2, 
  CheckCircle, 
  XCircle, 
  Clock, 
  RefreshCw, 
  Trash2,
  Image,
  PlayCircle
} from 'lucide-vue-next'

// 任务状态筛选
const statusFilter = ref<string>('')
const taskParams = ref({
  status: '',
  limit: 50,
  offset: 0,
})

// 获取任务列表
const { data: taskData, isLoading, refetch } = useTasks(taskParams)
const tasks = computed(() => taskData.value?.tasks || [])
const total = computed(() => taskData.value?.total || 0)

// Mutations
const clearCompletedMutation = useClearCompletedTasks()
const retryTaskMutation = useRetryTask()

function setStatusFilter(status: string) {
  statusFilter.value = status
  taskParams.value = { ...taskParams.value, status, offset: 0 }
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'completed': return CheckCircle
    case 'failed': return XCircle
    case 'processing': return Loader2
    default: return Clock
  }
}

function getStatusClass(status: string) {
  switch (status) {
    case 'completed': return 'text-green-500'
    case 'failed': return 'text-destructive'
    case 'processing': return 'text-blue-500 animate-spin'
    default: return 'text-muted-foreground'
  }
}

function getStatusLabel(status: string) {
  switch (status) {
    case 'pending': return '等待中'
    case 'processing': return '处理中'
    case 'completed': return '已完成'
    case 'failed': return '失败'
    default: return status
  }
}

function getTaskTypeLabel(type: string) {
  switch (type) {
    case 'image_analyze': return '图片分析'
    case 'batch_analyze': return '批量分析'
    case 'vector_embed': return '向量嵌入'
    default: return type
  }
}

function formatTime(dateString: string) {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', { 
    month: '2-digit', 
    day: '2-digit', 
    hour: '2-digit', 
    minute: '2-digit' 
  })
}

async function handleRetry(taskId: string) {
  await retryTaskMutation.mutateAsync(taskId)
}

async function handleClearCompleted() {
  await clearCompletedMutation.mutateAsync()
}

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '等待中' },
  { value: 'processing', label: '处理中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
]

const hasCompleted = computed(() => 
  tasks.value.some(t => t.status === 'completed')
)
</script>

<template>
  <div class="p-6 lg:p-8">
    <div class="max-w-5xl mx-auto">
      <!-- 标题 -->
      <div class="flex items-center justify-between mb-8">
        <div>
          <h1 class="text-2xl font-bold text-foreground">任务队列</h1>
          <p class="text-muted-foreground mt-1">查看后台任务处理状态</p>
        </div>
        <div class="flex gap-2">
          <Button 
            variant="outline" 
            size="sm" 
            @click="() => refetch()"
            :disabled="isLoading"
          >
            <RefreshCw class="w-4 h-4 mr-2" :class="isLoading && 'animate-spin'" />
            刷新
          </Button>
          <Button 
            v-if="hasCompleted"
            variant="outline" 
            size="sm"
            @click="handleClearCompleted"
            :disabled="clearCompletedMutation.isPending.value"
          >
            <Trash2 class="w-4 h-4 mr-2" />
            清理已完成
          </Button>
        </div>
      </div>

      <!-- 状态筛选 -->
      <div class="flex gap-2 mb-6">
        <button
          v-for="option in statusOptions"
          :key="option.value"
          @click="setStatusFilter(option.value)"
          class="px-4 py-2 text-sm rounded-lg border transition-colors"
          :class="[
            statusFilter === option.value
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-background text-muted-foreground border-border hover:border-primary/50'
          ]"
        >
          {{ option.label }}
        </button>
      </div>

      <!-- 任务统计 -->
      <div class="text-sm text-muted-foreground mb-4">
        共 {{ total }} 个任务
      </div>

      <!-- 加载状态 -->
      <div v-if="isLoading && tasks.length === 0" class="flex items-center justify-center py-20">
        <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
      </div>

      <!-- 空状态 -->
      <div v-else-if="tasks.length === 0" class="text-center py-20">
        <div class="w-16 h-16 bg-muted rounded-full flex items-center justify-center mx-auto mb-4">
          <Clock class="w-8 h-8 text-muted-foreground" />
        </div>
        <p class="text-muted-foreground">暂无任务</p>
      </div>

      <!-- 任务列表 -->
      <div v-else class="space-y-3">
        <div 
          v-for="task in tasks" 
          :key="task.id"
          class="flex items-center gap-4 p-4 bg-card border border-border rounded-xl"
        >
          <!-- 任务类型图标 -->
          <div class="w-10 h-10 bg-muted rounded-lg flex items-center justify-center shrink-0">
            <Image class="w-5 h-5 text-muted-foreground" />
          </div>

          <!-- 任务信息 -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="font-medium text-foreground">
                {{ getTaskTypeLabel(task.type) }}
              </span>
              <span class="text-xs text-muted-foreground">
                #{{ task.id.slice(0, 8) }}
              </span>
            </div>
            <div class="text-sm text-muted-foreground mt-1">
              {{ formatTime(task.created_at) }}
              <span v-if="task.completed_at"> → {{ formatTime(task.completed_at) }}</span>
            </div>
            <!-- 错误信息 -->
            <p v-if="task.error" class="text-sm text-destructive mt-1 truncate">
              {{ task.error }}
            </p>
          </div>

          <!-- 状态 -->
          <div class="flex items-center gap-2 shrink-0">
            <component 
              :is="getStatusIcon(task.status)" 
              class="w-5 h-5"
              :class="getStatusClass(task.status)"
            />
            <span 
              class="text-sm font-medium"
              :class="getStatusClass(task.status)"
            >
              {{ getStatusLabel(task.status) }}
            </span>
          </div>

          <!-- 操作按钮 -->
          <div v-if="task.status === 'failed'" class="shrink-0">
            <Button 
              variant="ghost" 
              size="sm"
              @click="handleRetry(task.id)"
              :disabled="retryTaskMutation.isPending.value"
            >
              <PlayCircle class="w-4 h-4 mr-1" />
              重试
            </Button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
