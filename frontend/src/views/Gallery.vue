<template>
  <div class="gallery-layout">
    <!-- 侧边栏 -->
    <div class="sidebar card">
      <div class="sidebar-header">
        <h3>收藏夹</h3>
        <el-button type="primary" size="small" circle @click="showCollectionDialog = true">
          <el-icon><Plus /></el-icon>
        </el-button>
      </div>
      <ul class="collection-list">
        <li 
          :class="{ active: activeCollectionId === null }"
          @click="handleCollectionFilter(null)"
        >
          <div class="collection-info">
            <el-icon><Picture /></el-icon>
            <span>全部图片</span>
          </div>
        </li>
        <!-- 根收藏夹 (parent_id === null) -->
        <template v-for="c in rootCollections" :key="c.id">
          <li 
            :class="{ active: activeCollectionId === c.id }"
            @click="handleCollectionFilter(c.id)"
          >
            <div class="collection-info">
              <el-icon v-if="hasChildren(c.id)" 
                @click.stop="toggleExpand(c.id)" 
                class="expand-icon" 
                :class="{ expanded: expandedIds.includes(c.id) }"
              ><ArrowRight /></el-icon>
              <el-icon v-else><Folder /></el-icon>
              <span class="name">{{ c.name }}</span>
            </div>
            <span class="count" v-if="c.image_count > 0">{{ c.image_count }}</span>
          </li>
          <!-- 子收藏夹 -->
          <template v-if="expandedIds.includes(c.id)">
            <li 
              v-for="child in getChildren(c.id)" 
              :key="child.id"
              :class="{ active: activeCollectionId === child.id }"
              class="child-collection"
              @click="handleCollectionFilter(child.id)"
            >
              <div class="collection-info">
                <el-icon><Folder /></el-icon>
                <span class="name">{{ child.name }}</span>
              </div>
              <span class="count" v-if="child.image_count > 0">{{ child.image_count }}</span>
            </li>
          </template>
        </template>
      </ul>
    </div>

    <!-- 主内容区 -->
    <div class="gallery-main">
      <!-- 搜索筛选栏 -->
      <div class="card filter-bar">
        <el-form :inline="true" @submit.prevent="handleSearch">
          <el-form-item label="标签">
            <el-select
              v-model="filters.tags"
              multiple
              filterable
              allow-create
              placeholder="输入标签筛选"
              style="width: 200px"
            >
              <el-option
                v-for="tag in suggestedTags"
                :key="tag"
                :label="tag"
                :value="tag"
              />
            </el-select>
          </el-form-item>
          
          <el-form-item>
            <el-popover placement="bottom" title="搜索设置" :width="300" trigger="click">
              <template #reference>
                <el-button :icon="Setting">设置</el-button>
              </template>
              <div class="search-settings">
                <div class="setting-item">
                  <span class="label">向量权重 ({{ vectorWeight }})</span>
                  <el-slider v-model="vectorWeight" :min="0" :max="1" :step="0.1" />
                </div>
                <div class="setting-item">
                  <span class="label">标签权重 ({{ tagWeight }})</span>
                  <el-slider v-model="tagWeight" :min="0" :max="1" :step="0.1" />
                </div>
              </div>
            </el-popover>
          </el-form-item>
          
          <el-form-item label="描述">
            <el-input
              v-model="filters.descriptionContains"
              placeholder="描述关键词"
              clearable
              style="width: 180px"
            />
          </el-form-item>
          
          <el-form-item>
            <el-button type="primary" @click="handleSearch">
              <el-icon><Search /></el-icon>
              搜索
            </el-button>
            <el-button @click="resetFilters">重置</el-button>
          </el-form-item>
        </el-form>
      </div>
      
      <!-- 图片列表 -->
      <div v-if="loading" class="loading-container">
        <el-icon class="is-loading" :size="48"><Loading /></el-icon>
        <p>加载中...</p>
      </div>
      
      <template v-else>
        <!-- 批量操作栏 -->
        <div v-if="images.length > 0 && selectMode" class="batch-bar">
          <div class="batch-bar-left">
            <el-checkbox 
              v-model="selectMode" 
              label="批量选择"
              @change="handleSelectModeChange"
            />
            <div class="batch-actions-group">
              <el-button 
                size="small" 
                @click="selectAll"
                :disabled="isAllSelected"
              >
                全选
              </el-button>
              <el-button 
                size="small" 
                @click="invertSelection"
                :disabled="images.length === 0"
              >
                反选
              </el-button>
            </div>
          </div>
          <div class="batch-bar-right">
            <div v-if="selectedIds.length > 0" class="selected-count-badge">
              <span class="selected-count-number">{{ selectedIds.length }}</span>
              <span class="selected-count-text">张已选</span>
            </div>
            <div v-else class="selected-count-badge empty">
              <span class="selected-count-text">未选择</span>
            </div>
            <div v-if="selectedIds.length > 0" class="batch-actions">
              <el-button type="primary" size="small" @click="openAddToCollectionDialog">
                <el-icon><FolderAdd /></el-icon>
                添加到收藏夹
              </el-button>
              <el-button type="primary" size="small" @click="handleBatchAnalyze" :loading="batchLoading">
                批量分析
              </el-button>
              <el-button size="small" @click="clearSelection">取消选择</el-button>
            </div>
          </div>
        </div>
        
        <!-- 批量选择模式提示 -->
        <div v-if="images.length > 0 && !selectMode" class="batch-mode-hint">
          <el-button 
            type="primary" 
            size="default"
            @click="selectMode = true"
            class="batch-mode-btn"
          >
            <el-icon><Select /></el-icon>
            进入批量选择模式
          </el-button>
        </div>
        
        <div v-if="images.length === 0" class="empty-container">
          <el-empty description="暂无图片">
            <router-link to="/upload">
              <el-button type="primary">上传图片</el-button>
            </router-link>
          </el-empty>
        </div>
        
        <div v-else class="images-grid">
          <div 
            v-for="image in images" 
            :key="image.id" 
            class="image-card"
            :class="{ selected: selectedIds.includes(image.id), 'no-tags': !image.description && !image.tags?.length }"
            @click="handleCardClick(image)"
          >
            <!-- 处理中标记 -->
            <div v-if="processingIds.includes(image.id)" class="processing-badge">
              <el-icon class="is-loading"><Loading /></el-icon>
              分析中
            </div>
            <!-- 待处理标记 -->
            <div v-else-if="pendingIds.includes(image.id)" class="pending-badge">
              队列中
            </div>
            <!-- 未分析标记 -->
            <div v-else-if="!image.description && !image.tags?.length" class="untagged-badge">
              待分析
            </div>
            
            <!-- 选择框 -->
            <div v-if="selectMode" class="select-checkbox" @click.stop>
              <el-checkbox 
                :model-value="selectedIds.includes(image.id)"
                @change="(val) => toggleSelect(image.id, val)"
              />
            </div>
            
            <div class="image-wrapper">
              <img :src="getImageUrl(image.image_url)" :alt="image.description" />
              <div v-if="!selectMode" class="image-overlay">
                <el-button circle size="small" type="primary" @click.stop="selectedImage = image; openAddToCollectionDialog()">
                  <el-icon><FolderAdd /></el-icon>
                </el-button>
                <el-button circle size="small" type="danger" @click.stop="confirmDelete(image)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
            <div class="image-card-content">
              <p class="description">{{ image.description || '暂无描述' }}</p>
              <div class="image-card-tags">
                <el-tag 
                  v-for="tag in image.tags?.slice(0, 4)" 
                  :key="tag" 
                  size="small"
                  type="info"
                >
                  {{ tag }}
                </el-tag>
                <el-tag v-if="image.tags?.length > 4" size="small">
                  +{{ image.tags.length - 4 }}
                </el-tag>
              </div>
            </div>
          </div>
        </div>
        
        <!-- 分页 -->
        <div v-if="total > pageSize" class="pagination-container">
          <el-pagination
            v-model:current-page="currentPage"
            :page-size="pageSize"
            :total="total"
            layout="prev, pager, next, total"
            @current-change="handlePageChange"
          />
        </div>
      </template>
    </div>

    <!-- 创建收藏夹弹窗 -->
    <el-dialog v-model="showCollectionDialog" title="创建收藏夹" width="400px">
      <el-form :model="collectionForm" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="collectionForm.name" placeholder="例如：初音未来" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="collectionForm.description" type="textarea" placeholder="可选描述" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showCollectionDialog = false">取消</el-button>
          <el-button type="primary" @click="handleCreateCollection">创建</el-button>
        </span>
      </template>
    </el-dialog>


    
    <!-- 全屏详情/编辑弹窗 -->
    <el-dialog
      v-model="fullscreenVisible"
      :title="isEditing ? '编辑图片' : '图片详情'"
      fullscreen
      class="fullscreen-dialog"
    >
      <div v-if="selectedImage" class="fullscreen-content">
        <!-- 左侧：大图展示 -->
        <div class="fullscreen-image-container">
          <img :src="getImageUrl(selectedImage.image_url)" class="fullscreen-image" />
        </div>
        
        <!-- 右侧：信息面板 -->
        <div class="fullscreen-info-panel">
          <div class="panel-header">
            <span class="image-id">#{{ selectedImage.id }}</span>
            <div class="panel-actions">
              <el-button v-if="!isEditing" type="primary" @click="startEdit" round>
                <el-icon><Edit /></el-icon>
                编辑
              </el-button>
              <el-button v-if="isEditing" @click="cancelEdit" round>
                取消
              </el-button>
              <el-button v-if="isEditing" type="primary" :loading="saving" @click="saveEdit" round>
                <el-icon><Check /></el-icon>
                保存并更新向量
              </el-button>
            </div>
          </div>
          
          <!-- 查看模式 -->
          <div v-if="!isEditing" class="info-display">
            <div class="info-section">
              <h3>描述</h3>
              <p class="description-text">{{ selectedImage.description || '暂无描述' }}</p>
            </div>
            
            <div class="info-section">
              <h3>标签</h3>
              <div class="tags-display">
                <el-tag 
                  v-for="tag in selectedImage.tags" 
                  :key="tag"
                  size="large"
                >
                  {{ tag }}
                </el-tag>
                <span v-if="!selectedImage.tags?.length" class="no-tags">暂无标签</span>
              </div>
            </div>
            
            <div class="info-section">
              <h3>图片地址</h3>
              <el-input :model-value="selectedImage.image_url" readonly>
                <template #append>
                  <el-button @click="copyUrl">复制</el-button>
                </template>
              </el-input>
            </div>

            <div class="info-section">
              <h3>操作</h3>
              <el-button @click="openAddToCollectionDialog">
                <el-icon><FolderAdd /></el-icon>
                添加到收藏夹
              </el-button>
            </div>
          </div>
          
          <!-- 编辑模式 -->
          <div v-else class="info-edit">
            <div class="info-section">
              <h3>描述</h3>
              <el-input
                v-model="editForm.description"
                type="textarea"
                :rows="6"
                placeholder="输入图片描述"
              />
            </div>
            
            <div class="info-section">
              <h3>标签</h3>
              <el-select
                v-model="editForm.tags"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="添加标签，回车确认"
                style="width: 100%"
              >
                <el-option
                  v-for="tag in editForm.tags"
                  :key="tag"
                  :label="tag"
                  :value="tag"
                />
              </el-select>
              <p class="edit-hint">输入后按回车添加标签</p>
            </div>
          </div>
          
          <!-- 危险操作 -->
          <div class="danger-zone">
            <el-popconfirm
              title="确定要删除这张图片吗？"
              confirm-button-text="删除"
              cancel-button-text="取消"
              @confirm="handleDeleteInFullscreen"
            >
              <template #reference>
                <el-button type="danger" plain>
                  <el-icon><Delete /></el-icon>
                  删除图片
                </el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
      </div>
    </el-dialog>
    <!-- 添加到收藏夹弹窗 -->
    <el-dialog
      v-model="showAddToCollectionDialog"
      title="添加到收藏夹"
      width="500px"
    >
      <el-form>
        <el-form-item label="选择收藏夹">
          <el-select v-model="targetCollectionId" placeholder="请选择收藏夹" style="width: 100%">
            <el-option
              v-for="item in collections"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showAddToCollectionDialog = false">取消</el-button>
          <el-button type="primary" @click="confirmAddToCollection">确定</el-button>
        </span>
      </template>
    </el-dialog>

    <!-- 标签管理器 -->
    <TagManager v-model="showTagManager" @tags-updated="fetchTags" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderAdd, Setting, Select } from '@element-plus/icons-vue'
