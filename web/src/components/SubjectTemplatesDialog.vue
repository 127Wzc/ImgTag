<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import apiClient from '@/api/client'
import type { SubjectTemplate } from '@/api/queries/subjects'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError } from '@/utils/notify'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Plus } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [boolean]; updated: [] }>()
const opened = computed({ get: () => props.open, set: value => emit('update:open', value) })
const rows = ref<SubjectTemplate[]>([])
const editing = ref<number | null>(null)
const formOpen = ref(false)
const name = ref('')
const content = ref('')
const busy = ref(false)
async function load() {
  try { rows.value = (await apiClient.get<SubjectTemplate[]>('/subjects/templates')).data }
  catch (e) { notifyError(getErrorMessage(e)) }
}
watch(() => props.open, value => { if (value) { formOpen.value = false; load() } }, { immediate: true })
function edit(row?: SubjectTemplate, copy = false) {
  formOpen.value = true
  editing.value = row && !copy ? row.id : null
  name.value = row ? row.name + (copy ? '（自定义）' : '') : ''
  content.value = row?.content || ''
}
async function save() {
  busy.value = true
  try {
    const data = { name: name.value.trim(), content: content.value.trim(), is_active: true }
    if (editing.value) await apiClient.patch(`/subjects/templates/${editing.value}`, data)
    else await apiClient.post('/subjects/templates', data)
    await load(); formOpen.value = false; emit('updated')
  } catch (e) { notifyError(getErrorMessage(e)) }
  finally { busy.value = false }
}
async function toggle(row: SubjectTemplate) {
  try {
    await apiClient.patch(`/subjects/templates/${row.id}`, { name: row.name, content: row.content, is_active: !row.is_active })
    await load(); emit('updated')
  } catch (e) { notifyError(getErrorMessage(e)) }
}
</script>
<template>
  <Dialog v-model:open="opened">
    <DialogContent class="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
      <DialogHeader><DialogTitle>提炼规则</DialogTitle><DialogDescription class="sr-only">管理内置和自定义规则</DialogDescription></DialogHeader>
      <div class="flex justify-end"><Button size="sm" variant="outline" class="gap-1.5" @click="edit()"><Plus class="w-3.5 h-3.5" />新建规则</Button></div>
      <div class="space-y-2">
        <details v-for="row in rows" :key="row.id" class="border border-border/50 rounded-lg p-3">
          <summary class="cursor-pointer text-sm font-medium">{{ row.name }}<span class="ml-2 text-xs font-normal text-muted-foreground">{{ row.is_builtin ? '内置' : row.is_active ? '' : '已停用' }}</span></summary>
          <p class="mt-3 text-sm text-muted-foreground whitespace-pre-wrap">{{ row.content }}</p>
          <div class="flex gap-2 mt-3"><Button size="sm" variant="outline" @click="edit(row, true)">复制</Button><Button v-if="!row.is_builtin" size="sm" variant="outline" @click="edit(row)">编辑</Button><Button v-if="!row.is_builtin" size="sm" variant="ghost" @click="toggle(row)">{{ row.is_active ? '停用' : '启用' }}</Button></div>
        </details>
      </div>
      <form v-if="formOpen" class="border-t border-border/50 pt-4 space-y-4" @submit.prevent="save">
        <h3 class="text-sm font-medium">{{ editing ? '编辑规则' : '新建规则' }}</h3>
        <label class="block text-sm">名称<Input v-model="name" required maxlength="120" class="mt-2" /></label>
        <label class="block text-sm">内容<textarea v-model="content" required maxlength="6000" rows="4" class="mt-2 w-full rounded-md border border-input bg-transparent p-3" /></label>
        <div class="flex justify-end gap-2"><Button type="button" variant="ghost" :disabled="busy" @click="formOpen = false">取消</Button><Button :disabled="busy || !name.trim() || !content.trim()" type="submit">保存</Button></div>
      </form>
    </DialogContent>
  </Dialog>
</template>
