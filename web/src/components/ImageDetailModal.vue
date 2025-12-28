<script setup lang="ts">
/**
 * ImageDetailModal - 图片详情模态框
 * 全屏查看图片，支持编辑标签和描述（统一保存）
 */
import { computed, onMounted, onUnmounted, ref, watch, nextTick } from 'vue'
import { X, ChevronLeft, ChevronRight, Info, Ruler, HardDrive, Hash, Plus, Pencil, Loader2, Save } from 'lucide-vue-next'
import { useUpdateImage, useTags, useCategories, useResolveTag } from '@/api/queries'
import { useUserStore } from '@/stores'
import { toast } from 'vue-sonner'
import { getErrorMessage } from '@/utils/api-error'

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

// 信息面板状态
const showInfoPanel = ref(false)
const showUnsavedConfirm = ref(false)

// 用户权限
const userStore = useUserStore()
const canEdit = computed(() => {
  if (!props.image) return false
  if (userStore.isAdmin) return true
  return props.image.uploaded_by === userStore.user?.id
})

// API
const updateMutation = useUpdateImage()
const resolveMutation = useResolveTag()
const { data: allTags } = useTags(100)
const { data: categories } = useCategories()

// 编辑用标签对象类型{ id, name }
interface DraftTag {
  id: number
  name: string
}

// ========== 编辑状态（本地草稿） ==========
const draftCategoryId = ref<number | null>(null)
const draftNormalTags = ref<DraftTag[]>([])  // 存储 { id, name } 对象
const draftDescription = ref('')
const isEditingDescription = ref(false)
const descriptionInput = ref<HTMLTextAreaElement | null>(null)

// 标签输入
const showTagInput = ref(false)
const newTagInput = ref('')
const tagInputRef = ref<HTMLInputElement | null>(null)
const isResolvingTag = ref(false)  // 正在解析标签
const isComposing = ref(false)  // 中文输入法组合状态

// 原始数据（用于检测变化）
const originalCategoryId = ref<number | null>(null)
const originalNormalTagIds = ref<number[]>([])
const originalDescription = ref('')

// 同步 props.image 到本地草稿
watch(() => props.image, (img) => {
  if (img) {
    const tags = img.tags || []
    
    // Level 0: 主分类
    const cat = tags.find(t => t.level === 0)
    const catTag = categories.value?.find(c => c.name === cat?.name)
    draftCategoryId.value = catTag?.id ?? null
    originalCategoryId.value = catTag?.id ?? null
    
    // Level 2: 普通标签 - 存储为 { id, name } 对象
    const normalTagObjs = tags.filter(t => t.level === 2 || t.level === undefined)
      .map(t => ({ id: t.id || 0, name: t.name }))
    draftNormalTags.value = [...normalTagObjs]
    originalNormalTagIds.value = normalTagObjs.map(t => t.id)
    
    // 描述
    draftDescription.value = img.description || ''
    originalDescription.value = img.description || ''
    
    // 重置编辑状态
    isEditingDescription.value = false
    showTagInput.value = false
    newTagInput.value = ''
  }
}, { immediate: true })

// 分辨率标签（只读）
const resolutionTags = computed(() => 
  (props.image?.tags || []).filter(t => t.level === 1)
)

// 检测是否有未保存的修改
const hasChanges = computed(() => {
  if (draftCategoryId.value !== originalCategoryId.value) return true
  if (draftDescription.value !== originalDescription.value) return true
  const currentIds = draftNormalTags.value.map(t => t.id).sort()
  const originalIds = [...originalNormalTagIds.value].sort()
  if (currentIds.length !== originalIds.length) return true
  return !currentIds.every((id, i) => id === originalIds[i])
})

// 开始编辑描述
async function startEditDescription() {
  if (!canEdit.value) return
  isEditingDescription.value = true
  await nextTick()
  descriptionInput.value?.focus()
  autoResizeTextarea()
}

// 自动调整 textarea 高度
function autoResizeTextarea() {
  const textarea = descriptionInput.value
  if (!textarea) return
  textarea.style.height = 'auto'
  const newHeight = Math.min(Math.max(textarea.scrollHeight, 60), 150) // min 60px, max 150px
  textarea.style.height = newHeight + 'px'
}

