<template>
  <div class="tags-page">
    <div class="page-header">
      <div class="page-header-left">
        <h1 class="page-title">
          <el-icon><CollectionTag /></el-icon>
          标签管理
        </h1>
        <p class="page-description">管理系统标签：主分类、分辨率与普通标签</p>
      </div>
      <el-button type="primary" @click="handleSync" :loading="syncing">
        <el-icon><Refresh /></el-icon> 同步所有标签
      </el-button>
    </div>

    <el-tabs v-model="activeTab" class="tags-tabs" @tab-change="handleTabChange">
      <!-- 主分类管理 -->
      <el-tab-pane label="主分类" name="categories">
        <template #label>
          <span class="tab-label">
            <el-icon><Folder /></el-icon>
            主分类
            <el-badge :value="categories.length" class="tab-badge" type="primary" />
          </span>
        </template>
        
        <div class="tab-content">
          <div class="toolbar">
            <el-button type="primary" @click="showAddCategoryDialog = true">
              <el-icon><Plus /></el-icon> 新增分类
            </el-button>
            <el-button @click="fetchCategories" :loading="loadingCategories">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>
          
          <div class="stats-row">
            <div class="stat-item">
              <span class="stat-value">{{ categories.length }}</span>
              <span class="stat-label">分类总数</span>
            </div>
            <div class="stat-item">
              <span class="stat-value">{{ categoryUsage }}</span>
              <span class="stat-label">总使用次数</span>
            </div>
          </div>
          
          <div class="category-grid">
            <div 
              v-for="cat in categories" 
              :key="cat.id" 
              class="category-card"
            >
              <div class="category-header">
                <span class="category-name">{{ cat.name }}</span>
                <el-tag size="small" type="info">{{ cat.usage_count || 0 }} 张</el-tag>
              </div>
              <p class="category-desc">{{ cat.description || '暂无描述' }}</p>
              <div class="category-actions">
                <el-button 
                  link 
                  type="primary" 
                  size="small"
                  @click="editCategory(cat)"
                >
                  编辑
                </el-button>
                <el-popconfirm
                  :title="cat.usage_count > 0 ? `该分类已被 ${cat.usage_count} 张图片使用，无法删除` : '确定要删除这个分类吗？'"
                  :disabled="cat.usage_count > 0"
                  @confirm="handleDeleteCategory(cat)"
                >
                  <template #reference>
                    <el-button 
                      link 
                      type="danger" 
                      size="small"
                      :disabled="cat.usage_count > 0"
                    >
                      删除
                    </el-button>
                  </template>
                </el-popconfirm>
              </div>
            </div>
            
            <!-- 空状态 -->
            <div v-if="categories.length === 0 && !loadingCategories" class="empty-state">
              <el-empty description="暂无主分类，点击上方按钮添加" />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 分辨率标签 -->
      <el-tab-pane label="分辨率" name="resolutions">
        <template #label>
          <span class="tab-label">
            <el-icon><Monitor /></el-icon>
            分辨率
            <el-badge :value="resolutions.length" class="tab-badge" />
          </span>
        </template>
        
        <div class="tab-content">
          <el-alert 
            type="info" 
            :closable="false"
            show-icon
            style="margin-bottom: 16px;"
          >
            分辨率标签由系统自动管理，用于标识图片的清晰度等级
          </el-alert>
          
          <div class="stats-row">
            <div class="stat-item">
              <span class="stat-value">{{ resolutions.length }}</span>
              <span class="stat-label">分辨率等级</span>
            </div>
            <div class="stat-item">
              <span class="stat-value">{{ resolutionUsage }}</span>
              <span class="stat-label">总使用次数</span>
            </div>
          </div>
          
          <div class="resolution-grid">
            <div 
              v-for="res in resolutions" 
              :key="res.id" 
              class="resolution-card"
            >
              <div class="resolution-icon">
                <el-icon :size="24"><Picture /></el-icon>
              </div>
              <div class="resolution-info">
                <span class="resolution-name">{{ res.name }}</span>
                <span class="resolution-desc">{{ res.description }}</span>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 普通标签 -->
      <el-tab-pane label="普通标签" name="tags">
        <template #label>
          <span class="tab-label">
            <el-icon><PriceTag /></el-icon>
            普通标签
            <el-badge :value="tags.length" class="tab-badge" />
          </span>
        </template>
        
        <div class="tab-content">
          <div class="toolbar">
            <el-button @click="fetchTags" :loading="loading">
              <el-icon><Refresh /></el-icon> 刷新
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
      </el-tab-pane>
    </el-tabs>

    <!-- 新增主分类对话框 -->
    <el-dialog
      v-model="showAddCategoryDialog"
      title="新增主分类"
      width="400px"
      :close-on-click-modal="false"
    >
      <el-form :model="newCategory" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="newCategory.name" placeholder="如：风景、人像" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input 
            v-model="newCategory.description" 
            type="textarea" 
            :rows="2"
            placeholder="分类说明（可选）" 
          />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="newCategory.sortOrder" :min="0" :max="999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddCategoryDialog = false">取消</el-button>
        <el-button type="primary" @click="handleAddCategory" :loading="addingCategory">
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑主分类对话框 -->
    <el-dialog
      v-model="showEditCategoryDialog"
      title="编辑主分类"
      width="400px"
      :close-on-click-modal="false"
    >
      <el-form :model="editingCategory" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="editingCategory.name" disabled />
          <p class="form-tip">主分类名称暂不支持修改</p>
        </el-form-item>
        <el-form-item label="描述">
          <el-input 
            v-model="editingCategory.description" 
            type="textarea" 
            :rows="2"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditCategoryDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { 
  Refresh, Search, CollectionTag, Plus, Folder, 
  Monitor, PriceTag, Picture 
} from '@element-plus/icons-vue'
import { 
  getTags, syncTags, renameTag, deleteTag,
  getCategories, createCategory, deleteCategory,
  getResolutions 
} from '@/api'

