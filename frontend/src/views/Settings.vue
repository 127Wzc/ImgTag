<template>
  <div class="settings-page">
    <!-- 模型配置 -->
    <div class="card config-card">
      <div class="card-header">
        <el-icon :size="22" color="var(--primary-color)"><Setting /></el-icon>
        <h2>模型配置</h2>
      </div>
      
      <div v-if="loading" class="loading-state">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
      
      <el-form v-else :model="configForm" label-width="120px" class="config-form">
        <div class="form-section">
          <h3>
            <el-icon><View /></el-icon>
            视觉模型
          </h3>
          <el-form-item label="API 地址">
            <el-input 
              v-model="configForm.vision_api_base_url" 
              placeholder="https://api.openai.com/v1"
            />
          </el-form-item>
          <el-form-item label="API 密钥">
            <el-input 
              v-model="configForm.vision_api_key" 
              type="password"
              placeholder="sk-xxx"
              show-password
            />
          </el-form-item>
          <el-form-item label="模型名称">
            <el-input 
              v-model="configForm.vision_model" 
              placeholder="gpt-4o-mini"
            />
          </el-form-item>
          <el-form-item label="分析提示词">
            <el-input 
              v-model="configForm.vision_prompt" 
              type="textarea"
              :rows="8"
              placeholder="请分析这张图片..."
            />
            <div class="form-hint">
              自定义提示词可以控制标签和描述的输出风格。要求模型返回 JSON 格式：{"tags": [...], "description": "..."}
            </div>
          </el-form-item>
        </div>
        
        <div class="form-section">
          <h3>
            <el-icon><DataAnalysis /></el-icon>
            嵌入模型
          </h3>
          <el-form-item label="模式">
            <el-radio-group v-model="configForm.embedding_mode">
              <el-radio-button value="local">本地模型</el-radio-button>
              <el-radio-button value="api">在线 API</el-radio-button>
            </el-radio-group>
          </el-form-item>
          
          <!-- 本地模型配置 -->
          <template v-if="configForm.embedding_mode === 'local'">
            <el-form-item label="模型名称">
              <el-select v-model="configForm.embedding_local_model" style="width: 100%">
                <el-option label="bge-small-zh-v1.5 (~90MB, 512维)" value="BAAI/bge-small-zh-v1.5" />
                <el-option label="bge-base-zh-v1.5 (~400MB, 768维)" value="BAAI/bge-base-zh-v1.5" />
                <el-option label="text2vec-base-chinese (~400MB, 768维)" value="shibing624/text2vec-base-chinese" />
              </el-select>
            </el-form-item>
            <el-alert type="info" :closable="false" show-icon>
              首次使用会自动下载模型，请耐心等待
            </el-alert>
          </template>
          
          <!-- API 配置 -->
          <template v-else>
            <el-form-item label="API 地址">
              <el-input 
                v-model="configForm.embedding_api_base_url" 
                placeholder="https://api.openai.com/v1"
              />
            </el-form-item>
            <el-form-item label="API 密钥">
              <el-input 
                v-model="configForm.embedding_api_key" 
                type="password"
                placeholder="sk-xxx"
                show-password
              />
            </el-form-item>
            <el-form-item label="模型名称">
              <el-input 
                v-model="configForm.embedding_model" 
                placeholder="text-embedding-3-small"
              />
            </el-form-item>
            <el-form-item label="向量维度">
              <el-input-number 
                v-model.number="configForm.embedding_dimensions" 
                :min="256" 
                :max="4096"
                :step="256"
              />
            </el-form-item>
          </template>
        </div>
        
        <div class="form-actions">
          <el-button type="primary" :loading="saving" @click="saveConfig" round>
            <el-icon><Check /></el-icon>
            保存配置
          </el-button>
          <el-button @click="resetConfig" round>
            <el-icon><Refresh /></el-icon>
            重置
          </el-button>
        </div>
      </el-form>
    </div>
    
    <!-- 向量数据管理 -->
    <div class="card vector-card">
      <div class="card-header">
        <el-icon :size="22" color="#f59e0b"><Coin /></el-icon>
        <h2>向量数据管理</h2>
      </div>
      
      <div class="vector-info">
        <div class="info-row">
          <span class="label">嵌入模式:</span>
          <span class="value">{{ vectorStatus?.embedding_mode === 'local' ? '本地模型' : '在线 API' }}</span>
        </div>
        <div class="info-row">
          <span class="label">模型:</span>
          <span class="value">{{ vectorStatus?.embedding_model || '-' }}</span>
        </div>
        <div class="info-row">
          <span class="label">模型维度:</span>
          <span class="value">{{ vectorStatus?.embedding_dimensions || '-' }}</span>
        </div>
        <div class="info-row">
          <span class="label">数据库维度:</span>
          <span class="value" :class="{ 'text-error': !vectorStatus?.dimensions_match }">
            {{ vectorStatus?.db_dimensions || '-' }}
          </span>
        </div>
        <div class="info-row">
          <span class="label">图片数量:</span>
          <span class="value">{{ vectorStatus?.image_count || 0 }}</span>
        </div>
      </div>
      
      <!-- 维度不匹配提示 -->
      <el-alert
        v-if="vectorStatus && !vectorStatus.dimensions_match"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 20px"
      >
        维度不匹配 (模型: {{ vectorStatus.embedding_dimensions }}, 数据库: {{ vectorStatus.db_dimensions }})，点击重建会自动调整
      </el-alert>
      
      <!-- 重建状态 -->
      <div v-if="rebuildStatus?.is_running" class="rebuild-progress">
        <el-progress 
          :percentage="rebuildProgress" 
          :status="rebuildProgress === 100 ? 'success' : ''"
          :stroke-width="10"
        />
        <p class="progress-text">{{ rebuildStatus.message }}</p>
      </div>
      
      <el-alert
        v-if="vectorStatus?.dimensions_match"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 20px"
      >
        向量数据基于图片的描述和标签生成，切换模型后需重建向量数据
      </el-alert>
      
      <div class="vector-actions">
        <el-button 
          type="primary" 
          :loading="rebuilding"
          :disabled="rebuildStatus?.is_running"
          @click="handleRebuild"
          round
        >
          <el-icon><Refresh /></el-icon>
          {{ vectorStatus && !vectorStatus.dimensions_match ? '调整维度并重建' : '重建向量数据' }}
        </el-button>
        
        <el-popconfirm
          title="确定要清空所有向量数据吗？"
          confirm-button-text="确定"
          cancel-button-text="取消"
          @confirm="handleClear"
        >
          <template #reference>
            <el-button type="danger" plain round :loading="clearing">
              <el-icon><Delete /></el-icon>
              清空向量数据
            </el-button>
          </template>
        </el-popconfirm>
      </div>
    </div>
    
    <!-- 标签管理 -->
    <div class="card tag-card">
      <div class="card-header">
        <el-icon :size="22" color="#f59e0b"><Collection /></el-icon>
        <h2>标签管理</h2>
      </div>
      
      <p class="card-description">管理系统中的标签，包括同步、重命名和删除操作</p>
      
      <el-button type="primary" round @click="showTagManager = true">
        <el-icon><Edit /></el-icon>
        打开标签管理器
      </el-button>
    </div>

    <TagManager v-model="showTagManager" />
    
    <!-- 健康检查 -->
    <div class="card health-card">
      <div class="card-header">
        <el-icon :size="22" color="#22c55e"><Monitor /></el-icon>
        <h2>服务状态</h2>
      </div>
      
      <div class="health-status">
        <div class="status-indicator" :class="healthStatus">
          <el-icon :size="28">
            <SuccessFilled v-if="healthStatus === 'healthy'" />
            <CircleCloseFilled v-else-if="healthStatus === 'error'" />
            <Loading v-else class="is-loading" />
          </el-icon>
          <div class="status-text">
            <span class="status-label">API 服务</span>
            <span class="status-value">
              {{ healthStatus === 'healthy' ? '正常运行' : healthStatus === 'error' ? '连接异常' : '检查中...' }}
            </span>
          </div>
        </div>
        
        <el-button @click="checkHealth" :loading="checkingHealth" round>
          <el-icon><Refresh /></el-icon>
          检查
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { 
  getAllConfigs, 
  updateConfigs, 
  healthCheck, 
  getVectorStatus,
  startRebuildVectors,
  getRebuildStatus,
  clearVectors,
  resizeVectorTable
} from '@/api'
import TagManager from '@/components/TagManager.vue'

