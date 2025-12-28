<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useTagStats, useCreateTag, useRenameTag, useDeleteTag, useUpdateTagCounts } from '@/api/queries'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import apiClient from '@/api/client'
import type { Tag } from '@/types'
import { Button } from '@/components/ui/button'
import { toast } from 'vue-sonner'
import { getErrorMessage } from '@/utils/api-error'
import { 
  Plus, 
  Trash2, 
  RefreshCw, 
  Loader2,
  Folder,
  Layers,
  Tag as TagIcon,
  Pencil,
  X,
  Check,
  ChevronLeft,
  ChevronRight
} from 'lucide-vue-next'

const PAGE_SIZE = 200

// 统计数据
const { data: stats, isLoading: statsLoading } = useTagStats()

// 当前选中的分类和页码
const activeLevel = ref(0)
const currentPage = ref(1)

// 重置页码当切换分类时
watch(activeLevel, () => {
  currentPage.value = 1
})

// 按需加载当前分类的标签（支持分页）
const { data: activeTags, isLoading: tagsLoading } = useQuery({
  queryKey: computed(() => ['tags', 'level', activeLevel.value, currentPage.value]),
  queryFn: async () => {
    const offset = (currentPage.value - 1) * PAGE_SIZE
    const { data } = await apiClient.get<Tag[]>('/tags/', {
      params: { level: activeLevel.value, limit: PAGE_SIZE, offset }
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
const totalPages = computed(() => Math.ceil(totalCount.value / PAGE_SIZE))

// 是否需要显示分页
const showPagination = computed(() => totalCount.value > PAGE_SIZE)

// Tab 配置
const tabs = computed(() => [
  { level: 0, label: '主分类', icon: Folder, color: 'text-primary', count: stats.value?.categories ?? 0 },
  { level: 1, label: '分辨率', icon: Layers, color: 'text-blue-500', count: stats.value?.resolutions ?? 0 },
  { level: 2, label: '普通标签', icon: TagIcon, color: 'text-muted-foreground', count: stats.value?.normal_tags ?? 0 },
])

// 编辑状态
const editingTagId = ref<number | null>(null)
const editingName = ref('')

function startEdit(tag: { id: number; name: string }) {
  editingTagId.value = tag.id
  editingName.value = tag.name
}

function cancelEdit() {
  editingTagId.value = null
  editingName.value = ''
}

// 重命名
const renameTagMutation = useRenameTag()
async function handleRename() {
  if (!editingTagId.value || !editingName.value.trim()) return
  try {
    await renameTagMutation.mutateAsync({ 
      id: editingTagId.value, 
      newName: editingName.value.trim() 
    })
    toast.success('重命名成功')
    cancelEdit()
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  }
}

// 新建标签
const showCreateDialog = ref(false)
const newTagName = ref('')
const createTagMutation = useCreateTag()

async function handleCreateTag() {
  if (!newTagName.value.trim()) return
  try {
    await createTagMutation.mutateAsync({
      name: newTagName.value.trim(),
      level: activeLevel.value,
      source: 'user'
    })
    toast.success('创建成功')
    newTagName.value = ''
    showCreateDialog.value = false
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  }
}

// 删除标签
const deleteTagMutation = useDeleteTag()
async function handleDeleteTag(tagId: number) {
  if (!confirm('确定删除？')) return
  try {
    await deleteTagMutation.mutateAsync(tagId)
    toast.success('删除成功')
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  }
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
    <div class="max-w-4xl mx-auto">
      <!-- 操作栏 -->
      <div class="flex items-center justify-end gap-2 mb-4">
        <Button 
          variant="ghost" 
          size="icon"
          @click="updateCountsMutation.mutateAsync()"
          :disabled="updateCountsMutation.isPending.value"
          title="同步"
        >
          <RefreshCw class="w-4 h-4" :class="updateCountsMutation.isPending.value && 'animate-spin'" />
        </Button>
        <Button size="sm" @click="showCreateDialog = true">
          <Plus class="w-4 h-4 mr-1" />
          新建
        </Button>
      </div>

      <!-- Tabs -->
      <div class="flex border-b border-border mb-4">
        <button
          v-for="tab in tabs"
          :key="tab.level"
          @click="activeLevel = tab.level"
          class="flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors"
          :class="[
            activeLevel === tab.level
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          ]"
        >
          <component :is="tab.icon" class="w-4 h-4" :class="tab.color" />
          <span>{{ tab.label }}</span>
          <span class="px-1.5 py-0.5 text-xs rounded-full bg-muted">{{ tab.count }}</span>
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
              <span>{{ tag.name }}</span>
              <span class="text-xs opacity-60">{{ tag.usage_count }}</span>
              
              <div class="hidden group-hover:flex items-center gap-0.5 ml-1">
                <button 
                  class="p-0.5 hover:text-foreground rounded"
                  @click.stop="startEdit(tag)"
                >
                  <Pencil class="w-3 h-3" />
                </button>
                <button 
                  class="p-0.5 hover:text-destructive rounded"
                  @click.stop="handleDeleteTag(tag.id)"
                >
                  <Trash2 class="w-3 h-3" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else class="text-center py-12 text-muted-foreground">
          <component 
            :is="tabs.find(t => t.level === activeLevel)?.icon || TagIcon" 
            class="w-10 h-10 mx-auto mb-3 opacity-50"
          />
          <p class="text-sm">暂无{{ tabs.find(t => t.level === activeLevel)?.label }}</p>
          <Button variant="outline" size="sm" class="mt-3" @click="showCreateDialog = true">
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
