<script setup lang="ts">
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import { toast } from 'vue-sonner'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { 
  Check, 
  X, 
  Loader2,
  RefreshCw,
  Inbox
} from 'lucide-vue-next'
import type { ImageResponse } from '@/types'

const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()

const loading = ref(false)
const pendingImages = ref<ImageResponse[]>([])
const total = ref(0)

async function fetchPendingImages() {
  loading.value = true
  try {
    const { data } = await apiClient.post('/images/search', {
      pending_only: true,
      limit: 50,
      offset: 0,
    })
    pendingImages.value = data.images
    total.value = data.total
  } catch {
    // ignore
  } finally {
    loading.value = false
  }
}

async function approve(imageId: number) {
  try {
    await apiClient.post(`/approvals/${imageId}/approve`)
    pendingImages.value = pendingImages.value.filter(img => img.id !== imageId)
    total.value--
    toast.success('已通过')
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '操作失败')
  }
}

async function reject(imageId: number) {
  const confirmed = await confirm({
    title: '拒绝图片',
    message: '确定要拒绝并删除这张图片吗？',
    variant: 'danger',
    confirmText: '拒绝',
  })
  if (!confirmed.confirmed) return
  
  try {
    await apiClient.post(`/approvals/${imageId}/reject`)
    pendingImages.value = pendingImages.value.filter(img => img.id !== imageId)
    total.value--
    toast.success('已拒绝')
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '操作失败')
  }
}

async function approveAll() {
  const confirmed = await confirm({
    title: '批量通过',
    message: `确定要批量通过 ${pendingImages.value.length} 张图片吗？`,
    variant: 'default',
    confirmText: '全部通过',
  })
  if (!confirmed.confirmed) return
  
  try {
    for (const img of pendingImages.value) {
      await apiClient.post(`/approvals/${img.id}/approve`)
    }
    toast.success('批量审批完成')
    await fetchPendingImages()
  } catch (e: any) {
    toast.error(e.response?.data?.detail || '操作失败')
  }
}

function getImageUrl(url: string): string {
  if (url.startsWith('http')) return url
  return url
}

onMounted(() => {
  fetchPendingImages()
})
</script>

<template>
  <div class="p-6 lg:p-8">
    <div class="max-w-5xl mx-auto">
      <!-- 标题 -->
      <div class="flex items-center justify-between mb-8">
        <div>
          <h1 class="text-2xl font-bold text-foreground">审批管理</h1>
          <p class="text-muted-foreground mt-1">审批待处理的图片</p>
        </div>
        <div class="flex gap-2">
          <Button variant="outline" size="sm" @click="fetchPendingImages" :disabled="loading">
            <RefreshCw class="w-4 h-4 mr-2" :class="loading && 'animate-spin'" />
            刷新
          </Button>
          <Button 
            v-if="pendingImages.length > 0"
            size="sm" 
            @click="approveAll"
          >
            <Check class="w-4 h-4 mr-2" />
            全部通过
          </Button>
        </div>
      </div>

      <!-- 统计 -->
      <div class="mb-6 text-sm text-muted-foreground">
        待审批: {{ total }} 张图片
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="flex items-center justify-center py-20">
        <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
      </div>

      <!-- 空状态 -->
      <div v-else-if="pendingImages.length === 0" class="text-center py-20">
        <div class="w-16 h-16 bg-muted rounded-full flex items-center justify-center mx-auto mb-4">
          <Inbox class="w-8 h-8 text-muted-foreground" />
        </div>
        <p class="text-muted-foreground">暂无待审批图片</p>
      </div>

      <!-- 图片列表 -->
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div 
          v-for="image in pendingImages" 
          :key="image.id"
          class="bg-card border border-border rounded-xl overflow-hidden"
        >
          <!-- 图片 -->
          <div class="aspect-video bg-muted relative">
            <img 
              :src="getImageUrl(image.image_url)" 
              :alt="image.description || '图片'"
              class="w-full h-full object-cover"
            />
          </div>
          
          <!-- 信息和操作 -->
          <div class="p-4">
            <p v-if="image.description" class="text-sm text-foreground line-clamp-2 mb-3">
              {{ image.description }}
            </p>
            <div class="flex flex-wrap gap-1 mb-4">
              <span 
                v-for="tag in image.tags.slice(0, 5)" 
                :key="tag.name"
                class="px-2 py-0.5 bg-muted text-muted-foreground text-xs rounded-full"
              >
                {{ tag.name }}
              </span>
            </div>
            <div class="flex gap-2">
              <Button 
                size="sm" 
                class="flex-1"
                @click="approve(image.id)"
              >
                <Check class="w-4 h-4 mr-1" />
                通过
              </Button>
              <Button 
                variant="outline" 
                size="sm" 
                class="flex-1 text-destructive hover:text-destructive"
                @click="reject(image.id)"
              >
                <X class="w-4 h-4 mr-1" />
                拒绝
              </Button>
            </div>
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
