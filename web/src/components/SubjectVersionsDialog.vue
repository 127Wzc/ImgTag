<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import apiClient from '@/api/client'
import type { SubjectVersion } from '@/api/queries/subjects'
import type { SubjectResponse } from '@/types'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError, notifySuccess } from '@/utils/notify'
import { useQueryClient } from '@tanstack/vue-query'
import { RefreshCw, RotateCcw, Trash2, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'

const props = defineProps<{ open: boolean; subjectId: number | null }>()
const emit = defineEmits<{ 'update:open': [boolean]; updated: [] }>()
const opened = computed({ get: () => props.open, set: value => { if (!busy.value) emit('update:open', value) } })
const rows = ref<SubjectVersion[]>([])
const loading = ref(false)
const restoringId = ref<number | null>(null)
const deletingId = ref<number | null>(null)
const busy = computed(() => restoringId.value !== null || deletingId.value !== null)
const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()
onUnmounted(handleCancel)
const query = useQueryClient()
const revision = ref<number | null>(null)
let generation = 0
async function load() {
  const run = ++generation
  rows.value = []
  revision.value = null
  if (!props.open || !props.subjectId) { loading.value = false; return }
  loading.value = true
  try {
    const [history, subject] = await Promise.all([
      apiClient.get<SubjectVersion[]>(`/subjects/${props.subjectId}/versions`),
      apiClient.get<SubjectResponse>(`/subjects/${props.subjectId}`),
    ])
    if (run === generation && props.open) {
      rows.value = history.data
      revision.value = subject.data.definition_revision
    }
  } catch (e) { if (run === generation && props.open) notifyError(getErrorMessage(e)) }
  finally { if (run === generation) loading.value = false }
}
async function restore(row: SubjectVersion) {
  const id = props.subjectId
  if (!id || busy.value || loading.value || revision.value === null) return
  restoringId.value = row.id
  try {
    const result = await confirm({
      title: '回退历史版本',
      message: `确定回退到 ${new Date(row.created_at).toLocaleString()} 的备份吗？将恢复主体描述和识别备注，回退前会备份当前内容。`,
      confirmText: '确认回退', variant: 'warning',
    })
    if (!result.confirmed || !props.open || props.subjectId !== id) return
    await apiClient.post(`/subjects/${id}/versions/${row.id}/restore`, { expected_revision: revision.value })
    for (const key of [['subjects']]) void query.invalidateQueries({ queryKey: key })
    emit('updated')
    notifySuccess('已回退，回退前的内容已备份')
    if (props.open && props.subjectId === id) await load()
  } catch (e) { notifyError(getErrorMessage(e)) }
  finally { restoringId.value = null }
}
async function remove(row: SubjectVersion) {
  const id = props.subjectId
  if (!id || busy.value || loading.value) return
  deletingId.value = row.id
  try {
    const result = await confirm({
      title: '删除历史备份',
      message: `确定删除 ${new Date(row.created_at).toLocaleString()} 的这份备份吗？删除后无法恢复，当前内容不会改变。`,
      confirmText: '确认删除', variant: 'danger',
    })
    if (!result.confirmed || !props.open || props.subjectId !== id) return
    await apiClient.delete(`/subjects/${id}/versions/${row.id}`)
    notifySuccess('历史备份已删除')
    if (props.open && props.subjectId === id) await load()
  } catch (e) { notifyError(getErrorMessage(e)) }
  finally { deletingId.value = null }
}
watch(() => [props.open, props.subjectId], load, { immediate: true })
</script>
<template>
  <Dialog v-model:open="opened">
    <DialogContent :show-close-button="false" class="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
      <div class="absolute top-3 right-3 flex items-center gap-1">
        <Button type="button" variant="ghost" size="icon" class="h-7 w-7 text-muted-foreground" :disabled="loading || busy" aria-label="刷新历史" title="刷新历史" @click="load"><RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" /></Button>
        <Button type="button" variant="ghost" size="icon" class="h-7 w-7 text-muted-foreground" :disabled="busy" aria-label="关闭" title="关闭" @click="opened = false"><X class="h-4 w-4" /></Button>
      </div>
      <DialogHeader class="pr-16"><DialogTitle>主体描述历史</DialogTitle><DialogDescription>提炼完成后直接更新描述，最多保留最近三份历史备份。</DialogDescription></DialogHeader>
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
        <p class="text-sm whitespace-pre-wrap">{{ row.definition || '无描述' }}</p>
        <p v-if="row.recognition_notes" class="text-sm whitespace-pre-wrap text-muted-foreground">识别备注：{{ row.recognition_notes }}</p>
      </article>
    </DialogContent>
  </Dialog>
  <ConfirmDialog :open="confirmState.open" :title="confirmState.title" :message="confirmState.message" :confirm-text="confirmState.confirmText" :variant="confirmState.variant" @confirm="handleConfirm" @cancel="handleCancel" />
</template>
