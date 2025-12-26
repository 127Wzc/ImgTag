<template>
  <div class="storage-page">
    <div class="page-header">
      <div class="page-header-left">
        <h1 class="page-title">
          <el-icon><Box /></el-icon>
          存储管理
        </h1>
        <p class="page-description">管理文件存储与 S3 备份同步</p>
      </div>
      <el-button 
        type="primary" 
        @click="testConnection" 
        :loading="testing"
        :disabled="!s3Enabled"
      >
        <el-icon><Connection /></el-icon> 测试连接
      </el-button>
    </div>

    <el-tabs v-model="activeTab" class="storage-tabs">
      <!-- S3 配置 -->
      <el-tab-pane label="S3 配置" name="config">
        <div class="tab-content">
          <el-form :model="s3Config" label-width="140px" class="config-form">
            <el-form-item label="启用 S3 备份">
              <el-switch v-model="s3Config.s3_enabled" />
            </el-form-item>
            
            <el-form-item label="S3 端点 URL">
              <el-input 
                v-model="s3Config.s3_endpoint_url" 
                placeholder="https://s3.amazonaws.com 或 MinIO 地址"
              />
            </el-form-item>
            
            <el-form-item label="Access Key ID">
              <el-input v-model="s3Config.s3_access_key_id" />
            </el-form-item>
            
            <el-form-item label="Secret Access Key">
              <el-input 
                v-model="s3Config.s3_secret_access_key" 
                type="password" 
                show-password
              />
            </el-form-item>
            
            <el-form-item label="存储桶名称">
              <el-input v-model="s3Config.s3_bucket_name" />
            </el-form-item>
            
            <el-form-item label="区域">
              <el-input v-model="s3Config.s3_region" placeholder="us-east-1" />
            </el-form-item>
            
            <el-form-item label="公开 URL 前缀">
              <el-input 
                v-model="s3Config.s3_public_url_prefix" 
                placeholder="https://cdn.example.com/bucket"
              />
              <p class="field-tip">可选，配置后图片将通过此前缀访问</p>
            </el-form-item>
            
            <el-form-item label="路径前缀">
              <el-input v-model="s3Config.s3_path_prefix" placeholder="imgtag/" />
            </el-form-item>
            
            <el-divider />
            
            <el-form-item label="图片 URL 优先级">
              <el-radio-group v-model="s3Config.image_url_priority">
                <el-radio-button value="auto">自动</el-radio-button>
                <el-radio-button value="local">本地优先</el-radio-button>
                <el-radio-button value="cdn">CDN 优先</el-radio-button>
              </el-radio-group>
              <p class="field-tip">
                自动：S3 启用时用 CDN，否则用本地 | 
                本地优先：开发模式 | 
                CDN 优先：生产模式
              </p>
            </el-form-item>
            
            <el-form-item>
              <el-button type="primary" @click="saveConfig" :loading="saving">
                保存配置
              </el-button>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- 同步管理 -->
      <el-tab-pane label="同步管理" name="sync">
        <div class="tab-content">
          <!-- 状态统计 -->
          <div class="stats-row">
            <div class="stat-card">
              <span class="stat-value">{{ status.total || 0 }}</span>
              <span class="stat-label">总文件数</span>
            </div>
            <div class="stat-card local">
              <span class="stat-value">{{ status.local_only || 0 }}</span>
              <span class="stat-label">仅本地</span>
            </div>
            <div class="stat-card s3">
              <span class="stat-value">{{ status.s3_only || 0 }}</span>
              <span class="stat-label">仅 S3</span>
            </div>
            <div class="stat-card synced">
              <span class="stat-value">{{ status.both || 0 }}</span>
              <span class="stat-label">已同步</span>
            </div>
          </div>

          <!-- 工具栏 -->
          <div class="toolbar">
            <el-select v-model="filter" @change="fetchFiles" style="width: 150px;">
              <el-option label="全部文件" value="all" />
              <el-option label="仅本地" value="local_only" />
              <el-option label="仅 S3" value="s3_only" />
              <el-option label="已同步" value="both" />
            </el-select>
            
            <div class="toolbar-right">
              <el-button 
                type="primary" 
                @click="batchSyncToS3"
                :loading="syncing"
                :disabled="!s3Enabled || selectedIds.length === 0"
              >
                <el-icon><Upload /></el-icon> 同步到 S3 ({{ selectedIds.length }})
              </el-button>
              <el-button 
                @click="batchSyncToLocal"
                :loading="syncing"
                :disabled="!s3Enabled || selectedIds.length === 0"
              >
                <el-icon><Download /></el-icon> 同步到本地 ({{ selectedIds.length }})
              </el-button>
            </div>
          </div>

          <!-- 文件列表 -->
          <el-table 
            v-loading="loading"
            :data="files" 
            @selection-change="handleSelectionChange"
            style="margin-top: 16px;"
          >
            <el-table-column type="selection" width="50" />
            <el-table-column prop="filename" label="文件名" min-width="200">
              <template #default="{ row }">
                <span class="filename">{{ row.filename }}</span>
              </template>
            </el-table-column>
            <el-table-column label="本地" width="80" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.local_exists" type="success" size="small">✓</el-tag>
                <el-tag v-else type="info" size="small">✗</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="S3" width="80" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.s3_path" type="primary" size="small">✓</el-tag>
                <el-tag v-else type="info" size="small">✗</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" align="center">
              <template #default="{ row }">
                <el-button 
                  v-if="row.local_exists && !row.s3_path"
                  link 
                  type="primary" 
                  size="small"
                  @click="syncSingleToS3(row.id)"
                  :disabled="!s3Enabled"
                >
                  同步到 S3
                </el-button>
                <el-button 
                  v-if="!row.local_exists && row.s3_path"
                  link 
                  type="primary" 
                  size="small"
                  @click="syncSingleToLocal(row.id)"
                  :disabled="!s3Enabled"
                >
                  同步到本地
                </el-button>
                <span v-if="row.local_exists && row.s3_path" class="synced-text">已同步</span>
              </template>
            </el-table-column>
          </el-table>

          <!-- 分页 -->
          <div class="pagination-wrapper">
            <el-pagination
              v-model:current-page="currentPage"
              :page-size="pageSize"
              :total="total"
              layout="total, prev, pager, next"
              @current-change="fetchFiles"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Box, Connection, Upload, Download } from '@element-plus/icons-vue'