import { getImages, updateImage, deleteImage, addToQueue, getQueueStatus, getCollections, createCollection, addImageToCollection, getCollectionImages, getTags, searchSimilar } from '@/api'

import TagManager from '@/components/TagManager.vue'

const loading = ref(true)
const images = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

const suggestedTags = ref([])
const showTagManager = ref(false)

// 搜索权重
const vectorWeight = ref(0.7)
const tagWeight = ref(0.3)

const filters = reactive({
  tags: [],
  descriptionContains: ''
})

// 收藏夹相关
const collections = ref([])
const showCollectionDialog = ref(false)
const collectionForm = reactive({
  name: '',
  description: '',
  parent_id: null
})
const activeCollectionId = ref(null)
const showAddToCollectionDialog = ref(false)
const targetCollectionId = ref(null)
const expandedIds = ref([])

// 层级收藏夹计算属性
const rootCollections = computed(() => 
  collections.value.filter(c => !c.parent_id)
)

const hasChildren = (parentId) => 
  collections.value.some(c => c.parent_id === parentId)

const getChildren = (parentId) => 
  collections.value.filter(c => c.parent_id === parentId)

const toggleExpand = (id) => {
  if (expandedIds.value.includes(id)) {
    expandedIds.value = expandedIds.value.filter(i => i !== id)
  } else {
    expandedIds.value.push(id)
  }
}

