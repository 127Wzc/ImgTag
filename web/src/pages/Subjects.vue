<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import {
  useCategories,
  useCreateSubject,
  useSearchTags,
  useSubjects,
  useTagsByLevel,
  useUpdateSubject,
  type SubjectsQueryParams,
} from '@/api/queries'
import type { SubjectResponse, Tag } from '@/types'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError } from '@/utils/notify'
import { Loader2, RefreshCw, Plus, Users, Pencil, X } from 'lucide-vue-next'

interface CreateSubjectFormState {
  category_tag_id: number | null
  primary_tag_id: number | null
  alias_tag_ids: number[]
  description: string
}

interface EditSubjectFormState {
  category_tag_id: number | null
  primary_tag_id: number | null
  alias_tag_ids: number[]
  description: string
  is_active: boolean
}

const params = ref<SubjectsQueryParams>({
  page: 1,
  size: 300,
  active_only: true,
})

const keywordInput = ref('')
const activeOnly = ref(true)
const categoryFilter = ref<'all' | number>('all')

const { data: subjects, isLoading, refetch } = useSubjects(params)
const { data: categoryOptions } = useCategories()
const level2 = ref(2)
const { data: level2Tags } = useTagsByLevel(level2, 1000)
const createSubjectMutation = useCreateSubject()
const updateSubjectMutation = useUpdateSubject()

const createForm = ref<CreateSubjectFormState>({
  category_tag_id: null,
  primary_tag_id: null,
  alias_tag_ids: [],
  description: '',
})
const createPrimaryKeyword = ref('')
const createAliasKeyword = ref('')
const createPrimaryKeywordNormalized = computed(() => createPrimaryKeyword.value.trim())
const createAliasKeywordNormalized = computed(() => createAliasKeyword.value.trim())
const { data: createPrimarySearchTags, isFetching: isCreatePrimarySearching } = useSearchTags(createPrimaryKeywordNormalized, level2, 200)
const { data: createAliasSearchTags, isFetching: isCreateAliasSearching } = useSearchTags(createAliasKeywordNormalized, level2, 200)

const editOpen = ref(false)
const editingSubjectId = ref<number | null>(null)
const editForm = ref<EditSubjectFormState>({
  category_tag_id: null,
  primary_tag_id: null,
  alias_tag_ids: [],
  description: '',
  is_active: true,
})
const editPrimaryKeyword = ref('')
const editAliasKeyword = ref('')
const editPrimaryKeywordNormalized = computed(() => editPrimaryKeyword.value.trim())
const editAliasKeywordNormalized = computed(() => editAliasKeyword.value.trim())
const { data: editPrimarySearchTags, isFetching: isEditPrimarySearching } = useSearchTags(editPrimaryKeywordNormalized, level2, 200)
const { data: editAliasSearchTags, isFetching: isEditAliasSearching } = useSearchTags(editAliasKeywordNormalized, level2, 200)

const tagNameMap = computed(() => {
  const map = new Map<number, string>()
  const sources = [
    ...(level2Tags.value || []),
    ...(createPrimarySearchTags.value || []),
    ...(createAliasSearchTags.value || []),
    ...(editPrimarySearchTags.value || []),
    ...(editAliasSearchTags.value || []),
  ]
  for (const tag of sources) map.set(tag.id, tag.name)
  return map
})
const tagMetaMap = computed(() => {
  const map = new Map<number, Tag>()
  const sources = [
    ...(level2Tags.value || []),
    ...(createPrimarySearchTags.value || []),
    ...(createAliasSearchTags.value || []),
    ...(editPrimarySearchTags.value || []),
    ...(editAliasSearchTags.value || []),
  ]
  for (const tag of sources) map.set(tag.id, tag)
  return map
})
const categoryIdSet = computed(() => new Set((categoryOptions.value || []).map((c) => c.id)))
const categoryNameMap = computed(() => {
  const map = new Map<number, string>()
  for (const cat of categoryOptions.value || []) map.set(cat.id, cat.name)
  return map
})

function normalizeKeyword(input: string): string {
  return input.trim().toLowerCase()
}

function getTagName(tagId: number): string {
  return tagNameMap.value.get(tagId) || `#${tagId}`
}

