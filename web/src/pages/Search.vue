<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PublicHeader } from '@/components/layout'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import ImageGrid from '@/components/ImageGrid.vue'
import ImageFilterBar from '@/components/ImageFilterBar.vue'
import ImageDetailModal from '@/components/ImageDetailModal.vue'
import { useImages, useTags, useSimilarSearch, useCategories, useResolutions } from '@/api/queries'
import { useUserStore } from '@/stores'
import type { ImageResponse, ImageWithSimilarity, SimilarSearchRequest, ImageSearchRequest, Tag } from '@/types'
import { 
  Search as SearchIcon, X, Image as ImageIcon, Loader2, Sparkles, 
  ChevronDown, Tag as TagIcon, Check, FolderOpen, Filter 
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isLoggedIn = computed(() => userStore.isLoggedIn)

// Tab 切换
type SearchMode = 'gallery' | 'smart'
const activeMode = ref<SearchMode>('gallery')

// 监听 URL query 参数
watch(() => route.query.mode, (mode) => {
  activeMode.value = mode === 'smart' ? 'smart' : 'gallery'
}, { immediate: true })

// 切换模式时更新 URL
function switchMode(mode: SearchMode) {
  activeMode.value = mode
  router.replace({ query: { mode } })
}

// ==================== 图库浏览模式 ====================
const galleryFilters = ref({ category: 'all', resolution: 'all', keyword: '' })
const showGalleryFilters = ref(false)
const galleryPageSize = ref(40)
const galleryCurrentPage = ref(1)
const gallerySearchParams = ref<ImageSearchRequest>({ limit: 40, offset: 0, sort_by: 'id', sort_desc: true })

const { data: galleryData, isLoading: galleryLoading, isError: galleryError, refetch: galleryRefetch } = useImages(gallerySearchParams)
const galleryImages = computed(() => galleryData.value?.images || [])
const galleryTotal = computed(() => galleryData.value?.total || 0)
const galleryTotalPages = computed(() => Math.ceil(galleryTotal.value / galleryPageSize.value))

function handleGallerySearch() {
  galleryCurrentPage.value = 1
  gallerySearchParams.value = {
    ...gallerySearchParams.value,
    keyword: galleryFilters.value.keyword || undefined,
    category_id: galleryFilters.value.category !== 'all' ? parseInt(galleryFilters.value.category) : undefined,
    resolution_id: galleryFilters.value.resolution !== 'all' ? parseInt(galleryFilters.value.resolution) : undefined,
    offset: 0,
  }
}

function handleGalleryReset() {
  galleryCurrentPage.value = 1
  galleryFilters.value = { category: 'all', resolution: 'all', keyword: '' }
  gallerySearchParams.value = { limit: galleryPageSize.value, offset: 0, sort_by: 'id', sort_desc: true }
}

function galleryGoToPage(page: number) {
  galleryCurrentPage.value = page
  gallerySearchParams.value = { ...gallerySearchParams.value, offset: (page - 1) * galleryPageSize.value }
}

function galleryChangePageSize(size: unknown) {
  if (!size) return
  const newSize = typeof size === 'string' ? parseInt(size) : Number(size)
  if (isNaN(newSize)) return
  galleryPageSize.value = newSize
  galleryCurrentPage.value = 1
  gallerySearchParams.value = { ...gallerySearchParams.value, limit: newSize, offset: 0 }
}

// ==================== 智能搜索模式 ====================
const smartQuery = ref('')
const selectedTagIds = ref<Set<number>>(new Set())
const selectedCategoryId = ref<number | null>(null)
const selectedResolutionId = ref<number | null>(null)
const tagSearchKeyword = ref('')
const showTagDropdown = ref(false)

const { data: tagsData } = useTags(200)
const { data: categoriesData } = useCategories()
const { data: resolutionsData } = useResolutions()

const categoryTags = computed<Tag[]>(() => categoriesData.value || [])
const resolutionTags = computed<Tag[]>(() => resolutionsData.value || [])
const availableTags = computed<Tag[]>(() => {
  const tags = tagsData.value?.filter(t => t.level === 2) || []
  if (!tagSearchKeyword.value) return tags.slice(0, 50)
  const kw = tagSearchKeyword.value.toLowerCase()
  return tags.filter(t => t.name.toLowerCase().includes(kw)).slice(0, 50)
})

const selectedTags = computed<Tag[]>(() => {
  if (!tagsData.value) return []
  return tagsData.value.filter(t => selectedTagIds.value.has(t.id))
})

const smartSearchParams = ref<SimilarSearchRequest | null>(null)
const { data: smartData, isLoading: smartLoading, isFetching: smartFetching } = useSimilarSearch(smartSearchParams)
const smartResults = computed<ImageWithSimilarity[]>(() => smartData.value?.images || [])
const smartTotal = computed(() => smartData.value?.total || 0)
const hasVectorSearch = computed(() => !!smartSearchParams.value?.text)

const hasAnySmartFilter = computed(() => 
  smartQuery.value || 
  selectedTagIds.value.size > 0 || 
  selectedCategoryId.value !== null || 
  selectedResolutionId.value !== null
)

function toggleTagSelection(tag: Tag) {
  const newSet = new Set(selectedTagIds.value)
  newSet.has(tag.id) ? newSet.delete(tag.id) : newSet.add(tag.id)
  selectedTagIds.value = newSet
}

function removeTag(tagId: number) {
  const newSet = new Set(selectedTagIds.value)
  newSet.delete(tagId)
  selectedTagIds.value = newSet
}

function handleSmartSearch() {
  if (!hasAnySmartFilter.value) return
  const tagNames = selectedTags.value.map(t => t.name)
  smartSearchParams.value = {
    text: smartQuery.value || '',
    tags: tagNames.length > 0 ? tagNames : undefined,
    category_id: selectedCategoryId.value || undefined,
    resolution_id: selectedResolutionId.value || undefined,
    limit: 50,
    threshold: 0.15,
    vector_weight: 0.7,
    tag_weight: 0.3,
  }
}

function clearSmartSearch() {
  smartQuery.value = ''
  selectedTagIds.value = new Set()
  selectedCategoryId.value = null
  selectedResolutionId.value = null
  tagSearchKeyword.value = ''
  smartSearchParams.value = null
}

// ==================== 共享：图片详情 ====================
const selectedImage = ref<ImageResponse | ImageWithSimilarity | null>(null)
const selectedIndex = ref(0)

function openGalleryImage(image: ImageResponse, index: number) {
  selectedImage.value = image
  selectedIndex.value = index
}

function openSmartImage(_image: ImageResponse, index: number) {
  selectedImage.value = smartResults.value[index] || null
  selectedIndex.value = index
}

function closeImage() { selectedImage.value = null }

function prevImage() {
  if (selectedIndex.value > 0) {
    selectedIndex.value--
    selectedImage.value = activeMode.value === 'gallery' 
      ? galleryImages.value[selectedIndex.value]
      : smartResults.value[selectedIndex.value]
  }
}

function nextImage() {
  const list = activeMode.value === 'gallery' ? galleryImages.value : smartResults.value
  if (selectedIndex.value < list.length - 1) {
    selectedIndex.value++
    selectedImage.value = list[selectedIndex.value]
  }
}

// 点击外部关闭下拉
function handleClickOutside(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.tag-dropdown-container')) {
    showTagDropdown.value = false
  }
}

