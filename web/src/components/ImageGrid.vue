<script setup lang="ts">
import { ref } from 'vue'
import type { ImageResponse, ImageWithSimilarity } from '@/types'
import { Copy } from 'lucide-vue-next'
import CopyToast from '@/components/ui/CopyToast.vue'

type ImageItem = ImageResponse | ImageWithSimilarity

interface Props {
  images: ImageItem[]
  selectMode?: boolean
  selectedIds?: Set<number>
  showPendingBadge?: boolean
  showSimilarity?: boolean  // 是否显示相似度
}

const props = withDefaults(defineProps<Props>(), {
  selectMode: false,
  selectedIds: () => new Set<number>(),
  showPendingBadge: false,
  showSimilarity: false,
})

const emit = defineEmits<{
  select: [image: ImageItem, index: number]
  toggleSelect: [id: number]
}>()

// 复制成功提示
const showCopied = ref(false)

function handleClick(image: ImageItem, index: number) {
  if (props.selectMode) {
    emit('toggleSelect', image.id)
  } else {
    emit('select', image, index)
  }
}

function getImageUrl(url: string): string {
  if (url.startsWith('http')) return url
  return url
}

// 复制图片地址
async function copyImageUrl(event: Event, url: string) {
  event.stopPropagation()
  try {
    await navigator.clipboard.writeText(url)
    showCopied.value = true
  } catch {
    // 静默失败
  }
}

// 根据图片分辨率计算合适的显示样式
function getImageSizeClass(image: ImageItem): string {
  const w = image.width || 0
  const h = image.height || 0
  const ratio = w / (h || 1)
  
  if (ratio > 2) return 'max-h-48'
  if (ratio > 1.5) return 'max-h-56'
  if (ratio >= 0.7) return ''
  if (ratio >= 0.5) return 'max-h-80'
  return 'max-h-96'
}

function isPending(image: ImageItem): boolean {
  return !image.description && (!image.tags || image.tags.length === 0)
}

// 获取相似度（如果有的话）
function getSimilarity(image: ImageItem): number | undefined {
  return 'similarity' in image ? image.similarity : undefined
}

// 相似度颜色等级
function getSimilarityColor(sim: number): string {
  if (sim >= 0.8) return 'bg-emerald-500'
  if (sim >= 0.6) return 'bg-green-500'
  if (sim >= 0.4) return 'bg-yellow-500'
  return 'bg-orange-500'
}
</script>

<template>
  <div class="columns-2 sm:columns-3 lg:columns-4 xl:columns-5 gap-4 space-y-4">
    <div 
      v-for="(image, index) in images" 
      :key="image.id"
      class="break-inside-avoid relative group cursor-pointer transition-transform duration-200"
      :class="{ 
        'scale-[0.97]': selectMode && selectedIds.has(image.id),
        'hover:scale-[0.98]': selectMode && !selectedIds.has(image.id)
      }"
      @click="handleClick(image, index)"
    >
      <!-- 选择框 -->
      <div 
        v-if="selectMode"
        class="absolute top-2 left-2 z-10"
        @click.stop="emit('toggleSelect', image.id)"
      >
        <div 
          class="w-6 h-6 rounded-lg flex items-center justify-center transition-all shadow-lg"
          :class="selectedIds.has(image.id) 
            ? 'bg-green-500 text-white' 
            : 'bg-black/50 border-2 border-white/60 text-transparent hover:border-green-400'"
        >
          <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
          </svg>
        </div>
      </div>

      <!-- 待分析标记 -->
      <div 
        v-if="showPendingBadge && isPending(image)"
        class="absolute top-2 right-2 z-10 px-2 py-0.5 bg-amber-500 text-white text-xs rounded-full"
      >
        待分析
      </div>

      <!-- 相似度徽章 -->
      <div 
        v-if="showSimilarity && getSimilarity(image) !== undefined"
        class="absolute top-2 left-2 z-10 px-2 py-0.5 text-white text-xs rounded-full font-medium shadow-lg"
        :class="getSimilarityColor(getSimilarity(image)!)"
        :title="`相似度: ${(getSimilarity(image)! * 100).toFixed(1)}%`"
      >
        {{ (getSimilarity(image)! * 100).toFixed(0) }}%
      </div>

      <div 
        class="overflow-hidden rounded-xl bg-muted"
        :class="getImageSizeClass(image)"
      >
        <img 
          :src="getImageUrl(image.image_url)" 
          :alt="image.description || '图片'"
          class="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
          loading="lazy"
        />
      </div>

      <!-- Hover 遮罩 -->
      <div 
        v-if="!selectMode"
        class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity rounded-xl"
      >
        <!-- 复制按钮（右下角）- 悬浮时放大变色 -->
        <button
          class="absolute bottom-3 right-3 p-1.5 bg-black/60 hover:bg-primary hover:scale-110 rounded-lg transition-all z-10"
          title="复制图片地址"
          @click="copyImageUrl($event, image.image_url)"
        >
          <Copy class="w-4 h-4 text-white" />
        </button>
        <!-- 底部信息（右侧留出复制按钮空间） -->
        <div class="absolute inset-x-0 bottom-0 p-3 pr-12">
          <p v-if="image.description" class="text-white text-sm font-medium truncate">
            {{ image.description }}
          </p>
          <div class="flex flex-wrap gap-1 mt-1">
            <span 
              v-for="tag in image.tags?.slice(0, 3)" 
              :key="tag.name"
              class="px-1.5 py-0.5 bg-white/20 text-white text-xs rounded-full"
            >
              {{ tag.name }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 复制成功提示 -->
    <CopyToast v-model:show="showCopied" />
  </div>
</template>
