<script setup lang="ts">
import { computed, ref } from 'vue'
import { useTaskFeedback } from '@/composables/useTaskFeedback'
import { useCategories, useSubjects, useTask, type SubjectsQueryParams } from '@/api/queries'
import apiClient from '@/api/client'
import type { SubjectResponse } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import SubjectEditorDialog from '@/components/SubjectEditorDialog.vue'
import SubjectVersionsDialog from '@/components/SubjectVersionsDialog.vue'
import SubjectTemplatesDialog from '@/components/SubjectTemplatesDialog.vue'
import SubjectExtractionDialog from '@/components/SubjectExtractionDialog.vue'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError, notifyInfo } from '@/utils/notify'
import { History, Check, Circle, ImagePlus, LayoutGrid, List, Loader2, Pencil, Plus, RefreshCw, Search, Settings2, Users, X } from 'lucide-vue-next'

const taskFeedback = useTaskFeedback()
const params = ref<SubjectsQueryParams>({ page: 1, size: 500, active_only: false })
const { data: subjects, isLoading, isError, refetch, isFetching } = useSubjects(params)
const { data: categories } = useCategories()
const keyword = ref(''), categoryFilter = ref('all'), stateFilter = ref('active')
const view = ref<'grid' | 'list'>('grid')
const editorOpen = ref(false), templatesOpen = ref(false), versionsOpen = ref(false)
const editing = ref<SubjectResponse | null>(null)
const extracting = ref<SubjectResponse | null>(null)
const extractionOpen = ref(false)
const extractionTaskId = ref<string | null>(null)
useTask(extractionTaskId, computed(() => !!extractionTaskId.value))
function submitted(taskId: string) { extractionTaskId.value = taskId; refetch() }