watch(showTagDropdown, (show) => {
  if (show) {
    document.addEventListener('click', handleClickOutside)
  } else {
    document.removeEventListener('click', handleClickOutside)
  }
})

const currentImageList = computed(() => activeMode.value === 'gallery' ? galleryImages.value : smartResults.value)
</script>

<template>
  <div class="min-h-screen">
    <!-- 未登录时显示公共头部 -->
    <PublicHeader v-if="!isLoggedIn" />

    <main :class="isLoggedIn ? 'py-6 px-6' : 'pt-20 pb-12 px-4 sm:px-6 lg:px-8'">
      <div :class="isLoggedIn ? 'max-w-7xl' : 'max-w-7xl mx-auto'">
        <!-- 标题和模式切换 -->
        <div class="mb-6">
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 class="text-xl font-bold text-foreground flex items-center gap-2">
                <SearchIcon class="w-5 h-5 text-primary" />
                图片探索
              </h1>
              <p class="text-sm text-muted-foreground mt-1">浏览图库或使用 AI 智能搜索</p>
            </div>
            
            <!-- 模式切换 Tab -->
            <div class="flex items-center bg-muted/50 rounded-full p-1">
              <button
                @click="switchMode('gallery')"
                class="flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-full transition-all"
                :class="activeMode === 'gallery' 
                  ? 'bg-background text-foreground shadow-sm' 
                  : 'text-muted-foreground hover:text-foreground'"
              >
                <FolderOpen class="w-4 h-4" />
                图库浏览
              </button>
              <button
                @click="switchMode('smart')"
                class="flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-full transition-all"
                :class="activeMode === 'smart' 
                  ? 'bg-gradient-to-r from-violet-500 to-purple-600 text-white shadow-sm' 
                  : 'text-muted-foreground hover:text-foreground'"
              >
                <Sparkles class="w-4 h-4" />
                智能搜索
              </button>
            </div>
          </div>
        </div>

        <!-- ==================== 图库浏览模式 ==================== -->
        <template v-if="activeMode === 'gallery'">
          <!-- 筛选按钮 -->
          <div class="flex items-center justify-between mb-4">
            <p class="text-sm text-muted-foreground">共 {{ galleryTotal }} 张图片</p>
            <Button variant="outline" size="sm" @click="showGalleryFilters = !showGalleryFilters">
              <Filter class="w-4 h-4 mr-1" />筛选
              <ChevronDown class="w-4 h-4 ml-1 transition-transform" :class="{ 'rotate-180': showGalleryFilters }" />
            </Button>
          </div>

          <!-- 筛选栏 -->
          <Transition name="slide">
            <ImageFilterBar 
              v-if="showGalleryFilters" 
              v-model="galleryFilters" 
              class="mb-6"
              auto-search
              @search="handleGallerySearch" 
              @reset="handleGalleryReset" 
            />
          </Transition>

          <!-- 加载状态 -->
          <div v-if="galleryLoading && !galleryImages.length" class="flex items-center justify-center py-20">
            <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
          </div>
          <div v-else-if="galleryError" class="text-center py-20">
            <p class="text-destructive mb-4">加载失败</p>
            <Button @click="() => galleryRefetch()">重试</Button>
          </div>
          <div v-else-if="!galleryImages.length" class="text-center py-20">
            <ImageIcon class="w-12 h-12 mx-auto text-muted-foreground mb-4" />
            <p class="text-muted-foreground">暂无图片</p>
          </div>

          <!-- 图片网格 -->
          <ImageGrid v-else :images="galleryImages" @select="openGalleryImage" />

          <!-- 分页 -->
          <div v-if="galleryTotal > 0" class="mt-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div class="text-sm text-muted-foreground">第 {{ galleryCurrentPage }} / {{ galleryTotalPages }} 页</div>
            <div class="flex items-center gap-2">
              <Select :model-value="String(galleryPageSize)" @update:model-value="galleryChangePageSize">
                <SelectTrigger class="w-24"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="20">20 张</SelectItem>
                  <SelectItem value="40">40 张</SelectItem>
                  <SelectItem value="60">60 张</SelectItem>
                  <SelectItem value="100">100 张</SelectItem>
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" @click="galleryGoToPage(galleryCurrentPage - 1)" :disabled="galleryCurrentPage <= 1">上一页</Button>
              <Button variant="outline" size="sm" @click="galleryGoToPage(galleryCurrentPage + 1)" :disabled="galleryCurrentPage >= galleryTotalPages">下一页</Button>
            </div>
          </div>
        </template>

        <!-- ==================== 智能搜索模式 ==================== -->
        <template v-else>
          <!-- 搜索卡片 -->
          <div class="bg-card/50 border border-border/50 rounded-2xl p-5 mb-6">
            <!-- 主搜索框 -->
            <div class="relative mb-4">
              <SearchIcon class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
              <input
                v-model="smartQuery"
                type="text"
                placeholder="输入描述文字，如：蓝天白云、城市夜景..."
                class="w-full pl-12 pr-12 py-3 bg-muted/50 border border-border/50 rounded-xl text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                @keyup.enter="handleSmartSearch"
              />
              <button
                v-if="smartQuery"
                @click="smartQuery = ''"
                class="absolute right-4 top-1/2 -translate-y-1/2 p-1 hover:bg-accent rounded-lg"
              >
                <X class="w-4 h-4 text-muted-foreground" />
              </button>
            </div>

            <!-- 筛选：分类 + 分辨率 + 标签 -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
              <div>
                <label class="block text-xs text-muted-foreground mb-1.5">主分类</label>
                <select
                  v-model="selectedCategoryId"
                  class="w-full px-3 py-2 bg-muted/50 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  <option :value="null">全部</option>
                  <option v-for="cat in categoryTags" :key="cat.id" :value="cat.id">{{ cat.name }}</option>
                </select>
              </div>
              <div>
                <label class="block text-xs text-muted-foreground mb-1.5">分辨率</label>
                <select
                  v-model="selectedResolutionId"
                  class="w-full px-3 py-2 bg-muted/50 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  <option :value="null">全部</option>
                  <option v-for="res in resolutionTags" :key="res.id" :value="res.id">{{ res.name }}</option>
                </select>
              </div>
              <div class="tag-dropdown-container">
                <label class="block text-xs text-muted-foreground mb-1.5">标签</label>
                <button
                  @click.stop="showTagDropdown = !showTagDropdown"
                  class="w-full px-3 py-2 bg-muted/50 border border-border/50 rounded-lg text-left text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 flex items-center justify-between"
                >
                  <span :class="selectedTagIds.size === 0 ? 'text-muted-foreground' : 'text-foreground'">
                    {{ selectedTagIds.size === 0 ? '选择标签...' : `已选 ${selectedTagIds.size} 个` }}
                  </span>
                  <ChevronDown class="w-4 h-4 text-muted-foreground" :class="{ 'rotate-180': showTagDropdown }" />
                </button>
                
                <!-- 标签下拉 -->
                <div
                  v-if="showTagDropdown"
                  class="absolute z-50 mt-1 w-72 bg-popover border border-border rounded-xl shadow-xl max-h-64 overflow-hidden"
                >
                  <div class="p-2 border-b border-border">
                    <div class="relative">
                      <SearchIcon class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                      <input
                        v-model="tagSearchKeyword"
                        type="text"
                        placeholder="搜索标签..."
                        class="w-full pl-8 pr-3 py-1.5 bg-muted/50 border border-border/50 rounded-lg text-xs focus:outline-none"
                        @click.stop
                      />
                    </div>
                  </div>
                  <div class="overflow-y-auto max-h-48 p-1.5">
                    <button
                      v-for="tag in availableTags"
                      :key="tag.id"
                      @click.stop="toggleTagSelection(tag)"
                      class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg hover:bg-accent text-left text-sm"
                    >
                      <div class="w-4 h-4 rounded border flex items-center justify-center"
                        :class="selectedTagIds.has(tag.id) ? 'bg-primary border-primary' : 'border-border'"
                      >
                        <Check v-if="selectedTagIds.has(tag.id)" class="w-3 h-3 text-primary-foreground" />
                      </div>
                      <span class="flex-1 truncate">{{ tag.name }}</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 已选标签 -->
            <div v-if="selectedTags.length > 0" class="flex flex-wrap gap-1.5 mb-4">
              <div
                v-for="tag in selectedTags"
                :key="tag.id"
                class="inline-flex items-center gap-1 px-2 py-1 bg-primary/10 text-primary rounded-full text-xs"
              >
                <TagIcon class="w-3 h-3" />
                {{ tag.name }}
                <button @click="removeTag(tag.id)" class="hover:bg-primary/20 rounded-full">
                  <X class="w-3 h-3" />
                </button>
              </div>
            </div>

            <!-- 搜索按钮 -->
            <div class="flex gap-2">
              <Button 
                size="sm"
                class="gap-1.5 bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700"
                :disabled="smartLoading || smartFetching || !hasAnySmartFilter"
                @click="handleSmartSearch"
              >
                <Loader2 v-if="smartLoading || smartFetching" class="w-4 h-4 animate-spin" />
                <Sparkles v-else class="w-4 h-4" />
                智能搜索
              </Button>
              <Button 
                v-if="smartSearchParams || hasAnySmartFilter"
                variant="outline" 
                size="sm"
                @click="clearSmartSearch"
              >
                清除
              </Button>
            </div>
          </div>

          <!-- 搜索结果 -->
          <div v-if="smartResults.length > 0">
            <p class="text-sm text-muted-foreground mb-4">找到 {{ smartTotal }} 张相关图片</p>
            <ImageGrid 
              :images="smartResults"
              :show-similarity="hasVectorSearch"
              @select="openSmartImage"
            />
          </div>

          <!-- 空状态 -->
          <div v-else-if="smartSearchParams && !smartLoading" class="text-center py-16">
            <ImageIcon class="w-12 h-12 mx-auto text-muted-foreground mb-4" />
            <p class="text-muted-foreground">未找到匹配的图片</p>
          </div>

          <!-- 初始提示 -->
          <div v-else-if="!smartLoading" class="text-center py-16">
            <div class="w-16 h-16 bg-gradient-to-br from-violet-500/10 to-purple-600/10 rounded-2xl flex items-center justify-center mx-auto mb-4">
              <Sparkles class="w-8 h-8 text-violet-500" />
            </div>
            <p class="text-muted-foreground">输入描述或选择筛选条件，AI 将匹配最相关的图片</p>
          </div>
        </template>
      </div>
    </main>

    <!-- 图片详情弹窗 -->
    <ImageDetailModal
      :image="selectedImage"
      :can-navigate-prev="selectedIndex > 0"
      :can-navigate-next="selectedIndex < currentImageList.length - 1"
      :current-index="selectedIndex"
      :total-count="currentImageList.length"
      @close="closeImage"
      @prev="prevImage"
      @next="nextImage"
    />
  </div>
</template>

<style scoped>
.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-10px); }
</style>
