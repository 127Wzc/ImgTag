<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { useCategories, useSearchTags } from '@/api/queries'
import apiClient from '@/api/client'
import type { SubjectResponse, Tag } from '@/types'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError, notifySuccess } from '@/utils/notify'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Check, Loader2, Plus, Tag as TagIcon, X } from 'lucide-vue-next'

const props = defineProps<{ open: boolean; subject?: SubjectResponse | null; subjects?: SubjectResponse[]; categoryId?: number | null }>()
const emit = defineEmits<{ 'update:open': [boolean]; saved: [SubjectResponse] }>()
const query = useQueryClient()
const { data: categories } = useCategories()
const name = ref(''), category = ref(''), description = ref(''), aliasInput = ref('')
const aliases = ref<string[]>([])
const active = ref(true), busy = ref(false), nameFocused = ref(false)
const savedForm = ref('')
const selectedTag = ref<Tag | null>(null)
const formValue = computed(() => JSON.stringify([name.value, category.value, description.value, aliases.value, aliasInput.value, active.value]))
const opened = computed({ get: () => props.open, set: value => {
  if (!value && (busy.value || (formValue.value !== savedForm.value && !window.confirm('有未保存的主体内容，确定关闭吗？')))) return
  emit('update:open', value)
} })
const keyword = computed(() => props.open && nameFocused.value ? name.value.trim() : '')
const { data: matches } = useSearchTags(keyword, 2, 15)
const nameOptions = computed(() => (matches.value || []).filter(t => t.name !== name.value.trim() && (!category.value || t.parent_id == null || t.parent_id === Number(category.value))).slice(0, 5))
const duplicate = computed(() => (props.subjects || []).find(s => s.id !== props.subject?.id && s.name === name.value.trim()))
const canSave = computed(() => name.value.trim().length > 0 && !!category.value && !duplicate.value && !busy.value)
watch(() => [props.open, props.subject?.id], () => {
  if (!props.open) return
  name.value = props.subject?.name || ''; category.value = String(props.subject?.category_tag_id || props.categoryId || '')
  description.value = props.subject?.description || ''; aliases.value = [...(props.subject?.aliases || [])]
  aliasInput.value = ''; active.value = props.subject?.is_active ?? true; busy.value = false; nameFocused.value = false
  selectedTag.value = null; savedForm.value = formValue.value
}, { immediate: true })
function chooseName(tag: Tag) {
  name.value = tag.name; selectedTag.value = tag; nameFocused.value = false
  if (!category.value && tag.parent_id && categories.value?.some(c => c.id === tag.parent_id)) category.value = String(tag.parent_id)
}
function addAliases() {
  aliases.value = [...new Set([...aliases.value, ...aliasInput.value.split(/[、,，\n]/).map(n => n.trim()).filter(Boolean)])]
    .filter(n => n !== name.value.trim())
  aliasInput.value = ''
}
async function save() {
  if (!canSave.value) return
  addAliases()
  if (aliases.value.some(n => n.length > 50 && !props.subject?.aliases.includes(n))) { notifyError('每个别名最多50个字'); return }
  busy.value = true
  try {
    const resolve = async (value: string) => {
      if (props.subject?.name === value) return props.subject.primary_tag_id
      if (selectedTag.value?.name === value) return selectedTag.value.id
      if (value.length > 50) {
        const tags = (await apiClient.get<Tag[]>('/tags/', { params: { keyword: value, level: 2, size: 200 } })).data
        const existing = tags.find(tag => tag.name === value)
        if (existing) return existing.id
        throw new Error('新名称或别名最多50个字')
      }
      return (await apiClient.post<{ id: number }>('/tags/resolve', null, { params: { name: value, level: 2 } })).data.id
    }
    const primary = await resolve(name.value.trim())
    const aliasIds = await Promise.all(aliases.value.map(resolve))
    const payload = { category_tag_id: Number(category.value), primary_tag_id: primary,
      alias_tag_ids: [...new Set(aliasIds)].filter(id => id !== primary), description: description.value.trim() || null }
    const result = props.subject
      ? await apiClient.patch<SubjectResponse>(`/subjects/${props.subject.id}`, { ...payload, is_active: active.value })
      : await apiClient.post<SubjectResponse>('/subjects/', payload)
    for (const key of [['subjects'], ['tags'], ['images']]) query.invalidateQueries({ queryKey: key })
    savedForm.value = formValue.value
    notifySuccess(props.subject ? '主体已保存' : '主体已创建')
    emit('saved', result.data); emit('update:open', false)
  } catch (e) {
    const message = getErrorMessage(e)
    notifyError(message.includes('父子关系') || message.includes('category_tag_id')
      ? '名称或别名已属于其他分类，请调整分类后重试。'
      : message.includes('主名称标签') && message.includes('占用')
        ? '同名主体已经存在，可以返回列表搜索并编辑。' : message)
  }
  finally { busy.value = false }
}
</script>
<template>
  <Dialog v-model:open="opened">
    <DialogContent class="sm:max-w-xl p-0 gap-0 max-h-[90vh] overflow-y-auto">
      <DialogHeader class="px-6 pt-6 pb-5 border-b border-border/50">
        <DialogTitle>{{ subject ? '编辑主体' : '新建主体' }}</DialogTitle>
        <DialogDescription :class="subject ? '' : 'sr-only'">{{ subject ? '主体资料供所有关联图片分析时引用。' : '名称、分类和描述' }}</DialogDescription>
      </DialogHeader>
      <form id="subject-editor" class="px-6 py-5 space-y-5" @submit.prevent="save">
        <fieldset :disabled="busy" class="space-y-5 disabled:opacity-70">
          <div class="grid sm:grid-cols-[1fr_148px] gap-4">
            <div class="space-y-2 relative">
              <label for="subject-name" class="text-sm font-medium">名称 <span class="text-muted-foreground">*</span></label>
              <Input id="subject-name" v-model="name" required maxlength="50" autocomplete="off" placeholder="主体名称" @focus="nameFocused = true" @blur="nameFocused = false" @keydown.escape.stop="nameFocused = false" />
              <div v-if="nameFocused && nameOptions.length" class="absolute top-full mt-1 z-50 w-full rounded-lg border border-border bg-popover shadow-lg p-1" aria-label="已有名称建议">
                <button v-for="tag in nameOptions" :key="tag.id" type="button" class="w-full flex items-center justify-between rounded-md px-3 py-2 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" @mousedown.prevent @click="chooseName(tag)"><span class="flex items-center gap-2"><TagIcon class="w-3.5 h-3.5 text-muted-foreground" />{{ tag.name }}</span><span class="text-xs text-muted-foreground">已有标签</span></button>
              </div>
            </div>
            <div class="space-y-2"><label for="subject-category" class="text-sm font-medium">分类 <span class="text-muted-foreground">*</span></label><Select v-model="category"><SelectTrigger id="subject-category" class="w-full" aria-required="true" aria-label="所属分类"><SelectValue placeholder="选择分类" /></SelectTrigger><SelectContent><SelectItem v-for="item in categories || []" :key="item.id" :value="String(item.id)">{{ item.name }}</SelectItem></SelectContent></Select></div>
          </div>
          <p v-if="!subject" class="text-xs text-muted-foreground">创建后关联所有带有同名标签的图片。</p>
          <p v-if="duplicate" class="text-xs text-amber-600 dark:text-amber-400" role="alert">“{{ duplicate.name }}”已创建主体，请返回列表编辑已有主体。</p>

          <div class="space-y-2"><label for="subject-alias" class="text-sm font-medium">别名 <span class="font-normal text-muted-foreground">可选</span></label><div v-if="aliases.length" class="flex flex-wrap gap-1.5"><button v-for="alias in aliases" :key="alias" type="button" class="inline-flex items-center gap-1.5 rounded-md bg-muted/60 border border-border/40 px-2 py-1 text-xs hover:bg-muted" :aria-label="`移除别名 ${alias}`" @click="aliases = aliases.filter(n => n !== alias)">{{ alias }}<X class="w-3 h-3 text-muted-foreground" /></button></div><div class="flex gap-2"><Input id="subject-alias" v-model="aliasInput" placeholder="输入别名，回车添加" @keydown.enter.prevent="addAliases" /><Button type="button" size="icon" variant="outline" :disabled="!aliasInput.trim()" aria-label="添加别名" @click="addAliases"><Plus class="w-4 h-4" /></Button></div></div>
          <div class="space-y-2"><label for="subject-definition" class="text-sm font-medium">描述 <span class="font-normal text-muted-foreground">可选</span></label><textarea id="subject-definition" v-model="description" maxlength="1000" rows="4" placeholder="外观、标记等特征" class="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y" /><div class="flex justify-between text-xs text-muted-foreground"><span /><span>{{ description.length }}/1000</span></div></div>
          <label v-if="subject" class="flex items-center gap-2 text-sm"><Checkbox :model-value="active" @update:model-value="active = $event === true" />启用</label>
        </fieldset>
      </form>
      <DialogFooter class="px-6 py-4 border-t border-border/50 bg-muted/10"><Button type="button" variant="ghost" :disabled="busy" @click="opened = false">取消</Button><Button type="submit" form="subject-editor" :disabled="!canSave"><Loader2 v-if="busy" class="w-4 h-4 mr-1.5 animate-spin" /><template v-else><Check v-if="subject" class="w-4 h-4 mr-1.5" /><Plus v-else class="w-4 h-4 mr-1.5" /></template>{{ subject ? '保存' : '创建' }}</Button></DialogFooter>
    </DialogContent>
  </Dialog>
</template>