// 当前标签页
const activeTab = ref('categories')

// 主分类数据
const categories = ref([])
const loadingCategories = ref(false)
const showAddCategoryDialog = ref(false)
const showEditCategoryDialog = ref(false)
const addingCategory = ref(false)
const newCategory = ref({ name: '', description: '', sortOrder: 0 })
const editingCategory = ref({})

// 分辨率数据
const resolutions = ref([])

// 普通标签数据
const loading = ref(false)
const syncing = ref(false)
const tags = ref([])
const searchQuery = ref('')
const editingId = ref(null)
const editName = ref('')

// 各分类统计
const categoryUsage = computed(() => categories.value.reduce((sum, c) => sum + (c.usage_count || 0), 0))
const resolutionUsage = computed(() => resolutions.value.reduce((sum, r) => sum + (r.usage_count || 0), 0))
const totalCount = computed(() => tags.value.length)
const totalUsage = computed(() => tags.value.reduce((sum, t) => sum + (t.usage_count || 0), 0))

const filteredTags = computed(() => {
  if (!searchQuery.value) return tags.value
  const query = searchQuery.value.toLowerCase()
  return tags.value.filter(tag => tag.name.toLowerCase().includes(query))
})

// 获取主分类
const fetchCategories = async () => {
  loadingCategories.value = true
  try {
    categories.value = await getCategories()
  } catch (error) {
    ElMessage.error('获取主分类失败')
  } finally {
    loadingCategories.value = false
  }
}

// 获取分辨率标签
const fetchResolutions = async () => {
  try {
    resolutions.value = await getResolutions()
  } catch (error) {
    ElMessage.error('获取分辨率标签失败')
  }
}

// 获取普通标签
const fetchTags = async () => {
  loading.value = true
  try {
    const res = await getTags({ limit: 1000, sort_by: 'usage_count' })
    // 只显示 level=2 的普通标签
    tags.value = res.filter(t => !t.level || t.level === 2)
  } catch (error) {
    ElMessage.error('获取标签列表失败')
  } finally {
    loading.value = false
  }
}

// 新增主分类
const handleAddCategory = async () => {
  if (!newCategory.value.name) {
    ElMessage.warning('请输入分类名称')
    return
  }
  
  addingCategory.value = true
  try {
    await createCategory(
      newCategory.value.name, 
      newCategory.value.description, 
      newCategory.value.sortOrder
    )
    ElMessage.success('创建成功')
    showAddCategoryDialog.value = false
    newCategory.value = { name: '', description: '', sortOrder: 0 }
    fetchCategories()
  } catch (error) {
    ElMessage.error(error.message || '创建失败')
  } finally {
    addingCategory.value = false
  }
}

