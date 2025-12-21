<template>
  <div class="collections-page">
    <div class="page-header card">
      <h2>📁 我的收藏</h2>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon> 新建收藏夹
      </el-button>
    </div>

    <!-- 收藏夹列表 -->
    <div v-if="loading" class="loading-container card">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>加载中...</p>
    </div>

    <div v-else-if="collections.length === 0" class="empty-container card">
      <el-empty description="暂无收藏夹">
        <el-button type="primary" @click="showCreateDialog = true">创建第一个收藏夹</el-button>
      </el-empty>
    </div>

    <div v-else class="collections-list">
      <el-row :gutter="20">
        <el-col :xs="24" :sm="12" :md="8" :lg="6" v-for="collection in collections" :key="collection.id">
          <el-card class="collection-card" shadow="hover" @click="goToCollection(collection.id)">
            <template #header>
              <div class="card-header">
                <span class="collection-name">{{ collection.name }}</span>
                <div class="card-actions" @click.stop>
                  <el-button text size="small" @click="editCollection(collection)">
                    <el-icon><Edit /></el-icon>
                  </el-button>
                  <el-popconfirm 
                    title="确定删除此收藏夹？" 
                    @confirm="deleteCollectionById(collection.id)"
                  >
                    <template #reference>
                      <el-button text size="small" type="danger">
                        <el-icon><Delete /></el-icon>
                      </el-button>
                    </template>
                  </el-popconfirm>
                </div>
              </div>
            </template>
            <div class="collection-body">
              <div class="cover-preview">
                <img 
                  v-if="collection.cover_url" 
                  :src="collection.cover_url" 
                  :alt="collection.name"
                />
                <div v-else class="cover-placeholder">
                  <el-icon :size="40"><Folder /></el-icon>
                </div>
              </div>
              <p class="description">{{ collection.description || '暂无描述' }}</p>
              <div class="meta">
                <el-tag size="small">{{ collection.image_count || 0 }} 张图片</el-tag>
                <span class="date">{{ formatDate(collection.created_at) }}</span>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 收藏夹详情抽屉 -->
    <el-drawer
      v-model="showDetailDialog"
      :title="currentCollection?.name || '收藏夹详情'"
      direction="rtl"
      size="70%"
    >
      <div v-if="detailLoading" class="loading-container">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      </div>
      <div v-else-if="collectionImages.length === 0" class="empty-container">
        <el-empty description="收藏夹为空" />
      </div>
      <div v-else class="drawer-content">
        <div class="collection-images-grid">
          <div 
            v-for="image in collectionImages" 
            :key="image.id" 
            class="image-item"
            @click="openImageDetail(image)"
          >
            <img :src="image.image_url" :alt="image.description" />
            <div class="image-overlay">
              <el-button 
                circle 
                size="small" 
                type="danger" 
                @click.stop="removeFromCollection(image.id)"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 图片详情弹窗 -->
    <el-dialog
      v-model="showImageDialog"
      title="图片详情"
      width="80%"
      top="5vh"
      :close-on-click-modal="true"
    >
      <div v-if="selectedImage" class="image-detail">
        <div class="image-preview">
          <img :src="selectedImage.image_url" :alt="selectedImage.description" />
        </div>
        <div class="image-info">
          <h3>描述</h3>
          <p>{{ selectedImage.description || '暂无描述' }}</p>
          <h3>标签</h3>
          <div class="tags">
            <el-tag v-for="tag in selectedImage.tags" :key="tag" size="small" style="margin-right: 6px; margin-bottom: 6px;">
              {{ tag }}
            </el-tag>
            <span v-if="!selectedImage.tags?.length" class="no-tags">暂无标签</span>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 创建/编辑收藏夹弹窗 -->
    <el-dialog 
      v-model="showCreateDialog" 
      :title="editingCollection ? '编辑收藏夹' : '新建收藏夹'"
      width="400px"
    >
      <el-form :model="collectionForm" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="collectionForm.name" placeholder="收藏夹名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input 
            v-model="collectionForm.description" 
            type="textarea" 
            :rows="3"
            placeholder="可选描述"
          />
        </el-form-item>
        <el-form-item label="公开">
          <el-switch v-model="collectionForm.is_public" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCollection" :loading="saving">
          {{ editingCollection ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { 
  getCollections, 
  createCollection, 
  updateCollection, 
  deleteCollection,
  getCollectionImages,
  removeImageFromCollection
} from '@/api'

const authStore = useAuthStore()

const loading = ref(true)
const collections = ref([])
const showCreateDialog = ref(false)
const showDetailDialog = ref(false)
const showImageDialog = ref(false)
const saving = ref(false)
const editingCollection = ref(null)
const currentCollection = ref(null)
const collectionImages = ref([])
const detailLoading = ref(false)
const selectedImage = ref(null)

const collectionForm = reactive({
  name: '',
  description: '',
  is_public: true
})

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

const fetchCollections = async () => {
  loading.value = true
  try {
    collections.value = await getCollections()
  } catch (e) {
    ElMessage.error('获取收藏夹失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

const goToCollection = async (id) => {
  const collection = collections.value.find(c => c.id === id)
  currentCollection.value = collection
  showDetailDialog.value = true
  detailLoading.value = true
  
  try {
    const result = await getCollectionImages(id)
    collectionImages.value = result.images || []
  } catch (e) {
    ElMessage.error('获取收藏内容失败')
  } finally {
    detailLoading.value = false
  }
}

const openImageDetail = (image) => {
  selectedImage.value = image
  showImageDialog.value = true
}

const editCollection = (collection) => {
  editingCollection.value = collection
  collectionForm.name = collection.name
  collectionForm.description = collection.description || ''
  collectionForm.is_public = collection.is_public ?? true
  showCreateDialog.value = true
}

const saveCollection = async () => {
  if (!collectionForm.name) {
    ElMessage.warning('请输入收藏夹名称')
    return
  }
  
  saving.value = true
  try {
    if (editingCollection.value) {
      await updateCollection(editingCollection.value.id, collectionForm)
      ElMessage.success('更新成功')
    } else {
      await createCollection(collectionForm)
      ElMessage.success('创建成功')
    }
    showCreateDialog.value = false
    resetForm()
    fetchCollections()
  } catch (e) {
    ElMessage.error('操作失败: ' + e.message)
  } finally {
    saving.value = false
  }
}

const deleteCollectionById = async (id) => {
  try {
    await deleteCollection(id)
    ElMessage.success('删除成功')
    fetchCollections()
  } catch (e) {
    ElMessage.error('删除失败: ' + e.message)
  }
}

const removeFromCollection = async (imageId) => {
  try {
    await removeImageFromCollection(currentCollection.value.id, imageId)
    collectionImages.value = collectionImages.value.filter(img => img.id !== imageId)
    ElMessage.success('已移除')
  } catch (e) {
    ElMessage.error('移除失败')
  }
}

const resetForm = () => {
  collectionForm.name = ''
  collectionForm.description = ''
  collectionForm.is_public = true
  editingCollection.value = null
}

onMounted(() => {
  if (!authStore.isLoggedIn) {
    ElMessage.warning('请先登录')
    return
  }
  fetchCollections()
})
</script>

<style scoped>
.collections-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-header h2 {
  margin: 0;
  color: var(--text-primary);
}

.loading-container, .empty-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
  color: var(--text-secondary);
  gap: 16px;
}

.collections-list {
  padding: 0;
}

.collection-card {
  margin-bottom: 20px;
  cursor: pointer;
  transition: all 0.3s;
}

.collection-card:hover {
  transform: translateY(-4px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.collection-name {
  font-weight: 600;
  font-size: 15px;
}

.card-actions {
  display: flex;
  gap: 4px;
}

.collection-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cover-preview {
  width: 100%;
  aspect-ratio: 16/10;
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-secondary);
}

.cover-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cover-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-hover) 100%);
}

.description {
  color: var(--text-secondary);
  font-size: 13px;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.date {
  font-size: 12px;
  color: var(--text-muted);
}

.drawer-content {
  padding: 10px;
}

.collection-images-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 16px;
}

.image-item {
  position: relative;
  aspect-ratio: 1;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
}

.image-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s;
}

.image-item:hover img {
  transform: scale(1.05);
}

.image-item .image-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s;
}

.image-item:hover .image-overlay {
  opacity: 1;
}

.image-detail {
  display: flex;
  gap: 24px;
}

.image-preview {
  flex: 2;
  max-height: 70vh;
  overflow: hidden;
  border-radius: 8px;
}

.image-preview img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.image-info {
  flex: 1;
  min-width: 250px;
}

.image-info h3 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--text-primary);
}

.image-info p {
  color: var(--text-secondary);
  margin: 0 0 16px;
}

.tags {
  display: flex;
  flex-wrap: wrap;
}

.no-tags {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