function getCategoryName(categoryId: number | null | undefined): string {
  if (!categoryId) return ''
  return categoryNameMap.value.get(categoryId) || `#${categoryId}`
}

function mergeTagsUnique(...groups: Tag[][]): Tag[] {
  const map = new Map<number, Tag>()
  for (const group of groups) {
    for (const tag of group) {
      if (!map.has(tag.id)) {
        map.set(tag.id, tag)
      }
    }
  }
  return Array.from(map.values())
}

function buildCandidateLevel2Tags(
  sourceTags: Tag[],
  categoryTagId: number | null,
  keyword: string,
  excludeTagId?: number | null,
): Tag[] {
  const normalized = normalizeKeyword(keyword)
  const candidates = sourceTags
    .filter((tag) => {
      if (!categoryTagId) return true
      return tag.parent_id === categoryTagId || tag.parent_id === null
    })
    .filter((tag) => !excludeTagId || tag.id !== excludeTagId)
    .filter((tag) => !normalized || tag.name.toLowerCase().includes(normalized))
    .sort((a, b) => {
      const aExactParent = categoryTagId && a.parent_id === categoryTagId ? 0 : 1
      const bExactParent = categoryTagId && b.parent_id === categoryTagId ? 0 : 1
      if (aExactParent !== bExactParent) return aExactParent - bExactParent
      return a.name.localeCompare(b.name, 'zh-Hans-CN')
    })

  return candidates.slice(0, 200)
}

const createPrimarySourceTags = computed(() => {
  if (!createForm.value.category_tag_id && !createPrimaryKeywordNormalized.value) return []
  if (!createPrimaryKeywordNormalized.value) return level2Tags.value || []
  return mergeTagsUnique(createPrimarySearchTags.value || [], level2Tags.value || [])
})
const createAliasSourceTags = computed(() => {
  if (!createForm.value.category_tag_id && !createAliasKeywordNormalized.value) return []
  if (!createAliasKeywordNormalized.value) return level2Tags.value || []
  return mergeTagsUnique(createAliasSearchTags.value || [], level2Tags.value || [])
})
const editPrimarySourceTags = computed(() => {
  if (!editForm.value.category_tag_id && !editPrimaryKeywordNormalized.value) return []
  if (!editPrimaryKeywordNormalized.value) return level2Tags.value || []
  return mergeTagsUnique(editPrimarySearchTags.value || [], level2Tags.value || [])
})
const editAliasSourceTags = computed(() => {
  if (!editForm.value.category_tag_id && !editAliasKeywordNormalized.value) return []
  if (!editAliasKeywordNormalized.value) return level2Tags.value || []
  return mergeTagsUnique(editAliasSearchTags.value || [], level2Tags.value || [])
})

const createPrimaryOptions = computed(() =>
  buildCandidateLevel2Tags(
    createPrimarySourceTags.value,
    createForm.value.category_tag_id,
    createPrimaryKeyword.value,
  ),
)
const createAliasOptions = computed(() =>
  buildCandidateLevel2Tags(
    createAliasSourceTags.value,
    createForm.value.category_tag_id,
    createAliasKeyword.value,
    createForm.value.primary_tag_id,
  ),
)
const editPrimaryOptions = computed(() =>
  buildCandidateLevel2Tags(
    editPrimarySourceTags.value,
    editForm.value.category_tag_id,
    editPrimaryKeyword.value,
  ),
)
const editAliasOptions = computed(() =>
  buildCandidateLevel2Tags(
    editAliasSourceTags.value,
    editForm.value.category_tag_id,
    editAliasKeyword.value,
    editForm.value.primary_tag_id,
  ),
)

const createPrimaryOpen = ref(false)
const createAliasOpen = ref(false)
const editPrimaryOpen = ref(false)
const editAliasOpen = ref(false)

const createPrimaryWrap = ref<HTMLElement | null>(null)
const createAliasWrap = ref<HTMLElement | null>(null)
const editPrimaryWrap = ref<HTMLElement | null>(null)
const editAliasWrap = ref<HTMLElement | null>(null)

const showCreateDescription = ref(false)
const showEditDescription = ref(false)