const fullscreenVisible = ref(false)
const selectedImage = ref(null)
const isEditing = ref(false)
const editForm = ref(null)
const saving = ref(false)

// 批量选择
const selectMode = ref(false)
const selectedIds = ref([])
const batchLoading = ref(false)

// 全选状态计算属性
const isAllSelected = computed(() => {
  return images.value.length > 0 && selectedIds.value.length === images.value.length
})

// 部分选中状态
const isIndeterminate = computed(() => {
  return selectedIds.value.length > 0 && selectedIds.value.length < images.value.length
})

// 队列状态
const queueStatus = ref(null)
let queueTimer = null

const processingIds = computed(() => {
  if (!queueStatus.value?.processing) return []
  return queueStatus.value.processing.map(t => t.image_id)
})

const pendingIds = computed(() => {
  if (!queueStatus.value?.pending) return []
  return queueStatus.value.pending.map(t => t.image_id)
})

const getImageUrl = (url) => {
  if (url.startsWith('http')) return url
  return url
}

// 收藏夹方法
const fetchCollections = async () => {
  try {
    const data = await getCollections()
    collections.value = data
  } catch (error) {
    console.error('获取收藏夹失败:', error)
  }
}

const fetchTags = async () => {
  try {
    const tags = await getTags({ limit: 100, sort_by: 'usage_count' })
    suggestedTags.value = tags.map(t => t.name)
  } catch (error) {
    console.error('获取标签失败:', error)
  }
}