// 编辑主分类
const editCategory = (cat) => {
  editingCategory.value = { ...cat }
  showEditCategoryDialog.value = true
}

// 删除主分类
const handleDeleteCategory = async (cat) => {
  try {
    await deleteCategory(cat.id)
    ElMessage.success('删除成功')
    fetchCategories()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}

// 同步普通标签
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

const handleTabChange = (tab) => {
  if (tab === 'categories' && categories.value.length === 0) {
    fetchCategories()
  } else if (tab === 'resolutions' && resolutions.value.length === 0) {
    fetchResolutions()
  } else if (tab === 'tags' && tags.value.length === 0) {
    fetchTags()
  }
}

onMounted(() => {
  fetchCategories()
  fetchResolutions()
})
</script>

<style scoped>
.tags-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
}

.page-header-left {
  flex: 1;
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

.tags-tabs {
  background: var(--bg-primary);
  border-radius: var(--radius-xl);
  padding: 20px;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border-color-light);
}

.tab-label {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tab-badge {
  margin-left: 4px;
}

:deep(.el-tabs__item) {
  font-weight: 500;
}

.tab-content {
  padding-top: 16px;
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

/* 主分类卡片网格 */
.category-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.category-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color-light);
  border-radius: var(--radius-lg);
  padding: 16px;
  transition: all 0.2s ease;
}

.category-card:hover {
  border-color: #8b5cf6;
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.1);
}

.category-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.category-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.category-desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 12px 0;
  line-height: 1.5;
}

.category-actions {
  display: flex;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color-light);
}

/* 分辨率卡片 */
.resolution-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.resolution-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color-light);
  border-radius: var(--radius-lg);
  padding: 16px;
}

.resolution-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%);
  border-radius: 12px;
  color: white;
}

.resolution-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.resolution-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.resolution-desc {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 统计行 */
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

.empty-state {
  grid-column: 1 / -1;
  padding: 40px;
}

.form-tip {
  margin: 4px 0 0 0;
  font-size: 12px;
  color: var(--text-secondary);
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

/* 操作按钮样式 - 白色文字更醒目 */
.category-actions :deep(.el-button.is-link) {
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  transition: all 0.2s ease;
}

.category-actions :deep(.el-button--primary.is-link) {
  color: #fff !important;
  background: rgba(255, 255, 255, 0.1);
}

.category-actions :deep(.el-button--primary.is-link:hover) {
  color: #fff !important;
  background: rgba(255, 255, 255, 0.2);
}

.category-actions :deep(.el-button--danger.is-link) {
  color: #fca5a5 !important;
  background: rgba(252, 165, 165, 0.1);
}

.category-actions :deep(.el-button--danger.is-link:hover) {
  color: #fecaca !important;
  background: rgba(252, 165, 165, 0.2);
}

/* 表格操作按钮 */
:deep(.el-button--primary.is-link) {
  color: #fff !important;
  font-weight: 500;
}

:deep(.el-button--danger.is-link) {
  color: #fca5a5 !important;
  font-weight: 500;
}

/* ===== 移动端响应式 ===== */
@media (max-width: 768px) {
  .tags-page {
    gap: 12px;
  }
  
  .tags-tabs {
    padding: 12px;
  }
  
  .page-title {
    font-size: 18px;
    gap: 8px;
  }
  
  .toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }
  
  .toolbar-right {
    margin-left: 0;
  }
  
  .toolbar-right .el-input {
    width: 100% !important;
  }
  
  .category-grid {
    grid-template-columns: 1fr;
  }
  
  .resolution-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .stats-row {
    gap: 8px;
  }
  
  .stat-item {
    padding: 10px 12px;
    flex: 1;
  }
  
  .stat-value {
    font-size: 18px;
  }
  
  /* 隐藏来源列 */
  :deep(.el-table th:nth-child(3)),
  :deep(.el-table td:nth-child(3)) {
    display: none;
  }
}

@media (max-width: 480px) {
  .resolution-grid {
    grid-template-columns: 1fr;
  }
  
  .stats-row {
    flex-direction: column;
  }
  
  :deep(.el-dialog) {
    width: 90% !important;
  }
}
</style>
