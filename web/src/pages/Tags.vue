<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useTagStats, useCreateTag, useRenameTag, useDeleteTag, useUpdateTagCounts } from '@/api/queries'
import { useQuery } from '@tanstack/vue-query'
import apiClient from '@/api/client'
import { useUserStore } from '@/stores'
import { usePermission } from '@/composables/usePermission'
import { Permission } from '@/constants/permissions'
import type { Tag } from '@/types'
import { Button } from '@/components/ui/button'
import { notifyError } from '@/utils/notify'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { 
  Plus, 
  Trash2, 
  RefreshCw, 
  Loader2,
  Folder,
  Layers,
  Tag as TagIcon,
  Tags as TagsIcon,
  Pencil,
  X,
  Check,
  ChevronLeft,
  ChevronRight
} from 'lucide-vue-next'

const MAX_PAGE_SIZE = 1000
const pageSizeOptions = [50, 100, 200, 500, 1000]
const userStore = useUserStore()
const { canCreateTags, checkPermissionWithToast } = usePermission()

// 统计数据
const { data: stats, isLoading: statsLoading } = useTagStats()

// 当前选中的分类和页码
const activeLevel = ref(0)
const currentPage = ref(1)
const pageSize = ref(200)

function setPageSize(value: string) {
  const parsed = Number.parseInt(value, 10)
  if (!Number.isFinite(parsed)) return
  const clamped = Math.min(Math.max(parsed, 1), MAX_PAGE_SIZE)
  pageSize.value = clamped
  currentPage.value = 1
}

// 重置页码当切换分类时
watch(activeLevel, () => {
  currentPage.value = 1
})

// 按需加载当前分类的标签（支持分页）
const { data: activeTags, isLoading: tagsLoading } = useQuery({
  queryKey: computed(() => ['tags', 'level', activeLevel.value, currentPage.value, pageSize.value]),
  queryFn: async () => {
    const { data } = await apiClient.get<Tag[]>('/tags/', {
      params: { level: activeLevel.value, size: pageSize.value, page: currentPage.value }
    })
    return data
  },
  staleTime: 5 * 60 * 1000,
})

// 当前分类的总数
const totalCount = computed(() => {
  if (!stats.value) return 0
  switch (activeLevel.value) {
    case 0: return stats.value.categories
    case 1: return stats.value.resolutions
    default: return stats.value.normal_tags
  }
})

// 总页数
const totalPages = computed(() => Math.ceil(totalCount.value / pageSize.value))

// 是否需要显示分页
const showPagination = computed(() => totalCount.value > pageSize.value)

const canManageActiveLevel = computed(() => {
  if (activeLevel.value === 2) return canCreateTags.value
  return userStore.isAdmin
})

function openCreateDialog() {
  if (activeLevel.value === 2) {
    if (!checkPermissionWithToast(Permission.CREATE_TAGS, '新建标签')) return
  } else {
    if (!userStore.isAdmin) {
      notifyError('需要管理员权限', { description: '主分类/分辨率仅管理员可管理' })
      return
    }
  }
  showCreateDialog.value = true
}

// Tab 配置
const tabs = computed(() => [
  { level: 0, label: '主分类', icon: Folder, color: 'text-primary', count: stats.value?.categories ?? 0 },
  { level: 1, label: '分辨率', icon: Layers, color: 'text-blue-500', count: stats.value?.resolutions ?? 0 },
  { level: 2, label: '普通标签', icon: TagIcon, color: 'text-muted-foreground', count: stats.value?.normal_tags ?? 0 },
])

// 编辑状态（内联编辑）
const editingTagId = ref<number | null>(null)
const editingName = ref('')

function startEdit(tag: Tag) {
  if (!canManageActiveLevel.value) {
    if (activeLevel.value === 2) {
      checkPermissionWithToast(Permission.CREATE_TAGS, '修改标签')
    } else {
      notifyError('需要管理员权限', { description: '主分类/分辨率仅管理员可管理' })
    }
    return
  }
  // 对于分类(level=0)，使用弹窗编辑；否则内联编辑
  if (activeLevel.value === 0) {
    showCategoryEdit(tag)
  } else {
    editingTagId.value = tag.id
    editingName.value = tag.name
  }
}

function cancelEdit() {
  editingTagId.value = null
  editingName.value = ''
}