const handleCreateCollection = async () => {
  if (!collectionForm.name) {
    ElMessage.warning('请输入收藏夹名称')
    return
  }
  
  try {
    await createCollection(collectionForm)
    ElMessage.success('创建成功')
    showCollectionDialog.value = false
    collectionForm.name = ''
    collectionForm.description = ''
    fetchCollections()
  } catch (error) {
    ElMessage.error('创建失败')
  }
}

const handleCollectionFilter = (id) => {
  activeCollectionId.value = id
  currentPage.value = 1
  fetchImages()
}

const openAddToCollectionDialog = () => {
  if (selectedIds.value.length === 0 && !selectedImage.value) {
    ElMessage.warning('请先选择图片')
    return
  }
  showAddToCollectionDialog.value = true
}

const confirmAddToCollection = async () => {
  if (!targetCollectionId.value) {
    ElMessage.warning('请选择收藏夹')
    return
  }
  
  try {
    const ids = selectedIds.value.length > 0 ? selectedIds.value : [selectedImage.value.id]
    
    let successCount = 0
    for (const id of ids) {
      const res = await addImageToCollection(targetCollectionId.value, id)
      if (res.task_id) {
        // 异步任务
        console.log(`任务已提交: ${res.task_id}`)
      }
      successCount++
    }
    
    ElMessage.success(`已提交 ${successCount} 个添加到收藏夹的任务，正在后台处理`)
    showAddToCollectionDialog.value = false
    targetCollectionId.value = null
    clearSelection()
    
    // 如果在详情页，刷新详情
    if (selectedImage.value) {
      // 简单刷新列表
      fetchImages()
    }
  } catch (error) {
    ElMessage.error('添加失败: ' + error.message)
  }
}

