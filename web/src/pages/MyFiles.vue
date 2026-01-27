<script setup lang="ts">
/**
 * MyFiles - 我的图库页面 (Linear Style)
 * 支持批量选择、悬浮操作栏、现代化分页
 */
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores'
import { useMyImages } from '@/api/queries'
import apiClient from '@/api/client'
import type { ImageResponse, ImageSearchRequest, TagWithSource } from '@/types'
import {
  Loader2, Filter, CheckSquare, Trash2, Tags, Sparkles, LayoutGrid,
  ChevronDown, ChevronLeft, ChevronRight, FolderOpen, ArrowUpDown, Tag,
  X, Check, Plus
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import ImageGrid from '@/components/ImageGrid.vue'
import ImageFilterBar from '@/components/ImageFilterBar.vue'
import ImageDetailModal from '@/components/ImageDetailModal.vue'
import { toast } from 'vue-sonner'
import { getErrorMessage } from '@/utils/api-error'
import { useCategories } from '@/api/queries'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import UploadDialog from '@/components/UploadDialog.vue'

const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()

const router = useRouter()
const userStore = useUserStore()

// 上传弹窗
const showUploadDialog = ref(false)

if (!userStore.isLoggedIn) router.push('/login?redirect=/my-files')

// 筛选状态
const filters = ref({
  category: 'all',
  resolution: 'all',
  keyword: '',
  pendingOnly: false,
  duplicatesOnly: false,
})
const showFilters = ref(false)

// 分页
const pageSize = ref(40)
const currentPage = ref(1)
const sortBy = ref('id') // 排序字段
const sortDesc = ref(true) // 是否倒序
const jumpPage = ref('')

// 显示模式
const showLabelsAlways = ref(false)

// 搜索参数
const searchParams = ref<ImageSearchRequest>({ size: pageSize.value, page: 1, sort_by: sortBy.value, sort_desc: sortDesc.value })

// 查询数据
const { data: imageData, isLoading, isError, refetch } = useMyImages(searchParams)
const { data: categoriesData } = useCategories()

// 标签局部更新覆盖层
const tagOverrides = ref<Map<number, TagWithSource[]>>(new Map())

// 合并原始数据和覆盖层
const images = computed(() => {
  const original = imageData.value?.data || []
  if (tagOverrides.value.size === 0) return original

  return original.map((img: ImageResponse) => {
    const override = tagOverrides.value.get(img.id)
    return override ? { ...img, tags: override } : img
  })
})
const total = computed(() => imageData.value?.total || 0)
const totalPages = computed(() => Math.ceil(total.value / pageSize.value))
const categories = computed(() => categoriesData.value || [])

// 处理标签更新（局部更新）
function handleTagsUpdated(imageId: number, newTags: TagWithSource[]) {
  tagOverrides.value.set(imageId, newTags)
  // 触发响应式更新
  tagOverrides.value = new Map(tagOverrides.value)
}

// 搜索参数变化时清理标签覆盖层
watch(searchParams, () => {
  tagOverrides.value.clear()
}, { deep: true })

// 搜索和分页
function handleSearch() {
  currentPage.value = 1
  searchParams.value = {
    ...searchParams.value,
    keyword: filters.value.keyword || undefined,
    category_id: filters.value.category !== 'all' ? parseInt(filters.value.category) : undefined,
    resolution_id: filters.value.resolution !== 'all' ? parseInt(filters.value.resolution) : undefined,
    pending_only: filters.value.pendingOnly || undefined,
    duplicates_only: filters.value.duplicatesOnly || undefined,
    page: 1,
  }
}

function handleReset() {
  currentPage.value = 1
  sortBy.value = 'id'
  sortDesc.value = true
  searchParams.value = { size: pageSize.value, page: 1, sort_by: 'id', sort_desc: true }
}

// 排序变更
function changeSort(value: string) {
  const [field, desc] = value.split('-')
  sortBy.value = field
  sortDesc.value = desc === 'desc'
  currentPage.value = 1
  searchParams.value = {
    ...searchParams.value,
    sort_by: field,
    sort_desc: desc === 'desc',
    page: 1,
  }
}

const currentSort = computed(() => `${sortBy.value}-${sortDesc.value ? 'desc' : 'asc'}`)

function changePage(page: number) {
  currentPage.value = page
  searchParams.value = { ...searchParams.value, page: page }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function changePageSize(size: string) {
  const newSize = parseInt(size)
  if (isNaN(newSize)) return
  pageSize.value = newSize
  currentPage.value = 1
  searchParams.value = { ...searchParams.value, size: newSize, page: 1 }
}

// 跳转到指定页码
function handleJump() {
  const page = parseInt(jumpPage.value)
  if (isNaN(page) || page < 1 || page > totalPages.value) {
    toast.error(`请输入 1-${totalPages.value} 之间的页码`)
    return
  }
  changePage(page)
  jumpPage.value = ''
}

// 批量选择
const selectMode = ref(false)
const selectedIds = ref<Set<number>>(new Set())

function toggleSelectMode() {
  selectMode.value = !selectMode.value
  if (!selectMode.value) selectedIds.value = new Set()
}

function toggleSelect(id: number) {
  const newSet = new Set(selectedIds.value)
  newSet.has(id) ? newSet.delete(id) : newSet.add(id)
  selectedIds.value = newSet
}

function selectAll() { selectedIds.value = new Set(images.value.map(img => img.id)) }
function invertSelection() {
  selectedIds.value = new Set(images.value.filter(img => !selectedIds.value.has(img.id)).map(img => img.id))
}
function clearSelection() { selectedIds.value = new Set() }
const isAllSelected = computed(() => images.value.length > 0 && selectedIds.value.size === images.value.length)

// 批量操作
const batchLoading = ref(false)

async function handleBatchAnalyze() {
  if (!selectedIds.value.size) return
  batchLoading.value = true
  try {
    await apiClient.post('/queue/add', { image_ids: Array.from(selectedIds.value) })
    toast.success(`已将 ${selectedIds.value.size} 张图片加入分析队列`)
    clearSelection()
  } catch (e: any) { toast.error(getErrorMessage(e)) }
  finally { batchLoading.value = false }
}

async function handleBatchDelete() {
  if (!selectedIds.value.size) return

  const result = await confirm({
    title: '批量删除',
    message: `确定要删除 ${selectedIds.value.size} 张图片吗？`,
    variant: 'danger',
    confirmText: '删除',
    checkboxLabel: '同时删除物理文件',
    checkboxDefault: false,
  })
  if (!result.confirmed) return

  batchLoading.value = true
  try {
    await apiClient.post('/images/batch/delete', {
      image_ids: Array.from(selectedIds.value),
      delete_files: result.checkboxChecked,
    })
    toast.success(`已删除 ${selectedIds.value.size} 张图片`)
    clearSelection()
    refetch()
  } catch (e: any) { toast.error(getErrorMessage(e)) }
  finally { batchLoading.value = false }
}

// 批量打标签弹窗
const showBatchTagDialog = ref(false)
const batchTags = ref('')
const batchTagMode = ref<'add' | 'replace'>('add')

async function handleBatchTag() {
  if (!selectedIds.value.size || !batchTags.value.trim()) return
  batchLoading.value = true
  try {
    const tags = batchTags.value.split(',').map(t => t.trim()).filter(Boolean)
    await apiClient.post('/images/batch/update-tags', { image_ids: Array.from(selectedIds.value), tags, mode: batchTagMode.value })
    toast.success(`操作成功`)
    showBatchTagDialog.value = false
    batchTags.value = ''
    clearSelection()
    refetch()
  } catch (e: any) { toast.error(getErrorMessage(e)) }
  finally { batchLoading.value = false }
}

// 批量分类弹窗
const showBatchCategoryDialog = ref(false)
const batchCategoryId = ref('')

async function handleBatchCategory() {
  if (!selectedIds.value.size || !batchCategoryId.value) return
  batchLoading.value = true
  try {
    await apiClient.post('/images/batch/set-category', { image_ids: Array.from(selectedIds.value), category_id: parseInt(batchCategoryId.value) })
    toast.success(`分类设置成功`)
    showBatchCategoryDialog.value = false
    batchCategoryId.value = ''
    clearSelection()
    refetch()
  } catch (e: any) { toast.error(getErrorMessage(e)) }
  finally { batchLoading.value = false }
}


// 图片详情
const selectedImage = ref<ImageResponse | null>(null)
const selectedIndex = ref(0)

function openImage(image: ImageResponse, index: number) {
  if (selectMode.value) { toggleSelect(image.id); return }
  selectedImage.value = image
  selectedIndex.value = index
}

function closeImage() { selectedImage.value = null }
function prevImage() {
  if (selectedIndex.value > 0) { selectedIndex.value--; selectedImage.value = images.value[selectedIndex.value] }
}
function nextImage() {
  if (selectedIndex.value < images.value.length - 1) { selectedIndex.value++; selectedImage.value = images.value[selectedIndex.value] }
}
</script>

<template>
  <div class="min-h-screen pb-20">
    <main class="py-4 px-4 md:py-6 md:px-6 max-w-[1800px] mx-auto">
      <div>
        <!-- 标题区 -->
        <div class="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 overflow-hidden">
          <div class="shrink-0">
            <h1 class="text-xl font-bold text-foreground flex items-center gap-2">
              <FolderOpen class="w-5 h-5 text-primary" />我的图库
            </h1>
            <p class="text-sm text-muted-foreground mt-1">管理与组织您的图片资产</p>
          </div>

          <div class="flex items-center gap-2 overflow-x-auto no-scrollbar -mx-4 px-4 sm:mx-0 sm:px-0 sm:overflow-visible w-[calc(100%+2rem)] sm:w-auto pb-1 sm:pb-0">
            <!-- 视图控制组 -->
            <div class="flex items-center bg-muted/40 p-1 rounded-lg border border-border/40 shrink-0">
              <Button
                variant="ghost"
                size="sm"
                @click="showLabelsAlways = !showLabelsAlways"
                class="h-7 px-3 text-xs rounded-md transition-all"
                :class="showLabelsAlways ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'"
              >
                <Tag class="w-3.5 h-3.5 mr-1.5" />{{ showLabelsAlways ? '隐藏标签' : '显示标签' }}
              </Button>
              <div class="w-px h-3 bg-border/50 mx-1"></div>
              <Button
                variant="ghost"
                size="sm"
                @click="toggleSelectMode"
                class="h-7 px-3 text-xs rounded-md transition-all"
                :class="selectMode ? 'bg-background shadow-sm text-primary' : 'text-muted-foreground hover:text-foreground'"
              >
                <CheckSquare class="w-3.5 h-3.5 mr-1.5" />{{ selectMode ? '退出选择' : '批量选择' }}
              </Button>
            </div>

            <!-- 排序 -->
            <Select :model-value="currentSort" @update:model-value="changeSort">
              <SelectTrigger class="w-[130px] h-9 text-xs">
                <ArrowUpDown class="w-3.5 h-3.5 mr-2 text-muted-foreground" />
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="id-desc">最近上传</SelectItem>
                <SelectItem value="id-asc">最早上传</SelectItem>
                <SelectItem value="analyzed_at-desc">最近分析</SelectItem>
              </SelectContent>
            </Select>

            <!-- 上传按钮 -->
            <Button size="sm" class="h-9 gap-1.5" @click="showUploadDialog = true">
              <Plus class="w-4 h-4" />
              上传
            </Button>
          </div>
        </div>

        <!-- 筛选栏 (可折叠) -->
        <div class="mb-6">
           <Button
             variant="ghost"
             size="sm"
             class="mb-2 px-0 hover:bg-transparent text-muted-foreground hover:text-foreground"
             @click="showFilters = !showFilters"
           >
             <ChevronDown class="w-4 h-4 mr-1 transition-transform" :class="{ '-rotate-90': !showFilters }" />
             {{ showFilters ? '收起筛选' : '展开筛选' }}
           </Button>
           <Transition name="slide">
            <ImageFilterBar
              v-show="showFilters"
              v-model="filters"
              class="mb-6"
              auto-search
              show-pending-filter
              show-duplicates-filter
              @search="handleSearch"
              @reset="handleReset"
            />
          </Transition>
        </div>

        <!-- 状态显示 -->
        <div v-if="isLoading && !images.length" class="flex items-center justify-center py-40">
          <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
        </div>

        <div v-else-if="!images.length" class="flex flex-col items-center justify-center py-40 border-2 border-dashed border-border/50 rounded-xl bg-muted/10">
          <div class="w-16 h-16 rounded-full bg-muted/30 flex items-center justify-center mb-4">
            <FolderOpen class="w-8 h-8 text-muted-foreground" />
          </div>
          <h3 class="text-lg font-medium text-foreground">暂无图片</h3>
          <p class="text-muted-foreground mt-1 mb-6">上传图片开始构建您的图库</p>
          <Button @click="showUploadDialog = true">上传图片</Button>
        </div>

        <!-- 图片网格 -->
        <ImageGrid
          v-else
          :images="images"
          :select-mode="selectMode"
          :selected-ids="selectedIds"
          :show-pending-badge="true"
          :show-labels-always="showLabelsAlways"
          :editable="showLabelsAlways"
          @select="openImage"
          @toggle-select="toggleSelect"
          @tags-updated="handleTagsUpdated"
        />

        <!-- 分页 -->
        <div v-if="total > 0" class="mt-12 flex items-center justify-center gap-4">
          <Select :model-value="String(pageSize)" @update:model-value="changePageSize">
            <SelectTrigger class="w-24 h-8 text-xs border-0 bg-secondary/50 hover:bg-secondary">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="20">20 / 页</SelectItem>
              <SelectItem value="40">40 / 页</SelectItem>
              <SelectItem value="60">60 / 页</SelectItem>
              <SelectItem value="100">100 / 页</SelectItem>
            </SelectContent>
          </Select>

          <div class="flex items-center bg-secondary/50 rounded-lg p-1">
            <button
              class="w-8 h-8 flex items-center justify-center rounded-md transition-colors disabled:opacity-30 disabled:cursor-not-allowed hover:bg-background"
              :disabled="currentPage <= 1"
              @click="changePage(currentPage - 1)"
            >
              <ChevronLeft class="w-4 h-4" />
            </button>

            <div class="flex items-center gap-1 px-3 text-sm font-medium font-mono">
              <span class="text-foreground">{{ currentPage }}</span>
              <span class="text-muted-foreground">/</span>
              <span class="text-muted-foreground">{{ totalPages }}</span>
            </div>

            <button
              class="w-8 h-8 flex items-center justify-center rounded-md transition-colors disabled:opacity-30 disabled:cursor-not-allowed hover:bg-background"
              :disabled="currentPage >= totalPages"
              @click="changePage(currentPage + 1)"
            >
              <ChevronRight class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </main>

    <!-- 底部悬浮批量操作栏 -->
    <Transition name="slide-up">
      <div v-if="selectMode && selectedIds.size > 0" class="fixed bottom-24 left-1/2 -translate-x-1/2 z-50 max-w-[calc(100vw-32px)] w-max">
        <div class="flex items-center gap-1 p-1.5 bg-zinc-900/90 backdrop-blur-xl border border-white/10 rounded-full shadow-2xl text-white pl-2 pr-1.5 overflow-x-auto no-scrollbar whitespace-nowrap">
          <!-- 计数器 (仅展示) -->
          <div class="shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-white text-zinc-950 font-bold text-xs mr-2 shadow-sm">
            {{ selectedIds.size }}
          </div>

          <!-- 操作按钮组 -->
          <button
            @click="selectAll"
            class="shrink-0 px-3 py-1.5 rounded-full hover:bg-white/10 text-xs font-medium transition-colors"
          >
            全选
          </button>

          <button
            @click="invertSelection"
            class="shrink-0 px-3 py-1.5 rounded-full hover:bg-white/10 text-xs font-medium transition-colors"
          >
            反选
          </button>

          <button
            @click="clearSelection"
            class="shrink-0 px-3 py-1.5 rounded-full hover:bg-white/10 text-xs font-medium transition-colors"
          >
            清空
          </button>

          <div class="shrink-0 h-4 w-px bg-white/10 mx-1"></div>

          <button
            @click="showBatchTagDialog = true"
            class="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full hover:bg-white/10 text-xs font-medium transition-colors"
          >
            <Tags class="w-3.5 h-3.5" />
            标签
          </button>

          <button
            @click="showBatchCategoryDialog = true"
            class="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full hover:bg-white/10 text-xs font-medium transition-colors"
          >
            <LayoutGrid class="w-3.5 h-3.5" />
            分类
          </button>

          <button
            @click="handleBatchAnalyze"
            class="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full hover:bg-white/10 text-xs font-medium transition-colors text-blue-400 hover:text-blue-300"
          >
            <Sparkles class="w-3.5 h-3.5" />
            分析
          </button>

          <button
            @click="handleBatchDelete"
            class="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full hover:bg-red-500/20 text-xs font-medium transition-colors text-red-400 hover:text-red-300 ml-1"
          >
            <Trash2 class="w-3.5 h-3.5" />
            删除
          </button>
        </div>
      </div>
    </Transition>

    <ImageDetailModal
      v-if="selectedImage"
      :image="selectedImage"
      :can-navigate-prev="selectedIndex > 0"
      :can-navigate-next="selectedIndex < images.length - 1"
      :current-index="selectedIndex"
      :total-count="images.length"
      @close="closeImage"
      @prev="prevImage"
      @next="nextImage"
    />

    <!-- 批量打标签弹窗 -->
    <Dialog v-model:open="showBatchTagDialog">
      <DialogContent>
        <DialogHeader><DialogTitle>批量编辑标签</DialogTitle></DialogHeader>
        <div class="space-y-4 py-4">
          <div><label class="text-sm font-medium mb-2 block">标签 (逗号分隔)</label><Input v-model="batchTags" placeholder="Landscape, HD, ..." /></div>
          <div class="flex gap-4">
            <label class="flex items-center gap-2 cursor-pointer"><input type="radio" v-model="batchTagMode" value="add" class="accent-primary" /><span class="text-sm">追加</span></label>
            <label class="flex items-center gap-2 cursor-pointer"><input type="radio" v-model="batchTagMode" value="replace" class="accent-primary" /><span class="text-sm">覆盖</span></label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showBatchTagDialog = false">取消</Button>
          <Button @click="handleBatchTag" :disabled="batchLoading">确认</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 批量分类弹窗 -->
    <Dialog v-model:open="showBatchCategoryDialog">
      <DialogContent>
        <DialogHeader><DialogTitle>批量设置分类</DialogTitle></DialogHeader>
        <div class="py-4">
          <label class="text-sm font-medium mb-2 block">选择分类</label>
          <Select v-model="batchCategoryId">
            <SelectTrigger><SelectValue placeholder="选择分类" /></SelectTrigger>
            <SelectContent>
              <SelectItem v-for="cat in categories" :key="cat.id" :value="String(cat.id)">{{ cat.name }}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showBatchCategoryDialog = false">取消</Button>
          <Button @click="handleBatchCategory" :disabled="batchLoading">确认</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 确认弹窗 -->
    <ConfirmDialog
      :open="confirmState.open"
      :title="confirmState.title"
      :message="confirmState.message"
      :confirm-text="confirmState.confirmText"
      :cancel-text="confirmState.cancelText"
      :variant="confirmState.variant"
      :loading="confirmState.loading"
      :checkbox-label="confirmState.checkboxLabel"
      :checkbox-checked="confirmState.checkboxChecked"
      @confirm="handleConfirm"
      @cancel="handleCancel"
      @update:checkbox-checked="(v) => confirmState.checkboxChecked = v"
    />

    <!-- 上传弹窗 -->
    <UploadDialog v-model:open="showUploadDialog" />
  </div>
</template>

<style scoped>
.slide-enter-active, .slide-leave-active { transition: all 0.3s ease; max-height: 100px; opacity: 1; }
.slide-enter-from, .slide-leave-to { max-height: 0; opacity: 0; overflow: hidden; }

.slide-up-enter-active, .slide-up-leave-active { transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1); }
.slide-up-enter-from, .slide-up-leave-to { transform: translate(-50%, 100%); opacity: 0; }

/* 隐藏滚动条但保留功能 */
.no-scrollbar::-webkit-scrollbar { display: none; }
.no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
</style>
