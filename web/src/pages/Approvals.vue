<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { 
  Check, 
  X, 
  Loader2,
  RefreshCw,
  Inbox,
  User,
  Clock,
  Tag,
  AlignLeft
} from 'lucide-vue-next'
import { useApprovals, useApproveApproval, useRejectApproval } from '@/api/queries'
import type { ApprovalResponse } from '@/types'

const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()

const params = ref({ page: 1, size: 50, types: 'suggest_image_update', include_preview: true })
const { data, isLoading, refetch } = useApprovals(params)
const approveMutation = useApproveApproval()
const rejectMutation = useRejectApproval()

const approvals = computed(() => data.value?.data || [])
const total = computed(() => data.value?.total || 0)

function requesterDisplay(approval: ApprovalResponse): string {
  const username = approval.requester_name
  const id = approval.requester_id
  if (username && id != null) return `${username} (#${id})`
  if (username) return username
  if (id != null) return `#${id}`
  return '-'
}

function getSuggestionPayload(approval: ApprovalResponse): {
  base: any
  proposed: any
} {
  const payload = approval.payload as any
  return {
    base: payload?.base || {},
    proposed: payload?.proposed || {},
  }
}

function getTagNames(tags: any): string[] {
  if (!Array.isArray(tags)) return []
  return tags
    .map((t: any) => (typeof t?.name === 'string' ? t.name : ''))
    .filter(Boolean)
}

function diffTags(baseTags: any, proposedTags: any): { added: string[]; removed: string[] } {
  const base = new Set(getTagNames(baseTags))
  const next = new Set(getTagNames(proposedTags))

  const added: string[] = []
  const removed: string[] = []

  next.forEach(name => {
    if (!base.has(name)) added.push(name)
  })
  base.forEach(name => {
    if (!next.has(name)) removed.push(name)
  })

  return { added, removed }
}

async function approve(approvalId: number) {
  try {
    await approveMutation.mutateAsync({ id: approvalId })
    await refetch()
  } catch (e: any) {
    // 错误提示由全局 mutationCache 统一处理
  }
}

async function reject(approvalId: number) {
  const confirmed = await confirm({
    title: '拒绝图片',
    message: '确定要拒绝该修改建议吗？',
    variant: 'danger',
    confirmText: '拒绝',
  })
  if (!confirmed.confirmed) return
  
  try {
    await rejectMutation.mutateAsync({ id: approvalId })
    await refetch()
  } catch (e: any) {
    // 错误提示由全局 mutationCache 统一处理
  }
}

const approvalViews = computed(() => {
  return approvals.value.map((approval) => {
    const suggestion = getSuggestionPayload(approval)
    const diff = diffTags(suggestion.base.normal_tags, suggestion.proposed.normal_tags)
    const previewUrl = approval.preview?.image_url || ''
    return { approval, suggestion, diff, previewUrl }
  })
})
</script>

