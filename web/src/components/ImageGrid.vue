<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ImageResponse, ImageWithSimilarity, TagWithSource } from '@/types'
import { Copy, X, Plus, Loader2 } from 'lucide-vue-next'
import CopyToast from '@/components/ui/CopyToast.vue'
import { useAddImageTag, useRemoveImageTag, useTags } from '@/api/queries'
import { toast } from 'vue-sonner'
import { getErrorMessage } from '@/utils/api-error'

type ImageItem = ImageResponse | ImageWithSimilarity

interface Props {
  images: ImageItem[]
  selectMode?: boolean
  selectedIds?: Set<number>
  showPendingBadge?: boolean
  showSimilarity?: boolean
  showLabelsAlways?: boolean
  editable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  selectMode: false,
  selectedIds: () => new Set<number>(),
  showPendingBadge: false,
  showSimilarity: false,
  showLabelsAlways: false,
  editable: false,
})

const emit = defineEmits<{
  select: [image: ImageItem, index: number]
  toggleSelect: [id: number]
  tagsUpdated: [imageId: number, newTags: TagWithSource[]]
}>()

// API
const addTagMutation = useAddImageTag()
const removeTagMutation = useRemoveImageTag()
const { data: allTags } = useTags(200)

// 复制成功提示
const showCopied = ref(false)

// 编辑状态
const editingImageId = ref<number | null>(null)
const newTagInput = ref('')
const isComposing = ref(false)
const tagInputRef = ref<HTMLInputElement | null>(null)

// 操作中的标签（防止重复提交）
const pendingTagOps = ref<Set<string>>(new Set())

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

async function copyImageUrl(event: Event, url: string) {
  event.stopPropagation()
  try {
    await navigator.clipboard.writeText(url)
    showCopied.value = true
  } catch {
    // 静默失败
  }
}

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

function getSimilarity(image: ImageItem): number | undefined {
  return 'similarity' in image ? image.similarity : undefined
}

function getSimilarityColor(sim: number): string {
  if (sim >= 0.8) return 'bg-emerald-500'
  if (sim >= 0.6) return 'bg-green-500'
  if (sim >= 0.4) return 'bg-yellow-500'
  return 'bg-orange-500'
}

// 标签样式
function getTagClass(tag: TagWithSource): string {
  if (tag.level === 0) {
    return 'bg-violet-500/80 text-white'
  } else if (tag.level === 1) {
    return 'bg-sky-500/80 text-white'
  }
  return 'bg-muted text-muted-foreground hover:bg-muted/80'
}

function isEditableTag(tag: TagWithSource): boolean {
  return tag.level === 2 || tag.level === undefined
}

// 检查是否正在操作某个标签
function isTagPending(imageId: number, tagId: number): boolean {
  return pendingTagOps.value.has(`${imageId}-${tagId}`)
}

// 开始编辑标签
async function startEditTag(event: Event, imageId: number) {
  event.stopPropagation()
  editingImageId.value = imageId
  newTagInput.value = ''
  await new Promise(r => setTimeout(r, 50))
  tagInputRef.value?.focus()
}

// 取消编辑
function cancelEdit(event: Event) {
  event.stopPropagation()
  editingImageId.value = null
  newTagInput.value = ''
}

// 删除标签（单条删除）
async function removeTag(event: Event, image: ImageItem, tag: TagWithSource) {
  event.stopPropagation()
  if (!props.editable || !tag.id) return
  
  const opKey = `${image.id}-${tag.id}`
  if (pendingTagOps.value.has(opKey)) return  // 防止重复提交
  
  pendingTagOps.value.add(opKey)
  
  try {
    await removeTagMutation.mutateAsync({ imageId: image.id, tagId: tag.id })
    
    // 局部更新：移除标签
    const currentTags = image.tags || []
    const newTags = currentTags.filter(t => t.id !== tag.id)
    emit('tagsUpdated', image.id, newTags)
    
    toast.success(`标签 "${tag.name}" 已移除`)
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    pendingTagOps.value.delete(opKey)
  }
}

// 添加标签
async function addTag(event: Event, image: ImageItem) {
  event.stopPropagation()
  if (isComposing.value) return
  
  const tagName = newTagInput.value.trim()
  if (!tagName) return
  
  const currentTags = image.tags || []
  if (currentTags.some(t => t.name.toLowerCase() === tagName.toLowerCase())) {
    newTagInput.value = ''
    toast.warning('标签已存在')
    return
  }
  
  const opKey = `${image.id}-add-${tagName}`
  if (pendingTagOps.value.has(opKey)) return
  
  pendingTagOps.value.add(opKey)
  
  try {
    // 直接使用 tagName，后端会自动解析/创建标签
    const result = await addTagMutation.mutateAsync({ imageId: image.id, tagName })
    handleAddTagSuccess(image, result)
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    pendingTagOps.value.delete(opKey)
  }
}

// 公共：处理标签添加成功
function handleAddTagSuccess(
  image: ImageItem, 
  result: { tag_id: number; tag_name: string; is_new: boolean }
) {
  const currentTags = image.tags || []
  const newTag: TagWithSource = {
    id: result.tag_id,
    name: result.tag_name,
    source: 'user',
    level: 2
  }
  emit('tagsUpdated', image.id, [...currentTags, newTag])
  
  newTagInput.value = ''
  editingImageId.value = null
  
  if (result.is_new) {
    toast.success(`新标签 "${result.tag_name}" 已创建并添加`)
  } else {
    toast.success(`标签 "${result.tag_name}" 已添加`)
  }
}

