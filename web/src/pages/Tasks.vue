<script setup lang="ts">
import { ref, computed } from 'vue'
import { useTasks, useRetryTask } from '@/api/queries'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { toast } from 'vue-sonner'
import { 
  Loader2, 
  CheckCircle, 
  XCircle, 
  Clock, 
  RefreshCw, 
  Trash2,
  Image,
  PlayCircle,
  Eye
} from 'lucide-vue-next'

interface TaskItem {
  id: string
  type: string
  status: string
  payload?: Record<string, any>
  result?: Record<string, any>
  error?: string
  created_at: string
  completed_at?: string
}

// 任务状态筛选
const statusFilter = ref<string>('')
const taskParams = ref({
  status: '',
  limit: 50,
  offset: 0,
})

// 获取任务列表
const queryClient = useQueryClient()
const { data: taskData, isLoading, refetch } = useTasks(taskParams)
const tasks = computed(() => (taskData.value?.tasks || []) as TaskItem[])
const total = computed(() => taskData.value?.total || 0)

// Mutations
const retryTaskMutation = useRetryTask()

// 批量删除 mutation
const deleteMutation = useMutation({
  mutationFn: (ids: string[]) => apiClient.delete('/tasks/batch', { data: { task_ids: ids } }),
  onSuccess: () => {
    toast.success('删除成功')
    selectedIds.value = []
    queryClient.invalidateQueries({ queryKey: ['tasks'] })
  },
  onError: () => toast.error('删除失败'),
})

// 多选
const selectedIds = ref<string[]>([])

// 任务详情弹窗
const showDetailDialog = ref(false)
const selectedTask = ref<TaskItem | null>(null)

// 可删除的任务（已完成或失败）
const deletableTasks = computed(() => tasks.value.filter(t => t.status === 'completed' || t.status === 'failed'))
const allSelected = computed(() => 
  deletableTasks.value.length > 0 && deletableTasks.value.every(t => selectedIds.value.includes(t.id))
)

function toggleSelectAll() {
  if (allSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = [...deletableTasks.value.map(t => t.id)]
  }
}