const showTagManager = ref(false)
const loading = ref(true)
const saving = ref(false)
const healthStatus = ref('checking')
const checkingHealth = ref(false)

const vectorStatus = ref(null)
const rebuildStatus = ref(null)
const rebuilding = ref(false)
const clearing = ref(false)
const resizing = ref(false)

let statusTimer = null

const configForm = reactive({
  vision_api_base_url: '',
  vision_api_key: '',
  vision_model: '',
  vision_prompt: '',
  embedding_mode: 'local',
  embedding_local_model: 'BAAI/bge-small-zh-v1.5',
  embedding_api_base_url: '',
  embedding_api_key: '',
  embedding_model: '',
  embedding_dimensions: 512
})

const originalConfig = ref({})

const rebuildProgress = computed(() => {
  if (!rebuildStatus.value || rebuildStatus.value.total === 0) return 0
  return Math.round((rebuildStatus.value.processed / rebuildStatus.value.total) * 100)
})

const fetchConfig = async () => {
  loading.value = true
  try {
    const data = await getAllConfigs()
    Object.keys(configForm).forEach(key => {
      if (data[key] !== undefined) {
        if (key === 'embedding_dimensions') {
          configForm[key] = parseInt(data[key]) || 1536
        } else {
          configForm[key] = data[key]
        }
      }
    })
    originalConfig.value = { ...configForm }
  } catch (e) {
    ElMessage.error('获取配置失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    const configs = {
      ...configForm,
      embedding_dimensions: String(configForm.embedding_dimensions)
    }
    await updateConfigs(configs)
    ElMessage.success('配置保存成功')
    originalConfig.value = { ...configForm }
  } catch (e) {
    ElMessage.error('保存配置失败: ' + e.message)
  } finally {
    saving.value = false
  }
}

