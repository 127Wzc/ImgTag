<script setup lang="ts">
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import { 
  Folder, 
  Plus, 
  Trash2, 
  Image,
  Loader2,
  FolderOpen
} from 'lucide-vue-next'
import type { Collection } from '@/types'

const loading = ref(false)
const collections = ref<Collection[]>([])

async function fetchCollections() {
  loading.value = true
  try {
    const { data } = await apiClient.get('/collections/')
    collections.value = data
  } catch {
    // ignore
  } finally {
    loading.value = false
  }
}

// 新建收藏夹
const showCreateDialog = ref(false)
const newCollectionName = ref('')
const newCollectionDesc = ref('')
const creating = ref(false)

async function handleCreate() {
  if (!newCollectionName.value.trim()) return
  creating.value = true
  try {
    await apiClient.post('/collections/', {
      name: newCollectionName.value.trim(),
      description: newCollectionDesc.value.trim() || null,
    })
    newCollectionName.value = ''
    newCollectionDesc.value = ''
    showCreateDialog.value = false
    await fetchCollections()
  } catch (e: any) {
    alert(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

async function handleDelete(id: number) {
  if (!confirm('确定要删除这个收藏夹吗？')) return
  try {
    await apiClient.delete(`/collections/${id}`)
    await fetchCollections()
  } catch (e: any) {
    alert(e.response?.data?.detail || '删除失败')
  }
}

onMounted(() => {
  fetchCollections()
})
</script>

<template>
  <div class="p-6 lg:p-8">
    <div class="max-w-5xl mx-auto">
      <!-- 标题 -->
      <div class="flex items-center justify-between mb-8">
        <div>
          <h1 class="text-2xl font-bold text-foreground">收藏夹</h1>
          <p class="text-muted-foreground mt-1">管理图片收藏夹</p>
        </div>
        <Button @click="showCreateDialog = true">
          <Plus class="w-4 h-4 mr-2" />
          新建收藏夹
        </Button>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="flex items-center justify-center py-20">
        <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
      </div>

      <!-- 空状态 -->
      <div v-else-if="collections.length === 0" class="text-center py-20">
        <div class="w-16 h-16 bg-muted rounded-full flex items-center justify-center mx-auto mb-4">
          <FolderOpen class="w-8 h-8 text-muted-foreground" />
        </div>
        <p class="text-muted-foreground mb-4">暂无收藏夹</p>
        <Button @click="showCreateDialog = true">
          <Plus class="w-4 h-4 mr-2" />
          创建第一个收藏夹
        </Button>
      </div>

      <!-- 收藏夹列表 -->
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div 
          v-for="collection in collections" 
          :key="collection.id"
          class="bg-card border border-border rounded-xl overflow-hidden group hover:shadow-lg transition-shadow"
        >
          <!-- 封面 -->
          <div class="aspect-video bg-muted flex items-center justify-center">
            <Folder class="w-12 h-12 text-muted-foreground" />
          </div>
          
          <!-- 信息 -->
          <div class="p-4">
            <div class="flex items-start justify-between">
              <div>
                <h3 class="font-semibold text-foreground">{{ collection.name }}</h3>
                <p v-if="collection.description" class="text-sm text-muted-foreground mt-1 line-clamp-2">
                  {{ collection.description }}
                </p>
                <div class="flex items-center gap-2 mt-2 text-sm text-muted-foreground">
                  <Image class="w-4 h-4" />
                  <span>{{ collection.image_count || 0 }} 张图片</span>
                </div>
              </div>
              <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <Button variant="ghost" size="icon" class="text-destructive" @click="handleDelete(collection.id)">
                  <Trash2 class="w-4 h-4" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建弹窗 -->
    <Teleport to="body">
      <Transition name="fade">
        <div 
          v-if="showCreateDialog"
          class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
          @click.self="showCreateDialog = false"
        >
          <div class="bg-card rounded-2xl p-6 w-full max-w-md shadow-xl">
            <h3 class="text-lg font-semibold text-foreground mb-4">新建收藏夹</h3>
            
            <div class="space-y-4">
              <div>
                <label class="block text-sm font-medium text-foreground mb-2">名称</label>
                <input
                  v-model="newCollectionName"
                  type="text"
                  placeholder="输入收藏夹名称"
                  class="w-full px-4 py-2 bg-muted border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-foreground mb-2">描述（可选）</label>
                <textarea
                  v-model="newCollectionDesc"
                  rows="3"
                  placeholder="输入描述"
                  class="w-full px-4 py-2 bg-muted border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                />
              </div>
            </div>

            <div class="flex justify-end gap-2 mt-6">
              <Button variant="outline" @click="showCreateDialog = false">取消</Button>
              <Button 
                @click="handleCreate"
                :disabled="!newCollectionName.trim() || creating"
              >
                <Loader2 v-if="creating" class="w-4 h-4 mr-2 animate-spin" />
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
