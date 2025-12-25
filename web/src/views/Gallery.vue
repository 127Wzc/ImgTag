<template>
  <div class="gallery-page">
    <!-- 主内容区 -->
      <!-- 搜索筛选栏 -->
      <div class="card filter-bar">
        <el-form :inline="true" @submit.prevent="handleSearch">
        <!-- 主分类筛选 -->
          <el-form-item label="分类">
            <el-select
              v-model="filters.category"
              placeholder="全部分类"
              clearable
              style="width: 120px"
            >
              <el-option
                v-for="cat in categoryOptions"
                :key="cat.id"
                :label="cat.name"
                :value="cat.id"
              />
            </el-select>
          </el-form-item>
          
          <!-- 分辨率筛选 -->
          <el-form-item label="分辨率">
            <el-select
              v-model="filters.resolution"
              placeholder="全部"
              clearable
              style="width: 100px"
            >
              <el-option
                v-for="res in resolutionOptions"
                :key="res.id"
                :label="res.name"
                :value="res.id"
              />
            </el-select>
          </el-form-item>
          
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
                :key="tag.name"
                :label="`${tag.name} (${tag.usage_count || 0})`"
                :value="tag.name"
              />
            </el-select>
          </el-form-item>
          
          
          <el-form-item label="关键字">
            <el-input
              v-model="filters.keyword"
              placeholder="搜索标签或描述"
              clearable
              style="width: 180px"
            />
          </el-form-item>
          
          <el-form-item v-if="authStore.isAdmin">
            <el-checkbox v-model="filters.pendingOnly">待分析</el-checkbox>
          </el-form-item>
          
          <el-form-item v-if="authStore.isAdmin">
            <el-checkbox v-model="filters.duplicatesOnly">重复图片</el-checkbox>
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
              <el-button v-if="authStore.isLoggedIn" type="primary" size="small" @click="openAddToCollectionDialog">
                <el-icon><FolderAdd /></el-icon>
                添加到收藏夹
              </el-button>
              <el-button type="success" size="small" @click="showBatchTagDialog = true">
                <el-icon><CollectionTag /></el-icon>
                批量打标签
              </el-button>
              <el-button 
                v-if="authStore.isAdmin" 
                type="primary" 
                size="small" 
                @click="handleBatchAnalyze" 
                :loading="batchLoading"
              >
                批量分析
              </el-button>
              <el-button 
                v-if="authStore.isAdmin" 
                type="warning" 
                size="small" 
                @click="showBatchCategoryDialog = true"
              >
                批量分类
              </el-button>
              <el-button 
                v-if="authStore.isAdmin" 
                type="danger" 
                size="small" 
                @click="handleBatchDelete"
                :loading="batchDeleting"
              >
                <el-icon><Delete /></el-icon>
                批量删除
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
              
              <!-- 右下角收藏图标 -->
              <div 
                v-if="authStore.isLoggedIn"
                class="favorite-icon" 
                :class="{ collected: isImageCollected(image.id) }"
                @click.stop="openCollectionDialogForImage(image)"
                :title="isImageCollected(image.id) ? '已收藏' : '添加到收藏夹'"
              >
                <el-icon v-if="isImageCollected(image.id)"><Star /></el-icon>
                <el-icon v-else><StarFilled /></el-icon>
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
        <div v-if="total > 0" class="pagination-container">
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[20, 40, 60, 80, 100]"
            layout="total, sizes, prev, pager, next"
            @current-change="handlePageChange"
            @size-change="handleSizeChange"
          />
        </div>
      </template>

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
      :show-close="true"
      :close-on-click-modal="true"
      :close-on-press-escape="true"
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
              <el-button circle @click="fullscreenVisible = false">
                <el-icon><Close /></el-icon>
              </el-button>
            </div>
          </div>
          
          <!-- 查看模式 -->
          <div v-if="!isEditing" class="info-display">
            <div class="info-section">
              <h3>描述</h3>
              <p class="description-text">{{ selectedImage.description || '暂无描述' }}</p>
            </div>

            <div class="info-section" v-if="selectedImage.width || selectedImage.file_size">
              <h3>图片信息</h3>
              <div class="image-meta">
                <span v-if="selectedImage.width && selectedImage.height" class="meta-item">
                  <el-icon><Picture /></el-icon>
                  {{ selectedImage.width }} × {{ selectedImage.height }} px
                </span>
                <span v-if="selectedImage.file_size" class="meta-item">
                  <el-icon><Document /></el-icon>
                  {{ selectedImage.file_size.toFixed(2) }} MB
                </span>
              </div>
            </div>
            
            <div class="info-section">
              <h3 class="section-title ai-title">
                <el-icon><Monitor /></el-icon>
                AI 标签
              </h3>
              <div class="tags-display">
                <el-tag 
                  v-for="tag in aiTags" 
                  :key="'ai-' + tag.name"
                  size="large"
                  type="info"
                  class="ai-tag"
                >
                  {{ tag.name }}
                </el-tag>
                <span v-if="!aiTags.length && !userTags.length" class="no-tags">暂无标签</span>
              </div>
            </div>
            
            <div class="info-section" v-if="userTags.length > 0">
              <h3 class="section-title user-title">
                <el-icon><User /></el-icon>
                用户自定义标签
              </h3>
              <div class="tags-display">
                <el-tag 
                  v-for="tag in userTags" 
                  :key="'user-' + tag.name"
                  size="large"
                >
                  {{ tag.name }}
                </el-tag>
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

            <div v-if="selectedImage.original_url && selectedImage.original_url !== selectedImage.image_url" class="info-section">
              <h3>原始地址</h3>
              <el-input :model-value="selectedImage.original_url" readonly>
                <template #append>
                  <el-button @click="copyOriginalUrl">复制</el-button>
                </template>
              </el-input>
            </div>

            <div v-if="authStore.isLoggedIn" class="info-section">
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
              <h3 class="section-title ai-title">
                <el-icon><Monitor /></el-icon>
                AI 标签
                <span class="title-hint">（可删除）</span>
              </h3>
              <div class="tags-display">
                <el-tag 
                  v-for="tag in editForm.aiTags" 
                  :key="'edit-ai-' + tag"
                  size="large"
                  type="info"
                  closable
                  @close="removeAiTag(tag)"
                >
                  {{ tag }}
                </el-tag>
                <span v-if="!editForm.aiTags?.length" class="no-tags">暂无 AI 标签</span>
              </div>
            </div>
            
            <div class="info-section">
              <h3 class="section-title user-title">
                <el-icon><User /></el-icon>
                用户自定义标签
              </h3>
              <div class="tags-display">
                <el-tag 
                  v-for="tag in editForm.userTags" 
                  :key="'edit-user-' + tag"
                  size="large"
                  closable
                  @close="removeUserTag(tag)"
                >
                  {{ tag }}
                </el-tag>
              </div>
              <div class="add-tag-row">
                <el-input
                  v-model="newUserTag"
                  placeholder="输入新标签，回车添加"
                  @keyup.enter="addUserTag"
                  style="flex: 1;"
                />
                <el-button type="primary" @click="addUserTag" :disabled="!newUserTag.trim()">添加</el-button>
              </div>
            </div>

            <div class="info-section">
              <h3>原始地址</h3>
              <el-input
                v-model="editForm.original_url"
                placeholder="图片原始来源地址（可选）"
                clearable
              />
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
        
        <!-- 新建收藏夹展开项 -->
        <el-divider>
          <el-button text type="primary" @click="showInlineNewCollection = !showInlineNewCollection">
            <el-icon><Plus /></el-icon>
            {{ showInlineNewCollection ? '收起' : '新建收藏夹' }}
          </el-button>
        </el-divider>
        
        <template v-if="showInlineNewCollection">
          <el-form-item label="收藏夹名称">
            <el-input v-model="newCollectionName" placeholder="输入新收藏夹名称" />
          </el-form-item>
          <el-form-item>
            <el-button type="success" @click="createAndSelectCollection" :loading="creatingCollection">
              创建并选择
            </el-button>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showAddToCollectionDialog = false">取消</el-button>
          <el-button type="primary" @click="confirmAddToCollection">确定</el-button>
        </span>
      </template>
    </el-dialog>

    <!-- 批量打标签弹窗 -->
    <el-dialog v-model="showBatchTagDialog" title="批量打标签" width="500px">
      <el-form label-width="80px">
        <el-form-item label="选择标签">
          <el-select
            v-model="batchTags"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入或选择标签"
            style="width: 100%"
          >
            <el-option
              v-for="tag in suggestedTags"
              :key="tag.name"
              :label="`${tag.name} (${tag.usage_count || 0})`"
              :value="tag.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="操作模式">
          <el-radio-group v-model="batchTagMode">
            <el-radio value="add">追加标签</el-radio>
            <el-radio value="replace">替换标签</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBatchTagDialog = false">取消</el-button>
        <el-button type="primary" @click="handleBatchTag" :loading="batchTagLoading">
          应用到 {{ selectedIds.length }} 张图片
        </el-button>
      </template>
    </el-dialog>

    <!-- 批量设置主分类对话框 -->
    <el-dialog
      v-model="showBatchCategoryDialog"
      title="批量设置主分类"
      width="400px"
    >
      <el-form label-width="80px">
        <el-form-item label="目标分类">
          <el-select v-model="batchCategoryId" placeholder="选择主分类" style="width: 100%;">
            <el-option
              v-for="cat in categoryOptions"
              :key="cat.id"
              :label="cat.name"
              :value="cat.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <p style="color: var(--text-secondary); font-size: 13px; margin: 0;">
            将 {{ selectedIds.length }} 张图片的主分类更改为选定的分类
          </p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBatchCategoryDialog = false">取消</el-button>
        <el-button 
          type="primary" 
          @click="handleBatchSetCategory" 
          :loading="batchCategoryLoading"
          :disabled="!batchCategoryId"
        >
          应用
        </el-button>
      </template>
    </el-dialog>

    <!-- 标签管理器 -->
    <TagManager v-model="showTagManager" @tags-updated="fetchTags" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderAdd, Setting, Select, Close, CollectionTag, User, Delete, Monitor, Star, StarFilled, Plus, Picture, Document } from '@element-plus/icons-vue'