// 显示添加标签输入
async function showAddTag() {
  if (!canEdit.value) return
  showTagInput.value = true
  await nextTick()
  tagInputRef.value?.focus()
}

// 添加普通标签（调用 resolve API 获取/创建标签 ID）
async function addTag() {
  // 如果正在输入法组合中，不处理
  if (isComposing.value) return
  
  const tagName = newTagInput.value.trim()
  if (!tagName) return
  
  // 检查是否已存在
  if (draftNormalTags.value.some(t => t.name.toLowerCase() === tagName.toLowerCase())) {
    newTagInput.value = ''
    return
  }
  
  try {
    isResolvingTag.value = true
    const resolved = await resolveMutation.mutateAsync({ name: tagName, level: 2 })
    
    // 添加到草稿
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

// 从建议列表选择标签（已有标签，直接添加无需 API）
function selectSuggestion(tag: { id: number; name: string }) {
  draftNormalTags.value.push({ id: tag.id, name: tag.name })
  newTagInput.value = ''
  showTagInput.value = false
}

// 删除普通标签（从草稿）
function removeTag(tagId: number) {
  if (!canEdit.value) return
  draftNormalTags.value = draftNormalTags.value.filter(t => t.id !== tagId)
}

// 标签建议
const tagSuggestions = computed(() => {
  if (!allTags.value || !newTagInput.value) return []
  const input = newTagInput.value.toLowerCase()
  const existingIds = new Set(draftNormalTags.value.map(t => t.id))
  return allTags.value
    .filter(t => t.level === 2 && t.name.toLowerCase().includes(input) && !existingIds.has(t.id))
    .slice(0, 5)
})

// ========== 保存 ==========
async function saveChanges() {
  if (!props.image || !hasChanges.value) return
  
  try {
    // 构建标签 ID 列表
    const allTagIds: number[] = []
    
    // 添加主分类 ID
    if (draftCategoryId.value) {
      allTagIds.push(draftCategoryId.value)
    }
    
    // 添加分辨率标签 ID（保持不变）
    resolutionTags.value.forEach(t => {
      if (t.id) allTagIds.push(t.id)
    })
    
    // 添加普通标签 ID
    draftNormalTags.value.forEach(t => allTagIds.push(t.id))
    
    await updateMutation.mutateAsync({
      id: props.image.id,
      data: {
        tag_ids: allTagIds,  // 使用新的 tag_ids 参数
        description: draftDescription.value,
      }
    })
    
    // 更新原始值
    originalCategoryId.value = draftCategoryId.value
    originalNormalTagIds.value = draftNormalTags.value.map(t => t.id)
    originalDescription.value = draftDescription.value
    
    emit('updated')
    toast.success('保存成功')
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  }
}

// 放弃修改
function discardChanges() {
  draftCategoryId.value = originalCategoryId.value
  // 恢复原始标签
  const tags = props.image?.tags || []
  const normalTagObjs = tags.filter(t => t.level === 2 || t.level === undefined)
    .map(t => ({ id: t.id || 0, name: t.name }))
  draftNormalTags.value = [...normalTagObjs]
  draftDescription.value = originalDescription.value
  isEditingDescription.value = false
}

// 格式化文件大小
function formatFileSize(bytes?: number | null): string {
  if (!bytes) return '-'
  if (bytes < 100) {
    if (bytes < 1) return (bytes * 1024).toFixed(0) + ' KB'
    return bytes.toFixed(2) + ' MB'
  }
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
}

function getImageUrl(url?: string): string {
  return url || ''
}

function handleBackdropClick() {
  if (showInfoPanel.value) {
    tryClosePanel()
  } else {
    tryClose()
  }
}

// 尝试关闭抽屉（检查未保存）
function tryClosePanel() {
  if (canEdit.value && hasChanges.value) {
    showUnsavedConfirm.value = true
  } else {
    showInfoPanel.value = false
  }
}

// 尝试关闭整个模态框
function tryClose() {
  if (canEdit.value && hasChanges.value) {
    showUnsavedConfirm.value = true
  } else {
    emit('close')
  }
}

// 确认保存后关闭
async function confirmSaveAndClose() {
  await saveChanges()
  showUnsavedConfirm.value = false
  showInfoPanel.value = false
}

// 放弃并关闭
function confirmDiscardAndClose() {
  discardChanges()
  showUnsavedConfirm.value = false
  showInfoPanel.value = false
}

function handleKeydown(e: KeyboardEvent) {
  if (!props.image) return
  if (isEditingDescription.value || showTagInput.value) return
  
  if (e.key === 'Escape') {
    if (showUnsavedConfirm.value) {
      showUnsavedConfirm.value = false
    } else if (showInfoPanel.value) {
      tryClosePanel()
    } else {
      tryClose()
    }
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
    <Transition name="image-modal">
      <div 
        v-if="image" 
        class="fixed inset-0 z-[100] bg-black group/modal"
      >
        <!-- 全屏图片区域 -->
        <div 
          class="absolute inset-0 flex items-center justify-center"
          @click.self="handleBackdropClick"
        >
          <img 
            :src="getImageUrl(image.image_url)" 
            :alt="image.description || '图片预览'"
            class="max-w-full max-h-full object-contain select-none cursor-default"
            @click="showInfoPanel && (showInfoPanel = false)"
          />
        </div>

        <!-- 顶部控制栏 -->
        <div class="absolute top-4 right-4 flex items-center gap-2 opacity-0 group-hover/modal:opacity-100 transition-opacity duration-300 z-20">
          <button 
            class="p-2.5 bg-black/40 hover:bg-black/60 rounded-full transition-colors backdrop-blur-sm"
            :class="{ 'bg-white/20': showInfoPanel }"
            @click="showInfoPanel = !showInfoPanel"
            title="显示详情 (i)"
          >
            <Info class="w-5 h-5 text-white" />
          </button>
          <button 
            class="p-2.5 bg-black/40 hover:bg-black/60 rounded-full transition-colors backdrop-blur-sm"
            @click="emit('close')"
            title="关闭 (Esc)"
          >
            <X class="w-5 h-5 text-white" />
          </button>
        </div>

        <!-- 未保存确认弹窗 -->
        <Transition name="fade">
          <div v-if="showUnsavedConfirm" class="fixed inset-0 z-[110] flex items-center justify-center bg-black/50">
            <div class="bg-gray-900 border border-white/20 rounded-xl p-5 max-w-sm mx-4 shadow-2xl">
              <p class="text-white text-sm mb-4">有未保存的修改，是否保存？</p>
              <div class="flex gap-2 justify-end">
                <button
                  @click="confirmDiscardAndClose"
                  class="px-4 py-2 text-sm text-white/70 hover:text-white"
                >
                  放弃
                </button>
                <button
                  @click="confirmSaveAndClose"
                  :disabled="updateMutation.isPending.value"
                  class="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-50"
                >
                  <Loader2 v-if="updateMutation.isPending.value" class="w-4 h-4 animate-spin inline mr-1" />
                  保存
                </button>
              </div>
            </div>
          </div>
        </Transition>

        <!-- 左侧切换按钮 -->
        <button
          v-if="canNavigatePrev"
          class="absolute left-4 top-1/2 -translate-y-1/2 p-4 bg-black/40 hover:bg-black/60 rounded-full backdrop-blur-sm opacity-0 group-hover/modal:opacity-100 transition-all duration-300 hover:scale-110 z-20"
          @click="emit('prev')"
          title="上一张 (←)"
        >
          <ChevronLeft class="w-6 h-6 text-white" />
        </button>

        <!-- 右侧切换按钮 -->
        <button
          v-if="canNavigateNext"
          class="absolute right-4 top-1/2 -translate-y-1/2 p-4 bg-black/40 hover:bg-black/60 rounded-full backdrop-blur-sm opacity-0 group-hover/modal:opacity-100 transition-all duration-300 hover:scale-110 z-20"
          @click="emit('next')"
          title="下一张 (→)"
        >
          <ChevronRight class="w-6 h-6 text-white" />
        </button>

        <!-- 底部计数器 -->
        <div 
          v-if="totalCount" 
          class="absolute bottom-4 right-4 px-3 py-1.5 bg-black/40 rounded-full text-white/90 text-sm font-medium backdrop-blur-sm opacity-0 group-hover/modal:opacity-100 transition-opacity duration-300 z-20"
        >
          {{ (currentIndex ?? 0) + 1 }} / {{ totalCount }}
        </div>

        <!-- 信息抽屉 -->
        <Transition name="drawer">
          <div 
            v-if="showInfoPanel"
            class="absolute top-0 right-0 bottom-0 w-80 bg-black/60 backdrop-blur-md overflow-y-auto z-10"
            @click.stop
          >
            <!-- 抽屉头部（简洁） -->
            <div class="sticky top-0 bg-black/80 backdrop-blur-sm px-4 py-3 flex items-center justify-end border-b border-white/10">
              <button 
                @click="tryClosePanel"
                class="p-1 hover:bg-white/10 rounded"
              >
                <ChevronRight class="w-4 h-4 text-white" />
              </button>
            </div>

            <div class="p-4 space-y-5">
              <!-- 元信息 -->
              <div class="flex flex-wrap gap-3 text-sm text-white/80">
                <span class="flex items-center gap-1.5 px-2 py-1 bg-white/10 rounded-lg">
                  <Hash class="w-3.5 h-3.5 text-white/50" />
                  {{ image.id }}
                </span>
                <span v-if="image.width && image.height" class="flex items-center gap-1.5 px-2 py-1 bg-white/10 rounded-lg">
                  <Ruler class="w-3.5 h-3.5 text-white/50" />
                  {{ image.width }} × {{ image.height }}
                </span>
                <span v-if="image.file_size" class="flex items-center gap-1.5 px-2 py-1 bg-white/10 rounded-lg">
                  <HardDrive class="w-3.5 h-3.5 text-white/50" />
                  {{ formatFileSize(image.file_size) }}
                </span>
              </div>

              <!-- 主分类（下拉选择） -->
              <div class="space-y-2">
                <div class="text-xs text-white/60">主分类</div>
                <select
                  v-if="canEdit"
                  v-model="draftCategoryId"
                  class="max-w-[180px] px-3 py-1.5 text-sm bg-white/10 text-white border border-white/20 rounded-lg focus:outline-none focus:border-white/40 truncate"
                >
                  <option :value="null" class="bg-gray-900">未分类</option>
                  <option v-for="cat in categories" :key="cat.id" :value="cat.id" class="bg-gray-900">
                    {{ cat.name }}
                  </option>
                </select>
                <div v-else class="inline-block px-3 py-1.5 text-sm text-white/80 bg-white/5 rounded-lg">
                  {{ categories?.find(c => c.id === draftCategoryId)?.name || '未分类' }}
                </div>
              </div>

              <!-- 分辨率标签（只读） -->
              <div v-if="resolutionTags.length" class="space-y-2">
                <div class="text-xs text-white/60">分辨率</div>
                <div class="flex flex-wrap gap-2">
                  <span 
                    v-for="tag in resolutionTags" 
                    :key="tag.name"
                    class="px-2.5 py-1 bg-blue-500/70 text-white text-xs rounded-full"
                  >
                    {{ tag.name }}
                  </span>
                </div>
              </div>

              <!-- 普通标签（可编辑） -->
              <div class="space-y-2">
                <div class="flex items-center gap-2 text-xs text-white/60">
                  <span>标签</span>
                  <span v-if="canEdit" class="text-white/40">(可增删)</span>
                  <span v-else class="text-amber-400/80">只读</span>
                </div>
                <div class="flex flex-wrap gap-2">
                  <button 
                    v-for="tag in draftNormalTags" 
                    :key="tag.id"
                    @click="removeTag(tag.id)"
                    class="px-2.5 py-1 bg-white/15 text-white/90 text-xs rounded-full transition-opacity group"
                    :class="canEdit ? 'hover:opacity-70 cursor-pointer' : 'cursor-default'"
                  >
                    #{{ tag.name }}
                    <X v-if="canEdit" class="w-3 h-3 inline ml-1 opacity-0 group-hover:opacity-100" />
                  </button>

                  <!-- 添加标签输入 -->
                  <div v-if="showTagInput" class="relative">
                    <input
                      ref="tagInputRef"
                      v-model="newTagInput"
                      @keydown.enter.prevent="addTag"
                      @keyup.escape="showTagInput = false; newTagInput = ''"
                      @compositionstart="isComposing = true"
                      @compositionend="isComposing = false"
                      placeholder="输入标签后回车"
                      class="w-32 px-2 py-1 text-xs bg-white/20 text-white border border-white/30 rounded-full focus:outline-none focus:border-white/60 placeholder:text-white/50"
                    />
                    <div v-if="tagSuggestions.length" class="absolute top-full left-0 mt-1 w-32 bg-black/90 border border-white/20 rounded-lg shadow-lg z-10 py-1">
                      <button
                        v-for="sug in tagSuggestions"
                        :key="sug.id"
                        @mousedown.prevent="selectSuggestion(sug)"
                        class="block w-full text-left px-2 py-1 text-xs text-white/80 hover:bg-white/10"
                      >
                        {{ sug.name }}
                      </button>
                    </div>
                  </div>
                  <button
                    v-if="canEdit && !showTagInput"
                    @click="showAddTag"
                    class="px-2.5 py-1 border border-dashed border-white/30 text-white/60 text-xs rounded-full hover:border-white/60 hover:text-white transition-colors"
                  >
                    <Plus class="w-3 h-3 inline mr-1" />添加
                  </button>
                </div>
              </div>

              <!-- 描述（可编辑） -->
              <div class="space-y-2">
                <div class="flex items-center gap-2 text-xs text-white/60">
                  <Pencil class="w-3 h-3" />
                  <span>描述</span>
                  <span v-if="canEdit" class="text-white/40">(可编辑)</span>
                  <span v-else class="text-amber-400/80">只读</span>
                </div>

                <div v-if="isEditingDescription" class="space-y-2">
                  <textarea
                    ref="descriptionInput"
                    v-model="draftDescription"
                    maxlength="150"
                    class="w-full px-3 py-2 text-sm bg-white/10 text-white border border-white/20 rounded-lg focus:outline-none focus:border-white/40 placeholder:text-white/40 overflow-hidden"
                    style="min-height: 60px; max-height: 150px; resize: none;"
                    placeholder="输入图片描述（最多150字）..."
                    @input="autoResizeTextarea"
                    @keydown.escape="isEditingDescription = false"
                  />
                  <button
                    @click="isEditingDescription = false"
                    class="px-3 py-1 text-xs text-white/70 hover:text-white"
                  >
                    完成
                  </button>
                </div>

                <div
                  v-else
                  @click="canEdit && startEditDescription()"
                  class="p-3 text-sm text-white/80 leading-relaxed rounded-lg border border-transparent transition-colors min-h-[60px]"
                  :class="[
                    draftDescription ? '' : 'text-white/40 italic',
                    canEdit ? 'hover:border-dashed hover:border-white/30 cursor-text' : 'cursor-default'
                  ]"
                >
                  {{ draftDescription || (canEdit ? '点击添加描述...' : '暂无描述') }}
                </div>
              </div>

              <!-- 保存按钮区域 -->
              <div v-if="canEdit && hasChanges" class="pt-3 border-t border-white/10 flex items-center gap-3">
                <button
                  @click="saveChanges"
                  :disabled="updateMutation.isPending.value"
                  class="flex-1 flex items-center justify-center gap-2 py-2.5 text-sm font-medium bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 shadow-lg shadow-blue-500/30"
                >
                  <Loader2 v-if="updateMutation.isPending.value" class="w-4 h-4 animate-spin" />
                  <Save v-else class="w-4 h-4" />
                  保存修改
                </button>
                <button
                  @click="discardChanges"
                  class="px-4 py-2.5 text-sm text-white/70 hover:text-white bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
                >
                  放弃
                </button>
              </div>
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.image-modal-enter-active,
.image-modal-leave-active {
  transition: opacity 0.2s ease;
}
.image-modal-enter-from,
.image-modal-leave-to {
  opacity: 0;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: transform 0.25s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  transform: translateX(100%);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
