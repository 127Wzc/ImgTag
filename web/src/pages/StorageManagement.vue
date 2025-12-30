<script setup lang="ts">
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import { toast } from 'vue-sonner'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { 
  HardDrive, 
  Database, 
  RefreshCw, 
  Trash2,
  Loader2,
  AlertTriangle,
  CheckCircle,
  FolderSync
} from 'lucide-vue-next'

const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()

interface StorageStats {
  total_images: number
  total_size_mb: number
  storage_type: string
  duplicates_count: number
  missing_hash_count: number
}

const loading = ref(false)
const stats = ref<StorageStats | null>(null)

// 操作状态
const scanning = ref(false)
const calculating = ref(false)
const cleaning = ref(false)

async function fetchStats() {
  loading.value = true
  try {
    const { data } = await apiClient.get('/storage/stats')
    stats.value = data
  } catch {
    // ignore
  } finally {
    loading.value = false
  }
}

async function scanDuplicates() {
  scanning.value = true
  try {
    const { data } = await apiClient.post('/storage/scan-duplicates')
    toast.success(`扫描完成: 发现 ${data.duplicates_count} 组重复图片`)
    await fetchStats()
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '扫描失败')
  } finally {
    scanning.value = false
  }
}

async function calculateHashes() {
  calculating.value = true
  try {
    const { data } = await apiClient.post('/storage/calculate-hashes')
    toast.success(`计算完成: 处理了 ${data.processed} 张图片`)
    await fetchStats()
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '计算失败')
  } finally {
    calculating.value = false
  }
}

async function cleanOrphans() {
  const confirmed = await confirm({
    title: '清理孤立文件',
    message: '确定要清理孤立文件吗？此操作不可恢复。',
    variant: 'danger',
    confirmText: '清理',
  })
  if (!confirmed.confirmed) return
  
  cleaning.value = true
  try {
    const { data } = await apiClient.post('/storage/clean-orphans')
    toast.success(`清理完成: 删除了 ${data.deleted_count} 个孤立文件`)
    await fetchStats()
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '清理失败')
  } finally {
    cleaning.value = false
  }
}

function formatSize(mb: number): string {
  if (mb < 1024) return mb.toFixed(2) + ' MB'
  return (mb / 1024).toFixed(2) + ' GB'
}

onMounted(() => {
  fetchStats()
})
</script>

<template>
  <div class="p-6 lg:p-8">
    <div class="max-w-4xl mx-auto">
      <!-- 标题 -->
      <div class="flex items-center justify-between mb-8">
        <div>
          <h1 class="text-2xl font-bold text-foreground">存储管理</h1>
          <p class="text-muted-foreground mt-1">管理图片存储和清理重复文件</p>
        </div>
        <Button variant="outline" @click="fetchStats" :disabled="loading">
          <RefreshCw class="w-4 h-4 mr-2" :class="loading && 'animate-spin'" />
          刷新
        </Button>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading && !stats" class="flex items-center justify-center py-20">
        <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
      </div>

      <div v-else-if="stats" class="space-y-6">
        <!-- 存储统计 -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div class="bg-card border border-border rounded-xl p-6">
            <div class="flex items-center gap-4">
              <div class="w-12 h-12 bg-primary/10 rounded-lg flex items-center justify-center">
                <Database class="w-6 h-6 text-primary" />
              </div>
              <div>
                <p class="text-2xl font-bold text-foreground">{{ stats.total_images }}</p>
                <p class="text-sm text-muted-foreground">总图片数</p>
              </div>
            </div>
          </div>
          
          <div class="bg-card border border-border rounded-xl p-6">
            <div class="flex items-center gap-4">
              <div class="w-12 h-12 bg-blue-500/10 rounded-lg flex items-center justify-center">
                <HardDrive class="w-6 h-6 text-blue-500" />
              </div>
              <div>
                <p class="text-2xl font-bold text-foreground">{{ formatSize(stats.total_size_mb) }}</p>
                <p class="text-sm text-muted-foreground">存储空间</p>
              </div>
            </div>
          </div>
          
          <div class="bg-card border border-border rounded-xl p-6">
            <div class="flex items-center gap-4">
              <div class="w-12 h-12 bg-green-500/10 rounded-lg flex items-center justify-center">
                <CheckCircle class="w-6 h-6 text-green-500" />
              </div>
              <div>
                <p class="text-2xl font-bold text-foreground capitalize">{{ stats.storage_type }}</p>
                <p class="text-sm text-muted-foreground">存储类型</p>
              </div>
            </div>
          </div>
        </div>

        <!-- 重复文件检测 -->
        <div class="bg-card border border-border rounded-xl p-6">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
              <FolderSync class="w-5 h-5 text-muted-foreground" />
              <h3 class="text-lg font-semibold text-foreground">重复文件检测</h3>
            </div>
            <Button 
              variant="outline"
              @click="scanDuplicates"
              :disabled="scanning"
            >
              <Loader2 v-if="scanning" class="w-4 h-4 mr-2 animate-spin" />
              <RefreshCw v-else class="w-4 h-4 mr-2" />
              扫描重复
            </Button>
          </div>
          
          <div v-if="stats.duplicates_count > 0" class="p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg flex items-start gap-3">
            <AlertTriangle class="w-5 h-5 text-yellow-500 shrink-0 mt-0.5" />
            <div>
              <p class="font-medium text-foreground">发现 {{ stats.duplicates_count }} 组重复图片</p>
              <p class="text-sm text-muted-foreground mt-1">建议清理重复文件以节省存储空间</p>
            </div>
          </div>
          <div v-else class="p-4 bg-green-500/10 border border-green-500/20 rounded-lg flex items-center gap-3">
            <CheckCircle class="w-5 h-5 text-green-500" />
            <p class="text-foreground">暂无重复文件</p>
          </div>
        </div>

        <!-- 哈希计算 -->
        <div class="bg-card border border-border rounded-xl p-6">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h3 class="text-lg font-semibold text-foreground">文件哈希计算</h3>
              <p class="text-sm text-muted-foreground mt-1">
                未计算哈希的图片: {{ stats.missing_hash_count }} 张
              </p>
            </div>
            <Button 
              variant="outline"
              @click="calculateHashes"
              :disabled="calculating || stats.missing_hash_count === 0"
            >
              <Loader2 v-if="calculating" class="w-4 h-4 mr-2 animate-spin" />
              计算哈希
            </Button>
          </div>
        </div>

        <!-- 清理孤立文件 -->
        <div class="bg-card border border-border rounded-xl p-6">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-lg font-semibold text-foreground">清理孤立文件</h3>
              <p class="text-sm text-muted-foreground mt-1">
                删除数据库中不存在记录的文件
              </p>
            </div>
            <Button 
              variant="outline"
              class="text-destructive hover:text-destructive"
              @click="cleanOrphans"
              :disabled="cleaning"
            >
              <Loader2 v-if="cleaning" class="w-4 h-4 mr-2 animate-spin" />
              <Trash2 v-else class="w-4 h-4 mr-2" />
              清理
            </Button>
          </div>
        </div>
      </div>
    </div>
  </div>

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
</template>
