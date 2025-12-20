<template>
  <div class="upload-page">
    <!-- 上传区域 -->
    <div class="card upload-card">
      <div class="card-header">
        <el-icon :size="22" color="#8b5cf6"><Upload /></el-icon>
        <h2>图片上传</h2>
      </div>
      
      <div class="upload-mode">
        <el-radio-group v-model="uploadMode" size="large">
          <el-radio-button value="analyze">上传并分析</el-radio-button>
          <el-radio-button value="batch">批量上传</el-radio-button>
          <el-radio-button value="zip">上传 ZIP</el-radio-button>
        </el-radio-group>
      </div>
      
      <el-upload
        ref="uploadRef"
        class="upload-area"
        drag
        :action="uploadAction"
        :multiple="uploadMode === 'batch'"
        :auto-upload="false"
        :on-change="handleFileChange"
        :on-success="handleSuccess"
        :on-error="handleError"
        :show-file-list="true"
        :accept="uploadMode === 'zip' ? '.zip' : 'image/*'"
      >
        <el-icon class="upload-icon"><Upload /></el-icon>
        <div class="upload-text">
          <p v-if="uploadMode === 'zip'">将 ZIP 压缩包拖到此处，或<em>点击上传</em></p>
          <p v-else>将图片拖到此处，或<em>点击上传</em></p>
          <p class="upload-hint">
            {{ uploadMode === 'zip' ? '支持包含图片的 ZIP 文件，解压后自动保存' : uploadMode === 'batch' ? '批量上传后可在队列中统一分析' : '上传后会自动分析标签和描述' }}
          </p>
        </div>
      </el-upload>
      
      <div v-if="fileList.length > 0" class="upload-actions">
        <el-button type="primary" :loading="uploading" @click="handleUpload" round>
          <el-icon><Upload /></el-icon>
          {{ uploadMode === 'zip' ? '上传 ZIP' : uploadMode === 'batch' ? `上传 ${fileList.length} 张图片` : '上传并分析' }}
        </el-button>
        <el-button @click="clearFileList" round>清空</el-button>
      </div>
      
      <!-- 上传进度 -->
      <div v-if="uploading" class="upload-progress">
        <el-progress :percentage="uploadProgress" :stroke-width="10" />
        <p>{{ uploadProgressText }}</p>
      </div>
    </div>
    
    <!-- 队列管理 -->
    <div class="card queue-card">
      <div class="card-header">
        <el-icon :size="22" color="#f59e0b"><List /></el-icon>
        <h2>分析队列</h2>
        <div class="queue-status-badge" :class="{ running: queueStatus?.running }">
          {{ queueStatus?.running ? '运行中' : '已停止' }}
        </div>
      </div>
      
      <div class="queue-stats">
        <div class="stat-item">
          <span class="stat-value">{{ queueStatus?.pending_count || 0 }}</span>
          <span class="stat-label">待处理</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ queueStatus?.processing_count || 0 }}</span>
          <span class="stat-label">处理中</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ queueStatus?.completed_count || 0 }}</span>
          <span class="stat-label">已完成</span>
        </div>
      </div>
      
      <div class="queue-config">
        <span class="config-label">并发线程数：</span>
        <el-input-number 
          v-model="maxWorkers" 
          :min="1" 
          :max="10" 
          size="small"
          @change="updateWorkers"
        />
      </div>
      
      <div class="queue-actions">
        <el-button 
          type="primary" 
          :disabled="queueStatus?.running"
          @click="handleAddUntagged"
          round
        >
          <el-icon><Plus /></el-icon>
          添加未分析图片
        </el-button>
        
        <el-button 
          v-if="!queueStatus?.running"
          type="success"
          :disabled="queueStatus?.pending_count === 0"
          @click="handleStartQueue"
          round
        >
          <el-icon><VideoPlay /></el-icon>
          开始处理
        </el-button>
        
        <el-button 
          v-else
          type="warning"
          @click="handleStopQueue"
          round
        >
          <el-icon><VideoPause /></el-icon>
          停止处理
        </el-button>
        
        <el-button 
          type="danger" 
          plain
          :disabled="queueStatus?.pending_count === 0"
          @click="handleClearQueue"
          round
        >
          清空队列
        </el-button>
      </div>
      
      <!-- 处理中的任务 -->
      <div v-if="queueStatus?.processing?.length > 0" class="queue-list">
        <h4>正在处理</h4>
        <div class="queue-item processing" v-for="task in queueStatus.processing" :key="task.image_id">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>图片 #{{ task.image_id }}</span>
        </div>
      </div>
      
      <!-- 最近完成的任务 -->
      <div v-if="queueStatus?.recent_completed?.length > 0" class="queue-list">
        <h4>最近完成</h4>
        <div 
          class="queue-item" 
          :class="task.status"
          v-for="task in queueStatus.recent_completed" 
          :key="task.image_id"
        >
          <el-icon v-if="task.status === 'completed'"><SuccessFilled /></el-icon>
          <el-icon v-else><CircleCloseFilled /></el-icon>
          <span>图片 #{{ task.image_id }}</span>
          <span v-if="task.error" class="error-text">{{ task.error }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { 
  uploadAndAnalyze, 
  uploadOnly,
  uploadZip,
  getQueueStatus,
  addUntaggedToQueue,
  startQueue,
  stopQueue,
  clearQueue,
  setQueueWorkers
} from '@/api'

const uploadRef = ref(null)
const uploadMode = ref('analyze')
const fileList = ref([])
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadProgressText = ref('')

const queueStatus = ref(null)
const maxWorkers = ref(2)

let statusTimer = null

const uploadAction = '/api/v1/images/upload'

const handleFileChange = (file, files) => {
  fileList.value = files
}

const clearFileList = () => {
  fileList.value = []
  uploadRef.value?.clearFiles()
}

const handleUpload = async () => {
  if (fileList.value.length === 0) {
    ElMessage.warning('请先选择文件')
    return
  }
  
  uploading.value = true
  uploadProgress.value = 0
  
  // ZIP 模式特殊处理
  if (uploadMode.value === 'zip') {
    try {
      uploadProgressText.value = '正在上传并解压 ZIP 文件...'
      const result = await uploadZip(fileList.value[0].raw)
      uploadProgress.value = 100
      
      ElMessage.success(result.message)
      
      // 自动添加到队列
      if (result.uploaded_count > 0) {
        fetchQueueStatus()
      }
    } catch (e) {
      ElMessage.error('ZIP 上传失败: ' + e.message)
    } finally {
      uploading.value = false
      clearFileList()
    }
    return
  }
  
  // 普通图片上传
  const total = fileList.value.length
  let completed = 0
  let failed = 0
  const newIds = []
  
  for (const fileItem of fileList.value) {
    try {
      uploadProgressText.value = `正在上传 ${completed + 1}/${total}: ${fileItem.name}`
      
      let result
      if (uploadMode.value === 'batch') {
        result = await uploadOnly(fileItem.raw)
      } else {
        result = await uploadAndAnalyze(fileItem.raw)
      }
      
      newIds.push(result.id)
      completed++
      uploadProgress.value = Math.round((completed / total) * 100)
    } catch (e) {
      failed++
      console.error(`上传失败: ${fileItem.name}`, e)
    }
  }
  
  uploading.value = false
  
  if (failed === 0) {
    ElMessage.success(`成功上传 ${completed} 张图片`)
  } else {
    ElMessage.warning(`上传完成: ${completed} 成功, ${failed} 失败`)
  }
  
  clearFileList()
  
  // 如果是批量上传模式，刷新队列状态
  if (uploadMode.value === 'batch') {
    fetchQueueStatus()
  }
}

const handleSuccess = () => {
  ElMessage.success('上传成功')
}

const handleError = (error) => {
  ElMessage.error('上传失败: ' + error.message)
}

const fetchQueueStatus = async () => {
  try {
    queueStatus.value = await getQueueStatus()
    maxWorkers.value = queueStatus.value.max_workers || 2
  } catch (e) {
    console.error('获取队列状态失败:', e)
  }
}

const updateWorkers = async (value) => {
  try {
    await setQueueWorkers(value)
    ElMessage.success(`并发线程数已设置为 ${value}`)
  } catch (e) {
    ElMessage.error('设置失败: ' + e.message)
  }
}

const handleAddUntagged = async () => {
  try {
    const result = await addUntaggedToQueue()
    ElMessage.success(result.message)
    fetchQueueStatus()
  } catch (e) {
    ElMessage.error('添加失败: ' + e.message)
  }
}

const handleStartQueue = async () => {
  try {
    await startQueue()
    ElMessage.success('队列处理已启动')
    startPolling()
  } catch (e) {
    ElMessage.error('启动失败: ' + e.message)
  }
}

const handleStopQueue = async () => {
  try {
    await stopQueue()
    ElMessage.success('队列处理已停止')
    fetchQueueStatus()
  } catch (e) {
    ElMessage.error('停止失败: ' + e.message)
  }
}

const handleClearQueue = async () => {
  try {
    await clearQueue()
    ElMessage.success('队列已清空')
    fetchQueueStatus()
  } catch (e) {
    ElMessage.error('清空失败: ' + e.message)
  }
}

const startPolling = () => {
  if (statusTimer) clearInterval(statusTimer)
  
  statusTimer = setInterval(async () => {
    await fetchQueueStatus()
    
    // 队列停止后停止轮询
    if (!queueStatus.value?.running && queueStatus.value?.pending_count === 0) {
      clearInterval(statusTimer)
      statusTimer = null
    }
  }, 2000)
}

onMounted(() => {
  fetchQueueStatus()
})

onUnmounted(() => {
  if (statusTimer) {
    clearInterval(statusTimer)
  }
})
</script>

<style scoped>
.upload-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
  max-width: 900px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.card-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  flex: 1;
}