import { 
  getAllConfigs, updateConfigs,
  getStorageStatus, getStorageFiles, testS3Connection, syncToS3, syncToLocal 
} from '@/api'

const activeTab = ref('sync')
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const syncing = ref(false)

// S3 配置
const s3Config = reactive({
  s3_enabled: false,
  s3_endpoint_url: '',
  s3_access_key_id: '',
  s3_secret_access_key: '',
  s3_bucket_name: '',
  s3_region: 'us-east-1',
  s3_public_url_prefix: '',
  s3_path_prefix: 'imgtag/',
  image_url_priority: 'auto'
})

// 存储状态
const status = ref({})
const s3Enabled = computed(() => s3Config.s3_enabled)

// 文件列表
const files = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const filter = ref('all')
const selectedIds = ref([])

onMounted(async () => {
  await fetchConfig()
  await fetchStatus()
  await fetchFiles()
})

const fetchConfig = async () => {
  try {
    const configs = await getAllConfigs()
    Object.keys(s3Config).forEach(key => {
      if (configs[key] !== undefined) {
        if (key === 's3_enabled') {
          s3Config[key] = configs[key] === 'true'
        } else {
          s3Config[key] = configs[key]
        }
      }
    })
  } catch (e) {
    console.error('获取配置失败:', e)
  }
}