function toggleSelect(id: string) {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter(i => i !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

function setStatusFilter(status: string) {
  statusFilter.value = status
  taskParams.value = { ...taskParams.value, status, offset: 0 }
  selectedIds.value = []
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
    case 'analyze_image': return '图片分析'
    case 'batch_analyze': return '批量分析'
    case 'vector_embed': return '向量嵌入'
    case 'storage_sync': return '存储同步'
    case 'storage_unlink': return '存储解绑'
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

function openTaskDetail(task: TaskItem) {
  selectedTask.value = task
  showDetailDialog.value = true
}

function handleBatchDelete() {
  if (selectedIds.value.length === 0) return
  deleteMutation.mutate(selectedIds.value)
}

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '等待中' },
  { value: 'processing', label: '处理中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
]

const canDelete = (status: string) => status === 'completed' || status === 'failed'
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
            v-if="selectedIds.length > 0"
            variant="destructive" 
            size="sm"
            @click="handleBatchDelete"
            :disabled="deleteMutation.isPending.value"
          >
            <Trash2 class="w-4 h-4 mr-2" />
            删除选中 ({{ selectedIds.length }})
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

      <!-- 任务统计和全选 -->
      <div class="flex items-center justify-between text-sm text-muted-foreground mb-4">
        <span>共 {{ total }} 个任务</span>
        <label v-if="deletableTasks.length > 0" class="flex items-center gap-2 cursor-pointer select-none">
          <input 
            type="checkbox" 
            :checked="allSelected" 
            @change="toggleSelectAll"
            class="w-4 h-4 accent-primary rounded"
          />
          <span>全选可删除 ({{ deletableTasks.length }})</span>
        </label>
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
          class="flex items-center gap-4 p-4 bg-card border border-border rounded-xl hover:border-primary/50 transition-colors"
        >
          <!-- 多选框 -->
          <div class="shrink-0" @click.stop>
            <input 
              v-if="canDelete(task.status)"
              type="checkbox" 
              :checked="selectedIds.includes(task.id)"
              @change="toggleSelect(task.id)"
              class="w-4 h-4 accent-primary rounded cursor-pointer"
            />
            <div v-else class="w-4 h-4" />
          </div>

          <!-- 任务类型图标 -->
          <div class="w-10 h-10 bg-muted rounded-lg flex items-center justify-center shrink-0">
            <Image class="w-5 h-5 text-muted-foreground" />
          </div>

          <!-- 任务信息 -->
          <div class="flex-1 min-w-0 cursor-pointer" @click="openTaskDetail(task)">
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
            <p v-if="task.error" class="text-sm text-destructive mt-1 truncate">
              {{ task.error.split('\n')[0] }}
            </p>
          </div>

          <!-- 状态 -->
          <div class="flex items-center gap-2 shrink-0">
            <component 
              :is="getStatusIcon(task.status)" 
              class="w-5 h-5"
              :class="getStatusClass(task.status)"
            />
            <span class="text-sm font-medium" :class="getStatusClass(task.status)">
              {{ getStatusLabel(task.status) }}
            </span>
          </div>

          <!-- 操作按钮 -->
          <div class="flex items-center gap-1 shrink-0">
            <Button variant="ghost" size="icon" @click="openTaskDetail(task)">
              <Eye class="w-4 h-4" />
            </Button>
            <Button 
              v-if="task.status === 'failed'"
              variant="ghost" 
              size="icon"
              @click="handleRetry(task.id)"
              :disabled="retryTaskMutation.isPending.value"
            >
              <PlayCircle class="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 任务详情弹窗 -->
  <Dialog :open="showDetailDialog" @update:open="showDetailDialog = $event">
    <DialogContent class="max-w-2xl max-h-[80vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>任务详情</DialogTitle>
      </DialogHeader>
      
      <div v-if="selectedTask" class="space-y-4">
        <!-- 基本信息 -->
        <div class="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span class="text-muted-foreground">任务 ID</span>
            <p class="font-mono text-xs mt-1">{{ selectedTask.id }}</p>
          </div>
          <div>
            <span class="text-muted-foreground">任务类型</span>
            <p class="mt-1">{{ getTaskTypeLabel(selectedTask.type) }}</p>
          </div>
          <div>
            <span class="text-muted-foreground">状态</span>
            <p class="mt-1 flex items-center gap-2">
              <component 
                :is="getStatusIcon(selectedTask.status)" 
                class="w-4 h-4"
                :class="getStatusClass(selectedTask.status)"
              />
              {{ getStatusLabel(selectedTask.status) }}
            </p>
          </div>
          <div>
            <span class="text-muted-foreground">创建时间</span>
            <p class="mt-1">{{ formatTime(selectedTask.created_at) }}</p>
          </div>
          <div v-if="selectedTask.completed_at">
            <span class="text-muted-foreground">完成时间</span>
            <p class="mt-1">{{ formatTime(selectedTask.completed_at) }}</p>
          </div>
        </div>

        <!-- 任务参数 -->
        <div v-if="selectedTask.payload && Object.keys(selectedTask.payload).length > 0">
          <span class="text-sm text-muted-foreground">任务参数</span>
          <pre class="mt-2 p-3 bg-muted rounded-lg text-xs overflow-x-auto">{{ JSON.stringify(selectedTask.payload, null, 2) }}</pre>
        </div>

        <!-- 任务结果 -->
        <div v-if="selectedTask.result && Object.keys(selectedTask.result).length > 0">
          <span class="text-sm text-muted-foreground">任务结果</span>
          <pre class="mt-2 p-3 bg-green-50 dark:bg-green-950/30 rounded-lg text-xs overflow-x-auto">{{ JSON.stringify(selectedTask.result, null, 2) }}</pre>
        </div>

        <!-- 错误信息 -->
        <div v-if="selectedTask.error">
          <span class="text-sm text-muted-foreground">错误信息</span>
          <pre class="mt-2 p-3 bg-destructive/10 rounded-lg text-xs text-destructive overflow-x-auto whitespace-pre-wrap">{{ selectedTask.error }}</pre>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
