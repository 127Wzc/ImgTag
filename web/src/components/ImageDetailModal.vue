<script setup lang="ts">
/**
 * ImageDetailModal - 图片详情模态框
 * 沉浸式全屏查看，Linear 风格悬浮面板
 */
import { computed, onMounted, onUnmounted, ref, watch, nextTick } from 'vue'
import {
  X, ChevronLeft, ChevronRight, Info, Ruler, HardDrive, Hash,
  Plus, Pencil, Loader2, Save, Link, Download, Share2, Tag as TagIcon,
  PanelRightClose
} from 'lucide-vue-next'
import { useUpdateImage, useTags, useCategories, useResolveTag } from '@/api/queries'
import { useUserStore } from '@/stores'
import { toast } from 'vue-sonner'
import { getErrorMessage } from '@/utils/api-error'
import CopyToast from '@/components/ui/CopyToast.vue'

// 图片信息接口
export interface ImageInfo {
  id: number
  image_url: string
  description?: string | null
  tags?: Array<{ id?: number; name: string; level?: number; source?: string }>
  width?: number | null
  height?: number | null
  file_size?: number | null
  created_at?: string | null
  file_path?: string | null
  uploaded_by?: number | null
}

const props = withDefaults(defineProps<{
  image: ImageInfo | null
  canNavigatePrev?: boolean
  canNavigateNext?: boolean
  currentIndex?: number
  totalCount?: number
}>(), {
  canNavigatePrev: false,
  canNavigateNext: false,
})

const emit = defineEmits<{
  close: []
  prev: []
  next: []
  updated: []
}>()

// 信息面板状态 (默认展开在宽屏下)
const showInfoPanel = ref(true)
const showUnsavedConfirm = ref(false)

// 用户权限
const userStore = useUserStore()
const isLoggedIn = computed(() => !!userStore.user)
const canEdit = computed(() => {
  if (!props.image) return false
  if (userStore.isAdmin) return true
  return props.image.uploaded_by === userStore.user?.id
})

// 复制成功提示
const showCopied = ref(false)

// 复制图片地址
async function copyImageUrl() {
  if (!props.image?.image_url) return
  try {
    await navigator.clipboard.writeText(props.image.image_url)
    showCopied.value = true
  } catch {
    toast.error('复制失败')
  }
}

// API
const updateMutation = useUpdateImage()
const resolveMutation = useResolveTag()
const { data: allTags } = useTags(100)
const { data: categories } = useCategories()

// 编辑用标签对象类型
interface DraftTag {
  id: number
  name: string
}

// ========== 编辑状态（本地草稿） ==========
const draftCategoryId = ref<number | null>(null)
const draftNormalTags = ref<DraftTag[]>([])
const draftDescription = ref('')
const isEditingDescription = ref(false)
const descriptionInput = ref<HTMLTextAreaElement | null>(null)

// 标签输入
const showTagInput = ref(false)
const newTagInput = ref('')
const tagInputRef = ref<HTMLInputElement | null>(null)
const isResolvingTag = ref(false)
const isComposing = ref(false)

// 原始数据
const originalCategoryId = ref<number | null>(null)
const originalNormalTagIds = ref<number[]>([])
const originalDescription = ref('')

// 同步 props.image 到本地草稿
watch(() => props.image, (img) => {
  if (img) {
    const tags = img.tags || []

    const cat = tags.find(t => t.level === 0)
    const catTag = categories.value?.find(c => c.name === cat?.name)
    draftCategoryId.value = catTag?.id ?? null
    originalCategoryId.value = catTag?.id ?? null

    const normalTagObjs = tags.filter(t => t.level === 2 || t.level === undefined)
      .map(t => ({ id: t.id || 0, name: t.name }))
    draftNormalTags.value = [...normalTagObjs]
    originalNormalTagIds.value = normalTagObjs.map(t => t.id)

    draftDescription.value = img.description || ''
    originalDescription.value = img.description || ''

    isEditingDescription.value = false
    showTagInput.value = false
    newTagInput.value = ''
  }
}, { immediate: true })

const resolutionTags = computed(() =>
  (props.image?.tags || []).filter(t => t.level === 1)
)

