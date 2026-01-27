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
  Search as SearchIcon, Loader2, Sparkles, Check, FolderOpen, SlidersHorizontal,
  Command,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isLoggedIn = computed(() => userStore.isLoggedIn)

// Tab 切换
type SearchMode = 'gallery' | 'smart'
const activeMode = ref<SearchMode>('gallery') // 默认改为图库浏览

// 监听 URL query 参数
watch(() => route.query.mode, (mode) => {
  if (mode === 'gallery' || mode === 'smart') {
    activeMode.value = mode
  }
}, { immediate: true })

// 切换模式时更新 URL
function switchMode(mode: SearchMode) {
  activeMode.value = mode
  router.replace({ query: { ...route.query, mode } })
}

// ==================== 图库浏览模式 ====================
const galleryFilters = ref({ category: 'all', resolution: 'all', keyword: '' })
const galleryPageSize = ref(40) // 默认更多
const galleryCurrentPage = ref(1)
const gallerySearchParams = ref<ImageSearchRequest>({ size: 40, page: 1, sort_by: 'id', sort_desc: true })

const { data: galleryData, isLoading: galleryLoading } = useImages(gallerySearchParams)
const galleryImages = computed(() => galleryData.value?.data || [])
const galleryTotal = computed(() => galleryData.value?.total || 0)
const galleryTotalPages = computed(() => Math.ceil(galleryTotal.value / galleryPageSize.value))

function handleGallerySearch() {
  galleryCurrentPage.value = 1
  gallerySearchParams.value = {
    ...gallerySearchParams.value,
    keyword: galleryFilters.value.keyword || undefined,
    category_id: galleryFilters.value.category !== 'all' ? parseInt(galleryFilters.value.category) : undefined,
    resolution_id: galleryFilters.value.resolution !== 'all' ? parseInt(galleryFilters.value.resolution) : undefined,
    page: 1,
  }
}

function handleGalleryReset() {
  galleryCurrentPage.value = 1
  galleryFilters.value = { category: 'all', resolution: 'all', keyword: '' }
  gallerySearchParams.value = { size: galleryPageSize.value, page: 1, sort_by: 'id', sort_desc: true }
}