const fetchStatus = async () => {
  try {
    status.value = await getStorageStatus()
  } catch (e) {
    console.error('获取存储状态失败:', e)
  }
}

const fetchFiles = async () => {
  loading.value = true
  try {
    const result = await getStorageFiles({
      filter: filter.value,
      page: currentPage.value,
      page_size: pageSize.value
    })
    files.value = result.files
    total.value = result.total
  } catch (e) {
    console.error('获取文件列表失败:', e)
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await updateConfigs({
      ...s3Config,
      s3_enabled: s3Config.s3_enabled ? 'true' : 'false'
    })
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + e.message)
  } finally {
    saving.value = false
  }
}

const testConnection = async () => {
  testing.value = true
  try {
    const result = await testS3Connection()
    if (result.success) {
      ElMessage.success(`连接成功！存储桶: ${result.bucket}, 对象数: ${result.object_count}`)
    } else {
      ElMessage.error('连接失败: ' + result.message)
    }
  } catch (e) {
    ElMessage.error('测试失败: ' + e.message)
  } finally {
    testing.value = false
  }
}

const handleSelectionChange = (selection) => {
  selectedIds.value = selection.map(item => item.id)
}

const syncSingleToS3 = async (id) => {
  syncing.value = true
  try {
    const result = await syncToS3([id])
    if (result.success > 0) {
      ElMessage.success('同步成功')
      await fetchFiles()
      await fetchStatus()
    } else {
      ElMessage.error('同步失败: ' + (result.errors[0] || '未知错误'))
    }
  } catch (e) {
    ElMessage.error('同步失败: ' + e.message)
  } finally {
    syncing.value = false
  }
}

const syncSingleToLocal = async (id) => {
  syncing.value = true
  try {
    const result = await syncToLocal([id])
    if (result.success > 0) {
      ElMessage.success('同步成功')
      await fetchFiles()
      await fetchStatus()
    } else {
      ElMessage.error('同步失败: ' + (result.errors[0] || '未知错误'))
    }
  } catch (e) {
    ElMessage.error('同步失败: ' + e.message)
  } finally {
    syncing.value = false
  }
}

const batchSyncToS3 = async () => {
  syncing.value = true
  try {
    const result = await syncToS3(selectedIds.value)
    ElMessage.success(`同步完成: 成功 ${result.success}, 失败 ${result.failed}`)
    await fetchFiles()
    await fetchStatus()
    selectedIds.value = []
  } catch (e) {
    ElMessage.error('批量同步失败: ' + e.message)
  } finally {
    syncing.value = false
  }
}

const batchSyncToLocal = async () => {
  syncing.value = true
  try {
    const result = await syncToLocal(selectedIds.value)
    ElMessage.success(`同步完成: 成功 ${result.success}, 失败 ${result.failed}`)
    await fetchFiles()
    await fetchStatus()
    selectedIds.value = []
  } catch (e) {
    ElMessage.error('批量同步失败: ' + e.message)
  } finally {
    syncing.value = false
  }
}
</script>

<style scoped>
.storage-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
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
  color: var(--text-secondary);
  font-size: 14px;
  margin: 0;
}

.tab-content {
  padding: 16px 0;
}

.config-form {
  max-width: 600px;
}

.field-tip {
  margin: 4px 0 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color-light);
  border-radius: var(--radius-lg);
  padding: 20px;
  text-align: center;
}

.stat-card.local { border-left: 3px solid #22c55e; }
.stat-card.s3 { border-left: 3px solid #3b82f6; }
.stat-card.synced { border-left: 3px solid #8b5cf6; }

.stat-value {
  display: block;
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.toolbar-right {
  display: flex;
  gap: 12px;
}

.filename {
  font-family: monospace;
  font-size: 13px;
}

.synced-text {
  color: var(--text-secondary);
  font-size: 12px;
}

.pagination-wrapper {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: var(--bg-secondary);
}
</style>
