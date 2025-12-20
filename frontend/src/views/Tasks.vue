<template>
  <div class="tasks-page">
    <div class="card">
      <div class="header">
        <h2>
          <el-icon><List /></el-icon>
          任务队列
        </h2>
        <div class="actions">
          <el-button @click="fetchTasks" :loading="loading">
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
            <el-tag :type="getTaskTypeTag(row.type)">
              {{ getTaskTypeName(row.type) }}
            </el-tag>
          </template>
        </el-table-column>
        
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" effect="dark">
              {{ getStatusName(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        
        <el-table-column prop="completed_at" label="完成时间" width="180">
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
            <span v-else>-</span>
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
    'vectorize_batch': 'primary'
  }
  return map[type] || 'info'
}

const getTaskTypeName = (type) => {
  const map = {
    'add_to_collection': '添加到收藏夹',
    'vectorize_batch': '批量向量化'
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
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 20px;
}

.task-id {
  font-family: monospace;
  color: var(--text-secondary);
}

.error-text {
  color: var(--danger-color);
  font-size: 12px;
  max-height: 60px;
  overflow-y: auto;
}

.result-json {
  font-size: 12px;
  max-height: 60px;
  overflow-y: auto;
  background: var(--bg-secondary);
  padding: 4px;
  border-radius: 4px;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}
</style>
