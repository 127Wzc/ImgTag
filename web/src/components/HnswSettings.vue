<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { Loader2, RefreshCw } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import apiClient from '@/api/client'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError, notifySuccess } from '@/utils/notify'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const props = defineProps<{
  modelValue: string
  efSearch: string
  hasChanges: boolean
  dimensionsMismatch: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:efSearch': [value: string]
}>()
interface IndexStatus {
  ready: boolean
  supported: boolean
  active: boolean
  enabled: boolean
  is_running: boolean
  dimensions_match: boolean
  size_bytes: number
  message: string
  last_error: string
}
const enabled = computed(() => props.modelValue === 'true')
const status = ref<IndexStatus | null>(null)
const loading = ref(false)
const starting = ref(false)
const error = ref('')
const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()
let timer: ReturnType<typeof setTimeout> | null = null
let generation = 0

function stopPolling() {
  generation++
  if (timer) clearTimeout(timer)
  timer = null
}

async function refresh() {
  stopPolling()
  if (!enabled.value) return
  const current = generation
  loading.value = true
  try {
    const { data } = await apiClient.get<IndexStatus>('/vectors/index/status')
    if (current !== generation) return
    status.value = data
    error.value = ''
    if (data.is_running) timer = setTimeout(() => void refresh(), 3000)
  } catch (e) {
    if (current !== generation) return
    error.value = getErrorMessage(e)
    if (status.value?.is_running) timer = setTimeout(() => void refresh(), 5000)
  } finally {
    if (current === generation) loading.value = false
  }
}

async function build(force = false) {
  if (force) {
    const result = await confirm({
      title: '强制重建搜索索引',
      message: '将在线重建索引，不重新生成图片向量。维护期间会增加服务器负载，建议在低峰执行。',
      variant: 'warning', confirmText: '开始重建',
    })
    if (!result.confirmed) return
  }
  starting.value = true
  try {
    const { data } = await apiClient.post<{ message: string }>(`/vectors/index/build?force=${force}`)
    notifySuccess(data.message, { once: true })
    await refresh()
  } catch (e) {
    notifyError(getErrorMessage(e))
    await refresh()
  } finally {
    starting.value = false
  }
}

watch([enabled, () => props.hasChanges, () => props.dimensionsMismatch], () => {
  if (enabled.value) void refresh()
  else {
    stopPolling()
    loading.value = false
  }
}, { immediate: true })
onUnmounted(stopPolling)
</script>

<template>
  <section class="rounded-xl border border-border p-4 space-y-3">
    <label class="flex items-center justify-between gap-4 cursor-pointer">
      <span>
        <span class="block text-sm font-medium">HNSW 索引加速</span>
        <span class="block text-xs text-muted-foreground mt-1">加速语义搜索；关闭时使用精确搜索并保留已有索引</span>
      </span>
      <input type="checkbox" class="h-4 w-4 accent-primary" :checked="enabled"
        @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked ? 'true' : 'false')" />
    </label>

    <div v-if="enabled" class="space-y-3 border-t border-border pt-3" aria-live="polite">
      <div class="flex items-center justify-between gap-3">
        <p class="text-sm text-muted-foreground">
          {{ error ? '索引状态检测失败' : status?.message || '正在检测已有索引…' }}
        </p>
        <Button size="sm" variant="ghost" :disabled="loading" aria-label="刷新索引状态" @click="refresh">
          <Loader2 v-if="loading" class="h-4 w-4 animate-spin" />
          <RefreshCw v-else class="h-4 w-4" />
        </Button>
      </div>
      <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
      <p v-if="hasChanges" class="text-xs text-muted-foreground">保存设置后生效；维护索引前请先保存。</p>
      <template v-if="status && !error">
        <p v-if="status.ready && status.supported !== false && status.dimensions_match && !dimensionsMismatch" class="text-xs text-muted-foreground">
          已有索引可直接复用，无需再次构建 · {{ (status.size_bytes / 1000000).toFixed(1) }} MB
        </p>
        <p v-if="!status.dimensions_match || dimensionsMismatch" class="text-xs text-amber-600">
          请先处理向量维度不一致；当前继续使用精确搜索。
        </p>
        <p v-if="status.supported === false" class="text-xs text-amber-600">
          索引加速需要 pgvector 0.8 或更高版本，且向量维度不超过 2000；当前继续使用精确搜索。
        </p>
        <p v-if="!status.active && !hasChanges && status.dimensions_match && !dimensionsMismatch && status.supported !== false" class="text-xs text-muted-foreground">
          索引就绪前继续使用精确搜索；构建完成后自动启用。
        </p>
        <p v-if="status.last_error" class="text-xs text-destructive">{{ status.last_error }}</p>
        <Button v-if="!status.ready && !status.is_running" size="sm" variant="secondary"
          :disabled="starting || hasChanges || dimensionsMismatch || !status.dimensions_match || status.supported === false" @click="build()">
          <Loader2 v-if="starting" class="h-4 w-4 mr-2 animate-spin" />
          构建搜索索引
        </Button>
        <p v-if="!status.ready && !status.is_running" class="text-xs text-muted-foreground">
          只构建索引，不重新分析图片或生成向量。会增加服务器负载，建议低峰操作。
        </p>
        <details class="text-xs">
          <summary class="cursor-pointer text-muted-foreground">高级设置与维护</summary>
          <div class="space-y-3 pt-3">
            <label class="flex items-center justify-between gap-3">
              搜索精度
              <input type="number" min="40" max="1000" step="20" :value="efSearch"
                class="w-24 rounded border border-border bg-background px-2 py-1"
                @input="emit('update:efSearch', ($event.target as HTMLInputElement).value)" />
            </label>
            <p class="text-muted-foreground">控制索引内部的搜索投入，数值越大通常越不容易遗漏，也会增加计算开销；默认 40，实际值不会低于每页数量。返回数量由每页数量控制，候选数量自动推导。</p>
            <Button v-if="status.ready" size="sm" variant="outline"
              :disabled="starting || status.is_running || hasChanges || dimensionsMismatch || !status.dimensions_match || status.supported === false"
              @click="build(true)">
              <Loader2 v-if="starting || status.is_running" class="h-4 w-4 mr-2 animate-spin" />
              强制重建索引
            </Button>
          </div>
        </details>
      </template>
    </div>
    <ConfirmDialog :open="confirmState.open" :title="confirmState.title" :message="confirmState.message"
      :variant="confirmState.variant" :confirm-text="confirmState.confirmText"
      @confirm="handleConfirm" @cancel="handleCancel" />
  </section>
</template>
