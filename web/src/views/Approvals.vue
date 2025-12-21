<template>
  <div class="approvals-page">
    <div class="page-header">
      <h2>📋 审批管理</h2>
      <div class="header-actions">
        <button 
          v-if="selectedIds.length > 0" 
          class="btn btn-primary"
          @click="handleBatchApprove"
        >
          批量批准 ({{ selectedIds.length }})
        </button>
        <button class="btn btn-secondary" @click="fetchApprovals">
          🔄 刷新
        </button>
      </div>
    </div>

    <div v-if="isLoading" class="loading">加载中...</div>

    <div v-else-if="approvals.length === 0" class="empty-state">
      <p>🎉 暂无待审批项目</p>
    </div>

    <div v-else class="approvals-list">
      <div class="select-all">
        <label>
          <input 
            type="checkbox" 
            :checked="selectedIds.length === approvals.length"
            @change="toggleSelectAll"
          />
          全选
        </label>
      </div>

      <div 
        v-for="approval in approvals" 
        :key="approval.id" 
        class="approval-card"
      >
        <div class="approval-checkbox">
          <input 
            type="checkbox" 
            :checked="selectedIds.includes(approval.id)"
            @change="toggleSelect(approval.id)"
          />
        </div>

        <div class="approval-content">
          <div class="approval-header">
            <span class="approval-type">{{ getTypeLabel(approval.type) }}</span>
            <span class="approval-time">
              {{ formatTime(approval.created_at) }}
            </span>
          </div>

          <div class="approval-meta">
            <span class="requester">
              👤 {{ approval.requester_name || '未知用户' }}
            </span>
          </div>

          <div class="approval-payload">
            <pre>{{ formatPayload(approval.payload) }}</pre>
          </div>
        </div>

        <div class="approval-actions">
          <button 
            class="btn btn-success" 
            @click="handleApprove(approval.id)"
            :disabled="processing === approval.id"
          >
            ✅ 批准
          </button>
          <button 
            class="btn btn-danger" 
            @click="handleReject(approval.id)"
            :disabled="processing === approval.id"
          >
            ❌ 拒绝
          </button>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="total > limit" class="pagination">
      <button 
        :disabled="offset === 0" 
        @click="prevPage"
      >
        上一页
      </button>
      <span>{{ Math.floor(offset / limit) + 1 }} / {{ Math.ceil(total / limit) }}</span>
      <button 
        :disabled="offset + limit >= total" 
        @click="nextPage"
      >
        下一页
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getPendingApprovals, approveRequest, rejectRequest, batchApprove } from '@/api'

const approvals = ref([])
const total = ref(0)
const offset = ref(0)
const limit = ref(20)
const isLoading = ref(false)
const processing = ref(null)
const selectedIds = ref([])

const typeLabels = {
  add_tags: '添加标签',
  update_tags: '修改标签',
  update_description: '修改描述',
  delete_image: '删除图片'
}

function getTypeLabel(type) {
  return typeLabels[type] || type
}

function formatTime(dateStr) {
  return new Date(dateStr).toLocaleString('zh-CN')
}

function formatPayload(payload) {
  return JSON.stringify(payload, null, 2)
}

async function fetchApprovals() {
  isLoading.value = true
  try {
    const result = await getPendingApprovals({ limit: limit.value, offset: offset.value })
    approvals.value = result.approvals || []
    total.value = result.total || 0
  } catch (e) {
    console.error('获取审批列表失败:', e)
  } finally {
    isLoading.value = false
  }
}

function toggleSelect(id) {
  const idx = selectedIds.value.indexOf(id)
  if (idx === -1) {
    selectedIds.value.push(id)
  } else {
    selectedIds.value.splice(idx, 1)
  }
}

function toggleSelectAll() {
  if (selectedIds.value.length === approvals.value.length) {
    selectedIds.value = []
  } else {
    selectedIds.value = approvals.value.map(a => a.id)
  }
}

async function handleApprove(id) {
  processing.value = id
  try {
    await approveRequest(id)
    await fetchApprovals()
  } catch (e) {
    alert('批准失败: ' + e.message)
  } finally {
    processing.value = null
  }
}

async function handleReject(id) {
  const comment = prompt('拒绝原因（可选）:')
  processing.value = id
  try {
    await rejectRequest(id, comment)
    await fetchApprovals()
  } catch (e) {
    alert('拒绝失败: ' + e.message)
  } finally {
    processing.value = null
  }
}

async function handleBatchApprove() {
  if (!confirm(`确定批量批准 ${selectedIds.value.length} 项？`)) return
  
  isLoading.value = true
  try {
    await batchApprove(selectedIds.value)
    selectedIds.value = []
    await fetchApprovals()
  } catch (e) {
    alert('批量批准失败: ' + e.message)
  } finally {
    isLoading.value = false
  }
}

function prevPage() {
  offset.value = Math.max(0, offset.value - limit.value)
  fetchApprovals()
}

function nextPage() {
  offset.value += limit.value
  fetchApprovals()
}

onMounted(() => {
  fetchApprovals()
})
</script>

<style scoped>
.approvals-page {
  padding: 1.5rem;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.page-header h2 {
  margin: 0;
  color: var(--color-text);
}

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.loading, .empty-state {
  text-align: center;
  padding: 3rem;
  color: var(--color-text-secondary);
}

.select-all {
  padding: 0.75rem 1rem;
  background: var(--color-bg-secondary);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.select-all label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.approvals-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.approval-card {
  display: flex;
  gap: 1rem;
  padding: 1rem;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  transition: box-shadow 0.2s;
}

.approval-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.approval-checkbox {
  display: flex;
  align-items: flex-start;
  padding-top: 0.25rem;
}

.approval-content {
  flex: 1;
  min-width: 0;
}

.approval-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.approval-type {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  background: var(--color-primary);
  color: white;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
}

.approval-time {
  color: var(--color-text-secondary);
  font-size: 0.75rem;
}

.approval-meta {
  margin-bottom: 0.5rem;
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.approval-payload {
  background: var(--color-bg-secondary);
  border-radius: 8px;
  padding: 0.5rem;
  overflow: auto;
}

.approval-payload pre {
  margin: 0;
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
}

.approval-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.btn {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.875rem;
  font-weight: 500;
  transition: all 0.2s;
}

.btn-primary {
  background: var(--color-primary);
  color: white;
}

.btn-secondary {
  background: var(--color-bg-secondary);
  color: var(--color-text);
  border: 1px solid var(--color-border);
}

.btn-success {
  background: #10b981;
  color: white;
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
  margin-top: 2rem;
}

.pagination button {
  padding: 0.5rem 1rem;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  cursor: pointer;
}

.pagination button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
