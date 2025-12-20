<template>
  <el-dialog
    v-model="visible"
    title="标签管理"
    width="600px"
    :before-close="handleClose"
  >
    <div class="tag-manager">
      <div class="toolbar">
        <el-button type="primary" @click="handleSync" :loading="syncing">
          <el-icon><Refresh /></el-icon> 同步标签
        </el-button>
        <el-input
          v-model="searchQuery"
          placeholder="搜索标签..."
          prefix-icon="Search"
          style="width: 200px; margin-left: auto;"
          clearable
        />
      </div>

      <el-table
        v-loading="loading"
        :data="filteredTags"
        style="width: 100%; margin-top: 20px;"
        height="400"
      >
        <el-table-column prop="name" label="标签名" sortable>
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
        <el-table-column prop="usage_count" label="使用次数" width="120" sortable />
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
  </el-dialog>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import { getTags, syncTags, renameTag, deleteTag } from '@/api'

const props = defineProps({
  modelValue: Boolean
})

const emit = defineEmits(['update:modelValue', 'tags-updated'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const loading = ref(false)
const syncing = ref(false)
const tags = ref([])
const searchQuery = ref('')

const editingId = ref(null)
const editName = ref('')

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
    emit('tags-updated')
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
    emit('tags-updated')
  } catch (error) {
    ElMessage.error('重命名失败')
  }
}

const handleDelete = async (row) => {
  try {
    await deleteTag(row.name)
    ElMessage.success('删除成功')
    tags.value = tags.value.filter(t => t.id !== row.id)
    emit('tags-updated')
  } catch (error) {
    ElMessage.error('删除失败')
  }
}

const handleClose = () => {
  visible.value = false
}

watch(visible, (val) => {
  if (val) {
    fetchTags()
  }
})
</script>

<style scoped>
.tag-manager {
  padding: 8px 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.08) 0%, rgba(212, 165, 116, 0.05) 100%);
  border-radius: var(--radius-lg);
  margin-bottom: 20px;
}

.edit-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(139, 92, 246, 0.06);
  --el-table-border-color: rgba(139, 92, 246, 0.08);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

:deep(.el-table th.el-table__cell) {
  background: rgba(139, 92, 246, 0.06) !important;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.8px;
  padding: 14px 16px;
}

:deep(.el-table td.el-table__cell) {
  padding: 12px 16px;
  border-bottom: 1px solid rgba(139, 92, 246, 0.06) !important;
}

:deep(.el-table tr:hover > td.el-table__cell) {
  background: rgba(139, 92, 246, 0.04) !important;
}

:deep(.el-dialog) {
  border-radius: 24px !important;
  overflow: hidden;
}

:deep(.el-dialog__header) {
  padding: 20px 24px !important;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(212, 165, 116, 0.05) 100%);
  border-bottom: 1px solid rgba(139, 92, 246, 0.1);
}

:deep(.el-dialog__title) {
  font-weight: 700;
  font-size: 18px;
  color: var(--text-primary);
  /* background: linear-gradient(135deg, #D4AF37 0%, #F3E5AB 100%); */
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

:deep(.el-dialog__body) {
  padding: 24px !important;
}
</style>
