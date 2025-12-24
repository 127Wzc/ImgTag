<template>
  <div class="tasks-page">
    <div class="card">
      <div class="header">
        <h2>
          <el-icon><List /></el-icon>
          任务队列
        </h2>
        <div class="actions">
          <el-button @click="fetchTasks" :loading="loading" plain>
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
          <el-popconfirm
            title="确定要清理 7 天前的已完成任务吗？"
            @confirm="handleCleanup"
          >
            <template #reference>
              <el-button type="danger" plain :loading="cleaning">
                <el-icon><Delete /></el-icon>
                清理旧任务
              </el-button>
            </template>
          </el-popconfirm>
        </div>
      </div>

      <el-table :data="tasks" style="width: 100%" v-loading="loading">
        <el-table-column prop="id" label="任务 ID" width="300">
          <template #default="{ row }">
            <span class="task-id">{{ row.id }}</span>
          </template>
        </el-table-column>
        
        <el-table-column prop="type" label="类型" width="180">
          <template #default="{ row }">
            <el-tag :type="getTaskTypeTag(row.type)" effect="light" round>
              {{ getTaskTypeName(row.type) }}
            </el-tag>
          </template>
        </el-table-column>
        
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" effect="light" round class="status-tag">
              <span class="dot" :class="row.status"></span>
              {{ getStatusName(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        
        <el-table-column prop="created_at" label="创建时间" width="200">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        
        <el-table-column prop="completed_at" label="完成时间" width="200">
          <template #default="{ row }">
            {{ row.completed_at ? formatDate(row.completed_at) : '-' }}
          </template>
        </el-table-column>
        
        <el-table-column label="结果/错误">
          <template #default="{ row }">
            <div v-if="row.error" class="error-text">
              {{ row.error }}
            </div>
            <div v-else-if="row.result" class="result-json">
              <pre>{{ JSON.stringify(row.result, null, 2) }}</pre>
            </div>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
      </el-table>
      
      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          :total="total"
          @size-change="handleSizeChange"
          @current-change="handlePageChange"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getTasks, cleanupTasks } from '@/api'

const tasks = ref([])
const total = ref(0)
const loading = ref(false)
const cleaning = ref(false)
const currentPage = ref(1)
const pageSize = ref(20)
let timer = null

const fetchTasks = async () => {
  loading.value = true
  try {
    const res = await getTasks({
      limit: pageSize.value,
      offset: (currentPage.value - 1) * pageSize.value
    })
    tasks.value = res.tasks
    total.value = res.total
  } catch (e) {
    ElMessage.error('获取任务列表失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

const handleCleanup = async () => {
  cleaning.value = true
  try {
    const res = await cleanupTasks(7)
    ElMessage.success(res.message)
    fetchTasks()
  } catch (e) {
    ElMessage.error('清理失败: ' + e.message)
  } finally {
    cleaning.value = false
  }
}

const handleSizeChange = (val) => {
  pageSize.value = val
  fetchTasks()
}

const handlePageChange = (val) => {
  currentPage.value = val
  fetchTasks()
}

const getTaskTypeTag = (type) => {
  const map = {
    'add_to_collection': 'warning',
    'vectorize_batch': 'primary',
    'analyze_image': 'success'
  }
  return map[type] || 'info'
}

const getTaskTypeName = (type) => {
  const map = {
    'add_to_collection': '添加到收藏夹',
    'vectorize_batch': '批量向量化',
    'analyze_image': '图片分析'
  }
  return map[type] || type
}

const getStatusType = (status) => {
  const map = {
    'pending': 'info',
    'processing': 'primary',
    'completed': 'success',
    'failed': 'danger'
  }
  return map[status] || 'info'
}

const getStatusName = (status) => {
  const map = {
    'pending': '等待中',
    'processing': '进行中',
    'completed': '已完成',
    'failed': '失败'
  }
  return map[status] || status
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString()
}

onMounted(() => {
  fetchTasks()
  // 自动刷新
  timer = setInterval(fetchTasks, 5000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.tasks-page {
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color-light);
}

.header h2 {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.header h2 .el-icon {
  color: var(--primary-color);
  background: rgba(0, 113, 227, 0.1);
  padding: 8px;
  border-radius: 8px;
}

.task-id {
  font-family: 'SF Mono', Monaco, Menlo, Consolas, monospace;
  color: var(--text-secondary);
  font-size: 13px;
}

.status-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.error-text {
  color: var(--danger-color);
  font-size: 13px;
  max-height: 80px;
  overflow-y: auto;
  padding: 8px;
  background: rgba(255, 59, 48, 0.05);
  border-radius: 4px;
}

.result-json {
  font-size: 12px;
  max-height: 80px;
  overflow-y: auto;
  background: var(--bg-secondary);
  padding: 8px;
  border-radius: 6px;
  color: var(--text-primary);
  font-family: 'SF Mono', Monaco, monospace;
}

.text-muted {
  color: var(--text-muted);
}

.pagination {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid var(--border-color-light);
}

/* 覆盖表格样式使其更现代 */
:deep(.el-table) {
  --el-table-header-bg-color: var(--bg-secondary);
  --el-table-row-hover-bg-color: var(--bg-hover);
  border-radius: 8px;
  overflow: hidden;
}

:deep(.el-table th.el-table__cell) {
  font-weight: 600;
  color: var(--text-primary);
}

/* ===== 移动端响应式样式 ===== */
@media (max-width: 768px) {
  .tasks-page {
    padding: 0;
  }
  
  .card {
    padding: 12px;
    overflow: hidden;
  }
  
  .header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
    padding-bottom: 12px;
    margin-bottom: 12px;
  }
  
  .header h2 {
    font-size: 16px;
  }
  
  .actions {
    width: 100%;
    display: flex;
    gap: 8px;
  }
  
  .actions .el-button {
    flex: 1;
    padding: 8px 12px;
    font-size: 13px;
  }
  
  /* 表格整体容器 */
  .el-table {
    width: 100% !important;
  }
  
  /* 隐藏不必要的列 */
  :deep(.el-table th:nth-child(4)),
  :deep(.el-table td:nth-child(4)),
  :deep(.el-table th:nth-child(5)),
  :deep(.el-table td:nth-child(5)) {
    display: none;
  }
  
  /* 缩小任务ID列宽 */
  :deep(.el-table .el-table__cell:first-child) {
    max-width: 100px !important;
    width: 100px !important;
  }
  
  .task-id {
    max-width: 80px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    display: inline-block;
    font-size: 11px;
  }
  
  /* 类型和状态列 */
  :deep(.el-table-column--type),
  :deep(.el-table-column--status) {
    width: auto !important;
  }
  
  /* 结果/错误区域 */
  .error-text,
  .result-json {
    max-height: 50px;
    max-width: 150px;
    font-size: 10px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .result-json pre {
    white-space: pre-wrap;
    word-break: break-all;
    font-size: 10px;
  }
  
  /* 分页 */
  .pagination {
    justify-content: center;
    margin-top: 12px;
    padding-top: 10px;
  }
  
  :deep(.el-pagination) {
    flex-wrap: wrap;
    justify-content: center;
    gap: 6px;
  }
  
  :deep(.el-pagination .el-pagination__sizes),
  :deep(.el-pagination .el-pagination__total) {
    display: none;
  }
}

@media (max-width: 480px) {
  .header h2 {
    font-size: 16px;
  }
  
  .header h2 .el-icon {
    padding: 6px;
  }
  
  .actions {
    flex-direction: column;
  }
  
  .actions .el-button {
    width: 100%;
  }
  
  :deep(.el-table) {
    font-size: 12px;
  }
  
  :deep(.el-table th.el-table__cell),
  :deep(.el-table td.el-table__cell) {
    padding: 8px 4px;
  }
}
</style>

