<script setup lang="ts">
import { ref, computed } from 'vue'
import { PublicHeader } from '@/components/layout'
import { useImages } from '@/api/queries'
import type { ImageResponse, ImageSearchRequest } from '@/types'
import { Loader2, Filter, ChevronDown, ChevronLeft, ChevronRight, Image as ImageIcon } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import ImageGrid from '@/components/ImageGrid.vue'
import ImageFilterBar from '@/components/ImageFilterBar.vue'
import ImageDetailModal from '@/components/ImageDetailModal.vue'

// 筛选状态
const filters = ref({ category: 'all', resolution: 'all', keyword: '' })
const showFilters = ref(false)

// 分页
const pageSize = ref(40)
const currentPage = ref(1)

// 搜索参数
const searchParams = ref<ImageSearchRequest>({ size: pageSize.value, page: 1, sort_by: 'id', sort_desc: true })

// 查询数据
const { data: imageData, isLoading, isError, refetch } = useImages(searchParams)

const images = computed(() => imageData.value?.data || [])
const total = computed(() => imageData.value?.total || 0)
const totalPages = computed(() => Math.ceil(total.value / pageSize.value))

// 搜索和分页
function handleSearch() {
  currentPage.value = 1
  searchParams.value = {
    ...searchParams.value,
    keyword: filters.value.keyword || undefined,
    category_id: filters.value.category !== 'all' ? parseInt(filters.value.category) : undefined,
    resolution_id: filters.value.resolution !== 'all' ? parseInt(filters.value.resolution) : undefined,
    page: 1,
  }
}

function handleReset() {
  currentPage.value = 1
  searchParams.value = { size: pageSize.value, page: 1, sort_by: 'id', sort_desc: true }
}

function goToPage(page: number) {
  currentPage.value = page
  searchParams.value = { ...searchParams.value, page: page }
}

function changePageSize(size: unknown) {
  if (!size) return
  const newSize = typeof size === 'string' ? parseInt(size) : Number(size)
  if (isNaN(newSize)) return
  pageSize.value = newSize
  currentPage.value = 1
  searchParams.value = { ...searchParams.value, size: newSize, page: 1 }
}

// 页码跳转
const jumpPage = ref('')
function handleJump() {
  const page = parseInt(jumpPage.value)
  if (!isNaN(page) && page >= 1 && page <= totalPages.value) {
    goToPage(page)
  }
  jumpPage.value = ''
}

// 图片详情
const selectedImage = ref<ImageResponse | null>(null)
const selectedIndex = ref(0)

function openImage(image: ImageResponse, index: number) {
  selectedImage.value = image
  selectedIndex.value = index
}

function closeImage() { selectedImage.value = null }
function prevImage() {
  if (selectedIndex.value > 0) {
    selectedIndex.value--
    selectedImage.value = images.value[selectedIndex.value]
  }
}
function nextImage() {
  if (selectedIndex.value < images.value.length - 1) {
    selectedIndex.value++
    selectedImage.value = images.value[selectedIndex.value]
  }
}
</script>

<template>
  <div class="min-h-screen">
    <PublicHeader show-back />

    <main class="pt-20 pb-12 px-4 sm:px-6 lg:px-8">
      <div>
        <!-- 标题 -->
        <div class="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 class="text-2xl font-bold text-foreground flex items-center gap-2">
              <ImageIcon class="w-6 h-6 text-primary" />
              图库
            </h1>
            <p class="text-sm text-muted-foreground mt-1">共 {{ total }} 张图片</p>
          </div>
          <Button variant="outline" size="sm" @click="showFilters = !showFilters">
            <Filter class="w-4 h-4 mr-1" />筛选
            <ChevronDown class="w-4 h-4 ml-1 transition-transform" :class="{ 'rotate-180': showFilters }" />
          </Button>
        </div>

        <!-- 筛选栏 -->
        <Transition name="slide">
          <ImageFilterBar 
            v-if="showFilters" 
            v-model="filters" 
            class="mb-6"
            auto-search
            @search="handleSearch" 
            @reset="handleReset" 
          />
        </Transition>

        <!-- 状态显示 -->
        <div v-if="isLoading && !images.length" class="flex items-center justify-center py-20">
          <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
        </div>
        <div v-else-if="isError" class="text-center py-20">
          <p class="text-destructive mb-4">加载失败</p>
          <Button @click="() => refetch()">重试</Button>
        </div>
        <div v-else-if="!images.length" class="text-center py-20">
          <ImageIcon class="w-12 h-12 mx-auto text-muted-foreground mb-4" />
          <p class="text-muted-foreground">暂无图片</p>
        </div>

        <!-- 图片网格 -->
        <ImageGrid v-else :images="images" @select="openImage" />

        <!-- 分页 (Apple 风格简洁设计) -->
        <div v-if="total > 0" class="mt-8 flex items-center justify-center gap-3 max-w-7xl mx-auto">
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
              @click="goToPage(currentPage - 1)"
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
              @click="goToPage(currentPage + 1)"
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
      @updated="refetch"
    />
  </div>
</template>

<style scoped>
.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-10px); }
</style>