const fetchImages = async () => {
  loading.value = true
  try {
    let result
    if (activeCollectionId.value) {
      result = await getCollectionImages(activeCollectionId.value, {
        limit: pageSize.value,
        offset: (currentPage.value - 1) * pageSize.value
      })
      images.value = result.images
      total.value = result.total
    } else if (filters.descriptionContains) {
      // 语义搜索
      const res = await searchSimilar(
        filters.descriptionContains,
        filters.tags.length > 0 ? filters.tags : [],
        pageSize.value,
        0.3, // 默认阈值
        vectorWeight.value,
        tagWeight.value
      )
      images.value = res.images
      total.value = res.total
    } else {
      result = await getImages({
        tags: filters.tags.length > 0 ? filters.tags : null,
        descriptionContains: null, // Ensure this is null for non-semantic search
        limit: pageSize.value,
        offset: (currentPage.value - 1) * pageSize.value,
        sortDesc: true
      })
      images.value = result.images
      total.value = result.total
    }
  } catch (e) {
    ElMessage.error('获取图片失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  currentPage.value = 1
  fetchImages()
}

const resetFilters = () => {
  filters.tags = []
  filters.descriptionContains = ''
  currentPage.value = 1
  fetchImages()
}

const handlePageChange = (page) => {
  currentPage.value = page
  fetchImages()
}

// 批量选择相关方法
const handleSelectModeChange = (val) => {
  if (!val) {
    selectedIds.value = []
  }
}

const toggleSelect = (id, val) => {
  if (val) {
    // 避免重复添加
    if (!selectedIds.value.includes(id)) {
      selectedIds.value.push(id)
    }
  } else {
    selectedIds.value = selectedIds.value.filter(i => i !== id)
  }
}

const clearSelection = () => {
  selectedIds.value = []
}

// 全选当前页
const selectAll = () => {
  selectedIds.value = images.value.map(img => img.id)
}

// 反选当前页
const invertSelection = () => {
  const currentPageIds = images.value.map(img => img.id)
  const newSelected = currentPageIds.filter(id => !selectedIds.value.includes(id))
  const keepSelected = selectedIds.value.filter(id => !currentPageIds.includes(id))
  selectedIds.value = [...keepSelected, ...newSelected]
}

const handleCardClick = (image) => {
  if (selectMode.value) {
    toggleSelect(image.id, !selectedIds.value.includes(image.id))
  } else {
    openFullscreen(image)
  }
}

const handleBatchAnalyze = async () => {
  if (selectedIds.value.length === 0) return
  
  batchLoading.value = true
  try {
    const result = await addToQueue(selectedIds.value)
    ElMessage.success(result.message)
    selectMode.value = false
    selectedIds.value = []
  } catch (e) {
    ElMessage.error('添加到队列失败: ' + e.message)
  } finally {
    batchLoading.value = false
  }
}

const openFullscreen = (image) => {
  selectedImage.value = { ...image }
  isEditing.value = false
  editForm.value = null
  fullscreenVisible.value = true
}

const startEdit = () => {
  editForm.value = {
    id: selectedImage.value.id,
    description: selectedImage.value.description || '',
    tags: [...(selectedImage.value.tags || [])]
  }
  isEditing.value = true
}

const cancelEdit = () => {
  isEditing.value = false
  editForm.value = null
}

const saveEdit = async () => {
  saving.value = true
  try {
    // 保存时后端会自动重建向量
    await updateImage(editForm.value.id, {
      description: editForm.value.description,
      tags: editForm.value.tags
    })
    ElMessage.success('保存成功，向量已更新')
    
    // 更新当前显示的数据
    selectedImage.value.description = editForm.value.description
    selectedImage.value.tags = [...editForm.value.tags]
    
    isEditing.value = false
    editForm.value = null
    fetchImages()
  } catch (e) {
    ElMessage.error('保存失败: ' + e.message)
  } finally {
    saving.value = false
  }
}

const copyUrl = () => {
  navigator.clipboard.writeText(selectedImage.value.image_url)
  ElMessage.success('已复制到剪贴板')
}

const confirmDelete = (image) => {
  ElMessageBox.confirm(
    `确定要删除这张图片吗？此操作不可撤销。`,
    '确认删除',
    {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    }
  ).then(async () => {
    try {
      await deleteImage(image.id)
      ElMessage.success('删除成功')
      fetchImages()
    } catch (e) {
      ElMessage.error('删除失败: ' + e.message)
    }
  }).catch(() => {})
}

const handleDeleteInFullscreen = async () => {
  try {
    await deleteImage(selectedImage.value.id)
    ElMessage.success('删除成功')
    fullscreenVisible.value = false
    fetchImages()
  } catch (e) {
    ElMessage.error('删除失败: ' + e.message)
  }
}

// 获取队列状态
const fetchQueueStatus = async () => {
  try {
    queueStatus.value = await getQueueStatus()
    
    // 如果有任务完成，刷新图片列表
    if (queueStatus.value?.running) {
      // 继续轮询
    } else if (queueStatus.value?.completed_count > 0) {
      // 队列停止了，刷新图片列表
      fetchImages()
    }
  } catch (e) {
    console.error('获取队列状态失败:', e)
  }
}

// 启动队列状态轮询
const startQueuePolling = () => {
  if (queueTimer) return
  
  queueTimer = setInterval(async () => {
    await fetchQueueStatus()
  }, 2000)
}

onMounted(() => {
  fetchImages()
  fetchCollections()
  fetchTags()
  fetchQueueStatus()
  startQueuePolling()
})

onUnmounted(() => {
  if (queueTimer) {
    clearInterval(queueTimer)
    queueTimer = null
  }
})
</script>

<style scoped>
.gallery-layout {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}

.sidebar {
  width: 260px;
  flex-shrink: 0;
  position: sticky;
  top: 24px;
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  padding: 0;
}

.gallery-main {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  gap: 24px;
  min-width: 0; /* 防止 grid 溢出 */
}

.sidebar-header {
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-color);
  background: linear-gradient(135deg, var(--primary-color) 0%, var(--primary-light) 100%);
  color: white;
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}

.sidebar-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: white;
}