// 分类编辑弹窗状态
const showCategoryEditDialog = ref(false)
const editingCategory = ref<Tag | null>(null)
const categoryEditForm = ref({ name: '', code: '', prompt: '' })

function showCategoryEdit(tag: Tag) {
  editingCategory.value = tag
  categoryEditForm.value = {
    name: tag.name,
    code: tag.code || '',
    prompt: tag.prompt || ''
  }
  showCategoryEditDialog.value = true
}

function closeCategoryEdit() {
  showCategoryEditDialog.value = false
  editingCategory.value = null
}

// 更新标签（支持 name/code/prompt）
const renameTagMutation = useRenameTag()

async function handleRename() {
  if (!editingTagId.value || !editingName.value.trim()) return
  try {
    if (activeLevel.value === 2 && !checkPermissionWithToast(Permission.CREATE_TAGS, '修改标签')) return
    if (activeLevel.value !== 2 && !userStore.isAdmin) {
      notifyError('需要管理员权限', { description: '主分类/分辨率仅管理员可管理' })
      return
    }
    await renameTagMutation.mutateAsync({ 
      id: editingTagId.value, 
      name: editingName.value.trim() 
    })
    cancelEdit()
  } catch {}
}

async function handleCategorySave() {
  if (!editingCategory.value) return
  try {
    if (!userStore.isAdmin) {
      notifyError('需要管理员权限', { description: '主分类仅管理员可管理' })
      return
    }
    await renameTagMutation.mutateAsync({
      id: editingCategory.value.id,
      name: categoryEditForm.value.name.trim() || undefined,
      code: categoryEditForm.value.code.trim() || null,
      prompt: categoryEditForm.value.prompt.trim() || null,
    })
    closeCategoryEdit()
  } catch {}
}

// 新建标签
const showCreateDialog = ref(false)
const newTagName = ref('')
const createTagMutation = useCreateTag()

async function handleCreateTag() {
  if (!newTagName.value.trim()) return
  try {
    if (activeLevel.value === 2 && !checkPermissionWithToast(Permission.CREATE_TAGS, '新建标签')) return
    if (activeLevel.value !== 2 && !userStore.isAdmin) {
      notifyError('需要管理员权限', { description: '主分类/分辨率仅管理员可管理' })
      return
    }
    await createTagMutation.mutateAsync({
      name: newTagName.value.trim(),
      level: activeLevel.value,
      source: 'user'
    })
    newTagName.value = ''
    showCreateDialog.value = false
  } catch {}
}

const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()

// 删除标签
const deleteTagMutation = useDeleteTag()
async function handleDeleteTag(tag: Tag) {
  if (tag.level === 2 && !checkPermissionWithToast(Permission.CREATE_TAGS, '删除标签')) return
  if (tag.level !== 2 && !userStore.isAdmin) {
    notifyError('需要管理员权限', { description: '主分类/分辨率仅管理员可管理' })
    return
  }
  const confirmed = await confirm({
    title: '删除标签',
    message: `确定删除标签 "${tag.name}" 吗？`,
    variant: 'danger',
    confirmText: '删除',
  })
  if (!confirmed.confirmed) return
  
  try {
    await deleteTagMutation.mutateAsync(tag.id)
  } catch {}
}

// 同步
const updateCountsMutation = useUpdateTagCounts()

// 颜色
function getTagColor(level: number) {
  switch (level) {
    case 0: return 'bg-primary/10 text-primary hover:bg-primary/20'
    case 1: return 'bg-blue-500/10 text-blue-600 dark:text-blue-400 hover:bg-blue-500/20'
    default: return 'bg-muted hover:bg-accent'
  }
}

const isLoading = computed(() => statsLoading.value || tagsLoading.value)
</script>