function openExtraction(subject: SubjectResponse) { extracting.value = subject; extractionOpen.value = true }
const versionSubjectId = ref<number | null>(null)
const filtered = computed(() => (subjects.value || []).filter(item => {
  const search = keyword.value.trim().toLocaleLowerCase()
  return (!search || [item.name, item.description || '', ...(item.aliases || [])].join(' ').toLocaleLowerCase().includes(search))
    && (categoryFilter.value === 'all' || item.category_tag_id === Number(categoryFilter.value))
    && (stateFilter.value === 'all' || item.is_active === (stateFilter.value === 'active'))
}))
const hasFilters = computed(() => !!keyword.value.trim() || categoryFilter.value !== 'all' || stateFilter.value !== 'active')
function resetFilters() { keyword.value = ''; categoryFilter.value = 'all'; stateFilter.value = 'active' }
function openEditor(subject: SubjectResponse | null = null) { editing.value = subject; editorOpen.value = true }
function openVersions(subject: SubjectResponse) { versionSubjectId.value = subject.id; versionsOpen.value = true }
const reanalyze = ref<SubjectResponse | null>(null)
const count = ref(0), reanalyzeBusy = ref(false), previewingId = ref<number | null>(null)
async function previewReanalysis(subject: SubjectResponse) {
  if (previewingId.value !== null || reanalyzeBusy.value) return
  previewingId.value = subject.id
  try { const { data } = await apiClient.get<{ count: number }>(`/subjects/${subject.id}/reanalyze`); count.value = data.count; reanalyze.value = subject }
  catch (e) { notifyError(getErrorMessage(e)) }
  finally { previewingId.value = null }
}
async function reanalyzeRelated() {
  if (!reanalyze.value || reanalyzeBusy.value) return
  reanalyzeBusy.value = true
  try {
    const { data } = await apiClient.post<{ added: number; upgraded: number; existing: number }>(`/subjects/${reanalyze.value.id}/reanalyze`, null, { params: { expected_count: count.value } })
    const queued = data.added + data.upgraded
    if (queued) taskFeedback(`已新增 ${data.added} 个分析任务${data.upgraded ? `，更新 ${data.upgraded} 个待处理任务` : ''}${data.existing ? `，复用 ${data.existing} 个待处理任务` : ''}`)
    else if (data.existing) taskFeedback('关联图片已有重分析任务')
    else notifyInfo('暂无需要重分析的关联图片')
    reanalyze.value = null
  } catch (e) {
    notifyError(getErrorMessage(e))
    if ((e as { response?: { status?: number } }).response?.status === 409) { reanalyze.value = null; refetch() }
  }
  finally { reanalyzeBusy.value = false }
}
</script>
<template>
  <div class="min-h-screen pb-20">
    <main class="py-4 px-4 md:py-6 md:px-6 max-w-[1800px] mx-auto">
      <div class="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div class="flex sm:block items-start justify-between gap-3"><div><h1 class="text-xl font-bold text-foreground flex items-center gap-2"><Users class="w-5 h-5 text-primary" />主体管理</h1><p class="text-sm text-muted-foreground mt-1">{{ isLoading ? '加载中…' : `${filtered.length} 个主体` }}</p></div><Button size="sm" class="sm:hidden h-9 gap-1.5 shrink-0" @click="openEditor()"><Plus class="w-4 h-4" />新建主体</Button></div>
        <div class="flex items-center gap-2 flex-wrap">
          <div class="flex items-center bg-muted/40 p-1 rounded-lg border border-border/40">
            <Button variant="ghost" size="sm" class="h-7 px-2 sm:px-3 text-xs rounded-md" :class="view === 'grid' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground'" aria-label="卡片视图" :aria-pressed="view === 'grid'" @click="view = 'grid'"><LayoutGrid class="w-3.5 h-3.5 sm:mr-1.5" /><span class="hidden sm:inline">卡片</span></Button><div class="w-px h-3 bg-border/50 mx-1" /><Button variant="ghost" size="sm" class="h-7 px-2 sm:px-3 text-xs rounded-md" :class="view === 'list' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground'" aria-label="列表视图" :aria-pressed="view === 'list'" @click="view = 'list'"><List class="w-3.5 h-3.5 sm:mr-1.5" /><span class="hidden sm:inline">列表</span></Button>
          </div>
          <Button variant="ghost" size="icon" class="h-9 w-8 sm:w-9 text-muted-foreground" aria-label="刷新主体" title="刷新主体" :disabled="isFetching" @click="refetch()"><RefreshCw class="w-4 h-4" :class="isFetching && 'animate-spin'" /></Button>
          <Button variant="ghost" size="icon" class="h-9 w-8 sm:w-9 text-muted-foreground" aria-label="提炼规则" title="提炼规则" @click="templatesOpen = true"><Settings2 class="w-4 h-4" /></Button>
          <Button size="sm" class="hidden sm:inline-flex h-9 gap-1.5" @click="openEditor()"><Plus class="w-4 h-4" />新建主体</Button>
        </div>
      </div>
      <div class="flex flex-col sm:flex-row gap-3 mb-5">
        <div class="relative flex-1"><Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" /><Input v-model="keyword" type="search" aria-label="搜索主体" placeholder="搜索主体" class="pl-9 bg-muted/20 border-border/50 shadow-none" /></div>
        <div class="flex items-center gap-2"><Select v-model="categoryFilter"><SelectTrigger class="w-full sm:w-[140px] h-9 text-xs" aria-label="筛选所属分类"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">全部分类</SelectItem><SelectItem v-for="category in categories || []" :key="category.id" :value="String(category.id)">{{ category.name }}</SelectItem></SelectContent></Select>
          <Select v-model="stateFilter"><SelectTrigger class="w-full sm:w-[120px] h-9 text-xs" aria-label="筛选主体状态"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="active">已启用</SelectItem><SelectItem value="all">全部状态</SelectItem><SelectItem value="inactive">已停用</SelectItem></SelectContent></Select>
          <Button v-if="hasFilters" variant="ghost" size="icon" class="h-9 w-9 shrink-0 text-muted-foreground" aria-label="清除筛选" @click="resetFilters"><X class="w-4 h-4" /></Button>
        </div>
      </div>
      <div v-if="isLoading" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4" aria-label="正在加载主体"><div v-for="i in 6" :key="i" class="h-56 rounded-xl border border-border/40 bg-muted/30 animate-pulse" /></div>
      <div v-else-if="isError" class="rounded-xl border border-dashed border-border/60 py-16 text-center"><p class="text-sm mb-4">主体资料暂时无法加载</p><Button variant="outline" size="sm" @click="refetch()">重试</Button></div>
      <div v-else-if="!filtered.length" class="rounded-xl border border-dashed border-border/60 bg-muted/10 py-20 px-5 text-center"><div class="w-14 h-14 mx-auto mb-5 rounded-2xl border border-border/50 bg-muted/40 flex items-center justify-center"><Search v-if="hasFilters" class="w-6 h-6 text-muted-foreground" /><Users v-else class="w-6 h-6 text-muted-foreground" /></div><h2 class="text-base font-medium">{{ hasFilters || subjects?.length ? '没有找到匹配的主体' : '暂无主体' }}</h2><Button v-if="hasFilters || subjects?.length" variant="outline" size="sm" class="mt-5" @click="resetFilters(); stateFilter = 'all'">查看全部主体</Button><Button v-else size="sm" class="mt-5 gap-1.5" @click="openEditor()"><Plus class="w-4 h-4" />新建主体</Button></div>
      <div v-else :class="view === 'grid' ? 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4' : 'rounded-xl border border-border/50 divide-y divide-border/50 overflow-hidden'">
        <article v-for="item in filtered" :key="item.id" :class="view === 'grid' ? 'group rounded-xl border border-border/50 bg-card/50 hover:bg-card hover:border-border transition-colors flex flex-col min-w-0' : 'group flex flex-wrap items-center gap-4 px-4 py-4 bg-card/20 hover:bg-muted/20 transition-colors'" :aria-label="`主体 ${item.name}`">
          <div :class="view === 'grid' ? 'px-5 pt-5 flex items-start justify-between gap-3' : 'flex items-center gap-3 min-w-0 w-full sm:w-[220px] shrink-0'">
            <div class="flex items-center gap-3 min-w-0 text-left"><span class="w-12 h-12 rounded-xl bg-muted/50 border border-border/40 flex items-center justify-center shrink-0 text-sm font-semibold text-muted-foreground overflow-hidden"><img v-if="item.cover_image_url" :src="item.cover_image_url" :alt="`${item.name} 封面`" class="w-full h-full object-cover" /><span v-else>{{ item.name.slice(0, 2) }}</span></span><span class="min-w-0"><span class="block truncate text-sm font-semibold group-hover:text-foreground">{{ item.name }}</span><span class="mt-1 block text-xs text-muted-foreground">{{ item.category_tag_name }}<span v-if="view === 'list' && !item.is_active" class="ml-2">· 已停用</span></span></span></div>
            <span v-if="view === 'grid'" class="inline-flex items-center gap-1 text-[11px] rounded-full px-2 py-0.5 shrink-0" :class="item.is_active ? 'bg-muted/60 text-muted-foreground' : 'border border-border/60 text-muted-foreground'"><Check v-if="item.is_active" class="w-3 h-3" /><Circle v-else class="w-2.5 h-2.5" />{{ item.is_active ? '已启用' : '已停用' }}</span>
          </div>
          <div :class="view === 'grid' ? 'px-5 pt-4 pb-5 flex-1 space-y-3' : 'flex-1 min-w-[180px] space-y-1'">
            <p class="text-sm leading-relaxed line-clamp-3" :class="item.description ? 'text-muted-foreground' : 'text-muted-foreground/60'">{{ item.description || '暂无描述' }}</p>
            <div v-if="item.aliases?.length" class="flex flex-wrap gap-1.5"><span v-for="alias in item.aliases.slice(0, 3)" :key="alias" class="max-w-[150px] truncate px-1.5 py-0.5 rounded bg-muted/50 text-[11px] text-muted-foreground">{{ alias }}</span><span v-if="item.aliases.length > 3" class="text-[11px] text-muted-foreground">+{{ item.aliases.length - 3 }}</span></div>
          </div>
          <div :class="view === 'grid' ? 'border-t border-border/40 px-3 py-2.5 flex items-center justify-between gap-0.5 flex-wrap' : 'flex items-center gap-1 ml-auto'">
            <Button variant="outline" size="sm" class="h-8 px-2 text-xs gap-1.5" :aria-label="`编辑主体 ${item.name}`" @click="openEditor(item)"><Pencil class="w-3.5 h-3.5" />编辑</Button>
            <Button variant="ghost" size="sm" class="h-8 px-2 text-xs gap-1.5 text-muted-foreground" :disabled="!item.is_active" :aria-label="`提炼主体 ${item.name}`" @click="openExtraction(item)"><ImagePlus class="w-3.5 h-3.5" />提炼</Button>
            <Button variant="ghost" size="sm" class="h-8 px-2 text-xs text-muted-foreground hover:text-foreground gap-1.5" @click="openVersions(item)"><History class="w-3.5 h-3.5" />历史</Button>
            <div class="flex items-center ml-auto"><Button variant="ghost" size="sm" class="h-8 px-2 gap-1.5 text-xs text-muted-foreground" :aria-label="`用 ${item.name} 更新关联图片描述${item.image_count !== undefined ? `，共 ${item.image_count} 张` : ''}`" :title="`引用主体资料，重新生成${item.image_count !== undefined ? `全部 ${item.image_count} 张` : '全部'}已关联图片的描述`" :disabled="previewingId !== null" @click="previewReanalysis(item)"><Loader2 v-if="previewingId === item.id" class="w-3.5 h-3.5 animate-spin" /><RefreshCw v-else class="w-3.5 h-3.5" /><span>更新描述<span v-if="item.image_count !== undefined"> · {{ item.image_count }} 张</span></span></Button></div>
          </div>
        </article>
      </div>
      <p v-if="(subjects?.length || 0) >= 500" class="mt-5 text-xs text-muted-foreground">当前加载前500个主体。</p>
    </main>
    <SubjectEditorDialog v-model:open="editorOpen" :subject="editing" :subjects="subjects || []" :category-id="categoryFilter !== 'all' ? Number(categoryFilter) : null" @saved="refetch()" />
    <SubjectVersionsDialog v-model:open="versionsOpen" :subject-id="versionSubjectId" @updated="refetch()" />
    <SubjectTemplatesDialog v-model:open="templatesOpen" />
    <SubjectExtractionDialog v-model:open="extractionOpen" :subject="extracting" @submitted="submitted" />
    <Dialog :open="!!reanalyze" @update:open="!$event && !reanalyzeBusy && (reanalyze = null)"><DialogContent class="sm:max-w-md"><DialogHeader><DialogTitle>更新关联图片描述</DialogTitle><DialogDescription>引用“{{ reanalyze?.name }}”的当前资料，更新全部已关联图片。</DialogDescription></DialogHeader><div class="space-y-2 py-2"><p class="text-base font-medium">将更新 {{ count }} 张图片</p><p class="text-sm text-muted-foreground">{{ count ? `最多新增 ${count} 个分析任务，已有待处理任务会复用。` : '暂无关联图片。' }}</p><p v-if="count" class="text-sm text-muted-foreground">完成后直接更新，替换前保留最近三份历史。</p></div><DialogFooter><Button variant="ghost" :disabled="reanalyzeBusy" @click="reanalyze = null">取消</Button><Button :disabled="reanalyzeBusy || !count" @click="reanalyzeRelated"><Loader2 v-if="reanalyzeBusy" class="w-4 h-4 mr-1.5 animate-spin" />{{ reanalyzeBusy ? '提交中…' : `确认更新 ${count} 张` }}</Button></DialogFooter></DialogContent></Dialog>
  </div>
</template>