function closePickersIfClickedOutside(e: MouseEvent) {
  const target = e.target as Node | null
  if (!target) return

  if (createPrimaryWrap.value && !createPrimaryWrap.value.contains(target)) createPrimaryOpen.value = false
  if (createAliasWrap.value && !createAliasWrap.value.contains(target)) createAliasOpen.value = false
  if (editPrimaryWrap.value && !editPrimaryWrap.value.contains(target)) editPrimaryOpen.value = false
  if (editAliasWrap.value && !editAliasWrap.value.contains(target)) editAliasOpen.value = false
}

onMounted(() => document.addEventListener('mousedown', closePickersIfClickedOutside))
onUnmounted(() => document.removeEventListener('mousedown', closePickersIfClickedOutside))

const canCreate = computed(
  () => !!createForm.value.category_tag_id && !!createForm.value.primary_tag_id,
)
const canSaveEdit = computed(
  () => !!editingSubjectId.value && !!editForm.value.category_tag_id && !!editForm.value.primary_tag_id,
)

const filteredSubjects = computed(() => {
  let rows = subjects.value || []
  if (categoryFilter.value !== 'all') {
    rows = rows.filter((row) => row.category_tag_id === Number(categoryFilter.value))
  }
  return rows
})

function applyFilters() {
  params.value = {
    ...params.value,
    page: 1,
    keyword: keywordInput.value.trim() || undefined,
    active_only: activeOnly.value,
  }
}

function handleCreateCategoryChange() {
  const nextCategoryId = createForm.value.category_tag_id
  if (!nextCategoryId) {
    createForm.value.primary_tag_id = null
    createForm.value.alias_tag_ids = []
    return
  }

  // 尽量保留已选项，只剔除在新分类下明确不合法（有 parent 且不匹配）的标签
  const primaryId = createForm.value.primary_tag_id
  if (primaryId) {
    const primaryTag = tagMetaMap.value.get(primaryId)
    if (primaryTag?.parent_id !== null && primaryTag?.parent_id !== undefined && primaryTag.parent_id !== nextCategoryId) {
      createForm.value.primary_tag_id = null
    }
  }

  createForm.value.alias_tag_ids = (createForm.value.alias_tag_ids || []).filter((id) => {
    const tag = tagMetaMap.value.get(id)
    if (!tag) return true
    if (tag.parent_id === null || tag.parent_id === undefined) return true
    return tag.parent_id === nextCategoryId
  })
  if (createForm.value.primary_tag_id) {
    createForm.value.alias_tag_ids = createForm.value.alias_tag_ids.filter((id) => id !== createForm.value.primary_tag_id)
  }
}

function selectCreatePrimaryTag(tag: Tag) {
  createForm.value.primary_tag_id = tag.id
  createForm.value.alias_tag_ids = createForm.value.alias_tag_ids.filter((id) => id !== tag.id)
  if (!createForm.value.category_tag_id && tag.parent_id && categoryIdSet.value.has(tag.parent_id)) {
    createForm.value.category_tag_id = tag.parent_id
  }
  createPrimaryOpen.value = false
}

function toggleCreateAlias(tagId: number) {
  if (createForm.value.alias_tag_ids.includes(tagId)) {
    createForm.value.alias_tag_ids = createForm.value.alias_tag_ids.filter((id) => id !== tagId)
    return
  }
  createForm.value.alias_tag_ids = [...createForm.value.alias_tag_ids, tagId]
}

function removeCreateAlias(tagId: number) {
  createForm.value.alias_tag_ids = createForm.value.alias_tag_ids.filter((id) => id !== tagId)
}

function clearCreatePrimary() {
  createForm.value.primary_tag_id = null
  createPrimaryKeyword.value = ''
}

function openCreatePrimary() {
  createPrimaryOpen.value = true
  createAliasOpen.value = false
}

function openCreateAlias() {
  createAliasOpen.value = true
  createPrimaryOpen.value = false
}

function openEditPrimary() {
  editPrimaryOpen.value = true
  editAliasOpen.value = false
}

function openEditAlias() {
  editAliasOpen.value = true
  editPrimaryOpen.value = false
}