import { getImages, getImage, updateImage, deleteImage, batchDeleteImages, batchUpdateTags, addToQueue, getQueueStatus, getCollections, createCollection, addImageToCollection, getCollectionImages, getTags, searchSimilar, getAllConfigs, getCategories, getResolutions, batchSetCategory } from '@/api'
import { useAuthStore } from '@/stores/auth'

import TagManager from '@/components/TagManager.vue'

const authStore = useAuthStore()

const loading = ref(true)
const images = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

const suggestedTags = ref([])
const showTagManager = ref(false)

// 批量打标签
const showBatchTagDialog = ref(false)
const batchTags = ref([])
const batchTagMode = ref('add')
const batchTagLoading = ref(false)

// 批量设置主分类
const showBatchCategoryDialog = ref(false)
const batchCategoryId = ref(null)
const batchCategoryLoading = ref(false)

// 搜索权重
const vectorWeight = ref(0.7)
const tagWeight = ref(0.3)

const filters = reactive({
  tags: [],
  keyword: '',
  pendingOnly: false,
  duplicatesOnly: false,
  category: '',
  resolution: ''
})

// 分类/分辨率选项
const categoryOptions = ref([])
const resolutionOptions = ref([])

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

// 新建收藏夹（内联）
const showInlineNewCollection = ref(false)
const newCollectionName = ref('')
const creatingCollection = ref(false)

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
const detailLoading = ref(false) // 详情加载状态，避免标签跳动

