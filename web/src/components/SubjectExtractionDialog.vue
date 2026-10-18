<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import apiClient from '@/api/client'
import type { SubjectTemplate } from '@/api/queries/subjects'
import type { SubjectResponse } from '@/types'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError } from '@/utils/notify'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import SubjectTemplatesDialog from './SubjectTemplatesDialog.vue'
import { Check, ChevronLeft, ChevronRight, Loader2, Search, X } from 'lucide-vue-next'
import { useTaskFeedback } from '@/composables/useTaskFeedback'

type ReferenceImage = { id: number; image_url: string; description: string | null }
type ImagePage = { data: ReferenceImage[]; total: number; pages: number }
const props = defineProps<{ open: boolean; subject: SubjectResponse | null }>()
const emit = defineEmits<{ 'update:open': [boolean]; submitted: [taskId: string] }>()
const busy = ref(false), loading = ref(false), initializing = ref(false), initialized = ref(false)
const opened = computed({ get: () => props.open, set: value => { if (!busy.value) emit('update:open', value) } })
const templates = ref<SubjectTemplate[]>([])
const selected = ref<ReferenceImage[]>([])
const images = ref<ImagePage>({ data: [], total: 0, pages: 0 })
const keyword = ref(''), page = ref(1), maxImages = ref(3)
const rules = ref<{ template_id: number; text: string }[]>([])
const custom = ref(''), background = ref(''), preview = ref('')
const loadError = ref(''), submitError = ref(''), alreadyQueued = ref(false), templatesOpen = ref(false)
const taskFeedback = useTaskFeedback()
const titleElement = ref<HTMLElement | null>(null)
function focusTitle(event: Event) { event.preventDefault(); titleElement.value?.focus() }
let generation = 0, dialogGeneration = 0, searchTimer: ReturnType<typeof setTimeout> | undefined
const selectedIds = computed(() => new Set(selected.value.map(image => image.id)))
const ready = computed(() => !!props.subject?.is_active && selected.value.length > 0 && selected.value.length <= maxImages.value && initialized.value && !initializing.value && !loadError.value && !alreadyQueued.value)
const request = computed(() => ({
  samples: selected.value.map(image => ({ image_id: image.id, role: 'positive', target: '' })),
  rules: rules.value, custom_supplement: custom.value, identity_background: background.value,
}))
watch(request, () => { preview.value = '' }, { deep: true })
async function loadImages() {
  const run = ++generation
  if (!props.open || !props.subject) return
  loading.value = true; loadError.value = ''
  try {
    const { data } = await apiClient.get<ImagePage>(`/subjects/${props.subject.id}/reference-images`, { params: { page: page.value, size: 12, keyword: keyword.value.trim() } })
    if (run === generation && props.open) images.value = data
  } catch (e) { if (run === generation) loadError.value = getErrorMessage(e) }
  finally { if (run === generation) loading.value = false }
}
async function loadTemplates() {
  try { templates.value = (await apiClient.get<SubjectTemplate[]>('/subjects/templates')).data }
  catch (e) { notifyError(getErrorMessage(e)) }
}
async function initialize() {
  const dialogRun = ++dialogGeneration
  initialized.value = false
  clearTimeout(searchTimer); ++generation
  selected.value = []; images.value = { data: [], total: 0, pages: 0 }; keyword.value = ''; page.value = 1
  custom.value = ''; background.value = ''; rules.value = []; preview.value = ''; submitError.value = ''; alreadyQueued.value = false; loadError.value = ''
  initializing.value = true
  const subjectId = props.subject?.id
  try {
    const [settings, list] = await Promise.all([
      apiClient.get<{ max_images: number }>('/subjects/extraction-settings'), apiClient.get<SubjectTemplate[]>('/subjects/templates'),
    ])
    if (dialogRun !== dialogGeneration || !props.open || props.subject?.id !== subjectId) return
    if (!Number.isInteger(settings.data.max_images) || settings.data.max_images < 1 || settings.data.max_images > 3) throw new Error('提炼图片上限配置无效')
    maxImages.value = settings.data.max_images; templates.value = list.data
    const category = props.subject?.category_tag_name || ''
    const names = /动物|宠物/.test(category) ? ['动物个体'] : /建筑|地点|风景/.test(category) ? ['地点与建筑'] : /产品|物品|商品/.test(category) ? ['物品与产品'] : /角色|动漫|游戏|二次元/.test(category) ? ['虚构角色'] : []
    if (/表情|Q版/i.test(category)) names.push('Q版与表情包')
    rules.value = templates.value.filter(t => t.is_builtin && t.is_active && names.includes(t.name)).map(t => ({ template_id: t.id, text: t.content }))
    initialized.value = true
    await loadImages()
  } catch (e) { if (dialogRun === dialogGeneration && props.open && props.subject?.id === subjectId) loadError.value = getErrorMessage(e) }
  finally { if (dialogRun === dialogGeneration && props.subject?.id === subjectId) initializing.value = false }
}
watch(() => [props.open, props.subject?.id] as const, ([open]) => {
  if (open) initialize()
  else { ++generation; ++dialogGeneration; clearTimeout(searchTimer) }
})
watch(keyword, () => {
  if (initializing.value || !props.open) return
  clearTimeout(searchTimer); ++generation; loading.value = true
  searchTimer = setTimeout(() => { page.value = 1; loadImages() }, 300)
})
function changePage(value: number) { clearTimeout(searchTimer); page.value = value; loadImages() }
function toggleImage(image: ReferenceImage) {
  if (busy.value) return
  if (selectedIds.value.has(image.id)) selected.value = selected.value.filter(item => item.id !== image.id)
  else if (selected.value.length < maxImages.value) selected.value.push(image)
}
function toggleRule(template: SubjectTemplate, checked: boolean) {
  rules.value = rules.value.filter(rule => rule.template_id !== template.id)
  if (checked) rules.value.push({ template_id: template.id, text: template.content })
}
async function showPreview() {
  if (!ready.value || busy.value || !props.subject) return
  busy.value = true
  try { preview.value = (await apiClient.post(`/subjects/${props.subject.id}/extract/preview`, request.value)).data.prompt }
  catch (e) { notifyError(getErrorMessage(e)) }
  finally { busy.value = false }
}
async function extract() {
  if (!ready.value || !props.subject || busy.value) return
  submitError.value = ''; busy.value = true
  try {
    const { data } = await apiClient.post<{ task_id: string }>(`/subjects/${props.subject.id}/extract`, request.value)
    taskFeedback('主体提炼已加入队列', data.task_id)
    emit('submitted', data.task_id); emit('update:open', false)
  } catch (e) {
    alreadyQueued.value = (e as { response?: { status?: number } }).response?.status === 409
    submitError.value = getErrorMessage(e); notifyError(submitError.value)
  } finally { busy.value = false }
}
</script>
<template>
  <Dialog v-model:open="opened">
    <DialogContent @open-auto-focus="focusTitle" class="sm:max-w-3xl p-0 gap-0 max-h-[90dvh] overflow-hidden flex flex-col">
      <DialogHeader class="px-5 py-4 border-b border-border/50">
        <DialogTitle><span ref="titleElement" tabindex="-1" class="outline-none">提炼 {{ subject?.name }}</span></DialogTitle>
        <DialogDescription>从“{{ subject?.primary_tag_name }}”标签中选择参考图，最多 {{ maxImages }} 张。</DialogDescription>
      </DialogHeader>
      <div class="px-5 py-4 overflow-y-auto space-y-4">
        <div class="flex items-center justify-between gap-3"><div class="relative flex-1"><Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" /><Input v-model="keyword" aria-label="筛选参考图片" placeholder="搜索描述或图片编号" class="pl-9" :disabled="busy || initializing" /></div><span class="text-xs text-muted-foreground shrink-0">已选 {{ selected.length }} / {{ maxImages }}</span></div>
        <div v-if="selected.length" class="rounded-xl border border-border/50 bg-muted/20 px-3 py-3 space-y-2">
          <div class="flex gap-3"><div v-for="(image, index) in selected" :key="image.id" class="relative w-20 shrink-0"><img :src="image.image_url" :alt="`已选参考图 #${image.id}`" class="h-16 w-full rounded-md object-cover bg-muted" /><span class="absolute bottom-0 left-0 rounded-tr-md rounded-bl-md bg-black/70 px-1.5 text-[10px] text-white">{{ index === 0 ? '封面' : index + 1 }}</span><button :disabled="busy" :aria-label="`移除参考图 ${image.id}`" class="absolute -right-1 -top-1 rounded-full bg-background border border-border p-0.5" @click="toggleImage(image)"><X class="h-3 w-3" /></button></div></div>
          <p class="text-xs text-muted-foreground">第一张作为主体封面。仅提交本次所选图片。</p>
        </div>
        <div v-if="loadError" class="text-sm text-destructive" role="alert">{{ loadError }}<Button variant="ghost" size="sm" @click="initialized ? loadImages() : initialize()">重试</Button></div>
        <div v-if="loading || initializing" class="h-44 flex items-center justify-center text-muted-foreground"><Loader2 class="h-5 w-5 animate-spin" /></div>
        <div v-else-if="!images.data.length" class="py-14 text-sm text-muted-foreground text-center">{{ keyword ? '没有匹配的图片' : '暂无带有该标签的图片' }}</div>
        <div v-else class="grid grid-cols-3 sm:grid-cols-4 gap-2">
          <button v-for="image in images.data" :key="image.id" :aria-label="`选择参考图 ${image.id}`" :aria-pressed="selectedIds.has(image.id)" :disabled="busy || (!selectedIds.has(image.id) && selected.length >= maxImages)" class="relative aspect-square overflow-hidden rounded-lg border-2 transition-colors disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" :class="selectedIds.has(image.id) ? 'border-primary' : 'border-transparent bg-muted/30 hover:border-border'" @click="toggleImage(image)">
            <img :src="image.image_url" :alt="image.description || `图片 #${image.id}`" class="h-full w-full object-cover" loading="lazy" />
            <span class="absolute top-1.5 right-1.5 h-5 w-5 rounded-full flex items-center justify-center" :class="selectedIds.has(image.id) ? 'bg-primary text-primary-foreground' : 'bg-black/30 border border-white/70'"><Check v-if="selectedIds.has(image.id)" class="h-3.5 w-3.5" /></span><span class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent text-white text-[10px] text-left px-2 py-1">#{{ image.id }}</span>
          </button>
        </div>
        <div v-if="images.total" class="flex justify-between items-center text-xs text-muted-foreground"><span>{{ images.total }} 张图片</span><div class="flex items-center gap-2"><Button variant="ghost" size="icon" class="h-7 w-7" aria-label="上一页参考图" :disabled="page <= 1 || loading || busy" @click="changePage(page - 1)"><ChevronLeft class="h-4 w-4" /></Button><span>{{ page }} / {{ images.pages }}</span><Button variant="ghost" size="icon" class="h-7 w-7" aria-label="下一页参考图" :disabled="page >= images.pages || loading || busy" @click="changePage(page + 1)"><ChevronRight class="h-4 w-4" /></Button></div></div>
        <label class="block text-sm font-medium">补充要求<textarea v-model="custom" :disabled="busy" maxlength="6000" rows="2" placeholder="需要特别注意的特征（可选）" class="block w-full rounded-md border border-input px-3 py-2 text-sm font-normal bg-transparent mt-2 placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" /></label>
        <details class="border-t border-border/50 pt-3">
          <summary class="text-xs text-muted-foreground cursor-pointer">更多设置</summary>
          <fieldset :disabled="busy" class="space-y-4 mt-4">
            <label class="block text-sm">背景资料<textarea v-model="background" maxlength="2000" rows="2" placeholder="来源、身份等已知资料（可选）" class="block w-full border border-input rounded-md p-2 bg-transparent mt-2" /></label>
            <div class="flex justify-between items-center"><span class="text-sm font-medium">提炼规则</span><Button variant="ghost" size="sm" @click="templatesOpen = true">管理规则</Button></div>
            <div v-for="t in templates.filter(t => t.is_active)" :key="t.id" class="space-y-2"><label class="flex gap-2 text-sm"><input type="checkbox" :checked="rules.some(r => r.template_id === t.id)" @change="toggleRule(t, ($event.target as HTMLInputElement).checked)" />{{ t.name }}</label><textarea v-for="rule in rules.filter(r => r.template_id === t.id)" :key="rule.template_id" v-model="rule.text" :aria-label="`补充规则 ${t.name}`" maxlength="6000" rows="2" class="w-full border border-input rounded-md p-2 text-sm bg-transparent" /></div>
            <Button variant="ghost" size="sm" :disabled="!ready" @click="showPreview">查看请求内容</Button><pre v-if="preview" class="text-xs whitespace-pre-wrap max-h-64 overflow-auto bg-muted rounded-lg p-3">{{ preview }}</pre>
          </fieldset>
        </details>
        <p v-if="submitError" class="text-sm text-destructive" role="alert">{{ submitError }}</p>
      </div>
      <div class="px-5 py-4 border-t border-border/50 flex items-center gap-2">
        <RouterLink v-if="alreadyQueued" to="/tasks" class="mr-auto text-xs underline text-muted-foreground" @click="opened = false">查看任务</RouterLink><p v-else class="mr-auto text-xs text-muted-foreground">完成后直接更新描述，保留最近三份历史</p>
        <Button variant="ghost" :disabled="busy" @click="opened = false">取消</Button><Button :disabled="busy || !ready" @click="extract"><Loader2 v-if="busy" class="w-4 h-4 mr-1.5 animate-spin" />{{ busy ? '提交中…' : alreadyQueued ? '已有提炼任务' : '提炼并更新' }}</Button>
      </div>
    </DialogContent>
  </Dialog>
  <SubjectTemplatesDialog v-model:open="templatesOpen" @updated="loadTemplates" />
</template>