<template>
  <div class="p-6 lg:p-8">
      <!-- 标题区 -->
      <div class="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-foreground flex items-center gap-2">
            <TagsIcon class="w-5 h-5 text-primary" />标签管理
          </h1>
          <p class="text-sm text-muted-foreground mt-1">管理系统标签、分类与分辨率规则</p>
        </div>
        <div class="flex items-center gap-2">
          <Button 
            variant="ghost" 
            size="sm"
            @click="updateCountsMutation.mutateAsync()"
            :disabled="updateCountsMutation.isPending.value"
            class="h-9"
          >
            <RefreshCw class="w-4 h-4 mr-2" :class="updateCountsMutation.isPending.value && 'animate-spin'" />
            同步计数
          </Button>
          <Button
            size="sm"
            class="h-9 gap-1.5"
            :disabled="!canManageActiveLevel"
            @click="openCreateDialog"
          >
            <Plus class="w-4 h-4" />
            新建标签
          </Button>
        </div>
      </div>

      <div class="max-w-6xl mx-auto">
      <!-- 分类 Tabs -->
      <div class="flex items-center p-1 bg-muted/30 rounded-lg w-full sm:w-fit mb-6 border border-border/50">
        <button
          v-for="tab in tabs"
          :key="tab.level"
          @click="activeLevel = tab.level"
          class="flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-1.5 text-sm font-medium rounded-md transition-all"
          :class="[
            activeLevel === tab.level
              ? 'bg-background text-foreground shadow-sm ring-1 ring-border/50'
              : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
          ]"
        >
          <component :is="tab.icon" class="w-4 h-4" :class="activeLevel === tab.level ? tab.color : 'opacity-70'" />
          <span>{{ tab.label }}</span>
          <span class="ml-1.5 bg-muted-foreground/10 px-1.5 py-0.5 rounded-full text-[10px]">{{ tab.count }}</span>
        </button>
      </div>

      <!-- 加载 -->
      <div v-if="isLoading" class="flex items-center justify-center py-16">
        <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
      </div>

      <template v-else>
        <!-- 标签列表 -->
        <div v-if="activeTags?.length" class="flex flex-wrap gap-2">
          <div 
            v-for="tag in activeTags" 
            :key="tag.id"
            class="group relative"
          >
            <!-- 编辑模式 -->
            <div v-if="editingTagId === tag.id" class="flex items-center gap-1">
              <input
                v-model="editingName"
                class="w-32 px-2 py-1 text-sm bg-muted border border-border rounded focus:outline-none focus:ring-1 focus:ring-ring"
                @keyup.enter="handleRename"
                @keyup.esc="cancelEdit"
                autofocus
              />
              <button 
                class="p-1 text-green-500 hover:bg-green-500/10 rounded"
                @click="handleRename"
              >
                <Check class="w-3.5 h-3.5" />
              </button>
              <button 
                class="p-1 text-muted-foreground hover:bg-muted rounded"
                @click="cancelEdit"
              >
                <X class="w-3.5 h-3.5" />
              </button>
            </div>

            <!-- 正常模式 -->
            <div 
              v-else
              class="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-sm cursor-default"
              :class="getTagColor(activeLevel)"
            >
              <!-- 主分类显示 ID（供外部 API 使用） -->
              <span v-if="activeLevel === 0" class="text-xs font-mono opacity-50">#{{ tag.id }}</span>
              <span>{{ tag.name }}</span>
              <span class="text-xs opacity-60">{{ tag.usage_count }}</span>
              
              <div
                v-if="canManageActiveLevel"
                class="flex items-center gap-0.5 ml-1 w-9 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none group-hover:pointer-events-auto"
              >
                <button 
                  class="p-0.5 hover:text-foreground rounded"
                  @click.stop="startEdit(tag)"
                >
                  <Pencil class="w-3 h-3" />
                </button>
                <button 
                  class="p-0.5 hover:text-destructive rounded"
                  @click.stop="handleDeleteTag(tag)"
                >
                  <Trash2 class="w-3 h-3" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 分页大小 -->
        <div v-if="activeTags?.length" class="flex items-center justify-between mt-6">
          <span class="text-xs text-muted-foreground">共 {{ totalCount }} 个</span>
          <div class="flex items-center gap-2">
            <span class="text-xs text-muted-foreground">每页</span>
            <input
              type="number"
              min="1"
              :max="String(MAX_PAGE_SIZE)"
              class="h-8 w-24 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              :value="String(pageSize)"
              @change="setPageSize(($event.target as HTMLInputElement).value)"
              list="tag-page-size-options"
            />
            <datalist id="tag-page-size-options">
              <option v-for="opt in pageSizeOptions" :key="opt" :value="String(opt)" />
            </datalist>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else class="text-center py-12 text-muted-foreground">
          <component 
            :is="tabs.find(t => t.level === activeLevel)?.icon || TagIcon" 
            class="w-10 h-10 mx-auto mb-3 opacity-50"
          />
          <p class="text-sm">暂无{{ tabs.find(t => t.level === activeLevel)?.label }}</p>
          <Button
            variant="outline"
            size="sm"
            class="mt-3"
            :disabled="!canManageActiveLevel"
            @click="openCreateDialog"
          >
            <Plus class="w-4 h-4 mr-1" />
            创建
          </Button>
        </div>

        <!-- 分页 -->
        <div v-if="showPagination" class="flex items-center justify-center gap-2 mt-6">
          <Button 
            variant="outline" 
            size="sm"
            :disabled="currentPage === 1"
            @click="currentPage--"
          >
            <ChevronLeft class="w-4 h-4" />
          </Button>
          <span class="text-sm text-muted-foreground">
            {{ currentPage }} / {{ totalPages }}
          </span>
          <Button 
            variant="outline" 
            size="sm"
            :disabled="currentPage >= totalPages"
            @click="currentPage++"
          >
            <ChevronRight class="w-4 h-4" />
          </Button>
        </div>
      </template>
    </div>

    <!-- 新建弹窗 -->
    <Teleport to="body">
      <Transition name="fade">
        <div 
          v-if="showCreateDialog"
          class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
          @click.self="showCreateDialog = false"
        >
          <div class="bg-card rounded-2xl p-5 w-full max-w-xs shadow-xl">
            <h3 class="text-base font-semibold text-foreground mb-3">
              新建{{ tabs.find(t => t.level === activeLevel)?.label }}
            </h3>
            
            <input
              v-model="newTagName"
              type="text"
              placeholder="输入名称"
              class="w-full px-3 py-2 text-sm bg-muted border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring mb-3"
              @keyup.enter="handleCreateTag"
            />

            <div class="flex justify-end gap-2">
              <Button variant="outline" size="sm" @click="showCreateDialog = false">取消</Button>
              <Button 
                size="sm"
                @click="handleCreateTag"
                :disabled="!newTagName.trim() || createTagMutation.isPending.value"
              >
                创建
              </Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 分类编辑弹窗 -->
    <Teleport to="body">
      <Transition name="fade">
        <div 
          v-if="showCategoryEditDialog"
          class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
          @click.self="closeCategoryEdit"
        >
          <div class="bg-card rounded-2xl p-5 w-full max-w-md shadow-xl">
            <h3 class="text-base font-semibold text-foreground mb-4">
              编辑分类: {{ editingCategory?.name }}
            </h3>
            
            <div class="space-y-4">
              <!-- 名称 -->
              <div>
                <label class="block text-sm font-medium mb-1.5">分类名称</label>
                <input
                  v-model="categoryEditForm.name"
                  type="text"
                  placeholder="分类名称"
                  class="w-full px-3 py-2 text-sm bg-muted border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              
              <!-- 代码 -->
              <div>
                <label class="block text-sm font-medium mb-1.5">存储代码 (用于目录名)</label>
                <input
                  v-model="categoryEditForm.code"
                  type="text"
                  placeholder="如: landscape, portrait, anime"
                  class="w-full px-3 py-2 text-sm bg-muted border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring font-mono"
                />
                <p class="text-xs text-muted-foreground mt-1">文件将存储在: /{code}/ab/cd/hash.jpg</p>
              </div>
              
              <!-- 提示词 -->
              <div>
                <label class="block text-sm font-medium mb-1.5">分析提示词 (追加到全局)</label>
                <textarea
                  v-model="categoryEditForm.prompt"
                  rows="3"
                  placeholder="如: 请特别关注人物的表情和姿态..."
                  class="w-full px-3 py-2 text-sm bg-muted border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                />
              </div>
            </div>

            <div class="flex justify-end gap-2 mt-5">
              <Button variant="outline" size="sm" @click="closeCategoryEdit">取消</Button>
              <Button 
                size="sm"
                @click="handleCategorySave"
                :disabled="renameTagMutation.isPending.value"
              >
                保存
              </Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 确认弹窗 -->
    <ConfirmDialog
      :open="confirmState.open"
      :title="confirmState.title"
      :message="confirmState.message"
      :confirm-text="confirmState.confirmText"
      :cancel-text="confirmState.cancelText"
      :variant="confirmState.variant"
      :loading="confirmState.loading"
      @confirm="handleConfirm"
      @cancel="handleCancel"
    />
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
