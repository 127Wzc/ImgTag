<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ImageResponse, ImageWithSimilarity, TagWithSource } from '@/types'
import { Copy, X, Plus, Loader2, Check } from 'lucide-vue-next'
import CopyToast from '@/components/ui/CopyToast.vue'
import { useAddImageTag, useRemoveImageTag, useTags } from '@/api/queries'
import { toast } from 'vue-sonner'
import { getErrorMessage } from '@/utils/api-error'
import { usePermission } from '@/composables/usePermission'

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

const { canCreateTags } = usePermission()
const canEditTags = computed(() => props.editable && canCreateTags.value)

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



function isPending(image: ImageItem): boolean {
  return !image.description && (!image.tags || image.tags.length === 0)
}

function getSimilarity(image: ImageItem): number | undefined {
  return 'similarity' in image ? image.similarity : undefined
}

function getSimilarityColor(sim: number): string {
  if (sim >= 0.8) return 'bg-emerald-500 shadow-emerald-500/20'
  if (sim >= 0.6) return 'bg-green-500 shadow-green-500/20'
  if (sim >= 0.4) return 'bg-yellow-500 shadow-yellow-500/20'
  return 'bg-orange-500 shadow-orange-500/20'
}

// 标签样式 - Linear 风格优化
function getTagClass(tag: TagWithSource): string {
  if (tag.level === 0) {
    return 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-200/50 dark:border-violet-500/20'
  } else if (tag.level === 1) {
    return 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-200/50 dark:border-blue-500/20'
  }
  return 'bg-muted/50 text-muted-foreground border-border/50 hover:bg-muted hover:text-foreground'
}

function isEditableTag(tag: TagWithSource): boolean {
  return tag.level === 2 || tag.level === undefined
}

function isTagPending(imageId: number, tagId: number): boolean {
  return pendingTagOps.value.has(`${imageId}-${tagId}`)
}

async function startEditTag(event: Event, imageId: number) {
  event.stopPropagation()
  if (!canEditTags.value) return
  editingImageId.value = imageId
  newTagInput.value = ''
  await new Promise(r => setTimeout(r, 50))
  tagInputRef.value?.focus()
}

function cancelEdit(event: Event) {
  event.stopPropagation()
  editingImageId.value = null
  newTagInput.value = ''
}