.collection-list {
  list-style: none;
  padding: 8px;
  margin: 0;
}

.collection-list li {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: all 0.2s;
  color: var(--text-secondary);
  font-size: 14px;
}

.collection-list li:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.collection-list li.active {
  background: var(--primary-color);
  color: white;
  font-weight: 500;
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}

.collection-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.collection-info .el-icon {
  font-size: 16px;
}

.expand-icon {
  cursor: pointer;
  transition: transform 0.2s;
}

.expand-icon.expanded {
  transform: rotate(90deg);
}

.child-collection {
  padding-left: 32px !important;
  background: var(--bg-secondary);
}

.collection-list .count {
  font-size: 12px;
  background: var(--bg-secondary);
  padding: 2px 6px;
  border-radius: 10px;
  color: var(--text-muted);
}

.collection-list li.active .count {
  background: rgba(255, 255, 255, 0.2);
  color: white;
}

.collection-select-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
}

.collection-item {
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: all 0.2s;
}

.collection-item:hover {
  border-color: var(--primary-color);
  background: var(--bg-hover);
}

.collection-item.active {
  border-color: var(--primary-color);
  background: var(--primary-light);
  color: var(--primary-color);
}

.collection-item .info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.collection-item .name {
  font-weight: 500;
}

.collection-item .count {
  font-size: 12px;
  color: var(--text-muted);
}