const resetConfig = () => {
  Object.assign(configForm, originalConfig.value)
}

const checkHealth = async () => {
  checkingHealth.value = true
  healthStatus.value = 'checking'
  try {
    const result = await healthCheck()
    healthStatus.value = result.status === 'healthy' ? 'healthy' : 'error'
  } catch (e) {
    healthStatus.value = 'error'
  } finally {
    checkingHealth.value = false
  }
}

const fetchVectorStatus = async () => {
  try {
    const data = await getVectorStatus()
    vectorStatus.value = data
    rebuildStatus.value = data.rebuild_status
  } catch (e) {
    console.error('获取向量状态失败:', e)
  }
}

const handleRebuild = async () => {
  rebuilding.value = true
  try {
    await startRebuildVectors()
    ElMessage.success('向量重建任务已启动')
    // 开始轮询状态
    startStatusPolling()
  } catch (e) {
    ElMessage.error('启动重建失败: ' + e.message)
  } finally {
    rebuilding.value = false
  }
}

const handleClear = async () => {
  clearing.value = true
  try {
    await clearVectors()
    ElMessage.success('向量数据已清空')
    await fetchVectorStatus()
  } catch (e) {
    ElMessage.error('清空失败: ' + e.message)
  } finally {
    clearing.value = false
  }
}

const handleResize = async () => {
  resizing.value = true
  try {
    const result = await resizeVectorTable()
    ElMessage.success(result.message)
    await fetchVectorStatus()
  } catch (e) {
    ElMessage.error('调整维度失败: ' + e.message)
  } finally {
    resizing.value = false
  }
}

const startStatusPolling = () => {
  if (statusTimer) clearInterval(statusTimer)
  
  statusTimer = setInterval(async () => {
    try {
      const status = await getRebuildStatus()
      rebuildStatus.value = status
      
      if (!status.is_running) {
        clearInterval(statusTimer)
        statusTimer = null
        ElMessage.success(status.message)
        await fetchVectorStatus()
      }
    } catch (e) {
      console.error('获取重建状态失败:', e)
    }
  }, 2000)
}

onMounted(() => {
  fetchConfig()
  checkHealth()
  fetchVectorStatus()
})

onUnmounted(() => {
  if (statusTimer) {
    clearInterval(statusTimer)
  }
})
</script>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 32px;
  max-width: 1200px;
  width: 100%;
}

/* 卡片头部 - 现代化设计 */
.card-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 28px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border-color-light);
}

.card-header .el-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: rgba(0, 113, 227, 0.08);
  color: var(--primary-color);
}