const hasChanges = computed(() => {
  if (draftCategoryId.value !== originalCategoryId.value) return true
  if (draftDescription.value !== originalDescription.value) return true
  const currentIds = draftNormalTags.value.map(t => t.id).sort()
  const originalIds = [...originalNormalTagIds.value].sort()
  if (currentIds.length !== originalIds.length) return true
  return !currentIds.every((id, i) => id === originalIds[i])
})

async function startEditDescription() {
  if (!canEdit.value) return
  isEditingDescription.value = true
  await nextTick()
  descriptionInput.value?.focus()
  autoResizeTextarea()
}

function autoResizeTextarea() {
  const textarea = descriptionInput.value
  if (!textarea) return
  textarea.style.height = 'auto'
  const newHeight = Math.min(Math.max(textarea.scrollHeight, 60), 150)
  textarea.style.height = newHeight + 'px'
}

async function showAddTag() {
  if (!canEdit.value) return
  showTagInput.value = true
  await nextTick()
  tagInputRef.value?.focus()
}

async function addTag() {
  if (isComposing.value) return

  const tagName = newTagInput.value.trim()
  if (!tagName) return

  if (draftNormalTags.value.some(t => t.name.toLowerCase() === tagName.toLowerCase())) {
    newTagInput.value = ''
    return
  }

  try {
    isResolvingTag.value = true
    const resolved = await resolveMutation.mutateAsync({ name: tagName, level: 2 })

    draftNormalTags.value.push({ id: resolved.id, name: resolved.name })
    newTagInput.value = ''

    if (resolved.is_new) {
      toast.success(`新标签 "${resolved.name}" 已创建`)
    }
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    isResolvingTag.value = false
  }
}

function selectSuggestion(tag: { id: number; name: string }) {
  draftNormalTags.value.push({ id: tag.id, name: tag.name })
  newTagInput.value = ''
  showTagInput.value = false
}

function removeTag(tagId: number) {
  if (!canEdit.value) return
  draftNormalTags.value = draftNormalTags.value.filter(t => t.id !== tagId)
}

const tagSuggestions = computed(() => {
  if (!allTags.value || !newTagInput.value) return []
  const input = newTagInput.value.toLowerCase()
  const existingIds = new Set(draftNormalTags.value.map(t => t.id))
  return allTags.value
    .filter(t => t.level === 2 && t.name.toLowerCase().includes(input) && !existingIds.has(t.id))
    .slice(0, 5)
})

async function saveChanges() {
  if (!props.image || !hasChanges.value) return

  try {
    const allTagIds: number[] = []

    if (draftCategoryId.value) {
      allTagIds.push(draftCategoryId.value)
    }

    resolutionTags.value.forEach(t => {
      if (t.id) allTagIds.push(t.id)
    })

    draftNormalTags.value.forEach(t => allTagIds.push(t.id))

    await updateMutation.mutateAsync({
      id: props.image.id,
      data: {
        tag_ids: allTagIds,
        description: draftDescription.value,
      }
    })

    originalCategoryId.value = draftCategoryId.value
    originalNormalTagIds.value = draftNormalTags.value.map(t => t.id)
    originalDescription.value = draftDescription.value

    emit('updated')
    toast.success('保存成功')
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  }
}

function discardChanges() {
  draftCategoryId.value = originalCategoryId.value
  const tags = props.image?.tags || []
  const normalTagObjs = tags.filter(t => t.level === 2 || t.level === undefined)
    .map(t => ({ id: t.id || 0, name: t.name }))
  draftNormalTags.value = [...normalTagObjs]
  draftDescription.value = originalDescription.value
  isEditingDescription.value = false
}

function formatFileSize(bytes?: number | null): string {
  if (!bytes) return '-'
  if (bytes < 100) return bytes + ' B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
}

function getImageUrl(url?: string): string {
  return url || ''
}

function handleBackdropClick() {
  if (canEdit.value && hasChanges.value) {
    showUnsavedConfirm.value = true
  } else {
    emit('close')
  }
}

async function confirmSaveAndClose() {
  await saveChanges()
  showUnsavedConfirm.value = false
  emit('close')
}

