<template>
  <div class="dashboard">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <el-icon class="is-loading" :size="36"><Loading /></el-icon>
      <span>加载中...</span>
    </div>
    
    <template v-else>
      <!-- 综合统计面板 -->
      <div class="stats-panel">
        <!-- 第一行：图片统计 + 今日数据 -->
        <div class="stats-row">
          <div class="stats-group">
            <div class="group-title">
              <el-icon><Picture /></el-icon>
              图片
            </div>
            <div class="stats-items">
              <div class="stat-item primary">
                <span class="stat-value">{{ stats?.images?.total ?? 0 }}</span>
                <span class="stat-label">总数</span>
              </div>
              <div class="stat-item success">
                <span class="stat-value">{{ stats?.images?.analyzed ?? 0 }}</span>
                <span class="stat-label">已分析</span>
              </div>
              <div class="stat-item warning">
                <span class="stat-value">{{ stats?.images?.pending ?? 0 }}</span>
                <span class="stat-label">待分析</span>
              </div>
            </div>
          </div>
          
          <div class="divider"></div>
          
          <div class="stats-group">
            <div class="group-title">
              <el-icon><Calendar /></el-icon>
              今日
            </div>
            <div class="stats-items">
              <div class="stat-item info">
                <span class="stat-value">{{ stats?.today?.uploaded ?? 0 }}</span>
                <span class="stat-label">上传</span>
              </div>
              <div class="stat-item success">
                <span class="stat-value">{{ stats?.today?.analyzed ?? 0 }}</span>
                <span class="stat-label">分析</span>
              </div>
            </div>
          </div>
          
          <div class="divider"></div>
          
          <div class="stats-group">
            <div class="group-title">
              <el-icon><List /></el-icon>
              队列
              <el-tag v-if="stats?.queue?.running" type="success" size="small" effect="dark" round>运行中</el-tag>
              <el-tag v-else type="info" size="small" effect="plain" round>停止</el-tag>
            </div>
            <div class="stats-items">
              <div class="stat-item">
                <span class="stat-value">{{ stats?.queue?.pending ?? 0 }}</span>
                <span class="stat-label">等待</span>
              </div>
              <div class="stat-item warning">
                <span class="stat-value">{{ stats?.queue?.processing ?? 0 }}</span>
                <span class="stat-label">处理中</span>
              </div>
            </div>
          </div>
        </div>
        
        <!-- 第二行：系统配置 -->
        <div class="config-row">
          <div class="config-item">
            <span class="config-label">视觉模型</span>
            <span class="config-value">{{ stats?.system?.vision_model ?? '-' }}</span>
          </div>
          <div class="config-item">
            <span class="config-label">向量维度</span>
            <span class="config-value highlight">{{ stats?.system?.embedding_dimensions ?? '-' }}</span>
          </div>
        </div>
      </div>
      
      <!-- 最近添加 -->
      <div class="recent-section">
        <div class="section-header">
          <h2 class="section-title">
            <el-icon><Clock /></el-icon>
            最近添加
          </h2>
          <router-link to="/gallery">
            <el-button type="primary" round size="small">
              查看全部
              <el-icon style="margin-left: 4px;"><ArrowRight /></el-icon>
            </el-button>
          </router-link>
        </div>
        
        <div v-if="recentImages.length === 0" class="empty-state">
          <el-icon :size="40" color="#cbd5e1"><Picture /></el-icon>
          <p>暂无图片，<router-link to="/upload">去上传</router-link></p>
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
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getDashboardStats, getImages } from '@/api'

const stats = ref(null)
const recentImages = ref([])
const loading = ref(true)

const getImageUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http')) return url
  return url
}

onMounted(async () => {
  try {
    const [dashboardData, imagesResult] = await Promise.all([
      getDashboardStats(),
      getImages({ limit: 8, sortDesc: true })
    ])
    
    stats.value = dashboardData
    recentImages.value = imagesResult.images
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
  gap: 20px;
}

.loading-state {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-height: 200px;
  gap: 12px;
  color: var(--text-secondary);
}

/* 综合统计面板 */
.stats-panel {
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  padding: 20px;
  border: 1px solid var(--border-color-light);
}

.stats-row {
  display: flex;
  align-items: stretch;
  gap: 20px;
}

.divider {
  width: 1px;
  background: var(--border-color-light);
  align-self: stretch;
}

.stats-group {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.group-title .el-icon {
  font-size: 14px;
  color: var(--primary-color);
}

.group-title .el-tag {
  margin-left: 6px;
  font-size: 10px;
}

.stats-items {
  display: flex;
  gap: 16px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.stat-item.primary .stat-value { color: var(--primary-color); }
.stat-item.success .stat-value { color: var(--success-color); }
.stat-item.warning .stat-value { color: var(--warning-color); }
.stat-item.info .stat-value { color: #3b82f6; }

.stat-label {
  font-size: 11px;
  color: var(--text-muted);
}

/* 配置行 */
.config-row {
  display: flex;
  gap: 24px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color-light);
}

.config-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.config-label {
  font-size: 12px;
  color: var(--text-muted);
}

.config-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.config-value.highlight {
  color: var(--primary-color);
  font-weight: 600;
}

/* 最近添加 */
.recent-section {
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  padding: 20px;
  border: 1px solid var(--border-color-light);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.section-title .el-icon {
  color: var(--primary-color);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 0;
  gap: 12px;
  color: var(--text-secondary);
}

.empty-state p {
  margin: 0;
  font-size: 14px;
}

.empty-state a {
  color: var(--primary-color);
}

/* 图片网格 */
.images-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.image-card {
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: all 0.2s ease;
  border: 1px solid var(--border-color-light);
}

.image-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.image-wrapper {
  overflow: hidden;
}

.image-card img {
  width: 100%;
  height: 100px;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.image-card:hover img {
  transform: scale(1.05);
}

.image-card-content {
  padding: 8px;
}

.description {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin: 0 0 6px 0;
}

.image-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.image-card-tags .el-tag {
  font-size: 10px;
  padding: 0 6px;
  height: 18px;
}

/* 响应式 */
@media (max-width: 1200px) {
  .images-grid {
    grid-template-columns: repeat(4, 1fr);
  }

  .image-card img {
    height: 120px;
  }
}

@media (max-width: 900px) {
  .images-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .stats-panel {
    padding: 16px;
  }
  
  .stats-row {
    flex-direction: column;
    gap: 16px;
  }
  
  .divider {
    width: 100%;
    height: 1px;
  }
  
  .stats-group {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
  
  .group-title {
    min-width: 80px;
  }
  
  .stats-items {
    flex: 1;
    justify-content: flex-end;
    gap: 20px;
  }
  
  .stat-item {
    align-items: center;
  }
  
  .stat-value {
    font-size: 20px;
  }
  
  .config-row {
    flex-direction: column;
    gap: 10px;
  }
  
  .config-item {
    justify-content: space-between;
  }
  
  .images-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .image-card img {
    height: 120px;
  }
}

@media (max-width: 480px) {
  .images-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }
  
  .image-card-content {
    padding: 6px;
  }
  
  .image-card img {
    height: 100px;
  }
}
</style>