.upload-mode {
  margin-bottom: 20px;
}

.upload-area {
  width: 100%;
}

.upload-area :deep(.el-upload-dragger) {
  padding: 60px 20px;
  border-radius: var(--radius-lg);
}

.upload-icon {
  font-size: 48px;
  color: var(--primary-color);
  margin-bottom: 16px;
}

.upload-text p {
  margin: 0;
  color: var(--text-secondary);
}

.upload-text em {
  color: var(--primary-color);
  font-style: normal;
}

.upload-hint {
  font-size: 12px;
  margin-top: 8px !important;
  color: var(--text-muted);
}

.upload-actions {
  display: flex;
  gap: 12px;
  margin-top: 20px;
  justify-content: center;
}

.upload-progress {
  margin-top: 20px;
  text-align: center;
}

.upload-progress p {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 14px;
}

/* 队列管理 */
.queue-status-badge {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  background: var(--bg-primary);
  color: var(--text-secondary);
}

.queue-status-badge.running {
  background: #dcfce7;
  color: #16a34a;
}

.queue-stats {
  display: flex;
  gap: 32px;
  padding: 20px;
  background: var(--bg-primary);
  border-radius: var(--radius-md);
  margin-bottom: 20px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.queue-config {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.config-label {
  font-size: 14px;
  color: var(--text-secondary);
}

.queue-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.queue-list {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--border-color);
}

.queue-list h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.queue-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
  margin-bottom: 8px;
  font-size: 14px;
}

.queue-item.processing {
  color: var(--primary-color);
}

.queue-item.completed {
  color: #16a34a;
}

.queue-item.failed {
  color: #dc2626;
}

.error-text {
  font-size: 12px;
  color: #dc2626;
  margin-left: auto;
}

@media (max-width: 600px) {
  .queue-stats {
    flex-direction: column;
    gap: 16px;
    align-items: flex-start;
  }
  
  .stat-item {
    flex-direction: row;
    gap: 12px;
  }
  
  .queue-actions {
    flex-direction: column;
  }
}
</style>
