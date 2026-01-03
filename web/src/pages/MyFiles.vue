<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores'
import { useMyImages } from '@/api/queries'
import apiClient from '@/api/client'
import type { ImageResponse, ImageSearchRequest, TagWithSource } from '@/types'
import { Loader2, Filter, CheckSquare, Trash2, Tags, Sparkles, LayoutGrid, ChevronDown, ChevronLeft, ChevronRight, FolderOpen, ArrowUpDown, Tag } from 'lucide-vue-next'
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

// 筛选状态（整合所有筛选条件）
const filters = ref({ 
  category: 'all', 
  resolution: 'all', 
  keyword: '',
  pendingOnly: false,
  duplicatesOnly: false,
})
const showFilters = ref(true)

// 分页
const pageSize = ref(40)
const currentPage = ref(1)
const sortBy = ref('id') // 排序字段
const sortDesc = ref(true) // 是否倒序
const jumpPage = ref('')  // 跳转页码输入

// 显示模式
const showLabelsAlways = ref(false)  // 是否始终显示标签

// 搜索参数
const searchParams = ref<ImageSearchRequest>({ limit: pageSize.value, offset: 0, sort_by: sortBy.value, sort_desc: sortDesc.value })

// 查询数据
const { data: imageData, isLoading, isError, refetch } = useMyImages(searchParams)
const { data: categoriesData } = useCategories()

// 标签局部更新覆盖层（用于避免刷新整个列表）
const tagOverrides = ref<Map<number, TagWithSource[]>>(new Map())

