<template>
  <div class="upload-page">
    <!-- 上传区域 -->
    <div class="card upload-card">
      <div class="card-header">
        <el-icon :size="22" color="var(--primary-color)"><Upload /></el-icon>
        <h2>图片上传</h2>
      </div>
      
      <div class="upload-mode">
        <el-radio-group v-model="uploadMode" size="large">
          <el-radio-button value="analyze">上传并分析</el-radio-button>
          <el-radio-button value="batch">批量上传</el-radio-button>
          <el-radio-button value="zip">上传 ZIP</el-radio-button>
        </el-radio-group>
      </div>
      
      <!-- 分类选择器 -->
      <div class="category-selector">
        <span class="selector-label">主分类：</span>
        <el-select v-model="selectedCategoryId" placeholder="待分类" clearable style="width: 200px;">
          <el-option
            v-for="cat in categories"
            :key="cat.id"
            :label="cat.name"
            :value="cat.id"
          />
        </el-select>
        <span class="selector-tip">留空则默认为"待分类"</span>
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
  setQueueWorkers,
  getCategories
} from '@/api'

const uploadRef = ref(null)
const uploadMode = ref('analyze')
const fileList = ref([])
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadProgressText = ref('')

const queueStatus = ref(null)
const maxWorkers = ref(2)

// 分类选择
const categories = ref([])
const selectedCategoryId = ref(null)

let statusTimer = null

const uploadAction = '/api/v1/images/upload'

// 获取主分类列表
const fetchCategories = async () => {
  try {
    categories.value = await getCategories()
  } catch (e) {
    console.error('获取分类列表失败:', e)
  }
}

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
  
  const categoryId = selectedCategoryId.value || null
  
  // ZIP 模式特殊处理
  if (uploadMode.value === 'zip') {
    try {
      uploadProgressText.value = '正在上传并解压 ZIP 文件...'
      const result = await uploadZip(fileList.value[0].raw, categoryId)
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
        result = await uploadOnly(fileItem.raw, categoryId)
      } else {
        result = await uploadAndAnalyze(fileItem.raw, true, categoryId)
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
  fetchCategories()
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

.category-selector {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  padding: 12px 16px;
  background: var(--bg-primary);
  border-radius: var(--radius-md);
}

.selector-label {
  font-size: 14px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.selector-tip {
  font-size: 12px;
  color: var(--text-muted);
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

/* ===== 移动端响应式样式 ===== */
@media (max-width: 768px) {
  .upload-page {
    gap: 16px;
  }
  
  .upload-card,
  .queue-card {
    padding: 16px;
  }
  
  .card-header {
    margin-bottom: 16px;
    padding-bottom: 12px;
  }
  
  .card-header h2 {
    font-size: 16px;
  }
  
  /* 上传模式选择器 */
  .upload-mode {
    margin-bottom: 16px;
  }
  
  .upload-mode :deep(.el-radio-group) {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  
  .upload-mode :deep(.el-radio-button) {
    flex: 1;
    min-width: auto;
  }
  
  .upload-mode :deep(.el-radio-button__inner) {
    width: 100%;
    padding: 10px 8px;
    font-size: 13px;
  }
  
  /* 上传区域 */
  .upload-area :deep(.el-upload-dragger) {
    padding: 40px 16px;
  }
  
  .upload-icon {
    font-size: 36px;
    margin-bottom: 12px;
  }
  
  .upload-text p {
    font-size: 14px;
  }
  
  .upload-hint {
    font-size: 11px;
  }
  
  /* 上传操作按钮 */
  .upload-actions {
    flex-direction: column;
  }
  
  .upload-actions .el-button {
    width: 100%;
  }
  
  /* 队列统计 */
  .queue-stats {
    gap: 16px;
    padding: 16px;
    flex-direction: row;
    justify-content: space-around;
  }
  
  .stat-value {
    font-size: 22px;
  }
  
  .stat-label {
    font-size: 11px;
  }
  
  /* 队列配置 */
  .queue-config {
    flex-wrap: wrap;
  }
  
  /* 队列操作按钮 */
  .queue-actions {
    flex-wrap: wrap;
    gap: 10px;
  }
  
  .queue-actions .el-button {
    flex: 1;
    min-width: calc(50% - 5px);
  }
  
  /* 队列列表 */
  .queue-list {
    margin-top: 16px;
    padding-top: 16px;
  }
  
  .queue-item {
    padding: 10px;
    font-size: 13px;
  }
  
  .error-text {
    width: 100%;
    margin-left: 24px;
    margin-top: 4px;
  }
}

@media (max-width: 600px) {
  .queue-stats {
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
  }
  
  .stat-item {
    flex-direction: row;
    gap: 12px;
    width: 100%;
    justify-content: space-between;
  }
  
  .queue-actions .el-button {
    min-width: 100%;
  }
}
</style>