.collection-item.active .count {
  color: var(--primary-color);
  opacity: 0.8;
}

.filter-bar {
  background: var(--bg-card);
}

.loading-container,
.empty-container {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-height: 400px;
  gap: 16px;
  color: var(--text-secondary);
}

.images-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

.image-card {
  cursor: pointer;
  transition: all var(--transition-normal);
  position: relative;
  transform-origin: center;
}

.image-wrapper {
  position: relative;
  overflow: hidden;
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}

.image-wrapper img {
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}

.image-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  opacity: 0;
  transition: opacity 0.2s;
}

.image-wrapper:hover .image-overlay {
  opacity: 1;
}

.image-card-content {
  padding: 12px;
  background: var(--bg-card);
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
  border: 1px solid var(--border-color);
  border-top: none;
}

.image-card-content .description {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 8px 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.4;
}

.image-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* 批量选择 */
.batch-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 20px;
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border-radius: var(--radius-lg);
  margin-bottom: 20px;
  border: 1px solid var(--border-color-light);
  box-shadow: var(--shadow-sm);
  transition: all var(--transition-normal);
}

.batch-bar:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-color);
}

.batch-bar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.batch-actions-group {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 16px;
  border-left: 1px solid var(--border-color-light);
}

.batch-bar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.selected-count-badge {
  display: flex;
  align-items: baseline;
  gap: 4px;
  padding: 6px 14px;
  background: rgba(0, 113, 227, 0.1);
  border-radius: var(--radius-md);
  border: 1px solid rgba(0, 113, 227, 0.2);
  transition: all var(--transition-fast);
}

.selected-count-badge.empty {
  background: var(--bg-secondary);
  border-color: var(--border-color-light);
}

.selected-count-number {
  font-size: 18px;
  font-weight: 700;
  color: var(--primary-color);
  line-height: 1;
}

.selected-count-text {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

.selected-count-badge.empty .selected-count-text {
  color: var(--text-muted);
}

.batch-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.batch-mode-hint {
  margin-bottom: 16px;
  padding: 8px 0;
}

.batch-mode-btn {
  font-weight: 500;
  box-shadow: var(--shadow-sm);
  transition: all var(--transition-fast);
}

.batch-mode-btn:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.image-card {
  transition: all var(--transition-normal);
}

.image-card.selected {
  transform: scale(1.02);
  box-shadow: 0 0 0 3px var(--primary-color), 
              0 8px 24px rgba(0, 113, 227, 0.25),
              var(--shadow-lg);
  border-radius: var(--radius-lg);
  z-index: 5;
  position: relative;
  animation: selectPulse 0.3s ease-out;
}

@keyframes selectPulse {
  0% {
    transform: scale(1);
    box-shadow: 0 0 0 0 rgba(0, 113, 227, 0.4);
  }
  50% {
    transform: scale(1.03);
    box-shadow: 0 0 0 4px rgba(0, 113, 227, 0.2);
  }
  100% {
    transform: scale(1.02);
    box-shadow: 0 0 0 3px var(--primary-color), 
                0 8px 24px rgba(0, 113, 227, 0.25),
                var(--shadow-lg);
  }
}

.image-card.selected .image-wrapper {
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}

.image-card.selected .image-wrapper::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 113, 227, 0.1);
  z-index: 1;
  pointer-events: none;
}

