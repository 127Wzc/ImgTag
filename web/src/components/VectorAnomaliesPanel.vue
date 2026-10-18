<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { AlertTriangle, Brain, Loader2, RefreshCw } from 'lucide-vue-next'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError, notifySuccess } from '@/utils/notify'
import type { Task } from '@/types'

type Anomaly = {
  id: number
  image_url: string
  description: string | null
  tags: string[]
  reason: 'missing' | 'dimension_mismatch' | 'invalid'
  actual_dimensions: number | null
}
type Scan = { data: Anomaly[]; total: number; pages: number; expected_dimensions: number; db_dimensions: number }
type Repair = { taskId?: string; status: 'submitting' | 'pending' | 'completed' | 'failed'; error?: string }
const results = ref<Scan | null>(null)
const loading = ref(false)
const error = ref('')
const page = ref(1)
const repairs = ref<Record<number, Repair>>({})
const query = useQueryClient()
const dimensionsMismatch = computed(() => results.value && results.value.expected_dimensions !== results.value.db_dimensions)
let timer: ReturnType<typeof setTimeout> | undefined
let polling = false
let disposed = false
onUnmounted(() => { disposed = true; clearTimeout(timer) })

async function scan(targetPage = 1) {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    let response = await apiClient.get<Scan>('/vectors/anomalies', { params: { page: targetPage, size: 20 } })
    // 修复或删除使最后一页变空时，回到有效页。
    if (targetPage > Math.max(1, response.data.pages)) {
      targetPage = Math.max(1, response.data.pages)
      response = await apiClient.get<Scan>('/vectors/anomalies', { params: { page: targetPage, size: 20 } })
    }
    if (!disposed) { results.value = response.data; page.value = targetPage }
  } catch (e) { if (!disposed) error.value = getErrorMessage(e) }
  finally { loading.value = false }
}

function busy(id: number) { return ['submitting', 'pending'].includes(repairs.value[id]?.status || '') }
function reason(row: Anomaly) {
  if (row.reason === 'missing') return '缺少向量'
  if (row.reason === 'dimension_mismatch') return `维度不符：现有 ${row.actual_dimensions}，需要 ${results.value?.expected_dimensions}`
  return '零向量或无效向量'
}
function schedulePoll() {
  if (!disposed && !timer && !polling && Object.values(repairs.value).some(r => r.status === 'pending')) {
    timer = setTimeout(() => { timer = undefined; void poll() }, 2500)
  }
}
async function poll() {
  if (disposed || polling) return
  polling = true
  let repaired = false
  await Promise.all(Object.entries(repairs.value).filter(([, value]) => value.status === 'pending').map(async ([key, repair]) => {
    try {
      const { data } = await apiClient.get<Task>(`/tasks/${repair.taskId}`)
      if (disposed || repairs.value[Number(key)]?.taskId !== repair.taskId) return
      if (data.status === 'completed' && data.result?.saved === true) {
        repairs.value[Number(key)] = { ...repair, status: 'completed' }
        repaired = true
        notifySuccess(`图片 #${key} 的向量已重建`)
      } else if (data.status === 'failed' || data.status === 'completed') {
        repairs.value[Number(key)] = { ...repair, status: 'failed', error: data.error || '向量未保存，内容可能已变化或向量服务不可用，请查看任务后重试' }
      }
    } catch (e) {
      if (!disposed) repairs.value[Number(key)] = { ...repair, status: 'failed', error: `无法确认重建结果：${getErrorMessage(e)}` }
    }
  }))
  if (repaired && !disposed) {
    for (const key of [['images'], ['my-images'], ['image']]) void query.invalidateQueries({ queryKey: key })
    await scan(page.value)
  }
  polling = false
  schedulePoll()
}
async function rebuild(row: Anomaly) {
  if (busy(row.id) || dimensionsMismatch.value) return
  repairs.value[row.id] = { status: 'submitting' }
  try {
    const { data } = await apiClient.post<{ task_ids: string[] }>(`/vectors/anomalies/${row.id}/rebuild`)
    if (disposed) return
    if (!data.task_ids[0]) throw new Error('图片已不存在，请重新检测')
    repairs.value[row.id] = { taskId: data.task_ids[0], status: 'pending' }
    void query.invalidateQueries({ queryKey: ['tasks'] })
    schedulePoll()
  } catch (e) {
    if (!disposed) {
      repairs.value[row.id] = { status: 'failed', error: getErrorMessage(e) }
      notifyError(getErrorMessage(e))
    }
  }
}
</script>