async function removeTag(event: Event, image: ImageItem, tag: TagWithSource) {
  event.stopPropagation()
  if (!canEditTags.value || !tag.id) return

  const opKey = `${image.id}-${tag.id}`
  if (pendingTagOps.value.has(opKey)) return

  pendingTagOps.value.add(opKey)

  try {
    await removeTagMutation.mutateAsync({ imageId: image.id, tagId: tag.id })
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

async function addTag(event: Event, image: ImageItem) {
  event.stopPropagation()
  if (!canEditTags.value) return
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
    const result = await addTagMutation.mutateAsync({ imageId: image.id, tagName })
    handleAddTagSuccess(image, result)
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    pendingTagOps.value.delete(opKey)
  }
}

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

const tagSuggestions = computed(() => {
  if (!allTags.value || !newTagInput.value || editingImageId.value === null) return []
  const input = newTagInput.value.toLowerCase()
  const image = props.images.find(i => i.id === editingImageId.value)
  const existingNames = new Set((image?.tags || []).map(t => t.name.toLowerCase()))

  return allTags.value
    .filter(t => t.level === 2 && t.name.toLowerCase().includes(input) && !existingNames.has(t.name.toLowerCase()))
    .slice(0, 5)
})

async function selectSuggestion(event: Event, image: ImageItem, tag: { id: number; name: string }) {
  event.stopPropagation()
  if (!canEditTags.value) return

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

function isAnyOpPending(imageId: number): boolean {
  for (const key of pendingTagOps.value) {
    if (key.startsWith(`${imageId}-`)) return true
  }
  return false
}
</script>

<template>
  <div class="columns-2 sm:columns-3 md:columns-4 lg:columns-5 xl:columns-6 2xl:columns-7 min-[1920px]:columns-8 gap-2 md:gap-4 space-y-2 md:space-y-4 pb-12">
    <div
      v-for="(image, index) in images"
      :key="image.id"
      class="break-inside-avoid relative group cursor-pointer w-full"
      @click="handleClick(image, index)"
    >
      <!-- 卡片容器 -->
      <div
        class="relative overflow-hidden rounded-2xl bg-black/5 dark:bg-white/5 transition-all duration-500 ease-out"
        :class="[
          selectMode && selectedIds.has(image.id)
            ? 'scale-[0.98] brightness-110'
            : 'hover:shadow-xl hover:scale-[1.02]'
        ]"
        :style="image.width && image.height ? { aspectRatio: `${image.width}/${image.height}` } : undefined"
      >
        <!-- 图片 -->
        <img
          :src="getImageUrl(image.image_url)"
          :alt="image.description || '图片'"
          class="w-full h-full object-cover transition-transform duration-700 ease-out group-hover:scale-105"
          loading="lazy"
        />

        <!-- 遮罩层 (Hover or Selected) -->
        <div
          class="absolute inset-0 transition-colors duration-300 pointer-events-none"
          :class="[
            selectMode && selectedIds.has(image.id) ? 'bg-primary/20 backdrop-blur-[1px]' : 'opacity-0 group-hover:opacity-100 bg-gradient-to-t from-black/60 via-transparent to-transparent'
          ]"
        ></div>

        <!-- 左上角选择指示器 (Select Mode) -->
        <div
          v-if="selectMode"
          class="absolute top-3 left-3 z-20"
          @click.stop="emit('toggleSelect', image.id)"
        >
           <div
             class="w-6 h-6 rounded-full flex items-center justify-center transition-all duration-300 shadow-lg backdrop-blur-md"
             :class="selectedIds.has(image.id)
               ? 'bg-white text-green-600 scale-100 shadow-md'
               : 'bg-black/30 text-white/50 hover:bg-black/50 hover:text-white scale-90 hover:scale-100'"
           >
             <Check v-if="selectedIds.has(image.id)" class="w-3.5 h-3.5" stroke-width="5" />
             <div v-else class="w-2 h-2 rounded-full bg-current opacity-50" />
           </div>
        </div>

        <!-- 右上角状态徽章 -->
        <div class="absolute top-2 right-2 flex flex-col gap-1.5 items-end z-20 pointer-events-none">
           <!-- 待分析 -->
           <div
            v-if="showPendingBadge && isPending(image)"
            class="px-2 py-0.5 bg-amber-500/90 backdrop-blur-sm text-white text-[10px] font-medium rounded-full shadow-sm"
          >
            待分析
          </div>

          <!-- 相似度 -->
          <div
            v-if="showSimilarity && getSimilarity(image) !== undefined"
            class="px-2 py-0.5 text-white text-[10px] font-bold rounded-full shadow-sm backdrop-blur-sm"
            :class="getSimilarityColor(getSimilarity(image)!)"
          >
            {{ (getSimilarity(image)! * 100).toFixed(0) }}%
          </div>
        </div>

        <!-- Hover Actions (Top Left/Right if not select mode) -->
        <div
          v-if="!selectMode"
          class="absolute top-2 right-2 flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity duration-200 z-20"
        >
          <button
            class="p-1.5 rounded-md bg-black/50 backdrop-blur border border-white/10 text-white hover:bg-black/70 hover:scale-105 transition-all shadow-sm"
            title="复制链接"
            @click="copyImageUrl($event, image.image_url)"
          >
            <Copy class="w-3.5 h-3.5" />
          </button>
        </div>

        <!-- 底部信息 (Hover) -->
        <div
          v-if="!selectMode && !showLabelsAlways"
          class="absolute inset-x-0 bottom-0 p-3 pt-6 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col justify-end pointer-events-none"
        >
          <p v-if="image.description" class="text-white text-xs font-medium line-clamp-2 mb-1.5 drop-shadow-md">
            {{ image.description }}
          </p>
          <div class="flex flex-wrap gap-1">
            <span
              v-for="tag in image.tags?.slice(0, 3)"
              :key="tag.name"
              class="px-1.5 py-0.5 bg-white/20 backdrop-blur-sm border border-white/10 text-white text-[10px] rounded-md shadow-sm"
            >
              {{ tag.name }}
            </span>
            <span v-if="(image.tags?.length || 0) > 3" class="px-1.5 py-0.5 bg-black/40 backdrop-blur text-white text-[10px] rounded-md">
               +{{ (image.tags?.length || 0) - 3 }}
            </span>
          </div>
        </div>
      </div>

      <!-- 始终显示的标签区域 (Inline Edit) -->
      <div v-if="showLabelsAlways && !selectMode" class="mt-2.5 px-0.5">
        <div class="flex flex-wrap gap-1.5 items-center">
          <template v-for="tag in image.tags" :key="tag.id || tag.name">
            <!-- 不可编辑标签 -->
            <span
              v-if="!isEditableTag(tag)"
              class="px-2 py-0.5 text-[10px] border rounded-md font-medium"
              :class="getTagClass(tag)"
            >
              {{ tag.name }}
            </span>
            <!-- 可编辑标签 -->
            <span
              v-else
              class="group/tag inline-flex items-center px-2 py-0.5 text-[10px] border rounded-md transition-colors"
              :class="[
                getTagClass(tag),
                canEditTags ? 'pr-1' : '',
                isTagPending(image.id, tag.id) ? 'opacity-50' : ''
              ]"
            >
              {{ tag.name }}
              <button
                v-if="canEditTags && !isTagPending(image.id, tag.id)"
                @click="removeTag($event, image, tag)"
                class="ml-1 p-0.5 rounded-full hover:bg-red-500/10 hover:text-red-500 opacity-0 group-hover/tag:opacity-100 transition-all"
                title="删除"
              >
                <X class="w-2.5 h-2.5" />
              </button>
              <Loader2
                v-if="canEditTags && isTagPending(image.id, tag.id)"
                class="w-2.5 h-2.5 ml-1 animate-spin"
              />
            </span>
          </template>

          <!-- 添加标签按钮 -->
          <template v-if="canEditTags">
            <div v-if="editingImageId === image.id" class="relative z-30" @click.stop>
              <div class="flex items-center gap-1">
                <input
                  ref="tagInputRef"
                  v-model="newTagInput"
                  @keydown.enter.prevent="addTag($event, image)"
                  @keyup.escape="cancelEdit($event)"
                  @compositionstart="isComposing = true"
                  @compositionend="isComposing = false"
                  placeholder="新标签..."
                  class="w-20 px-2 py-0.5 text-[10px] bg-background border border-primary/30 rounded-md focus:outline-none focus:ring-1 focus:ring-primary shadow-sm"
                  :disabled="isAnyOpPending(image.id)"
                />
                <button
                  @click="addTag($event, image)"
                  :disabled="isAnyOpPending(image.id) || !newTagInput.trim()"
                  class="p-0.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  <Loader2 v-if="isAnyOpPending(image.id)" class="w-3 h-3 animate-spin" />
                  <Plus v-else class="w-3 h-3" />
                </button>
                <button
                  @click="cancelEdit($event)"
                  class="p-0.5 rounded-md hover:bg-muted text-muted-foreground"
                >
                  <X class="w-3 h-3" />
                </button>
              </div>

              <!-- 建议列表 -->
              <div
                v-if="tagSuggestions.length"
                class="absolute top-full left-0 mt-1 w-32 bg-popover border border-border rounded-md shadow-lg overflow-hidden py-0.5"
              >
                <button
                  v-for="sug in tagSuggestions"
                  :key="sug.id"
                  @click="selectSuggestion($event, image, sug)"
                  class="block w-full text-left px-2 py-1.5 text-[10px] text-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
                >
                  {{ sug.name }}
                </button>
              </div>
            </div>

            <button
              v-else
              @click="startEditTag($event, image.id)"
              class="inline-flex items-center justify-center w-5 h-5 rounded-md border border-dashed border-border text-muted-foreground hover:border-primary/50 hover:text-primary hover:bg-primary/5 transition-all"
              title="添加/新建标签"
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