async function handleCreateSubject() {
  if (!canCreate.value || createSubjectMutation.isPending.value) return

  try {
    await createSubjectMutation.mutateAsync({
      category_tag_id: Number(createForm.value.category_tag_id),
      primary_tag_id: Number(createForm.value.primary_tag_id),
      alias_tag_ids: createForm.value.alias_tag_ids,
      description: createForm.value.description.trim() || null,
    })

    createForm.value = {
      category_tag_id: createForm.value.category_tag_id,
      primary_tag_id: null,
      alias_tag_ids: [],
      description: '',
    }
    createPrimaryKeyword.value = ''
    createAliasKeyword.value = ''
    await refetch()
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  }
}

function openEditDialog(subject: SubjectResponse) {
  editingSubjectId.value = subject.id
  editForm.value = {
    category_tag_id: subject.category_tag_id,
    primary_tag_id: subject.primary_tag_id,
    alias_tag_ids: [...(subject.alias_tag_ids || [])],
    description: subject.description || '',
    is_active: subject.is_active,
  }
  editPrimaryKeyword.value = ''
  editAliasKeyword.value = ''
  editPrimaryOpen.value = false
  editAliasOpen.value = false
  showEditDescription.value = !!(subject.description || '').trim()
  editOpen.value = true
}

function handleEditCategoryChange() {
  const nextCategoryId = editForm.value.category_tag_id
  if (!nextCategoryId) {
    editForm.value.primary_tag_id = null
    editForm.value.alias_tag_ids = []
    return
  }

  const primaryId = editForm.value.primary_tag_id
  if (primaryId) {
    const primaryTag = tagMetaMap.value.get(primaryId)
    if (primaryTag?.parent_id !== null && primaryTag?.parent_id !== undefined && primaryTag.parent_id !== nextCategoryId) {
      editForm.value.primary_tag_id = null
    }
  }

  editForm.value.alias_tag_ids = (editForm.value.alias_tag_ids || []).filter((id) => {
    const tag = tagMetaMap.value.get(id)
    if (!tag) return true
    if (tag.parent_id === null || tag.parent_id === undefined) return true
    return tag.parent_id === nextCategoryId
  })
  if (editForm.value.primary_tag_id) {
    editForm.value.alias_tag_ids = editForm.value.alias_tag_ids.filter((id) => id !== editForm.value.primary_tag_id)
  }
}

function selectEditPrimaryTag(tag: Tag) {
  editForm.value.primary_tag_id = tag.id
  editForm.value.alias_tag_ids = editForm.value.alias_tag_ids.filter((id) => id !== tag.id)
  if (!editForm.value.category_tag_id && tag.parent_id && categoryIdSet.value.has(tag.parent_id)) {
    editForm.value.category_tag_id = tag.parent_id
  }
  editPrimaryOpen.value = false
}

function toggleEditAlias(tagId: number) {
  if (editForm.value.alias_tag_ids.includes(tagId)) {
    editForm.value.alias_tag_ids = editForm.value.alias_tag_ids.filter((id) => id !== tagId)
    return
  }
  editForm.value.alias_tag_ids = [...editForm.value.alias_tag_ids, tagId]
}

function removeEditAlias(tagId: number) {
  editForm.value.alias_tag_ids = editForm.value.alias_tag_ids.filter((id) => id !== tagId)
}

function clearEditPrimary() {
  editForm.value.primary_tag_id = null
  editPrimaryKeyword.value = ''
}

async function handleSaveEdit() {
  if (!canSaveEdit.value || updateSubjectMutation.isPending.value || !editingSubjectId.value) return

  try {
    await updateSubjectMutation.mutateAsync({
      id: editingSubjectId.value,
      category_tag_id: Number(editForm.value.category_tag_id),
      primary_tag_id: Number(editForm.value.primary_tag_id),
      alias_tag_ids: editForm.value.alias_tag_ids,
      description: editForm.value.description.trim() || null,
      is_active: editForm.value.is_active,
    })
    editOpen.value = false
    await refetch()
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  }
}
</script>