/* 不同卡片的图标颜色 */
.vector-card .card-header .el-icon {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.tag-card .card-header .el-icon {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.health-card .card-header .el-icon {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}

.card-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.3px;
}

/* 卡片描述 */
.card-description {
  margin: 0 0 24px 0;
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.6;
}

/* 加载状态 */
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 64px 48px;
  color: var(--text-secondary);
}

/* 表单样式 */
.config-form {
  width: 100%;
}

.form-section {
  margin-bottom: 40px;
  padding: 24px;
  background: var(--bg-secondary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-color-light);
}

.form-section:last-of-type {
  margin-bottom: 0;
}

.form-section h3 {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 24px 0;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color-light);
}

.form-section h3 .el-icon {
  color: var(--primary-color);
  font-size: 18px;
}

.form-section :deep(.el-form-item) {
  margin-bottom: 22px;
}

.form-section :deep(.el-form-item__label) {
  font-weight: 500;
  color: var(--text-primary);
  font-size: 14px;
}

@media (max-width: 768px) {
  .config-form :deep(.el-form-item__label) {
    width: 100% !important;
    text-align: left !important;
    margin-bottom: 8px;
  }
}

.form-hint {
  margin-top: 10px;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
  padding: 12px 16px;
  background: rgba(0, 113, 227, 0.05);
  border-radius: var(--radius-sm);
  border-left: 3px solid var(--primary-color);
}

.form-actions {
  display: flex;
  gap: 14px;
  padding-top: 24px;
  margin-top: 32px;
  border-top: 1px solid var(--border-color-light);
}

/* 向量管理 - 网格布局 */
.vector-info {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
  padding: 0;
}

.info-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 20px;
  background: var(--bg-secondary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-color-light);
  transition: all var(--transition-fast);
}

.info-row:hover {
  background: var(--bg-hover);
  border-color: var(--border-color);
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}

.info-row .label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.info-row .value {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
}

.info-row .value.text-error {
  color: var(--danger-color);
}

.rebuild-progress {
  margin-bottom: 24px;
  padding: 24px;
  background: var(--bg-secondary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-color-light);
}

.progress-text {
  margin-top: 12px;
  font-size: 14px;
  color: var(--text-secondary);
  text-align: center;
  font-weight: 500;
}

.vector-actions {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

/* 健康检查 */
.health-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  border-radius: var(--radius-lg);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color-light);
  flex: 1;
  min-width: 200px;
  transition: all var(--transition-fast);
}

.status-indicator:hover {
  background: var(--bg-hover);
  border-color: var(--border-color);
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}

.status-indicator .el-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: rgba(52, 199, 89, 0.1);
}

.status-indicator.healthy .el-icon {
  background: rgba(52, 199, 89, 0.1);
  color: var(--success-color);
}

.status-indicator.error .el-icon {
  background: rgba(255, 59, 48, 0.1);
  color: var(--danger-color);
}

.status-indicator.checking .el-icon {
  background: rgba(134, 134, 139, 0.1);
  color: var(--text-secondary);
}

.status-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.status-label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.status-value {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

/* Alert 样式优化 */
:deep(.el-alert) {
  border-radius: var(--radius-lg) !important;
  border: 1px solid var(--border-color-light) !important;
  margin-bottom: 24px !important;
}

/* 按钮样式优化 */
:deep(.el-button) {
  font-weight: 500;
  padding: 10px 20px;
}

:deep(.el-button.is-round) {
  padding: 10px 24px;
}

/* 响应式布局 */
@media (max-width: 1024px) {
  .settings-page {
    max-width: 100%;
  }
  
  .vector-info {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .settings-page {
    gap: 24px;
  }
  
  .form-section {
    padding: 20px;
    margin-bottom: 32px;
  }
  
  .vector-info {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  
  .vector-actions {
    flex-direction: column;
  }
  
  .vector-actions .el-button {
    width: 100%;
  }
  
  .health-status {
    flex-direction: column;
    gap: 16px;
    align-items: stretch;
  }
  
  .status-indicator {
    min-width: auto;
  }
  
  .form-actions {
    flex-direction: column;
  }
  
  .form-actions .el-button {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  
  .card-header .el-icon {
    width: 36px;
    height: 36px;
  }
  
  .form-section {
    padding: 16px;
  }
}
</style>