// 用户标签和 AI 标签计算属性
const userTags = computed(() => {
  const tagsWithSource = selectedImage.value?.tags_with_source || []
  return tagsWithSource.filter(t => t.source === 'user')
})

const aiTags = computed(() => {
  // 在加载详情时不显示标签，避免跳动
  if (detailLoading.value) return []
  
  const tagsWithSource = selectedImage.value?.tags_with_source || []
  
  // 只使用 tags_with_source 中的 AI 标签
  return tagsWithSource.filter(t => t.source !== 'user')
})

// 批量选择
const selectMode = ref(false)
const selectedIds = ref([])
const batchLoading = ref(false)
const batchDeleting = ref(false)

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

// 获取完整图片 URL（包含 base_url）
const getFullImageUrl = async (url) => {
  if (url.startsWith('http')) return url
  try {
    const config = await getAllConfigs()
    const baseUrl = (config.base_url || '').replace(/\/$/, '')
    return baseUrl ? `${baseUrl}${url}` : url
  } catch (e) {
    return url
  }
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
    suggestedTags.value = tags // 保存完整对象以显示数量
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

// 为单张图片打开收藏弹窗
const openCollectionDialogForImage = (image) => {
  selectedImage.value = image
  selectedIds.value = [] // 清空批量选择，用于单图收藏
  showAddToCollectionDialog.value = true
}

// 检测图片是否已收藏（暂时未实现真实检测，需后端 API 支持）
const isImageCollected = (imageId) => {
  // TODO: 实现真实的收藏状态检测
  return false
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
    showInlineNewCollection.value = false
    newCollectionName.value = ''
    clearSelection()
    
    // 不再刷新列表，等待自动刷新即可
  } catch (error) {
    ElMessage.error('添加失败: ' + error.message)
  }
}