<template>
  <div class="p-6 lg:p-8">
    <div class="max-w-5xl mx-auto">
      <!-- 标题 -->
      <div class="flex items-center justify-between mb-8">
        <div>
          <h1 class="text-2xl font-bold text-foreground">审批管理</h1>
          <p class="text-muted-foreground mt-1">审批成员提交的修改建议</p>
        </div>
        <div class="flex gap-2">
          <Button variant="outline" size="sm" @click="refetch" :disabled="isLoading">
            <RefreshCw class="w-4 h-4 mr-2" :class="isLoading && 'animate-spin'" />
            刷新
          </Button>
        </div>
      </div>

      <!-- 统计 -->
      <div class="mb-6 text-sm text-muted-foreground">
        待审批: {{ total }} 条建议
      </div>

      <!-- 加载状态 -->
      <div v-if="isLoading" class="flex items-center justify-center py-20">
        <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
      </div>

      <!-- 空状态 -->
      <div v-else-if="approvals.length === 0" class="text-center py-20">
        <div class="w-16 h-16 bg-muted rounded-full flex items-center justify-center mx-auto mb-4">
          <Inbox class="w-8 h-8 text-muted-foreground" />
        </div>
        <p class="text-muted-foreground">暂无待审批建议</p>
      </div>

      <!-- 建议列表 -->
      <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div 
          v-for="view in approvalViews" 
          :key="view.approval.id"
          class="bg-card border border-border rounded-xl overflow-hidden"
        >
          <!-- 图片 -->
          <div class="aspect-video bg-muted relative">
            <img
              v-if="view.previewUrl"
              :src="view.previewUrl"
              alt="图片预览"
              class="w-full h-full object-cover"
            />
            <img 
              v-else
              src=""
              alt=""
              class="w-full h-full object-cover opacity-0"
            />
          </div>
          
          <!-- 信息和操作 -->
          <div class="p-4">
            <div class="space-y-3 mb-4">
              <div class="flex items-center gap-2 text-xs text-muted-foreground">
                <User class="w-3.5 h-3.5" />
                <span>
                  申请人:
                  {{ requesterDisplay(view.approval) }}
                </span>
                <span class="mx-1">·</span>
                <Clock class="w-3.5 h-3.5" />
                <span>{{ view.approval.created_at ? new Date(view.approval.created_at).toLocaleString() : '-' }}</span>
              </div>

              <div class="space-y-2 text-sm">
                <div class="flex items-start gap-2">
                  <AlignLeft class="w-4 h-4 mt-0.5 text-muted-foreground" />
                  <div class="flex-1 min-w-0">
                    <div class="text-xs text-muted-foreground">描述</div>
                    <div class="text-foreground line-clamp-2">
                      {{ view.suggestion.base.description || '（空）' }}
                      <span class="text-muted-foreground mx-1">→</span>
                      {{ view.suggestion.proposed.description || '（空）' }}
                    </div>
                  </div>
                </div>

                <div class="flex items-start gap-2">
                  <Tag class="w-4 h-4 mt-0.5 text-muted-foreground" />
                  <div class="flex-1 min-w-0">
                    <div class="text-xs text-muted-foreground">分类</div>
                    <div class="text-foreground">
                      {{ view.suggestion.base.category_name || '未分类' }}
                      <span class="text-muted-foreground mx-1">→</span>
                      {{ view.suggestion.proposed.category_name || '未分类' }}
                    </div>
                  </div>
                </div>

                <div class="flex items-start gap-2">
                  <Tag class="w-4 h-4 mt-0.5 text-muted-foreground opacity-60" />
                  <div class="flex-1 min-w-0">
                    <div class="text-xs text-muted-foreground">标签变更</div>
                    <div class="text-xs text-foreground">
                      <span v-if="view.diff.added.length">
                        +{{ view.diff.added.join('、') }}
                      </span>
                      <span
                        v-if="view.diff.removed.length"
                        class="text-muted-foreground"
                      >
                        <span v-if="view.diff.added.length"> · </span>
                        -{{ view.diff.removed.join('、') }}
                      </span>
                      <span
                        v-if="!view.diff.added.length && !view.diff.removed.length"
                        class="text-muted-foreground"
                      >
                        无变更
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <p v-if="view.suggestion.proposed.comment" class="text-xs text-muted-foreground">
                备注：{{ view.suggestion.proposed.comment }}
              </p>
            </div>

            <div class="flex gap-2">
              <Button 
                size="sm" 
                class="flex-1"
                @click="approve(view.approval.id)"
                :disabled="approveMutation.isPending.value || rejectMutation.isPending.value"
              >
                <Check class="w-4 h-4 mr-1" />
                通过
              </Button>
              <Button 
                variant="outline" 
                size="sm" 
                class="flex-1 text-destructive hover:text-destructive"
                @click="reject(view.approval.id)"
                :disabled="approveMutation.isPending.value || rejectMutation.isPending.value"
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