// 标签建议
const tagSuggestions = computed(() => {
  if (!allTags.value || !newTagInput.value || editingImageId.value === null) return []
  const input = newTagInput.value.toLowerCase()
  const image = props.images.find(i => i.id === editingImageId.value)
  const existingNames = new Set((image?.tags || []).map(t => t.name.toLowerCase()))
  
  return allTags.value
    .filter(t => t.level === 2 && t.name.toLowerCase().includes(input) && !existingNames.has(t.name.toLowerCase()))
    .slice(0, 5)
})

// 选择建议标签
async function selectSuggestion(event: Event, image: ImageItem, tag: { id: number; name: string }) {
  event.stopPropagation()
  
  const opKey = `${image.id}-${tag.id}`
  if (pendingTagOps.value.has(opKey)) return
  
  pendingTagOps.value.add(opKey)
  
  try {
    const result = await addTagMutation.mutateAsync({ imageId: image.id, tagId: tag.id })
    handleAddTagSuccess(image, result)
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    pendingTagOps.value.delete(opKey)
  }
}

// 检查是否有任何操作进行中
function isAnyOpPending(imageId: number): boolean {
  for (const key of pendingTagOps.value) {
    if (key.startsWith(`${imageId}-`)) return true
  }
  return false
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
        :style="image.width && image.height ? { aspectRatio: `${image.width}/${image.height}` } : undefined"
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
        v-if="!selectMode && !showLabelsAlways"
        class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity rounded-xl"
      >
        <button
          class="absolute bottom-3 right-3 p-1.5 bg-black/60 hover:bg-primary hover:scale-110 rounded-lg transition-all z-10"
          title="复制图片地址"
          @click="copyImageUrl($event, image.image_url)"
        >
          <Copy class="w-4 h-4 text-white" />
        </button>
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

      <!-- 始终显示的标签区域 -->
      <div v-if="showLabelsAlways && !selectMode" class="mt-2 px-1">
        <p v-if="image.description" class="text-sm text-foreground line-clamp-2" :title="image.description">
          {{ image.description }}
        </p>
        <div class="flex flex-wrap gap-1 mt-1.5 items-center">
          <template v-for="tag in image.tags" :key="tag.id || tag.name">
            <!-- 不可编辑的标签 -->
            <span 
              v-if="!isEditableTag(tag)"
              class="px-1.5 py-0.5 text-xs rounded-full font-medium"
              :class="getTagClass(tag)"
            >
              {{ tag.name }}
            </span>
            <!-- 可编辑的标签 -->
            <span 
              v-else
              class="inline-flex items-center px-1.5 py-0.5 text-xs rounded-full transition-colors group/tag"
              :class="[
                getTagClass(tag),
                editable ? 'pr-0.5' : '',
                isTagPending(image.id, tag.id) ? 'opacity-50' : ''
              ]"
            >
              {{ tag.name }}
              <button
                v-if="editable && !isTagPending(image.id, tag.id)"
                @click="removeTag($event, image, tag)"
                class="ml-0.5 p-0.5 rounded-full opacity-0 group-hover/tag:opacity-100 hover:bg-black/20 transition-all"
                title="删除标签"
              >
                <X class="w-3 h-3" />
              </button>
              <Loader2 
                v-if="editable && isTagPending(image.id, tag.id)" 
                class="w-3 h-3 ml-0.5 animate-spin" 
              />
            </span>
          </template>
          
          <!-- 添加标签 -->
          <template v-if="editable">
            <div v-if="editingImageId === image.id" class="relative" @click.stop>
              <div class="flex items-center gap-1">
                <input
                  ref="tagInputRef"
                  v-model="newTagInput"
                  @keydown.enter.prevent="addTag($event, image)"
                  @keyup.escape="cancelEdit($event)"
                  @compositionstart="isComposing = true"
                  @compositionend="isComposing = false"
                  placeholder="输入标签"
                  class="w-20 px-1.5 py-0.5 text-xs bg-background border border-border rounded-full focus:outline-none focus:ring-1 focus:ring-primary"
                  :disabled="isAnyOpPending(image.id)"
                />
                <button
                  @click="addTag($event, image)"
                  :disabled="isAnyOpPending(image.id) || !newTagInput.trim()"
                  class="p-0.5 rounded-full bg-primary text-primary-foreground disabled:opacity-50"
                >
                  <Loader2 v-if="isAnyOpPending(image.id)" class="w-3 h-3 animate-spin" />
                  <Plus v-else class="w-3 h-3" />
                </button>
                <button
                  @click="cancelEdit($event)"
                  class="p-0.5 rounded-full hover:bg-muted"
                >
                  <X class="w-3 h-3 text-muted-foreground" />
                </button>
              </div>
              <div 
                v-if="tagSuggestions.length" 
                class="absolute top-full left-0 mt-1 w-32 bg-popover border border-border rounded-lg shadow-lg z-20 py-1"
              >
                <button
                  v-for="sug in tagSuggestions"
                  :key="sug.id"
                  @click="selectSuggestion($event, image, sug)"
                  class="block w-full text-left px-2 py-1 text-xs text-foreground hover:bg-muted"
                >
                  {{ sug.name }}
                </button>
              </div>
            </div>
            <button
              v-else
              @click="startEditTag($event, image.id)"
              class="inline-flex items-center px-1.5 py-0.5 text-xs rounded-full border border-dashed border-muted-foreground/50 text-muted-foreground hover:border-primary hover:text-primary transition-colors"
            >
              <Plus class="w-3 h-3" />
            </button>
          </template>
        </div>
      </div>
    </div>

    <CopyToast v-model:show="showCopied" />
  </div>
</template>
