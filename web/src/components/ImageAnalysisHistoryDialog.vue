<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import apiClient from '@/api/client'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError, notifySuccess } from '@/utils/notify'
import { useQueryClient } from '@tanstack/vue-query'
import { RefreshCw, RotateCcw, Trash2, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'

type Version = { id: number; description: string; tags: string[]; created_at: string }
const props = defineProps<{ open: boolean; imageId: number | null }>()
const emit = defineEmits<{ 'update:open': [boolean]; updated: [] }>()
const opened = computed({ get: () => props.open, set: value => { if (!busy.value) emit('update:open', value) } })
const rows = ref<Version[]>([])
const loading = ref(false)
const restoringId = ref<number | null>(null)
const deletingId = ref<number | null>(null)
const busy = computed(() => restoringId.value !== null || deletingId.value !== null)
const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()
onUnmounted(handleCancel)
const query = useQueryClient()
const current = ref<Record<string, unknown> | null>(null)
let generation = 0
async function load() {
  const run = ++generation
  rows.value = []
  current.value = null
  if (!props.open || !props.imageId) { loading.value = false; return }
  loading.value = true
  try {
    const { data } = await apiClient.get<{ versions: Version[]; current: Record<string, unknown> }>(`/analysis-reviews/${props.imageId}`)
    if (run === generation && props.open) {
      rows.value = data.versions
      current.value = data.current
    }
  } catch (e) { if (run === generation && props.open) notifyError(getErrorMessage(e)) }
  finally { if (run === generation) loading.value = false }
}
async function restore(row: Version) {
  const id = props.imageId
  if (!id || busy.value || loading.value || current.value === null) return
  restoringId.value = row.id
  try {
    const result = await confirm({
      title: '回退历史版本',
      message: `确定回退到 ${new Date(row.created_at).toLocaleString()} 的备份吗？将恢复图片描述和普通标签，回退前会备份当前内容。`,
      confirmText: '确认回退', variant: 'warning',
    })
    if (!result.confirmed || !props.open || props.imageId !== id) return
    await apiClient.post(`/analysis-reviews/${id}/${row.id}/restore`, { expected_snapshot: current.value })
    for (const key of [['images'], ['my-images'], ['image'], ['tasks']]) void query.invalidateQueries({ queryKey: key })
    emit('updated')
    notifySuccess('已回退，回退前的内容已备份')
    if (props.open && props.imageId === id) await load()
  } catch (e) { notifyError(getErrorMessage(e)) }
  finally { restoringId.value = null }
}
async function remove(row: Version) {
  const id = props.imageId
  if (!id || busy.value || loading.value) return
  deletingId.value = row.id
  try {
    const result = await confirm({
      title: '删除历史备份',
      message: `确定删除 ${new Date(row.created_at).toLocaleString()} 的这份备份吗？删除后无法恢复，当前内容不会改变。`,
      confirmText: '确认删除', variant: 'danger',
    })
    if (!result.confirmed || !props.open || props.imageId !== id) return
    await apiClient.delete(`/analysis-reviews/${id}/${row.id}`)
    notifySuccess('历史备份已删除')
    if (props.open && props.imageId === id) await load()
  } catch (e) { notifyError(getErrorMessage(e)) }
  finally { deletingId.value = null }
}
watch(() => [props.open, props.imageId], load, { immediate: true })
</script>
<template>
  <Dialog v-model:open="opened">
    <DialogContent :show-close-button="false" class="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
      <div class="absolute top-3 right-3 flex items-center gap-1">
        <Button type="button" variant="ghost" size="icon" class="h-7 w-7 text-muted-foreground" :disabled="loading || busy" aria-label="刷新历史" title="刷新历史" @click="load"><RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" /></Button>
        <Button type="button" variant="ghost" size="icon" class="h-7 w-7 text-muted-foreground" :disabled="busy" aria-label="关闭" title="关闭" @click="opened = false"><X class="h-4 w-4" /></Button>
      </div>
      <DialogHeader class="pr-16"><DialogTitle>图片分析历史</DialogTitle><DialogDescription>分析完成后直接更新，最多保留最近三份历史备份。</DialogDescription></DialogHeader>
      <p v-if="loading" class="text-sm text-muted-foreground">加载中…</p>
      <p v-else-if="!rows.length" class="py-6 text-center text-sm text-muted-foreground">暂无历史备份</p>
      <article v-for="row in rows" :key="row.id" class="space-y-3 rounded-lg border p-4">
        <div class="flex items-center justify-between gap-3">
          <p class="text-xs text-muted-foreground">备份于 {{ new Date(row.created_at).toLocaleString() }}</p>
          <div class="flex shrink-0 items-center gap-1">
            <Button type="button" variant="ghost" size="sm" class="h-7 shrink-0 gap-1 px-2 text-xs" :disabled="loading || busy" :aria-label="`回退到 ${new Date(row.created_at).toLocaleString()} 的备份`" @click="restore(row)"><RotateCcw class="h-3.5 w-3.5" :class="{ 'animate-spin': restoringId === row.id }" />{{ restoringId === row.id ? '回退中…' : '回退' }}</Button>
            <Button type="button" variant="ghost" size="sm" class="h-7 gap-1 px-2 text-xs text-destructive hover:text-destructive" :disabled="loading || busy" :aria-label="`删除 ${new Date(row.created_at).toLocaleString()} 的备份`" @click="remove(row)"><Trash2 class="h-3.5 w-3.5" />{{ deletingId === row.id ? '删除中…' : '删除' }}</Button>
          </div>
        </div>
        <p class="text-sm whitespace-pre-wrap">{{ row.description || '无描述' }}</p>
        <div class="flex flex-wrap gap-2"><span v-for="tag in row.tags" :key="tag" class="rounded bg-muted px-2 py-1 text-xs">{{ tag }}</span></div>
      </article>
    </DialogContent>
  </Dialog>
  <ConfirmDialog :open="confirmState.open" :title="confirmState.title" :message="confirmState.message" :confirm-text="confirmState.confirmText" :variant="confirmState.variant" @confirm="handleConfirm" @cancel="handleCancel" />
</template>
