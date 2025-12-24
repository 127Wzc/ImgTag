<template>
  <div class="tags-page">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><CollectionTag /></el-icon>
        标签管理
      </h1>
      <p class="page-description">管理系统中的所有标签，查看使用统计</p>
    </div>

    <div class="card">
      <div class="toolbar">
        <el-button type="primary" @click="handleSync" :loading="syncing">
          <el-icon><Refresh /></el-icon> 同步标签
        </el-button>
        <div class="toolbar-right">
          <el-input
            v-model="searchQuery"
            placeholder="搜索标签..."
            :prefix-icon="Search"
            style="width: 250px;"
            clearable
          />
        </div>
      </div>

      <div class="stats-row">
        <div class="stat-item">
          <span class="stat-value">{{ totalCount }}</span>
          <span class="stat-label">标签总数</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ totalUsage }}</span>
          <span class="stat-label">总使用次数</span>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="filteredTags"
        style="width: 100%;"
        :default-sort="{ prop: 'usage_count', order: 'descending' }"
      >
        <el-table-column prop="name" label="标签名" sortable min-width="200">
          <template #default="{ row }">
            <div v-if="editingId === row.id" class="edit-cell">
              <el-input
                v-model="editName"
                size="small"
                @keyup.enter="saveEdit(row)"
                @keyup.esc="cancelEdit"
              />
              <el-button link type="primary" @click="saveEdit(row)">保存</el-button>
              <el-button link @click="cancelEdit">取消</el-button>
            </div>
            <span v-else>{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="usage_count" label="图片数量" width="120" sortable align="center">
          <template #default="{ row }">
            <el-tag type="info" size="small">{{ row.usage_count || 0 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.source === 'user'" type="success" size="small">用户</el-tag>
            <el-tag v-else type="info" size="small">AI</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="right">
          <template #default="{ row }">
            <el-button
              v-if="editingId !== row.id"
              link
              type="primary"
              @click="startEdit(row)"
            >
              重命名
            </el-button>
            <el-popconfirm
              title="确定要删除这个标签吗？这将从所有图片中移除该标签。"
              @confirm="handleDelete(row)"
            >
              <template #reference>
                <el-button link type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search, CollectionTag } from '@element-plus/icons-vue'
import { getTags, syncTags, renameTag, deleteTag } from '@/api'

const loading = ref(false)
const syncing = ref(false)
const tags = ref([])
const searchQuery = ref('')

const editingId = ref(null)
const editName = ref('')

const totalCount = computed(() => tags.value.length)
const totalUsage = computed(() => tags.value.reduce((sum, t) => sum + (t.usage_count || 0), 0))

const filteredTags = computed(() => {
  if (!searchQuery.value) return tags.value
  const query = searchQuery.value.toLowerCase()
  return tags.value.filter(tag => tag.name.toLowerCase().includes(query))
})

const fetchTags = async () => {
  loading.value = true
  try {
    const res = await getTags({ limit: 1000, sort_by: 'usage_count' })
    tags.value = res
  } catch (error) {
    ElMessage.error('获取标签列表失败')
  } finally {
    loading.value = false
  }
}

const handleSync = async () => {
  syncing.value = true
  try {
    const res = await syncTags()
    ElMessage.success(res.message)
    fetchTags()
  } catch (error) {
    ElMessage.error('同步标签失败')
  } finally {
    syncing.value = false
  }
}

const startEdit = (row) => {
  editingId.value = row.id
  editName.value = row.name
}

const cancelEdit = () => {
  editingId.value = null
  editName.value = ''
}

const saveEdit = async (row) => {
  if (!editName.value || editName.value === row.name) {
    cancelEdit()
    return
  }

  try {
    await renameTag(row.name, editName.value)
    ElMessage.success('重命名成功')
    row.name = editName.value
    cancelEdit()
  } catch (error) {
    ElMessage.error(error.message || '重命名失败')
  }
}

const handleDelete = async (row) => {
  try {
    await deleteTag(row.name)
    ElMessage.success('删除成功')
    tags.value = tags.value.filter(t => t.id !== row.id)
  } catch (error) {
    ElMessage.error('删除失败')
  }
}

onMounted(() => {
  fetchTags()
})
</script>

<style scoped>
.tags-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header {
  margin-bottom: 8px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 8px 0;
  color: var(--text-primary);
}

.page-title .el-icon {
  color: #8b5cf6;
}

.page-description {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.toolbar-right {
  margin-left: auto;
}

.stats-row {
  display: flex;
  gap: 24px;
  margin-bottom: 24px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px 24px;
  background: var(--bg-secondary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-color-light);
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #8b5cf6;
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.edit-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: var(--bg-secondary);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

:deep(.el-table th.el-table__cell) {
  background: var(--bg-secondary) !important;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.8px;
}

/* 操作按钮样式 - 增强可见度 */
:deep(.el-button--primary.is-link) {
  color: #409eff !important;
  font-weight: 500;
}

:deep(.el-button--danger.is-link) {
  color: #f56c6c !important;
  font-weight: 500;
}

:deep(.el-button.is-link:hover) {
  opacity: 0.8;
}
</style>