.image-card.no-tags {
  opacity: 0.8;
}

.select-checkbox {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 15;
  background: transparent;
  border-radius: var(--radius-md);
  padding: 4px;
  transition: all var(--transition-fast);
}

.select-checkbox:hover {
  transform: scale(1.1);
}

.select-checkbox :deep(.el-checkbox) {
  --el-checkbox-bg-color: transparent;
}

.select-checkbox :deep(.el-checkbox__input) {
  background: transparent;
}

.select-checkbox :deep(.el-checkbox__inner) {
  background-color: transparent;
  border: 2px solid rgba(255, 255, 255, 0.9);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.select-checkbox :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: var(--primary-color);
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.3),
              0 2px 8px rgba(0, 113, 227, 0.4);
}

.select-checkbox :deep(.el-checkbox__input.is-checked .el-checkbox__inner::after) {
  border-color: white;
}

.image-card.selected .select-checkbox :deep(.el-checkbox__inner) {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.5),
              0 0 0 4px rgba(0, 113, 227, 0.3),
              0 4px 12px rgba(0, 113, 227, 0.4);
}

.untagged-badge {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
  background: #f59e0b;
  color: white;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 10px;
  font-weight: 500;
  box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
}

.processing-badge {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
  background: var(--primary-color);
  color: white;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
  box-shadow: 0 2px 8px rgba(0, 113, 227, 0.3);
}

.pending-badge {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
  background: #6b7280;
  color: white;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 10px;
  font-weight: 500;
  box-shadow: 0 2px 8px rgba(107, 114, 128, 0.3);
}

.pagination-container {
  display: flex;
  justify-content: center;
  padding: 20px 0;
}

/* 全屏弹窗样式 */
.fullscreen-content {
  display: flex;
  height: calc(100vh - 120px);
  gap: 32px;
  padding: 20px;
}

.fullscreen-image-container {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #000;
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.fullscreen-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.fullscreen-info-panel {
  width: 400px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 24px;
  overflow-y: auto;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.image-id {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-secondary);
}

.panel-actions {
  display: flex;
  gap: 8px;
}

.info-display,
.info-edit {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.info-section h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.description-text {
  font-size: 15px;
  line-height: 1.6;
  color: var(--text-primary);
}

.tags-display {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.no-tags {
  color: var(--text-muted);
  font-size: 14px;
}

.edit-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.danger-zone {
  margin-top: auto;
  padding-top: 20px;
  border-top: 1px solid var(--border-color);
}

@media (max-width: 1400px) {
  .images-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 1000px) {
  .images-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .fullscreen-content {
    flex-direction: column;
  }
  
  .fullscreen-image-container {
    height: 50vh;
  }
  
  .fullscreen-info-panel {
    width: 100%;
  }
}

@media (max-width: 600px) {
  .images-grid {
    grid-template-columns: 1fr;
  }
  
  .batch-bar {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  
  .batch-bar-left {
    flex-wrap: wrap;
  }
  
  .batch-actions-group {
    padding-left: 0;
    border-left: none;
    border-top: 1px solid var(--border-color-light);
    padding-top: 12px;
    width: 100%;
    justify-content: flex-start;
  }
  
  .batch-bar-right {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  
  .batch-actions {
    flex-wrap: wrap;
    gap: 8px;
  }
  
  .selected-count-badge {
    width: 100%;
    justify-content: center;
  }
}
</style>

<style>
/* 全屏弹窗全局样式 */
.fullscreen-dialog .el-dialog__body {
  padding: 0;
  height: calc(100vh - 60px);
}

.fullscreen-dialog .el-dialog__header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}
</style>