function confirmDiscardAndClose() {
  discardChanges()
  showUnsavedConfirm.value = false
  emit('close')
}

function handleKeydown(e: KeyboardEvent) {
  if (!props.image) return
  if (isEditingDescription.value || showTagInput.value) return

  if (e.key === 'Escape') {
    handleBackdropClick()
  }
  if (e.key === 'ArrowLeft' && props.canNavigatePrev) emit('prev')
  if (e.key === 'ArrowRight' && props.canNavigateNext) emit('next')
  if (e.key === 'i' || e.key === 'I') showInfoPanel.value = !showInfoPanel.value
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="image"
        class="fixed inset-0 z-[100] flex items-center justify-center bg-black/95 backdrop-blur-sm overflow-hidden"
      >
        <!-- 背景点击层 -->
        <div class="absolute inset-0 z-0" @click="handleBackdropClick"></div>

        <!-- 全屏图片容器 -->
        <div
          class="relative z-10 w-full h-full flex items-center justify-center transition-all duration-300 ease-in-out px-4 py-12 md:px-12 md:py-8"
          :class="showInfoPanel ? 'md:pr-96' : ''"
        >
          <img
            :src="getImageUrl(image.image_url)"
            :alt="image.description || '图片预览'"
            class="max-w-full max-h-full object-contain shadow-2xl select-none"
            @click.stop="showInfoPanel = !showInfoPanel"
          />
        </div>

        <!-- 顶部操作栏 (悬浮感应区) -->
        <Transition name="scale-fade">
          <div
            v-if="!showInfoPanel"
            class="absolute top-0 right-0 z-50 p-6 group/top"
          >
            <div
              class="flex items-center p-1.5 rounded-full bg-black/20 backdrop-blur-3xl shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05)] hover:bg-black/30 transition-all origin-top-right md:opacity-0 md:group-hover/top:opacity-100 duration-300"
            >
              <button
                class="p-2.5 rounded-full text-white/70 hover:text-white hover:bg-white/10 transition-all active:scale-95"
                @click.stop="showInfoPanel = true"
                title="显示信息"
              >
                <Info class="w-5 h-5" />
              </button>
              <div class="w-px h-4 bg-white/10 mx-1" />
              <button
                class="p-2.5 rounded-full text-white/70 hover:text-white hover:bg-white/10 transition-all active:scale-95"
                @click.stop="handleBackdropClick"
                title="关闭 (Esc)"
              >
                <X class="w-5 h-5" />
              </button>
            </div>
          </div>
        </Transition>

        <!-- 导航按钮 (左侧感应区) -->
        <div
          v-if="canNavigatePrev"
          class="absolute left-0 top-0 bottom-0 w-32 z-30 flex items-center justify-start pl-6 group/nav hover:bg-gradient-to-r hover:from-black/30 hover:to-transparent transition-all"
          @click.stop="emit('prev')"
        >
          <button
            class="p-4 rounded-full bg-white/5 hover:bg-white/10 text-white/50 hover:text-white backdrop-blur-sm transition-all duration-300 transform -translate-x-4 opacity-0 group-hover/nav:opacity-100 group-hover/nav:translate-x-0 group-hover/nav:scale-110 active:scale-95"
          >
            <ChevronLeft class="w-10 h-10" />
          </button>
        </div>

        <!-- 导航按钮 (右侧感应区) -->
        <div
          v-if="canNavigateNext"
          class="absolute top-0 bottom-0 w-32 z-30 flex items-center justify-end pr-6 group/nav hover:bg-gradient-to-l hover:from-black/30 hover:to-transparent transition-all"
          :class="showInfoPanel ? 'right-80 md:right-96' : 'right-0'"
          @click.stop="emit('next')"
        >
          <button
            class="p-4 rounded-full bg-white/5 hover:bg-white/10 text-white/50 hover:text-white backdrop-blur-sm transition-all duration-300 transform translate-x-4 opacity-0 group-hover/nav:opacity-100 group-hover/nav:translate-x-0 group-hover/nav:scale-110 active:scale-95"
          >
            <ChevronRight class="w-10 h-10" />
          </button>
        </div>

        <!-- 底部页码 (底部感应区) -->
        <div
          v-if="totalCount"
          class="absolute bottom-0 left-0 right-0 h-24 z-20 flex items-end justify-center pb-8 group/bottom"
        >
           <div class="text-white/60 text-sm font-medium tabular-nums drop-shadow-md transition-opacity duration-300 md:opacity-0 md:group-hover/bottom:opacity-100">
             <span class="text-white shadow-black drop-shadow-md">{{ (currentIndex ?? 0) + 1 }}</span> <span class="opacity-50 mx-1">/</span> {{ totalCount }}
           </div>
        </div>

        <!-- 信息侧边栏 (悬浮卡片风格 - 高透明度玻璃拟态) -->
        <Transition name="drawer-expand">
          <div
            v-if="showInfoPanel"
            class="absolute top-4 bottom-4 right-4 z-40 w-[calc(100vw-32px)] md:w-96 flex flex-col bg-black/20 backdrop-blur-3xl rounded-[2rem] md:rounded-[2rem] shadow-[0_20px_50px_-12px_rgba(0,0,0,0.5)] overflow-hidden shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05)] origin-top-right"
            @click.stop
          >
            <!-- Header (集成操作按钮) -->
            <div class="shrink-0 pl-6 pr-4 py-4 flex items-start justify-between bg-gradient-to-b from-white/5 to-transparent">
              <div class="mr-4 overflow-hidden pt-1.5">
                <h2 class="text-lg font-medium text-white line-clamp-1 drop-shadow-md" :title="image.description || '无标题'">
                  {{ image.description || '未命名图片' }}
                </h2>
                <div class="text-xs text-white/50 mt-1 font-mono">ID: {{ image.id }}</div>
              </div>

              <!-- 顶部操作区 (对应胶囊位置) -->
              <div class="flex items-center p-1.5 -mr-1.5 -mt-1.5">
                 <button
                  class="p-2.5 rounded-full text-white/70 hover:text-white hover:bg-white/10 transition-colors active:scale-95"
                  @click.stop="showInfoPanel = false"
                  title="收起面板"
                >
                  <PanelRightClose class="w-5 h-5" />
                </button>
                <div class="w-px h-4 bg-white/10 mx-1" />
                <button
                  class="p-2.5 rounded-full text-white/70 hover:text-white hover:bg-white/10 transition-colors active:scale-95"
                  @click.stop="handleBackdropClick"
                  title="关闭"
                >
                  <X class="w-5 h-5" />
                </button>
              </div>
            </div>

            <!-- Scrollable Content -->
            <div class="flex-1 overflow-y-auto px-6 py-2 space-y-8 scrollbar-thin scrollbar-thumb-white/10 hover:scrollbar-thumb-white/20">

              <!-- 操作区 -->
              <div class="flex gap-2">
                <button
                  @click="copyImageUrl"
                  class="flex-1 flex items-center justify-center gap-2 py-2.5 bg-white/5 hover:bg-white/10 rounded-2xl text-sm text-white/80 hover:text-white transition-all"
                >
                  <Link class="w-4 h-4" />
                  复制链接
                </button>
                <a
                  :href="getImageUrl(image.image_url)"
                  target="_blank"
                  download
                  class="flex-1 flex items-center justify-center gap-2 py-2.5 bg-white/5 hover:bg-white/10 rounded-2xl text-sm text-white/80 hover:text-white transition-all"
                >
                  <Download class="w-4 h-4" />
                  下载原图
                </a>
              </div>

              <!-- 描述 -->
              <div class="space-y-3">
                <div class="flex items-center justify-between text-xs text-white/40 uppercase tracking-wider font-medium">
                  <span>描述</span>
                  <Pencil v-if="canEdit" class="w-3 h-3" />
                </div>
                <div v-if="isEditingDescription" class="space-y-2">
                  <textarea
                    ref="descriptionInput"
                    v-model="draftDescription"
                    maxlength="150"
                    class="w-full px-4 py-3 text-sm bg-white/5 text-white rounded-2xl focus:outline-none focus:bg-white/10 placeholder:text-white/20 resize-none transition-all"
                    style="min-height: 80px;"
                    placeholder="添加图片描述..."
                    @input="autoResizeTextarea"
                    @keydown.escape="isEditingDescription = false"
                  />
                  <div class="flex justify-end gap-2">
                    <button @click="isEditingDescription = false" class="px-3 py-1.5 text-xs text-white/60 hover:text-white">取消</button>
                    <button @click="isEditingDescription = false" class="px-3 py-1.5 text-xs bg-white/20 text-white rounded-lg hover:bg-white/30">完成</button>
                  </div>
                </div>
                <div
                  v-else
                  @click="canEdit && startEditDescription()"
                  class="text-sm leading-relaxed text-white/80 min-h-[1.5em]"
                  :class="canEdit ? 'cursor-text hover:text-white transition-colors' : ''"
                >
                  {{ draftDescription || '暂无描述' }}
                </div>
              </div>

              <!-- 标签系统 -->
              <div class="space-y-4">
                <!-- 分类选择 -->
                <div class="space-y-2">
                  <div class="text-xs text-white/40 uppercase tracking-wider font-medium">分类</div>
                  <div class="flex flex-wrap gap-2">
                    <select
                      v-if="canEdit"
                      v-model="draftCategoryId"
                      class="w-full px-3 py-2 text-sm bg-white/5 text-white rounded-xl focus:outline-none hover:bg-white/10 transition-colors appearance-none cursor-pointer"
                    >
                      <option :value="null" class="bg-zinc-900">未分类</option>
                      <option v-for="cat in categories" :key="cat.id" :value="cat.id" class="bg-zinc-900">
                        {{ cat.name }}
                      </option>
                    </select>
                    <div v-else class="px-3 py-2 text-sm bg-white/5 rounded-xl text-white/80">
                      {{ categories?.find(c => c.id === draftCategoryId)?.name || '未分类' }}
                    </div>
                  </div>
                </div>

                <!-- 标签列表 -->
                <div class="space-y-3">
                  <div class="flex items-center justify-between text-xs text-white/40 uppercase tracking-wider font-medium">
                    <span>标签</span>
                    <span v-if="canEdit" class="text-[10px] bg-white/10 px-1.5 py-0.5 rounded">{{ draftNormalTags.length }}</span>
                  </div>

                  <div class="flex flex-wrap gap-2">
                    <!-- 分辨率标签 (只读) -->
                    <span
                      v-for="tag in resolutionTags"
                      :key="tag.name"
                      class="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-blue-500/10 text-blue-400"
                    >
                      {{ tag.name }}
                    </span>

                    <!-- 普通标签 -->
                    <div
                      v-for="tag in draftNormalTags"
                      :key="tag.id"
                      class="group inline-flex items-center px-2.5 py-1 rounded-md text-xs bg-white/5 text-zinc-400 hover:bg-white/10 hover:text-zinc-200 transition-all"
                    >
                      <Hash class="w-3 h-3 mr-1 opacity-30 group-hover:opacity-50" />
                      {{ tag.name }}
                      <button
                        v-if="canEdit"
                        @click.stop="removeTag(tag.id)"
                        class="ml-1.5 p-0.5 rounded-full hover:bg-white/10 text-white/20 hover:text-white/60 opacity-0 group-hover:opacity-100 transition-all"
                      >
                        <X class="w-3 h-3" />
                      </button>
                    </div>

                    <!-- 添加标签 -->
                    <div v-if="canEdit" class="relative inline-block">
                      <div v-if="showTagInput" class="flex items-center">
                        <input
                          ref="tagInputRef"
                          v-model="newTagInput"
                          @keydown.enter.prevent="addTag"
                          @keyup.escape="showTagInput = false; newTagInput = ''"
                          @compositionstart="isComposing = true"
                          @compositionend="isComposing = false"
                          @blur="!newTagInput && (showTagInput = false)"
                          class="w-24 px-2 py-1 text-xs bg-transparent border-b border-white/20 text-white focus:outline-none focus:border-white/50 focus:w-32 transition-all placeholder:text-white/20"
                          placeholder="输入..."
                        />
                        <!-- 建议列表 -->
                        <div v-if="tagSuggestions.length" class="absolute top-full left-0 mt-2 w-40 bg-zinc-900 border border-white/10 rounded-lg shadow-xl z-50 overflow-hidden">
                          <button
                            v-for="sug in tagSuggestions"
                            :key="sug.id"
                            @mousedown.prevent="selectSuggestion(sug)"
                            class="block w-full text-left px-3 py-2 text-xs text-white/60 hover:bg-white/5 hover:text-white transition-colors"
                          >
                            {{ sug.name }}
                          </button>
                        </div>
                      </div>
                      <button
                        v-else
                        @click="showAddTag"
                        class="inline-flex items-center px-2.5 py-1 rounded-md text-xs bg-white/5 text-white/30 hover:text-white/80 hover:bg-white/10 transition-all"
                      >
                        <Plus class="w-3 h-3 mr-1" />
                        添加
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 元数据 -->
              <div class="pt-6 border-t border-white/5 space-y-3">
                <div class="text-xs text-white/40 uppercase tracking-wider font-medium">元数据</div>
                <div class="grid grid-cols-2 gap-y-3 gap-x-4 text-xs text-white/60">
                  <div class="flex flex-col gap-1">
                    <span class="text-white/30">尺寸</span>
                    <span class="text-white/80">{{ image.width }} × {{ image.height }}</span>
                  </div>
                  <div class="flex flex-col gap-1">
                    <span class="text-white/30">大小</span>
                    <span class="text-white/80">{{ formatFileSize(image.file_size) }}</span>
                  </div>
                  <div class="flex flex-col gap-1">
                    <span class="text-white/30">创建时间</span>
                    <span class="text-white/80">{{ image.created_at ? new Date(image.created_at).toLocaleDateString() : '-' }}</span>
                  </div>
                  <div class="flex flex-col gap-1">
                    <span class="text-white/30">路径</span>
                    <span class="truncate" :title="image.file_path || ''">{{ image.file_path || '-' }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Footer: Save Actions -->
            <div v-if="canEdit && hasChanges" class="shrink-0 p-4 border-t border-white/10 bg-white/5 backdrop-blur">
              <div class="flex gap-3">
                <button
                  @click="discardChanges"
                  class="flex-1 px-4 py-2.5 text-sm font-medium text-white/70 hover:text-white hover:bg-white/10 rounded-xl transition-colors"
                >
                  放弃
                </button>
                <button
                  @click="saveChanges"
                  :disabled="updateMutation.isPending.value"
                  class="flex-[2] flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-white text-black rounded-xl hover:bg-white/90 transition-colors shadow-lg disabled:opacity-50"
                >
                  <Loader2 v-if="updateMutation.isPending.value" class="w-4 h-4 animate-spin" />
                  <Save v-else class="w-4 h-4" />
                  保存修改
                </button>
              </div>
            </div>
          </div>
        </Transition>

        <!-- 未保存确认弹窗 -->
        <Transition name="fade">
          <div v-if="showUnsavedConfirm" class="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div class="bg-zinc-900 border border-white/20 rounded-2xl p-6 max-w-sm w-full mx-4 shadow-2xl transform scale-100">
              <h3 class="text-white font-medium text-lg mb-2">未保存的更改</h3>
              <p class="text-white/60 text-sm mb-6">您修改了图片信息，是否保存更改？</p>
              <div class="flex gap-3 justify-end">
                <button
                  @click="confirmDiscardAndClose"
                  class="px-4 py-2 text-sm text-white/70 hover:text-white transition-colors"
                >
                  不保存
                </button>
                <button
                  @click="confirmSaveAndClose"
                  :disabled="updateMutation.isPending.value"
                  class="px-5 py-2 text-sm bg-white text-black font-medium rounded-lg hover:bg-gray-200 transition-colors"
                >
                  保存
                </button>
              </div>
            </div>
          </div>
        </Transition>

        <CopyToast v-model:show="showCopied" />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.scale-fade-enter-active,
.scale-fade-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.scale-fade-enter-from,
.scale-fade-leave-to {
  opacity: 0;
  transform: scale(0.9);
}

.drawer-expand-enter-active,
.drawer-expand-leave-active {
  transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1);
}
.drawer-expand-enter-from,
.drawer-expand-leave-to {
  opacity: 0;
  transform: scale(0.95) translateX(10px);
}
</style>