// 内联创建收藏夹并选择
const createAndSelectCollection = async () => {
  if (!newCollectionName.value.trim()) {
    ElMessage.warning('请输入收藏夹名称')
    return
  }
  
  creatingCollection.value = true
  try {
    const result = await createCollection({
      name: newCollectionName.value.trim(),
      is_public: true
    })
    
    // 刷新收藏夹列表
    await fetchCollections()
    
    // 选择新创建的收藏夹
    targetCollectionId.value = result.id
    
    // 重置表单
    showInlineNewCollection.value = false
    newCollectionName.value = ''
    
    ElMessage.success('收藏夹创建成功')
  } catch (error) {
    ElMessage.error('创建失败: ' + error.message)
  } finally {
    creatingCollection.value = false
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
    } else {
      result = await getImages({
        tags: filters.tags.length > 0 ? filters.tags : null,
        keyword: filters.keyword || null,
        category_id: filters.category || null,
        resolution_id: filters.resolution || null,
        pendingOnly: filters.pendingOnly,
        duplicatesOnly: filters.duplicatesOnly,
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
  filters.keyword = ''
  filters.pendingOnly = false
  filters.duplicatesOnly = false
  filters.category = ''
  filters.resolution = ''
  currentPage.value = 1
  fetchImages()
}

const handlePageChange = (page) => {
  currentPage.value = page
  fetchImages()
}

const handleSizeChange = (size) => {
  pageSize.value = size
  currentPage.value = 1
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

const openFullscreen = async (image) => {
  selectedImage.value = { ...image, tags_with_source: [] } // 初始化为空
  isEditing.value = false
  editForm.value = null
  fullscreenVisible.value = true
  detailLoading.value = true
  
  // 获取详细信息（包含 tags_with_source）
  try {
    const detail = await getImage(image.id)
    selectedImage.value = { ...selectedImage.value, ...detail }
  } catch (e) {
    console.error('获取图片详情失败:', e)
  } finally {
    detailLoading.value = false
  }
}

const startEdit = () => {
  // 检查登录状态
  if (!authStore.isLoggedIn) {
    ElMessage.warning('请先登录后再操作')
    return
  }
  
  // 分离 AI 标签和用户标签
  const tagsWithSource = selectedImage.value?.tags_with_source || []
  const aiTagNames = tagsWithSource.filter(t => t.source !== 'user').map(t => t.name)
  const userTagNames = tagsWithSource.filter(t => t.source === 'user').map(t => t.name)
  
  editForm.value = {
    id: selectedImage.value.id,
    description: selectedImage.value.description || '',
    aiTags: [...aiTagNames],
    userTags: [...userTagNames],
    original_url: selectedImage.value.original_url || ''
  }
  newUserTag.value = ''
  isEditing.value = true
}

// 新用户标签输入
const newUserTag = ref('')

// 删除 AI 标签
const removeAiTag = (tag) => {
  editForm.value.aiTags = editForm.value.aiTags.filter(t => t !== tag)
}

// 删除用户标签
const removeUserTag = (tag) => {
  editForm.value.userTags = editForm.value.userTags.filter(t => t !== tag)
}

// 添加用户标签（带重复检测）
const addUserTag = () => {
  const tag = newUserTag.value.trim()
  if (!tag) return
  
  // 检测是否与 AI 标签重复
  if (editForm.value.aiTags.includes(tag)) {
    ElMessage.warning(`标签 "${tag}" 已存在于 AI 标签中`)
    return
  }
  
  // 检测是否与现有用户标签重复
  if (editForm.value.userTags.includes(tag)) {
    ElMessage.warning(`标签 "${tag}" 已存在`)
    return
  }
  
  editForm.value.userTags.push(tag)
  newUserTag.value = ''
}

const cancelEdit = () => {
  isEditing.value = false
  editForm.value = null
}

const saveEdit = async () => {
  saving.value = true
  try {
    // 合并 AI 标签和用户标签
    const allTags = [...editForm.value.aiTags, ...editForm.value.userTags]
    
    // 保存时后端会自动重建向量
    await updateImage(editForm.value.id, {
      description: editForm.value.description,
      tags: allTags,
      original_url: editForm.value.original_url || null
    })
    ElMessage.success('保存成功，向量已更新')
    
    // 更新当前显示的数据
    selectedImage.value.description = editForm.value.description
    selectedImage.value.tags = allTags
    selectedImage.value.original_url = editForm.value.original_url
    
    // 更新 tags_with_source 以便正确显示分类
    selectedImage.value.tags_with_source = [
      ...editForm.value.aiTags.map(name => ({ name, source: 'ai' })),
      ...editForm.value.userTags.map(name => ({ name, source: 'user' }))
    ]
    
    // 本地更新 images 数组中对应的项，避免刷新整个列表
    const idx = images.value.findIndex(img => img.id === selectedImage.value.id)
    if (idx !== -1) {
      images.value[idx] = { ...images.value[idx], tags: allTags }
    }
    
    isEditing.value = false
    editForm.value = null
  } catch (e) {
    ElMessage.error('保存失败: ' + e.message)
  } finally {
    saving.value = false
  }
}

const handleBatchTag = async () => {
  if (batchTags.value.length === 0) {
    ElMessage.warning('请选择或输入标签')
    return
  }
  if (selectedIds.value.length === 0) {
    ElMessage.warning('请先选择图片')
    return
  }
  
  const count = selectedIds.value.length
  batchTagLoading.value = true
  try {
    const result = await batchUpdateTags(selectedIds.value, batchTags.value, batchTagMode.value)
    ElMessage.success(`已为 ${count} 张图片${batchTagMode.value === 'add' ? '添加' : '替换'}标签`)
    showBatchTagDialog.value = false
    batchTags.value = []
    clearSelection()
    // 不刷新列表，等待自动刷新
  } catch (e) {
    ElMessage.error('批量打标签失败: ' + e.message)
  } finally {
    batchTagLoading.value = false
  }
}

const handleBatchSetCategory = async () => {
  if (!batchCategoryId.value) {
    ElMessage.warning('请选择目标分类')
    return
  }
  if (selectedIds.value.length === 0) {
    ElMessage.warning('请先选择图片')
    return
  }
  
  const count = selectedIds.value.length
  batchCategoryLoading.value = true
  try {
    const result = await batchSetCategory(selectedIds.value, batchCategoryId.value)
    ElMessage.success(result.message || `已为 ${count} 张图片设置主分类`)
    showBatchCategoryDialog.value = false
    batchCategoryId.value = null
    clearSelection()
    fetchImages() // 刷新列表以显示新分类
  } catch (e) {
    ElMessage.error('批量设置分类失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    batchCategoryLoading.value = false
  }
}

const handleBatchDelete = async () => {
  if (selectedIds.value.length === 0) {
    ElMessage.warning('请先选择图片')
    return
  }
  
  try {
    await ElMessageBox.confirm(
      `确定要删除 ${selectedIds.value.length} 张图片吗？此操作不可撤销！`,
      '批量删除确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return // 用户取消
  }
  
  batchDeleting.value = true
  const idsToDelete = new Set(selectedIds.value)
  try {
    const result = await batchDeleteImages(selectedIds.value)
    ElMessage.success(result.message)
    clearSelection()
    // 刷新列表
    fetchImages()
  } catch (e) {
    ElMessage.error('批量删除失败: ' + e.message)
  } finally {
    batchDeleting.value = false
  }
}

const copyUrl = async () => {
  // 使用 getFullImageUrl 获取完整 URL（包含 base_url）
  const fullUrl = await getFullImageUrl(selectedImage.value.image_url)
  navigator.clipboard.writeText(fullUrl)
  ElMessage.success('已复制到剪贴板')
}

const copyOriginalUrl = () => {
  if (selectedImage.value?.original_url) {
    navigator.clipboard.writeText(selectedImage.value.original_url)
    ElMessage.success('原始地址已复制到剪贴板')
  }
}

const confirmDelete = (image) => {
  // 检查管理员权限
  if (!authStore.isAdmin) {
    ElMessage.warning('只有管理员才能删除图片')
    return
  }
  
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
      // 刷新列表
      fetchImages()
    } catch (e) {
      ElMessage.error('删除失败: ' + e.message)
    }
  }).catch(() => {})
}

const handleDeleteInFullscreen = async () => {
  const imageId = selectedImage.value.id
  try {
    await deleteImage(imageId)
    ElMessage.success('删除成功')
    fullscreenVisible.value = false
    // 刷新列表
    fetchImages()
  } catch (e) {
    ElMessage.error('删除失败: ' + e.message)
  }
}

// 获取队列状态
const fetchQueueStatus = async () => {
  try {
    queueStatus.value = await getQueueStatus()
    
    // 智能刷新：只有在队列从运行变为停止时才刷新
    if (!queueStatus.value?.running && prevRunning) {
      // 队列刚停止，刷新一次
      fetchImages()
    }
    prevRunning = queueStatus.value?.running
  } catch (e) {
    console.error('获取队列状态失败:', e)
  }
}

// 记录上次队列状态
let prevRunning = false

// 启动队列状态轮询
const startQueuePolling = () => {
  if (queueTimer) return
  
  queueTimer = setInterval(async () => {
    await fetchQueueStatus()
  }, 5000) // 5 秒轮询间隔
}

// 获取分类和分辨率选项
const fetchCategoryAndResolutionOptions = async () => {
  try {
    const [cats, ress] = await Promise.all([
      getCategories(),
      getResolutions()
    ])
    categoryOptions.value = cats || []
    resolutionOptions.value = ress || []
  } catch (e) {
    console.error('获取分类/分辨率选项失败', e)
  }
}

onMounted(() => {
  fetchImages()
  fetchCollections()
  fetchTags()
  fetchQueueStatus()
  startQueuePolling()
  fetchCategoryAndResolutionOptions()
})

onUnmounted(() => {
  if (queueTimer) {
    clearInterval(queueTimer)
    queueTimer = null
  }
})
</script>

<style scoped>
.gallery-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.filter-bar {
  background: var(--bg-card);
}

/* 标签区域标题样式 */
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
}

/* AI 标签标题 - 灰色 */
.ai-title {
  color: #909399;
}

.ai-title .el-icon {
  font-size: 18px;
}

/* 用户标签标题 - 绿色 */
.user-title {
  color: #67c23a;
}

.user-title .el-icon {
  font-size: 18px;
}

/* AI 标签样式 */
.tags-display .el-tag--info {
  background: rgba(144, 147, 153, 0.15);
  border-color: rgba(144, 147, 153, 0.3);
  color: #909399;
}

.tags-display .el-tag {
  margin-right: 8px;
  margin-bottom: 8px;
}

/* 添加标签行 */
.add-tag-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

/* 标题提示 */
.title-hint {
  font-weight: 400;
  font-size: 12px;
  opacity: 0.7;
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

/* 右下角收藏图标 */
.favorite-icon {
  position: absolute;
  bottom: 8px;
  right: 8px;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  color: rgba(255, 255, 255, 0.7);
}

.favorite-icon:hover {
  background: rgba(0, 0, 0, 0.8);
  transform: scale(1.1);
  color: #f7ba2a;
}

.favorite-icon.collected {
  color: #f7ba2a;
  background: rgba(247, 186, 42, 0.2);
}

.favorite-icon .el-icon {
  font-size: 18px;
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

.image-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: var(--text-secondary);
}

.meta-item .el-icon {
  font-size: 16px;
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

/* ===== 移动端响应式样式 768px ===== */
@media (max-width: 768px) {
  .gallery-page {
    padding: 0;
  }
  
  /* 筛选栏垂直布局 */
  .filter-bar {
    padding: 12px;
  }
  
  .filter-bar :deep(.el-form--inline) {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  .filter-bar :deep(.el-form-item) {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    margin-right: 0;
    margin-bottom: 0;
    width: 100%;
  }
  
  .filter-bar :deep(.el-form-item__label) {
    padding-bottom: 6px;
    padding-right: 0;
  }
  
  .filter-bar :deep(.el-form-item__content) {
    width: 100%;
  }
  
  .filter-bar :deep(.el-select),
  .filter-bar :deep(.el-input) {
    width: 100% !important;
  }
  
  .filter-bar :deep(.el-form-item:last-child) {
    flex-direction: row;
    flex-wrap: wrap;
    gap: 8px;
  }
  
  .filter-bar :deep(.el-form-item:last-child .el-button) {
    flex: 1;
  }
  
  /* 批量选择模式提示 */
  .batch-mode-hint {
    padding: 12px;
  }
  
  .batch-mode-btn {
    width: 100%;
  }
  
  /* 分页 */
  .pagination-container {
    padding: 12px 0;
  }
  
  :deep(.el-pagination) {
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
  }
  
  :deep(.el-pagination .el-pagination__sizes),
  :deep(.el-pagination .el-pagination__total) {
    display: none;
  }
  
  /* 图片卡片 */
  .image-card {
    border-radius: var(--radius-md);
  }
  
  .image-card img {
    height: 140px;
  }
  
  .image-card-content {
    padding: 10px;
  }
  
  .description {
    font-size: 13px;
    -webkit-line-clamp: 2;
  }
  
  /* 全屏弹窗适配 */
  .fullscreen-info-panel {
    padding: 16px;
    gap: 16px;
  }
  
  .panel-header {
    flex-wrap: wrap;
    gap: 12px;
  }
  
  .panel-actions {
    width: 100%;
    flex-wrap: wrap;
  }
  
  .panel-actions .el-button {
    flex: 1;
    min-width: auto;
  }
  
  .info-section h3 {
    font-size: 13px;
  }
  
  .description-text {
    font-size: 14px;
  }
  
  .add-tag-row {
    flex-direction: column;
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