<template>
  <section class="p-4 bg-muted/50 rounded-xl space-y-3">
    <div class="flex items-center justify-between gap-3">
      <h3 class="font-medium text-foreground flex items-center gap-2"><Brain class="w-5 h-5 text-muted-foreground" />异常向量检测</h3>
      <Button variant="outline" size="sm" :disabled="loading" @click="scan(1)">
        <Loader2 v-if="loading" class="w-4 h-4 mr-1 animate-spin" /><RefreshCw v-else class="w-4 h-4 mr-1" />{{ loading ? '检测中…' : '检测' }}
      </Button>
    </div>
    <p class="text-xs text-muted-foreground">检测有描述或标签、但向量缺失、无效或维度不符的图片。单张重建使用现有描述和标签，不重新分析图片。</p>
    <p v-if="error" role="alert" class="text-sm text-destructive">{{ error }}</p>
    <p v-if="dimensionsMismatch" role="alert" class="text-xs text-amber-600 flex gap-2"><AlertTriangle class="w-4 h-4 shrink-0" />配置维度 {{ results?.expected_dimensions }} 与数据库维度 {{ results?.db_dimensions }} 不一致，请先在向量嵌入设置中处理维度配置。</p>
    <template v-if="results">
      <p class="text-sm" role="status" aria-live="polite">{{ results.total ? `发现 ${results.total} 张异常图片` : '未发现异常向量' }}</p>
      <article v-for="row in results.data" :key="row.id" class="rounded-lg border border-border bg-background p-3 space-y-2">
        <div class="flex gap-3">
          <a v-if="row.image_url" :href="row.image_url" target="_blank" rel="noopener noreferrer" :aria-label="`查看图片 ${row.id}`" class="shrink-0"><img :src="row.image_url" :alt="`图片 #${row.id}`" class="w-16 h-16 rounded object-cover" loading="lazy" /></a>
          <div class="min-w-0 flex-1 space-y-1">
            <p class="text-xs text-muted-foreground">#{{ row.id }} · {{ reason(row) }}</p>
            <p class="text-sm line-clamp-2">{{ row.description || '无描述' }}</p>
            <p v-if="row.tags.length" class="text-xs text-muted-foreground line-clamp-2">{{ row.tags.join('、') }}</p>
          </div>
        </div>
        <p v-if="repairs[row.id]?.error" role="alert" class="text-xs text-destructive break-words">{{ repairs[row.id]?.error }}</p>
        <div class="flex items-center justify-end gap-3">
          <RouterLink v-if="repairs[row.id]?.taskId" :to="{ path: '/tasks', query: { task: repairs[row.id]?.taskId } }" class="text-xs underline text-muted-foreground">查看任务</RouterLink>
          <Button size="sm" variant="outline" :disabled="busy(row.id) || !!dimensionsMismatch || loading" @click="rebuild(row)"><Loader2 v-if="busy(row.id)" class="w-3 h-3 mr-1 animate-spin" />{{ busy(row.id) ? '重建中…' : '重建向量' }}</Button>
        </div>
      </article>
      <div v-if="results.pages > 1" class="flex items-center justify-between gap-2">
        <Button size="sm" variant="ghost" :disabled="loading || page <= 1" @click="scan(page - 1)">上一页</Button>
        <span class="text-xs text-muted-foreground">{{ page }} / {{ results.pages }}</span>
        <Button size="sm" variant="ghost" :disabled="loading || page >= results.pages" @click="scan(page + 1)">下一页</Button>
      </div>
    </template>
  </section>
</template>