// 合并原始数据和覆盖层
const images = computed(() => {
  const original = imageData.value?.images || []
  if (tagOverrides.value.size === 0) return original
  
  return original.map(img => {
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
    offset: 0,
  }
}

function handleReset() {
  currentPage.value = 1
  sortBy.value = 'id'
  sortDesc.value = true
  searchParams.value = { limit: pageSize.value, offset: 0, sort_by: 'id', sort_desc: true }
}

// 排序变更
function changeSort(value: unknown) {
  if (typeof value !== 'string') return
  const [field, desc] = value.split('-')
  sortBy.value = field
  sortDesc.value = desc === 'desc'
  currentPage.value = 1
  searchParams.value = {
    ...searchParams.value,
    sort_by: field,
    sort_desc: desc === 'desc',
    offset: 0,
  }
}

const currentSort = computed(() => `${sortBy.value}-${sortDesc.value ? 'desc' : 'asc'}`)

function changePage(page: number) {
  currentPage.value = page
  searchParams.value = { ...searchParams.value, offset: (page - 1) * pageSize.value }
}

function changePageSize(size: unknown) {
  if (!size) return
  const newSize = typeof size === 'string' ? parseInt(size) : Number(size)
  if (isNaN(newSize)) return
  pageSize.value = newSize
  currentPage.value = 1
  searchParams.value = { ...searchParams.value, limit: newSize, offset: 0 }
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
    message: `确定要删除 ${selectedIds.value.size} 张图片吗？此操作不可恢复！`,
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
    toast.success(`已删除 ${selectedIds.value.size} 张图片${result.checkboxChecked ? '（含物理文件）' : ''}`)
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
    toast.success(`已为 ${selectedIds.value.size} 张图片${batchTagMode.value === 'add' ? '添加' : '替换'}标签`)
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
    toast.success(`已为 ${selectedIds.value.size} 张图片设置分类`)
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
  <div class="min-h-screen">
    <main class="py-6 px-6">
      <div class="max-w-7xl">
        <!-- 标题区 -->
        <div class="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 class="text-xl font-bold text-foreground flex items-center gap-2">
              <FolderOpen class="w-5 h-5 text-primary" />我的图库
            </h1>
            <p class="text-sm text-muted-foreground mt-1">共 {{ total }} 张图片</p>
          </div>
          <div class="flex items-center gap-2">
            <!-- 标签显示开关 -->
            <Button 
              variant="outline" 
              size="sm" 
              @click="showLabelsAlways = !showLabelsAlways"
              :class="{ 'bg-primary text-primary-foreground': showLabelsAlways }"
            >
              <Tag class="w-4 h-4 mr-1" />{{ showLabelsAlways ? '隐藏标签' : '显示标签' }}
            </Button>
            <!-- 排序选择 -->
            <Select :model-value="currentSort" @update:model-value="changeSort">
              <SelectTrigger class="w-[140px]">
                <ArrowUpDown class="w-4 h-4 mr-1" />
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="id-desc">最近上传</SelectItem>
                <SelectItem value="id-asc">最早上传</SelectItem>
                <SelectItem value="analyzed_at-desc">最近分析</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" @click="showFilters = !showFilters">
              <Filter class="w-4 h-4 mr-1" />筛选
              <ChevronDown class="w-4 h-4 ml-1 transition-transform" :class="{ 'rotate-180': showFilters }" />
            </Button>
            <Button variant="outline" size="sm" @click="toggleSelectMode" :class="{ 'bg-primary text-primary-foreground': selectMode }">
              <CheckSquare class="w-4 h-4 mr-1" />{{ selectMode ? '退出选择' : '批量选择' }}
            </Button>
          </div>
        </div>

        <!-- 筛选栏 -->
        <Transition name="slide">
          <ImageFilterBar 
            v-if="showFilters" 
            v-model="filters" 
            class="mb-6"
            auto-search
            show-pending-filter
            show-duplicates-filter
            @search="handleSearch" 
            @reset="handleReset"
          />
        </Transition>

        <!-- 批量操作栏 -->
        <div v-if="selectMode && selectedIds.size > 0" class="mb-4 p-4 bg-gradient-to-r from-primary/10 to-primary/5 rounded-xl border border-primary/20">
          <div class="flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center gap-4">
              <div class="flex items-center gap-2">
                <div class="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center">
                  <span class="text-primary font-bold text-sm">{{ selectedIds.size }}</span>
                </div>
                <span class="text-sm text-muted-foreground">张已选</span>
              </div>
              <div class="flex items-center gap-1 border-l border-border pl-4">
                <Button variant="ghost" size="sm" @click="selectAll" :disabled="isAllSelected" class="h-7 px-2 text-xs">全选</Button>
                <Button variant="ghost" size="sm" @click="invertSelection" class="h-7 px-2 text-xs">反选</Button>
                <Button variant="ghost" size="sm" @click="clearSelection" class="h-7 px-2 text-xs">取消</Button>
              </div>
            </div>
            <div class="flex items-center gap-2">
              <div class="flex items-center gap-1 bg-background/80 rounded-lg p-1">
                <Button size="sm" variant="ghost" @click="showBatchTagDialog = true" class="h-8 gap-1.5"><Tags class="w-4 h-4" /><span class="hidden sm:inline">标签</span></Button>
                <Button size="sm" variant="ghost" @click="showBatchCategoryDialog = true" class="h-8 gap-1.5"><LayoutGrid class="w-4 h-4" /><span class="hidden sm:inline">分类</span></Button>
                <Button size="sm" variant="ghost" @click="handleBatchAnalyze" :disabled="batchLoading" class="h-8 gap-1.5"><Sparkles class="w-4 h-4" /><span class="hidden sm:inline">分析</span></Button>
              </div>
              <Button size="sm" variant="destructive" @click="handleBatchDelete" :disabled="batchLoading" class="h-8 gap-1.5"><Trash2 class="w-4 h-4" /><span class="hidden sm:inline">删除</span></Button>
            </div>
          </div>
        </div>

        <!-- 状态显示 -->
        <div v-if="isLoading && !images.length" class="flex items-center justify-center py-20">
          <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
        </div>
        <div v-else-if="isError" class="text-center py-20">
          <p class="text-destructive mb-4">加载失败</p>
          <Button @click="() => refetch()">重试</Button>
        </div>
        <div v-else-if="!images.length" class="text-center py-20">
          <FolderOpen class="w-12 h-12 mx-auto text-muted-foreground mb-4" />
          <p class="text-muted-foreground">暂无上传的图片</p>
          <Button variant="outline" class="mt-4" @click="showUploadDialog = true">上传图片</Button>
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

        <!-- 分页 (Apple 风格简洁设计) -->
        <div v-if="total > 0" class="mt-8 flex items-center justify-center gap-3">
          <!-- 每页数量 -->
          <Select :model-value="String(pageSize)" @update:model-value="changePageSize">
            <SelectTrigger class="w-20 h-8 text-xs border-0 bg-muted/50 hover:bg-muted">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="20">20 张</SelectItem>
              <SelectItem value="40">40 张</SelectItem>
              <SelectItem value="60">60 张</SelectItem>
              <SelectItem value="100">100 张</SelectItem>
            </SelectContent>
          </Select>

          <div class="flex items-center gap-1 bg-muted/50 rounded-lg p-1">
            <!-- 上一页 -->
            <button
              class="w-8 h-8 flex items-center justify-center rounded-md transition-colors"
              :class="currentPage <= 1 ? 'text-muted-foreground/30 cursor-not-allowed' : 'text-foreground hover:bg-background'"
              :disabled="currentPage <= 1"
              @click="changePage(currentPage - 1)"
            >
              <ChevronLeft class="w-4 h-4" />
            </button>

            <!-- 可编辑页码 -->
            <div class="flex items-center gap-1 px-2">
              <input
                v-model="jumpPage"
                type="text"
                class="w-10 h-7 text-center text-sm bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-primary"
                :placeholder="String(currentPage)"
                @keyup.enter="handleJump"
                @blur="handleJump"
              />
              <span class="text-muted-foreground text-sm">/</span>
              <span class="text-muted-foreground text-sm">{{ totalPages }}</span>
            </div>

            <!-- 下一页 -->
            <button
              class="w-8 h-8 flex items-center justify-center rounded-md transition-colors"
              :class="currentPage >= totalPages ? 'text-muted-foreground/30 cursor-not-allowed' : 'text-foreground hover:bg-background'"
              :disabled="currentPage >= totalPages"
              @click="changePage(currentPage + 1)"
            >
              <ChevronRight class="w-4 h-4" />
            </button>
          </div>

          <!-- 总数提示 -->
          <span class="text-xs text-muted-foreground">共 {{ total }} 张</span>
        </div>
      </div>
    </main>


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
        <DialogHeader><DialogTitle>批量打标签</DialogTitle></DialogHeader>
        <div class="space-y-4 py-4">
          <div><label class="text-sm font-medium mb-2 block">标签（逗号分隔）</label><Input v-model="batchTags" placeholder="标签1, 标签2, 标签3" /></div>
          <div class="flex gap-4">
            <label class="flex items-center gap-2 cursor-pointer"><input type="radio" v-model="batchTagMode" value="add" class="accent-primary" /><span class="text-sm">追加标签</span></label>
            <label class="flex items-center gap-2 cursor-pointer"><input type="radio" v-model="batchTagMode" value="replace" class="accent-primary" /><span class="text-sm">替换标签</span></label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showBatchTagDialog = false">取消</Button>
          <Button @click="handleBatchTag" :disabled="batchLoading">确定</Button>
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
          <Button @click="handleBatchCategory" :disabled="batchLoading">确定</Button>
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
.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-10px); }
</style>
