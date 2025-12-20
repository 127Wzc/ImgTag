<template>
  <div class="dashboard">
    <!-- 统计卡片 -->
    <div class="grid-4">
      <div class="stat-card">
        <div class="stat-icon primary">
          <el-icon><Picture /></el-icon>
        </div>
        <div class="stat-content">
          <h3>图片总数</h3>
          <p>{{ status?.image_count ?? '0' }}</p>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon success">
          <el-icon><CircleCheck /></el-icon>
        </div>
        <div class="stat-content">
          <h3>系统状态</h3>
          <p>{{ status?.status === 'running' ? '运行中' : '检查中' }}</p>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon info">
          <el-icon><View /></el-icon>
        </div>
        <div class="stat-content">
          <h3>视觉模型</h3>
          <p class="text-sm">{{ status?.vision_model ?? '-' }}</p>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon warning">
          <el-icon><DataAnalysis /></el-icon>
        </div>
        <div class="stat-content">
          <h3>向量维度</h3>
          <p>{{ status?.embedding_dimensions ?? '-' }}</p>
        </div>
      </div>
    </div>
    
    <!-- 快捷操作 -->
    <div class="card">
      <div class="section-header">
        <h2>快捷操作</h2>
      </div>
      <div class="actions-grid">
        <router-link to="/upload" class="action-card">
          <div class="action-icon upload">
            <el-icon :size="28"><Upload /></el-icon>
          </div>
          <div class="action-info">
            <span class="action-title">上传图片</span>
            <span class="action-desc">本地或远程 URL</span>
          </div>
        </router-link>
        
        <router-link to="/search" class="action-card">
          <div class="action-icon search">
            <el-icon :size="28"><Search /></el-icon>
          </div>
          <div class="action-info">
            <span class="action-title">智能搜索</span>
            <span class="action-desc">向量相似度匹配</span>
          </div>
        </router-link>
        
        <router-link to="/gallery" class="action-card">
          <div class="action-icon gallery">
            <el-icon :size="28"><FolderOpened /></el-icon>
          </div>
          <div class="action-info">
            <span class="action-title">图片库</span>
            <span class="action-desc">浏览和管理</span>
          </div>
        </router-link>
        
        <router-link to="/settings" class="action-card">
          <div class="action-icon settings">
            <el-icon :size="28"><Setting /></el-icon>
          </div>
          <div class="action-info">
            <span class="action-title">系统设置</span>
            <span class="action-desc">配置和状态</span>
          </div>
        </router-link>
      </div>
    </div>
    
    <!-- 最近图片 -->
    <div class="card">
      <div class="section-header">
        <h2>最近添加</h2>
        <router-link to="/gallery">
          <el-button type="primary" round>
            <el-icon style="margin-right: 4px;"><ArrowRight /></el-icon>
            查看全部
          </el-button>
        </router-link>
      </div>
      
      <div v-if="loading" class="loading-state">
        <el-icon class="is-loading" :size="36"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
      
      <div v-else-if="recentImages.length === 0" class="empty-state">
        <el-icon :size="48" color="#cbd5e1"><Picture /></el-icon>
        <p>暂无图片</p>
        <router-link to="/upload">
          <el-button type="primary" round>上传第一张图片</el-button>
        </router-link>
      </div>
      
      <div v-else class="images-grid">
        <div 
          v-for="image in recentImages" 
          :key="image.id" 
          class="image-card"
        >
          <div class="image-wrapper">
            <img :src="getImageUrl(image.image_url)" :alt="image.description" />
          </div>
          <div class="image-card-content">
            <p class="description">{{ image.description || '暂无描述' }}</p>
            <div class="image-card-tags">
              <el-tag 
                v-for="tag in image.tags?.slice(0, 3)" 
                :key="tag" 
                size="small"
                type="info"
                effect="plain"
                round
              >
                {{ tag }}
              </el-tag>
              <el-tag v-if="image.tags?.length > 3" size="small" type="info" effect="plain" round>
                +{{ image.tags.length - 3 }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getSystemStatus, getImages } from '@/api'

const status = ref(null)
const recentImages = ref([])
const loading = ref(true)

const getImageUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http')) return url
  return url
}

onMounted(async () => {
  try {
    status.value = await getSystemStatus()
    const result = await getImages({ limit: 6, sortDesc: true })
    recentImages.value = result.images
  } catch (e) {
    console.error('获取数据失败:', e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.text-sm {
  font-size: 16px !important;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.section-header h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

/* 快捷操作 */
.actions-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border-radius: var(--radius-lg);
  background: var(--bg-primary);
  text-decoration: none;
  transition: all 0.3s ease;
  border: 1px solid transparent;
}

.action-card:hover {
  background: white;
  border-color: var(--border-color);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.action-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  color: white;
}

.action-icon.upload {
  background: linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%);
}

.action-icon.search {
  background: linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%);
}

.action-icon.gallery {
  background: linear-gradient(135deg, #22c55e 0%, #4ade80 100%);
}

.action-icon.settings {
  background: linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%);
}

.action-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.action-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.action-desc {
  font-size: 13px;
  color: var(--text-secondary);
}

/* 状态提示 */
.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-height: 240px;
  gap: 16px;
  color: var(--text-secondary);
}

.empty-state p {
  margin: 0;
  font-size: 15px;
}

/* 图片网格 */
.images-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.image-wrapper {
  overflow: hidden;
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}

.image-card img {
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  height: 160px;
}

.description {
  font-size: 14px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 10px;
}

@media (max-width: 1200px) {
  .actions-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 900px) {
  .images-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .actions-grid,
  .images-grid {
    grid-template-columns: 1fr;
  }
}
</style>
