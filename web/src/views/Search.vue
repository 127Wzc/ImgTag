<template>
  <div class="search-page">
    <!-- 搜索表单 -->
    <div class="card search-form">
      <h2>
        <el-icon><MagicStick /></el-icon>
        智能向量搜索
      </h2>
      <p class="form-description">
        输入描述或关键词，系统将使用向量相似度匹配最相关的图片
      </p>
      
      <el-form @submit.prevent="handleSearch">
        <el-form-item>
          <el-input
            v-model="searchText"
            placeholder="描述你想要找的图片，例如：蓝天白云下的草原"
            size="large"
            clearable
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-form-item>
        
        <el-form-item>
          <el-select
            v-model="searchTags"
            multiple
            filterable
            allow-create
            placeholder="可选：添加标签辅助搜索"
            style="width: 100%"
            size="large"
          />
        </el-form-item>
        
        <div class="search-options">
          <el-form-item label="相似度阈值">
            <el-slider
              v-model="threshold"
              :min="0"
              :max="1"
              :step="0.05"
              :format-tooltip="(val) => (val * 100).toFixed(0) + '%'"
              style="width: 150px"
            />
            <span class="threshold-value">{{ (threshold * 100).toFixed(0) }}%</span>
          </el-form-item>
          
          <el-form-item label="向量权重">
            <el-slider
              v-model="vectorWeight"
              :min="0"
              :max="1"
              :step="0.1"
              style="width: 100px"
            />
            <span class="threshold-value">{{ vectorWeight }}</span>
          </el-form-item>
          
          <el-form-item label="标签权重">
            <el-slider
              v-model="tagWeight"
              :min="0"
              :max="1"
              :step="0.1"
              style="width: 100px"
            />
            <span class="threshold-value">{{ tagWeight }}</span>
          </el-form-item>
          
          <el-form-item label="结果数量">
            <el-input-number
              v-model="limit"
              :min="1"
              :max="50"
              size="small"
              style="width: 100px"
            />
          </el-form-item>
        </div>
        
        <div class="search-actions">
          <el-button
            type="primary"
            size="large"
            :loading="searching"
            :disabled="!searchText.trim()"
            @click="handleSearch"
          >
            <el-icon><Search /></el-icon>
            搜索
          </el-button>
        </div>
      </el-form>
    </div>
    
    <!-- 搜索结果 -->
    <div v-if="searched" class="results-section">
      <div class="results-header">
        <h3>搜索结果</h3>
        <span class="results-count">共找到 {{ results.length }} 个相似图片</span>
      </div>
      
      <div v-if="results.length === 0" class="empty-results">
        <el-empty description="未找到相似图片">
          <p>尝试使用不同的描述或降低相似度阈值</p>
        </el-empty>
      </div>
      
      <div v-else class="results-grid">
        <div 
          v-for="item in results" 
          :key="item.id" 
          class="result-card"
        >
          <div class="similarity-badge">
            {{ (item.similarity * 100).toFixed(1) }}%
          </div>
          <img :src="getImageUrl(item.image_url)" :alt="item.description" />
          <div class="result-content">
            <p class="description">{{ item.description || '暂无描述' }}</p>
            <div class="result-tags">
              <el-tag 
                v-for="tag in item.tags?.slice(0, 4)" 
                :key="tag" 
                size="small"
                type="info"
              >
                {{ tag }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { searchSimilar } from '@/api'

const searchText = ref('')
const searchTags = ref([])
const threshold = ref(0.5)
const vectorWeight = ref(0.7)
const tagWeight = ref(0.3)
const limit = ref(10)

const searching = ref(false)
const searched = ref(false)
const results = ref([])

const getImageUrl = (url) => {
  if (url.startsWith('http')) return url
  return url
}

const handleSearch = async () => {
  if (!searchText.value.trim()) {
    ElMessage.warning('请输入搜索内容')
    return
  }
  
  searching.value = true
  searched.value = false
  
  try {
    const response = await searchSimilar(
      searchText.value,
      searchTags.value,
      limit.value,
      threshold.value,
      vectorWeight.value,
      tagWeight.value
    )
    
    results.value = response.images
    searched.value = true
    
    if (results.value.length === 0) {
      ElMessage.info('未找到符合条件的结果')
    }
  } catch (e) {
    ElMessage.error('搜索失败: ' + e.message)
  } finally {
    searching.value = false
  }
}
</script>

<style scoped>
.search-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.search-form {
  text-align: center;
}

.search-form h2 {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 24px;
}

.form-description {
  color: var(--text-secondary);
  margin-bottom: 24px;
}

.search-options {
  display: flex;
  justify-content: center;
  gap: 40px;
  margin: 20px 0;
}

.search-options .el-form-item {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 0;
}

.threshold-value {
  width: 40px;
  text-align: right;
  font-weight: 600;
  color: var(--primary-color);
}

.search-actions {
  margin-top: 20px;
}

.search-actions .el-button {
  padding: 16px 48px;
}

.results-section {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-color);
  padding: 24px;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.results-header h3 {
  margin: 0;
}

.results-count {
  color: var(--text-secondary);
}

.empty-results {
  padding: 40px;
}

.empty-results p {
  color: var(--text-secondary);
  margin-top: 8px;
}

.results-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.result-card {
  position: relative;
  background: var(--bg-primary);
  border-radius: var(--radius-lg);
  overflow: hidden;
  border: 1px solid var(--border-color);
  transition: transform 0.2s, box-shadow 0.2s;
}

.result-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-lg);
}

.similarity-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  background: linear-gradient(135deg, var(--primary-color) 0%, var(--primary-light) 100%);
  color: white;
  padding: 4px 12px;
  border-radius: 20px;
  font-weight: 600;
  font-size: 14px;
  z-index: 1;
}

.result-card img {
  width: 100%;
  height: 200px;
  object-fit: cover;
}

.result-content {
  padding: 16px;
}

.description {
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.result-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 1000px) {
  .results-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 768px 移动端适配 */
@media (max-width: 768px) {
  .search-page {
    gap: 16px;
  }
  
  .search-form {
    padding: 16px;
  }
  
  .search-form h2 {
    font-size: 20px;
  }
  
  .form-description {
    font-size: 13px;
    margin-bottom: 16px;
  }
  
  .search-options {
    flex-direction: column;
    gap: 16px;
    align-items: stretch;
  }
  
  .search-options .el-form-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    width: 100%;
  }
  
  .search-options :deep(.el-slider) {
    width: 100% !important;
    margin: 0;
  }
  
  .search-options :deep(.el-input-number) {
    width: 100% !important;
  }
  
  .threshold-value {
    width: auto;
    text-align: left;
  }
  
  .search-actions .el-button {
    width: 100%;
    padding: 14px;
  }
  
  .results-section {
    padding: 16px;
  }
  
  .results-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  
  .results-header h3 {
    font-size: 16px;
  }
  
  .result-card img {
    height: 160px;
  }
  
  .result-content {
    padding: 12px;
  }
}

@media (max-width: 600px) {
  .results-grid {
    grid-template-columns: 1fr;
  }
  
  .search-form h2 {
    font-size: 18px;
  }
  
  .result-card img {
    height: 180px;
  }
}
</style>