function galleryGoToPage(page: number) {
  galleryCurrentPage.value = page
  gallerySearchParams.value = { ...gallerySearchParams.value, page: page }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function galleryChangePageSize(size: any) {
  const newSize = parseInt(size as string)
  if (isNaN(newSize)) return
  galleryPageSize.value = newSize
  galleryCurrentPage.value = 1
  gallerySearchParams.value = { ...gallerySearchParams.value, size: newSize, page: 1 }
}

// ==================== 智能搜索模式 ====================
const smartQuery = ref('')
const selectedTagIds = ref<Set<number>>(new Set())
const selectedCategoryId = ref<number | null>(null)
const selectedResolutionId = ref<number | null>(null)
const tagSearchKeyword = ref('')
const showTagDropdown = ref(false)
const showSimilarityPopover = ref(false)
const similarityThreshold = ref([0.15])

const RATE_LIMIT_KEY = 'imgtag_smart_search_last_time'
const RATE_LIMIT_SECONDS = 30

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
const { data: smartData, isLoading: smartLoading } = useSimilarSearch(smartSearchParams)
const smartResults = computed<ImageWithSimilarity[]>(() => smartData.value?.data || [])
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



function handleSmartSearch() {
  if (!hasAnySmartFilter.value) return

  if (!isLoggedIn.value) {
    const lastTime = localStorage.getItem(RATE_LIMIT_KEY)
    if (lastTime) {
      const elapsed = (Date.now() - parseInt(lastTime)) / 1000
      if (elapsed < RATE_LIMIT_SECONDS) {
        toast.warning(`请等待 ${Math.ceil(RATE_LIMIT_SECONDS - elapsed)} 秒后再次搜索`)
        return
      }
    }
    localStorage.setItem(RATE_LIMIT_KEY, String(Date.now()))
  }

  const tagNames = selectedTags.value.map(t => t.name)
  smartSearchParams.value = {
    text: smartQuery.value || '',
    tags: tagNames.length > 0 ? tagNames : undefined,
    category_id: selectedCategoryId.value || undefined,
    resolution_id: selectedResolutionId.value || undefined,
    page: 1,
    size: 50,
    threshold: similarityThreshold.value[0],
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

// 下拉关闭逻辑
function handleClickOutside(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.tag-dropdown-container')) {
    showTagDropdown.value = false
  }
  if (!target.closest('.similarity-popover-container')) {
    showSimilarityPopover.value = false
  }
}
watch([showTagDropdown, showSimilarityPopover], ([showTag, showSim]) => {
  if (showTag || showSim) document.addEventListener('click', handleClickOutside)
  else document.removeEventListener('click', handleClickOutside)
})

const currentImageList = computed(() => activeMode.value === 'gallery' ? galleryImages.value : smartResults.value)
</script>

<template>
  <div class="min-h-screen">
    <PublicHeader v-if="!isLoggedIn" />

    <main class="py-6 px-6 max-w-[1800px] mx-auto" :class="isLoggedIn ? '' : 'max-w-7xl pt-24'">

      <!-- 顶部模式切换与标题 -->
      <div class="mb-8 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-foreground flex items-center gap-2">
            <SearchIcon class="w-5 h-5 text-primary" />探索
          </h1>
          <p class="text-sm text-muted-foreground mt-1">发现与检索图片灵感</p>
        </div>

        <div class="inline-flex items-center p-1 rounded-lg bg-muted/40 border border-border/40">
          <button
            @click="switchMode('gallery')"
            class="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-300"
            :class="activeMode === 'gallery'
              ? 'bg-background text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'"
          >
            <FolderOpen class="w-3.5 h-3.5" />
            图库浏览
          </button>
          <button
            @click="switchMode('smart')"
            class="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-300"
            :class="activeMode === 'smart'
              ? 'bg-background text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'"
          >
            <Sparkles class="w-3.5 h-3.5" />
            智能搜索
          </button>
        </div>
      </div>

      <!-- ==================== 智能搜索视图 ==================== -->
      <Transition name="fade" mode="out-in">
        <div v-if="activeMode === 'smart'" class="max-w-5xl mx-auto w-full space-y-8">
          <!-- 搜索区域 -->
          <div class="relative w-full max-w-2xl mx-auto group">
            <div class="absolute inset-0 bg-gradient-to-r from-violet-500/20 to-purple-500/20 rounded-2xl blur-xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"></div>
            <div class="relative bg-background border border-border/50 rounded-2xl shadow-lg shadow-primary/5 transition-all duration-300 focus-within:shadow-xl focus-within:shadow-primary/10 focus-within:border-primary/30">
              <SearchIcon class="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground group-focus-within:text-primary transition-colors" />
              <input
                v-model="smartQuery"
                type="text"
                placeholder="描述画面，例如：夕阳下的海边城市..."
                class="w-full pl-14 pr-16 py-4 text-base bg-transparent border-none focus:outline-none focus:ring-0 placeholder:text-muted-foreground/70"
                @keyup.enter="handleSmartSearch"
              />
              <div class="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-2 pointer-events-none">
                 <span class="text-xs text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded border border-border/50">↵</span>
              </div>
            </div>
          </div>

          <!-- 筛选控制栏 (Smart Mode) -->
          <div class="flex flex-wrap items-center justify-center gap-3">
             <!-- 分类 -->
             <Select :model-value="selectedCategoryId ? String(selectedCategoryId) : 'all'" @update:model-value="v => selectedCategoryId = v === 'all' ? null : Number(v)">
               <SelectTrigger class="w-[140px] h-9 bg-muted/30 border-border/50 hover:bg-muted/50 rounded-full text-xs">
                 <SelectValue placeholder="全部分类" />
               </SelectTrigger>
               <SelectContent>
                 <SelectItem value="all">全部分类</SelectItem>
                 <SelectItem v-for="cat in categoryTags" :key="cat.id" :value="String(cat.id)">{{ cat.name }}</SelectItem>
               </SelectContent>
             </Select>

             <!-- 分辨率 -->
             <Select :model-value="selectedResolutionId ? String(selectedResolutionId) : 'all'" @update:model-value="v => selectedResolutionId = v === 'all' ? null : Number(v)">
               <SelectTrigger class="w-[140px] h-9 bg-muted/30 border-border/50 hover:bg-muted/50 rounded-full text-xs">
                 <SelectValue placeholder="全部分辨率" />
               </SelectTrigger>
               <SelectContent>
                 <SelectItem value="all">全部分辨率</SelectItem>
                 <SelectItem v-for="res in resolutionTags" :key="res.id" :value="String(res.id)">{{ res.name }}</SelectItem>
               </SelectContent>
             </Select>

             <!-- 相似度 (Slider Popover) -->
             <div class="relative similarity-popover-container">
               <button
                 @click="showSimilarityPopover = !showSimilarityPopover"
                 class="h-9 px-4 flex items-center gap-2 bg-muted/30 border border-border/50 hover:bg-muted/50 rounded-full text-xs text-muted-foreground hover:text-foreground transition-colors"
                 :class="similarityThreshold[0] !== 0.15 && 'text-primary bg-primary/5 border-primary/20'"
               >
                 <SlidersHorizontal class="w-3.5 h-3.5" />
                 <span>相似度 {{ Math.round(similarityThreshold[0] * 100) }}%</span>
               </button>

               <div v-if="showSimilarityPopover" class="absolute z-50 top-full mt-2 w-64 bg-popover border border-border rounded-xl shadow-xl p-4">
                 <div class="flex items-center justify-between mb-4">
                   <span class="text-xs font-medium text-foreground">匹配阈值</span>
                   <span class="text-xs font-mono text-muted-foreground">{{ Math.round(similarityThreshold[0] * 100) }}%</span>
                 </div>
                 <div class="relative flex items-center h-4">
                   <input
                     type="range"
                     min="0.1"
                     max="0.9"
                     step="0.05"
                     v-model.number="similarityThreshold[0]"
                     class="w-full h-1.5 bg-secondary rounded-full appearance-none cursor-pointer accent-primary hover:accent-primary/80 transition-all"
                   />
                 </div>
                 <div class="flex justify-between text-[10px] text-muted-foreground mt-2 px-0.5">
                   <span>广泛</span>
                   <span>平衡</span>
                   <span>严格</span>
                 </div>
               </div>
             </div>

             <!-- 标签选择器 -->
             <div class="relative tag-dropdown-container">
                <button
                  @click="showTagDropdown = !showTagDropdown"
                  class="h-9 px-4 flex items-center gap-2 bg-muted/30 border border-border/50 hover:bg-muted/50 rounded-full text-xs text-muted-foreground hover:text-foreground transition-colors"
                  :class="selectedTagIds.size > 0 && 'text-primary bg-primary/5 border-primary/20'"
                >
                  <Sparkles class="w-3.5 h-3.5" />
                  {{ selectedTagIds.size === 0 ? '选择标签' : `已选 ${selectedTagIds.size}` }}
                </button>
                <!-- 下拉省略，保持原逻辑但优化样式 -->
                <div v-if="showTagDropdown" class="absolute z-50 top-full mt-2 w-64 bg-popover border border-border rounded-xl shadow-xl p-2 max-h-64 overflow-hidden flex flex-col">
                   <input
                      v-model="tagSearchKeyword"
                      placeholder="搜索..."
                      class="w-full px-2 py-1.5 bg-muted/50 rounded-lg text-xs mb-2 focus:outline-none"
                    />
                    <div class="overflow-y-auto flex-1 space-y-0.5">
                       <button
                         v-for="tag in availableTags"
                         :key="tag.id"
                         @click="toggleTagSelection(tag)"
                         class="w-full flex items-center justify-between px-2 py-1.5 rounded-md hover:bg-accent text-xs text-left"
                       >
                         <span>{{ tag.name }}</span>
                         <Check v-if="selectedTagIds.has(tag.id)" class="w-3 h-3 text-primary" />
                       </button>
                    </div>
                </div>
             </div>

             <Button
                size="sm"
                class="rounded-full h-9 px-6 bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/20"
                @click="handleSmartSearch"
                :disabled="smartLoading"
              >
                <Loader2 v-if="smartLoading" class="w-4 h-4 mr-2 animate-spin" />
                <Sparkles v-else class="w-4 h-4 mr-2" />
                开始搜索
             </Button>
          </div>

          <!-- 搜索结果展示 -->
          <div v-if="smartResults.length > 0" class="space-y-4">
             <div class="flex items-center justify-between px-2">
               <h3 class="text-lg font-semibold flex items-center gap-2">
                 搜索结果
                 <span class="text-xs font-normal text-muted-foreground bg-muted px-2 py-0.5 rounded-full">{{ smartTotal }}</span>
               </h3>
               <Button variant="ghost" size="sm" class="text-muted-foreground" @click="clearSmartSearch">清除结果</Button>
             </div>
             <ImageGrid :images="smartResults" :show-similarity="hasVectorSearch" @select="openSmartImage" />
          </div>

          <!-- 初始/空状态 -->
          <div v-else-if="!smartLoading" class="flex flex-col items-center justify-center py-20 text-center space-y-4 opacity-50">
             <div class="w-16 h-16 rounded-3xl bg-muted/30 flex items-center justify-center">
               <Command class="w-8 h-8 text-muted-foreground" />
             </div>
             <p class="text-muted-foreground">输入描述，开始 AI 探索之旅</p>
          </div>
        </div>

        <!-- ==================== 图库浏览视图 ==================== -->
        <div v-else class="space-y-6">
           <!-- 筛选栏 (自动展开) -->
           <ImageFilterBar
             v-model="galleryFilters"
             auto-search
             @search="handleGallerySearch"
             @reset="handleGalleryReset"
           />

           <div v-if="galleryLoading && !galleryImages.length" class="flex justify-center py-20">
              <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
           </div>

           <ImageGrid v-else :images="galleryImages" @select="openGalleryImage" />

           <!-- 分页 -->
           <div v-if="galleryTotal > 0" class="flex flex-col sm:flex-row items-center justify-between gap-4 py-4 border-t border-border/40">
             <div class="text-sm text-muted-foreground">
               显示 {{ (galleryCurrentPage - 1) * galleryPageSize + 1 }} - {{ Math.min(galleryCurrentPage * galleryPageSize, galleryTotal) }} 共 {{ galleryTotal }}
             </div>
             <div class="flex items-center gap-2">
               <Select :model-value="String(galleryPageSize)" @update:model-value="galleryChangePageSize">
                  <SelectTrigger class="w-[100px] h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="20">20 / 页</SelectItem>
                    <SelectItem value="40">40 / 页</SelectItem>
                    <SelectItem value="60">60 / 页</SelectItem>
                    <SelectItem value="100">100 / 页</SelectItem>
                  </SelectContent>
               </Select>
               <div class="flex items-center rounded-md border border-border/50 overflow-hidden">
                 <button
                   class="px-3 py-1.5 hover:bg-muted disabled:opacity-50 border-r border-border/50 transition-colors"
                   :disabled="galleryCurrentPage <= 1"
                   @click="galleryGoToPage(galleryCurrentPage - 1)"
                 >
                   上一页
                 </button>
                 <button
                   class="px-3 py-1.5 hover:bg-muted disabled:opacity-50 transition-colors"
                   :disabled="galleryCurrentPage >= galleryTotalPages"
                   @click="galleryGoToPage(galleryCurrentPage + 1)"
                 >
                   下一页
                 </button>
               </div>
             </div>
           </div>
        </div>
      </Transition>

    </main>

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
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