<template>
  <div class="p-6 lg:p-8">
    <div class="max-w-6xl mx-auto space-y-6">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-foreground flex items-center gap-2">
            <Users class="w-5 h-5 text-primary" />
            主体管理
          </h1>
          <p class="text-sm text-muted-foreground mt-1">管理主体词典，用于图片主体识别与纠正</p>
        </div>
        <Button variant="outline" size="sm" @click="refetch" :disabled="isLoading">
          <RefreshCw class="w-4 h-4 mr-2" :class="isLoading && 'animate-spin'" />
          刷新
        </Button>
      </div>

      <div class="bg-card border border-border rounded-xl p-4 space-y-4">
        <h2 class="text-sm font-medium text-foreground">新建主体</h2>
        <div>
          <select
            v-model="createForm.category_tag_id"
            class="h-9 w-full md:w-80 px-3 rounded-md border border-input bg-background text-sm"
            @change="handleCreateCategoryChange"
          >
            <option :value="null">选择一级分类（必填）</option>
            <option v-for="cat in (categoryOptions || [])" :key="cat.id" :value="cat.id">
              {{ cat.name }}
            </option>
          </select>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-12 gap-3">
          <div ref="createPrimaryWrap" class="lg:col-span-5 relative">
            <div class="flex items-center justify-between">
              <div class="text-xs text-muted-foreground">主体名称</div>
              <button
                v-if="createForm.primary_tag_id"
                class="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1"
                @click="clearCreatePrimary"
                type="button"
              >
                <X class="w-3.5 h-3.5" />
                清除
              </button>
            </div>
            <div
              class="mt-1 flex min-h-9 items-center gap-2 rounded-md border border-input bg-background px-2 py-1.5 focus-within:ring-2 focus-within:ring-primary/25"
              @mousedown="openCreatePrimary"
            >
              <span
                v-if="createForm.primary_tag_id"
                class="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-foreground"
              >
                {{ getTagName(createForm.primary_tag_id) }}
              </span>
              <input
                v-model="createPrimaryKeyword"
                type="text"
                class="flex-1 min-w-24 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70"
                placeholder="搜索 level=2 标签作为名称"
                @focus="openCreatePrimary"
                @keydown.escape.stop.prevent="createPrimaryOpen = false"
                @keydown.enter.prevent="createPrimaryOptions[0] && selectCreatePrimaryTag(createPrimaryOptions[0])"
              />
            </div>

            <div
              v-if="createPrimaryOpen"
              class="absolute z-50 mt-2 w-full overflow-hidden rounded-md border border-border bg-popover shadow-xl"
            >
              <div class="max-h-64 overflow-y-auto p-1">
                <button
                  v-for="tag in createPrimaryOptions"
                  :key="`create-primary-dd-${tag.id}`"
                  class="w-full rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-muted flex items-center justify-between gap-3"
                  :class="createForm.primary_tag_id === tag.id ? 'bg-primary/10' : ''"
                  type="button"
                  @mousedown.prevent="selectCreatePrimaryTag(tag)"
                >
                  <span class="truncate">{{ tag.name }}</span>
                  <span v-if="tag.parent_id" class="shrink-0 text-xs text-muted-foreground">
                    {{ getCategoryName(tag.parent_id) }}
                  </span>
                </button>
                <div v-if="createPrimaryOptions.length === 0" class="px-2 py-2 text-xs text-muted-foreground">
                  {{ isCreatePrimarySearching ? '搜索中...' : (createPrimaryKeywordNormalized ? '无匹配结果' : '输入关键字开始搜索') }}
                </div>
              </div>
            </div>
          </div>

          <div ref="createAliasWrap" class="lg:col-span-7 relative">
            <div class="flex items-center justify-between">
              <div class="text-xs text-muted-foreground">别名（可选）</div>
              <button
                v-if="createForm.alias_tag_ids.length"
                class="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1"
                @click="createForm.alias_tag_ids = []"
                type="button"
              >
                <X class="w-3.5 h-3.5" />
                清空
              </button>
            </div>
            <div
              class="mt-1 flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-2 py-1.5 focus-within:ring-2 focus-within:ring-primary/25"
              @mousedown="openCreateAlias"
            >
              <button
                v-for="tagId in createForm.alias_tag_ids"
                :key="`create-alias-chip-${tagId}`"
                type="button"
                class="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-foreground hover:bg-muted/80 transition-colors"
                @mousedown.stop
                @click.stop="removeCreateAlias(tagId)"
                :title="`移除 ${getTagName(tagId)}`"
              >
                {{ getTagName(tagId) }}
                <X class="w-3.5 h-3.5 text-muted-foreground" />
              </button>

              <input
                v-model="createAliasKeyword"
                type="text"
                class="flex-1 min-w-24 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70 py-1"
                placeholder="搜索并添加"
                @focus="openCreateAlias"
                @keydown.escape.stop.prevent="createAliasOpen = false"
                @keydown.enter.prevent="createAliasOptions[0] && toggleCreateAlias(createAliasOptions[0].id)"
              />
            </div>

            <div
              v-if="createAliasOpen"
              class="absolute z-50 mt-2 w-full overflow-hidden rounded-md border border-border bg-popover shadow-xl"
            >
              <div class="max-h-64 overflow-y-auto p-1">
                <button
                  v-for="tag in createAliasOptions"
                  :key="`create-alias-dd-${tag.id}`"
                  class="w-full rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-muted flex items-center justify-between gap-3"
                  :class="createForm.alias_tag_ids.includes(tag.id) ? 'bg-primary/10' : ''"
                  type="button"
                  @mousedown.prevent="toggleCreateAlias(tag.id)"
                >
                  <span class="truncate">
                    {{ tag.name }}
                    <span v-if="createForm.alias_tag_ids.includes(tag.id)" class="ml-2 text-xs text-primary">已选</span>
                  </span>
                  <span v-if="tag.parent_id" class="shrink-0 text-xs text-muted-foreground">
                    {{ getCategoryName(tag.parent_id) }}
                  </span>
                </button>
                <div v-if="createAliasOptions.length === 0" class="px-2 py-2 text-xs text-muted-foreground">
                  {{ isCreateAliasSearching ? '搜索中...' : (createAliasKeywordNormalized ? '无匹配结果' : '输入关键字开始搜索') }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-between">
          <button
            type="button"
            class="text-xs text-muted-foreground hover:text-foreground transition-colors"
            @click="showCreateDescription = !showCreateDescription"
          >
            {{ showCreateDescription ? '隐藏备注' : '添加备注' }}
          </button>
        </div>

        <textarea
          v-if="showCreateDescription"
          v-model="createForm.description"
          maxlength="1000"
          rows="2"
          placeholder="备注（可选）"
          class="w-full px-3 py-2 rounded-md border border-input bg-background text-sm resize-y"
        />

        <div>
          <Button :disabled="!canCreate || createSubjectMutation.isPending.value" @click="handleCreateSubject">
            <Loader2 v-if="createSubjectMutation.isPending.value" class="w-4 h-4 mr-2 animate-spin" />
            <Plus v-else class="w-4 h-4 mr-2" />
            新建主体
          </Button>
        </div>
      </div>

      <div class="bg-card border border-border rounded-xl p-4 space-y-4">
        <div class="flex flex-col md:flex-row gap-3">
          <input
            v-model="keywordInput"
            type="text"
            placeholder="按名称/描述筛选"
            class="h-9 px-3 rounded-md border border-input bg-background text-sm flex-1"
            @keydown.enter.prevent="applyFilters"
          />
          <select
            v-model="categoryFilter"
            class="h-9 px-3 rounded-md border border-input bg-background text-sm w-full md:w-40"
          >
            <option value="all">全部分类</option>
            <option v-for="cat in (categoryOptions || [])" :key="cat.id" :value="cat.id">
              {{ cat.name }}
            </option>
          </select>
          <label class="h-9 inline-flex items-center gap-2 text-sm px-3 rounded-md border border-input bg-background">
            <input v-model="activeOnly" type="checkbox" @change="applyFilters" />
            仅启用
          </label>
          <Button variant="outline" @click="applyFilters">筛选</Button>
        </div>

        <div v-if="isLoading" class="py-10 flex items-center justify-center text-muted-foreground">
          <Loader2 class="w-5 h-5 animate-spin mr-2" />
          加载中...
        </div>
        <div v-else-if="!filteredSubjects || filteredSubjects.length === 0" class="py-10 text-center text-muted-foreground">
          暂无主体
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-border text-muted-foreground">
                <th class="text-left py-2 pr-3">一级分类</th>
                <th class="text-left py-2 pr-3">主体名</th>
                <th class="text-left py-2 pr-3">主标签</th>
                <th class="text-left py-2 pr-3">别名</th>
                <th class="text-left py-2 pr-3">描述</th>
                <th class="text-left py-2 pr-3">状态</th>
                <th class="text-left py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in filteredSubjects" :key="item.id" class="border-b border-border/60">
                <td class="py-2 pr-3 text-muted-foreground">{{ item.category_tag_name }}</td>
                <td class="py-2 pr-3 font-medium text-foreground">{{ item.name }}</td>
                <td class="py-2 pr-3 text-muted-foreground">{{ item.primary_tag_name }}</td>
                <td class="py-2 pr-3 text-muted-foreground">{{ (item.aliases || []).join('、') || '-' }}</td>
                <td class="py-2 pr-3 text-muted-foreground">{{ item.description || '-' }}</td>
                <td class="py-2 pr-3">
                  <span
                    class="inline-flex items-center px-2 py-0.5 rounded text-xs"
                    :class="item.is_active ? 'bg-emerald-500/10 text-emerald-500' : 'bg-muted text-muted-foreground'"
                  >
                    {{ item.is_active ? '启用' : '停用' }}
                  </span>
                </td>
                <td class="py-2">
                  <Button variant="outline" size="sm" class="h-8 px-2" @click="openEditDialog(item)">
                    <Pencil class="w-3.5 h-3.5 mr-1" />
                    编辑
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <Dialog v-model:open="editOpen">
    <DialogContent class="sm:max-w-3xl">
      <DialogHeader>
        <DialogTitle>编辑主体</DialogTitle>
        <DialogDescription>调整分类、名称标签、别名与启用状态</DialogDescription>
      </DialogHeader>

      <div class="space-y-4">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <select
            v-model="editForm.category_tag_id"
            class="h-9 px-3 rounded-md border border-input bg-background text-sm"
            @change="handleEditCategoryChange"
          >
            <option :value="null">选择一级分类（必填）</option>
            <option v-for="cat in (categoryOptions || [])" :key="cat.id" :value="cat.id">
              {{ cat.name }}
            </option>
          </select>
          <label class="h-9 inline-flex items-center gap-2 text-sm px-3 rounded-md border border-input bg-background">
            <input v-model="editForm.is_active" type="checkbox" />
            启用主体
          </label>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-12 gap-3">
          <div ref="editPrimaryWrap" class="lg:col-span-5 relative">
            <div class="flex items-center justify-between">
              <div class="text-xs text-muted-foreground">主体名称</div>
              <button
                v-if="editForm.primary_tag_id"
                class="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1"
                @click="clearEditPrimary"
                type="button"
              >
                <X class="w-3.5 h-3.5" />
                清除
              </button>
            </div>
            <div
              class="mt-1 flex min-h-9 items-center gap-2 rounded-md border border-input bg-background px-2 py-1.5 focus-within:ring-2 focus-within:ring-primary/25"
              @mousedown="openEditPrimary"
            >
              <span
                v-if="editForm.primary_tag_id"
                class="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-foreground"
              >
                {{ getTagName(editForm.primary_tag_id) }}
              </span>
              <input
                v-model="editPrimaryKeyword"
                type="text"
                class="flex-1 min-w-24 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70"
                placeholder="搜索 level=2 标签作为名称"
                @focus="openEditPrimary"
                @keydown.escape.stop.prevent="editPrimaryOpen = false"
                @keydown.enter.prevent="editPrimaryOptions[0] && selectEditPrimaryTag(editPrimaryOptions[0])"
              />
            </div>

            <div
              v-if="editPrimaryOpen"
              class="absolute z-50 mt-2 w-full overflow-hidden rounded-md border border-border bg-popover shadow-xl"
            >
              <div class="max-h-64 overflow-y-auto p-1">
                <button
                  v-for="tag in editPrimaryOptions"
                  :key="`edit-primary-dd-${tag.id}`"
                  class="w-full rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-muted flex items-center justify-between gap-3"
                  :class="editForm.primary_tag_id === tag.id ? 'bg-primary/10' : ''"
                  type="button"
                  @mousedown.prevent="selectEditPrimaryTag(tag)"
                >
                  <span class="truncate">{{ tag.name }}</span>
                  <span v-if="tag.parent_id" class="shrink-0 text-xs text-muted-foreground">
                    {{ getCategoryName(tag.parent_id) }}
                  </span>
                </button>
                <div v-if="editPrimaryOptions.length === 0" class="px-2 py-2 text-xs text-muted-foreground">
                  {{ isEditPrimarySearching ? '搜索中...' : (editPrimaryKeywordNormalized ? '无匹配结果' : '输入关键字开始搜索') }}
                </div>
              </div>
            </div>
          </div>

          <div ref="editAliasWrap" class="lg:col-span-7 relative">
            <div class="flex items-center justify-between">
              <div class="text-xs text-muted-foreground">别名（可选）</div>
              <button
                v-if="editForm.alias_tag_ids.length"
                class="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1"
                @click="editForm.alias_tag_ids = []"
                type="button"
              >
                <X class="w-3.5 h-3.5" />
                清空
              </button>
            </div>
            <div
              class="mt-1 flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-2 py-1.5 focus-within:ring-2 focus-within:ring-primary/25"
              @mousedown="openEditAlias"
            >
              <button
                v-for="tagId in editForm.alias_tag_ids"
                :key="`edit-alias-chip-${tagId}`"
                type="button"
                class="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-foreground hover:bg-muted/80 transition-colors"
                @mousedown.stop
                @click.stop="removeEditAlias(tagId)"
                :title="`移除 ${getTagName(tagId)}`"
              >
                {{ getTagName(tagId) }}
                <X class="w-3.5 h-3.5 text-muted-foreground" />
              </button>

              <input
                v-model="editAliasKeyword"
                type="text"
                class="flex-1 min-w-24 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70 py-1"
                placeholder="搜索并添加"
                @focus="openEditAlias"
                @keydown.escape.stop.prevent="editAliasOpen = false"
                @keydown.enter.prevent="editAliasOptions[0] && toggleEditAlias(editAliasOptions[0].id)"
              />
            </div>

            <div
              v-if="editAliasOpen"
              class="absolute z-50 mt-2 w-full overflow-hidden rounded-md border border-border bg-popover shadow-xl"
            >
              <div class="max-h-64 overflow-y-auto p-1">
                <button
                  v-for="tag in editAliasOptions"
                  :key="`edit-alias-dd-${tag.id}`"
                  class="w-full rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-muted flex items-center justify-between gap-3"
                  :class="editForm.alias_tag_ids.includes(tag.id) ? 'bg-primary/10' : ''"
                  type="button"
                  @mousedown.prevent="toggleEditAlias(tag.id)"
                >
                  <span class="truncate">
                    {{ tag.name }}
                    <span v-if="editForm.alias_tag_ids.includes(tag.id)" class="ml-2 text-xs text-primary">已选</span>
                  </span>
                  <span v-if="tag.parent_id" class="shrink-0 text-xs text-muted-foreground">
                    {{ getCategoryName(tag.parent_id) }}
                  </span>
                </button>
                <div v-if="editAliasOptions.length === 0" class="px-2 py-2 text-xs text-muted-foreground">
                  {{ isEditAliasSearching ? '搜索中...' : (editAliasKeywordNormalized ? '无匹配结果' : '输入关键字开始搜索') }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-between">
          <button
            type="button"
            class="text-xs text-muted-foreground hover:text-foreground transition-colors"
            @click="showEditDescription = !showEditDescription"
          >
            {{ showEditDescription ? '隐藏备注' : '添加备注' }}
          </button>
        </div>

        <textarea
          v-if="showEditDescription"
          v-model="editForm.description"
          maxlength="1000"
          rows="2"
          placeholder="备注（可选）"
          class="w-full px-3 py-2 rounded-md border border-input bg-background text-sm resize-y"
        />
      </div>

      <DialogFooter>
        <Button variant="outline" @click="editOpen = false">取消</Button>
        <Button :disabled="!canSaveEdit || updateSubjectMutation.isPending.value" @click="handleSaveEdit">
          <Loader2 v-if="updateSubjectMutation.isPending.value" class="w-4 h-4 mr-2 animate-spin" />
          保存
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
