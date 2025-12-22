<template>
  <div class="settings-page">
    <el-tabs v-model="activeTab" class="settings-tabs">
      <!-- 视觉模型配置 Tab -->
      <el-tab-pane label="视觉模型" name="models">
        <div class="tab-content">
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
                <div style="display: flex; gap: 8px; width: 100%;">
                  <el-select 
                    v-model="configForm.vision_model" 
                    placeholder="请选择模型"
                    style="flex: 1;"
                    filterable
                    allow-create
                    :loading="loadingModels"
                  >
                    <el-option 
                      v-for="model in availableModels" 
                      :key="model" 
                      :label="model" 
                      :value="model" 
                    />
                  </el-select>
                  <el-button @click="fetchModels" :loading="loadingModels" :icon="Refresh">
                    刷新
                  </el-button>
                </div>
                <div class="form-hint" v-if="modelsError">
                  <span style="color: var(--el-color-warning);">{{ modelsError }}</span>
                </div>
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
      </el-tab-pane>
      
      <!-- 队列配置 Tab -->
      <el-tab-pane label="队列配置" name="queue">
        <div class="tab-content">
          <div class="form-section">
            <h3>
              <el-icon><List /></el-icon>
              任务队列设置
            </h3>
            <el-form :model="queueConfigForm" label-width="140px">
              <el-form-item label="最大并发数">
                <el-input-number 
                  v-model.number="queueConfigForm.queue_max_workers" 
                  :min="1" 
                  :max="10"
                  :step="1"
                />
                <div class="form-hint">同时处理的任务数量，建议根据服务器性能设置</div>
              </el-form-item>
              <el-form-item label="任务间隔(秒)">
                <el-input-number 
                  v-model.number="queueConfigForm.queue_batch_interval" 
                  :min="0" 
                  :max="60"
                  :step="0.5"
                  :precision="1"
                />
                <div class="form-hint">每个任务完成后的等待时间，可以降低 API 调用频率</div>
              </el-form-item>
            </el-form>
            <div class="form-actions">
              <el-button type="primary" :loading="savingQueue" @click="saveQueueConfig" round>
                <el-icon><Check /></el-icon>
                保存队列配置
              </el-button>
            </div>
          </div>
        </div>
      </el-tab-pane>
      
      <!-- 向量管理 Tab -->
      <el-tab-pane label="向量管理" name="vectors">
        <div class="tab-content">
          <!-- 嵌入模型配置 -->
          <el-form :model="configForm" label-width="120px" class="config-form">
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
              
              <div class="form-actions" style="margin-top: 16px;">
                <el-button type="primary" :loading="saving" @click="saveConfig" round>
                  <el-icon><Check /></el-icon>
                  保存嵌入配置
                </el-button>
              </div>
            </div>
          </el-form>
          
          <el-divider />
          
          <!-- 向量状态信息 -->
          <div class="form-section">
            <h3>
              <el-icon><Histogram /></el-icon>
              向量数据
            </h3>
            <div class="vector-info">
              <div class="info-row">
                <span class="label">当前模式:</span>
                <span class="value">{{ vectorStatus?.embedding_mode === 'local' ? '本地模型' : '在线 API' }}</span>
              </div>
              <div class="info-row">
                <span class="label">当前模型:</span>
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
      </el-tab-pane>
      
      <!-- 外部 API Tab -->
      <el-tab-pane label="外部API" name="api">
        <div class="tab-content">
          <el-form :model="apiConfigForm" label-width="120px" class="config-form">
            <div class="form-section">
              <h3>
                <el-icon><Link /></el-icon>
                外部 API 配置
              </h3>
              <el-form-item label="Base URL">
                <el-input 
                  v-model="apiConfigForm.base_url" 
                  placeholder="http://example.com"
                />
                <div class="form-hint">
                  外部 API 返回的图片 URL 将拼接此地址，例如：http://example.com/uploads/xxx.jpg
                </div>
              </el-form-item>
              <el-form-item label="API 密钥">
                <el-input 
                  v-model="apiConfigForm.external_api_key" 
                  placeholder="留空则不验证"
                  show-password
                  type="password"
                />
                <div class="form-hint">
                  外部调用需在 Header (X-API-Key) 或参数 (api_key) 中传入此密钥
                </div>
              </el-form-item>
            </div>
            
            <div class="form-actions">
              <el-button type="primary" :loading="savingApiConfig" @click="saveApiConfig" round>
                <el-icon><Check /></el-icon>
                保存外部 API 配置
              </el-button>
            </div>
          </el-form>
        </div>
      </el-tab-pane>
      
      <!-- 数据备份 Tab -->
      <el-tab-pane label="数据备份" name="backup">
        <div class="tab-content">
          <p class="card-description">导出和导入数据库记录（图片元数据、标签、收藏夹、配置）</p>
          
          <div class="backup-section">
            <h3>导出数据</h3>
            <p style="color: var(--text-secondary); margin-bottom: 16px;">
              导出所有图片记录、标签、收藏夹和配置到 JSON 文件（不含图片文件和向量数据）
            </p>
            <el-button type="primary" round @click="handleExport" :loading="exporting">
              <el-icon><Download /></el-icon>
              导出数据库
            </el-button>
          </div>
          
          <el-divider />
          
          <div class="backup-section">
            <h3>导入数据</h3>
            <p style="color: var(--text-secondary); margin-bottom: 16px;">
              从导出的 JSON 文件恢复数据。已存在的记录会被更新或跳过
            </p>
            <el-upload
              ref="importUpload"
              :auto-upload="false"
              :show-file-list="false"
              accept=".json"
              :on-change="handleImportSelect"
            >
              <el-button round :loading="importing">
                <el-icon><Upload /></el-icon>
                选择并导入
              </el-button>
            </el-upload>
          </div>
        </div>
      </el-tab-pane>
      
      <!-- 重复检测 Tab -->
      <el-tab-pane label="重复检测" name="duplicates">
        <div class="tab-content">
          <p class="card-description">检测和管理重复的图片（基于文件 MD5 哈希）</p>
          
          <div class="duplicate-stats" v-if="duplicateInfo">
            <div class="info-row">
              <span class="label">重复组数:</span>
              <span class="value">{{ duplicateInfo.total_groups }}</span>
            </div>
            <div class="info-row">
              <span class="label">可删除数量:</span>
              <span class="value text-warning">{{ duplicateInfo.total_duplicates }}</span>
            </div>
            <div class="info-row">
              <span class="label">未计算哈希:</span>
              <span class="value">{{ duplicateInfo.images_without_hash }}</span>
            </div>
          </div>
          
          <div class="duplicate-actions" style="margin: 20px 0; display: flex; gap: 12px;">
            <el-button type="primary" round @click="scanDuplicates" :loading="scanningDuplicates">
              <el-icon><Search /></el-icon>
              扫描重复
            </el-button>
            <el-button round @click="calcHashes" :loading="calculatingHashes" v-if="duplicateInfo?.images_without_hash > 0">
              <el-icon><Refresh /></el-icon>
              计算缺失哈希 ({{ duplicateInfo.images_without_hash }})
            </el-button>
          </div>
          
          <!-- 重复组列表 -->
          <div v-if="duplicateGroups.length > 0" class="duplicate-groups">
            <div v-for="group in duplicateGroups" :key="group.file_hash" class="duplicate-group">
              <div class="group-header">
                <span>哈希: {{ group.file_hash.slice(0, 8) }}...</span>
                <el-tag type="warning" size="small">{{ group.count }} 张重复</el-tag>
              </div>
              <div class="group-images">
                <div v-for="img in group.images" :key="img.id" class="dup-image-item">
                  <span class="img-id">#{{ img.id }}</span>
                  <span class="img-url" :title="img.image_url">{{ img.image_url.split('/').pop() }}</span>
                  <el-button size="small" type="danger" plain @click="handleDeleteImage(img.id)">删除</el-button>
                </div>
              </div>
            </div>
          </div>
          
          <el-empty v-else-if="!scanningDuplicates && duplicateInfo" description="没有重复的图片" />
        </div>
      </el-tab-pane>
      
      <!-- 用户管理 Tab -->
      <el-tab-pane label="用户管理" name="users">
        <div class="tab-content">
          <div class="user-actions">
            <el-button type="primary" round @click="showCreateUserDialog = true">
              <el-icon><Plus /></el-icon>
              创建用户
            </el-button>
            <el-button round @click="fetchUsers">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
          
          <el-table :data="users" style="width: 100%" v-loading="loadingUsers">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="username" label="用户名" width="120" />
            <el-table-column prop="email" label="邮箱" />
            <el-table-column prop="role" label="角色" width="100">
              <template #default="{ row }">
                <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
                  {{ row.role === 'admin' ? '管理员' : '用户' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="is_active" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.is_active ? 'success' : 'warning'" size="small">
                  {{ row.is_active ? '正常' : '禁用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="260">
              <template #default="{ row }">
                <el-button 
                  size="small" 
                  @click="openChangePasswordDialog(row)"
                >
                  改密
                </el-button>
                <el-button 
                  size="small" 
                  :type="row.is_active ? 'warning' : 'success'"
                  @click="toggleUserStatus(row)"
                  :disabled="row.role === 'admin' && row.username === 'admin'"
                >
                  {{ row.is_active ? '禁用' : '启用' }}
                </el-button>
                <el-popconfirm
                  title="确定删除此用户？"
                  @confirm="handleDeleteUser(row.id)"
                >
                  <template #reference>
                    <el-button 
                      size="small" 
                      type="danger"
                      :disabled="row.role === 'admin' && row.username === 'admin'"
                    >
                      删除
                    </el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
    
    <!-- 创建用户弹窗 -->
    <el-dialog v-model="showCreateUserDialog" title="创建用户" width="400px">
      <el-form :model="newUserForm" label-width="80px">
        <el-form-item label="用户名" required>
          <el-input v-model="newUserForm.username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="newUserForm.email" placeholder="可选" />
        </el-form-item>
        <el-form-item label="密码" required>
          <el-input v-model="newUserForm.password" type="password" placeholder="至少6位" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateUserDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreateUser" :loading="creatingUser">创建</el-button>
      </template>
    </el-dialog>
    
    <!-- 修改密码弹窗 -->
    <el-dialog v-model="showPasswordDialog" title="修改密码" width="400px">
      <p style="margin-bottom: 16px; color: var(--text-secondary);">
        正在修改用户 <strong>{{ selectedUserForPassword?.username }}</strong> 的密码
      </p>
      <el-form :model="passwordForm" label-width="80px">
        <el-form-item label="新密码" required>
          <el-input v-model="passwordForm.newPassword" type="password" placeholder="至少6位" show-password />
        </el-form-item>
        <el-form-item label="确认密码" required>
          <el-input v-model="passwordForm.confirmPassword" type="password" placeholder="再次输入" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showPasswordDialog = false">取消</el-button>
        <el-button type="primary" @click="handleChangePassword" :loading="changingPassword">确定</el-button>
      </template>
    </el-dialog>

    <TagManager v-model="showTagManager" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, Download, Upload, Search } from '@element-plus/icons-vue'
import { 
  getAllConfigs, 
  updateConfigs, 
  healthCheck, 
  getVectorStatus,
  startRebuildVectors,
  getRebuildStatus,
  clearVectors,
  resizeVectorTable,
  getUsers,
  createUser,
  updateUser as updateUserApi,
  deleteUser as deleteUserApi,
  changeUserPassword,
  exportDatabase,
  importDatabase,
  getAvailableModels,
  getDuplicates,
  calculateHashes,
  deleteImage,
  installLocalDeps,
  getInstallStatus,
  checkLocalDeps
} from '@/api'
import TagManager from '@/components/TagManager.vue'

const activeTab = ref('models')
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

// 用户管理
const users = ref([])
const loadingUsers = ref(false)
const showCreateUserDialog = ref(false)
const creatingUser = ref(false)
const newUserForm = reactive({
  username: '',
  email: '',
  password: ''
})

// 修改密码
const showPasswordDialog = ref(false)
const selectedUserForPassword = ref(null)
const changingPassword = ref(false)
const passwordForm = reactive({
  newPassword: '',
  confirmPassword: ''
})

// 数据备份
const exporting = ref(false)
const importing = ref(false)

// 模型列表
const availableModels = ref([])
const loadingModels = ref(false)
const modelsError = ref('')

// 重复检测
const duplicateInfo = ref(null)
const duplicateGroups = ref([])
const scanningDuplicates = ref(false)
const calculatingHashes = ref(false)

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

// 队列配置
const queueConfigForm = reactive({
  queue_max_workers: 2,
  queue_batch_interval: 1
})
const savingQueue = ref(false)

// 外部 API 配置
const apiConfigForm = reactive({
  base_url: '',
  external_api_key: ''
})
const savingApiConfig = ref(false)

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
    // 加载外部 API 配置
    if (data.base_url !== undefined) apiConfigForm.base_url = data.base_url
    if (data.external_api_key !== undefined) apiConfigForm.external_api_key = data.external_api_key
    
    // 加载队列配置
    if (data.queue_max_workers !== undefined) queueConfigForm.queue_max_workers = parseInt(data.queue_max_workers) || 2
    if (data.queue_batch_interval !== undefined) queueConfigForm.queue_batch_interval = parseFloat(data.queue_batch_interval) || 1
    
    originalConfig.value = { ...configForm }
    
    // 如果有 API 配置，尝试获取模型列表
    if (data.vision_api_base_url && data.vision_api_key) {
      fetchModels()
    }
  } catch (e) {
    ElMessage.error('获取配置失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

const fetchModels = async () => {
  loadingModels.value = true
  modelsError.value = ''
  try {
    const result = await getAvailableModels()
    if (result.error) {
      modelsError.value = result.error
      availableModels.value = []
    } else {
      availableModels.value = result.models || []
    }
  } catch (e) {
    modelsError.value = e.message
    availableModels.value = []
  } finally {
    loadingModels.value = false
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
    
    // 如果选择了本地嵌入模式，自动安装依赖
    if (configForm.embedding_mode === 'local') {
      await tryInstallLocalDeps()
    }
  } catch (e) {
    ElMessage.error('保存配置失败: ' + e.message)
  } finally {
    saving.value = false
  }
}

// 尝试安装本地嵌入模型依赖
const tryInstallLocalDeps = async () => {
  try {
    // 先检查是否已安装
    const checkResult = await checkLocalDeps()
    if (checkResult.installed) {
      return // 已安装，无需操作
    }
    
    // 触发安装
    const result = await installLocalDeps()
    if (result.status === 'started') {
      ElMessage.info('正在后台安装本地嵌入模型依赖（约 700MB），请稍候...')
      // 启动轮询检查安装状态
      pollInstallStatus()
    } else if (result.status === 'already_installed') {
      // 已安装
    } else if (result.status === 'installing') {
      ElMessage.info('依赖正在安装中，请稍候...')
    }
  } catch (e) {
    console.error('检查/安装本地依赖失败:', e)
  }
}

// 轮询安装状态
const pollInstallStatus = () => {
  const checkInterval = setInterval(async () => {
    try {
      const status = await getInstallStatus()
      if (!status.is_running) {
        clearInterval(checkInterval)
        if (status.success) {
          ElMessage.success('本地嵌入模型依赖安装成功！')
        } else if (status.success === false) {
          ElMessage.error('依赖安装失败：' + status.message)
        }
      }
    } catch (e) {
      clearInterval(checkInterval)
    }
  }, 3000) // 每 3 秒检查一次
}

// 保存队列配置
const saveQueueConfig = async () => {
  savingQueue.value = true
  try {
    await updateConfigs({
      queue_max_workers: String(queueConfigForm.queue_max_workers),
      queue_batch_interval: String(queueConfigForm.queue_batch_interval)
    })
    ElMessage.success('队列配置保存成功')
  } catch (e) {
    ElMessage.error('保存失败: ' + e.message)
  } finally {
    savingQueue.value = false
  }
}

// 保存外部 API 配置
const saveApiConfig = async () => {
  savingApiConfig.value = true
  try {
    await updateConfigs(apiConfigForm)
    ElMessage.success('外部 API 配置保存成功')
  } catch (e) {
    ElMessage.error('保存失败: ' + e.message)
  } finally {
    savingApiConfig.value = false
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

// 用户管理函数
const fetchUsers = async () => {
  loadingUsers.value = true
  try {
    const data = await getUsers()
    users.value = data.users || []
  } catch (e) {
    console.error('获取用户列表失败:', e)
  } finally {
    loadingUsers.value = false
  }
}

const toggleUserStatus = async (user) => {
  try {
    await updateUserApi(user.id, { is_active: !user.is_active })
    ElMessage.success(user.is_active ? '已禁用' : '已启用')
    fetchUsers()
  } catch (e) {
    ElMessage.error('操作失败: ' + e.message)
  }
}

const handleDeleteUser = async (userId) => {
  try {
    await deleteUserApi(userId)
    ElMessage.success('删除成功')
    users.value = users.value.filter(u => u.id !== userId)
  } catch (e) {
    ElMessage.error('删除失败: ' + e.message)
  }
}

const handleCreateUser = async () => {
  if (!newUserForm.username || !newUserForm.password) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  if (newUserForm.password.length < 6) {
    ElMessage.warning('密码至少6位')
    return
  }
  
  creatingUser.value = true
  try {
    await createUser(newUserForm.username, newUserForm.password, newUserForm.email || null)
    ElMessage.success('创建成功')
    showCreateUserDialog.value = false
    newUserForm.username = ''
    newUserForm.email = ''
    newUserForm.password = ''
    fetchUsers()
  } catch (e) {
    ElMessage.error('创建失败: ' + e.message)
  } finally {
    creatingUser.value = false
  }
}

const openChangePasswordDialog = (user) => {
  selectedUserForPassword.value = user
  passwordForm.newPassword = ''
  passwordForm.confirmPassword = ''
  showPasswordDialog.value = true
}

const handleChangePassword = async () => {
  if (!passwordForm.newPassword || !passwordForm.confirmPassword) {
    ElMessage.warning('请填写密码')
    return
  }
  if (passwordForm.newPassword.length < 6) {
    ElMessage.warning('密码至少6位')
    return
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  
  changingPassword.value = true
  try {
    await changeUserPassword(selectedUserForPassword.value.id, passwordForm.newPassword)
    ElMessage.success('密码修改成功')
    showPasswordDialog.value = false
  } catch (e) {
    ElMessage.error('修改失败: ' + e.message)
  } finally {
    changingPassword.value = false
  }
}

// 导出数据
const handleExport = async () => {
  exporting.value = true
  try {
    const response = await exportDatabase()
    // 由于使用了 blob 响应，需要手动处理下载
    const blob = new Blob([JSON.stringify(response, null, 2)], { type: 'application/json' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `imgtag_backup_${new Date().toISOString().slice(0,10)}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    ElMessage.success(`导出成功: ${response.stats?.image_count || 0} 张图片`)
  } catch (e) {
    ElMessage.error('导出失败: ' + e.message)
  } finally {
    exporting.value = false
  }
}

// 导入数据
const handleImportSelect = async (uploadFile) => {
  if (!uploadFile.raw) return
  
  importing.value = true
  try {
    const result = await importDatabase(uploadFile.raw)
    if (result.error) {
      ElMessage.error('导入失败: ' + result.error)
    } else {
      ElMessage.success(`导入完成: ${result.stats.images_imported} 张图片, ${result.stats.tags_imported} 个标签`)
      if (result.stats.errors?.length > 0) {
        console.warn('导入错误:', result.stats.errors)
      }
    }
  } catch (e) {
    ElMessage.error('导入失败: ' + e.message)
  } finally {
    importing.value = false
  }
}

// 重复检测功能
const scanDuplicates = async () => {
  scanningDuplicates.value = true
  try {
    const result = await getDuplicates()
    if (result.error) {
      ElMessage.error(result.error)
    } else {
      duplicateInfo.value = result
      duplicateGroups.value = result.duplicate_groups || []
      if (result.total_duplicates > 0) {
        ElMessage.warning(`发现 ${result.total_duplicates} 张重复图片`)
      } else {
        ElMessage.success('没有发现重复图片')
      }
    }
  } catch (e) {
    ElMessage.error('扫描失败: ' + e.message)
  } finally {
    scanningDuplicates.value = false
  }
}

const calcHashes = async () => {
  calculatingHashes.value = true
  try {
    const result = await calculateHashes(100)
    if (result.error) {
      ElMessage.error(result.error)
    } else {
      ElMessage.success(result.message)
      // 重新扫描更新结果
      await scanDuplicates()
    }
  } catch (e) {
    ElMessage.error('计算失败: ' + e.message)
  } finally {
    calculatingHashes.value = false
  }
}

const handleDeleteImage = async (imageId) => {
  try {
    await deleteImage(imageId)
    ElMessage.success('删除成功')
    // 重新扫描
    await scanDuplicates()
  } catch (e) {
    ElMessage.error('删除失败: ' + e.message)
  }
}

onMounted(() => {
  fetchConfig()
  checkHealth()
  fetchVectorStatus()
  fetchUsers()
})

onUnmounted(() => {
  if (statusTimer) {
    clearInterval(statusTimer)
  }
})
</script>

<style scoped>
.settings-page {
  max-width: 1200px;
  width: 100%;
}

/* Tabs 样式 */
.settings-tabs {
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  border: 1px solid var(--border-color-light);
  padding: 24px;
  box-shadow: var(--shadow-sm);
}

.user-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.backup-section {
  margin-bottom: 24px;
}

.backup-section h3 {
  margin-bottom: 8px;
}

/* 重复检测样式 */
.duplicate-stats {
  background: var(--card-bg);
  border-radius: var(--radius);
  padding: 16px;
  margin-bottom: 16px;
}

.duplicate-groups {
  max-height: 400px;
  overflow-y: auto;
}

.duplicate-group {
  background: var(--card-bg);
  border-radius: var(--radius);
  padding: 12px;
  margin-bottom: 12px;
}

.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.group-images {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dup-image-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 8px;
  background: rgba(255,255,255,0.03);
  border-radius: 4px;
}

.dup-image-item .img-id {
  color: var(--text-muted);
  font-size: 12px;
  min-width: 40px;
}

.dup-image-item .img-url {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.text-warning {
  color: var(--el-color-warning);
}

:deep(.el-tabs__header) {
  margin-bottom: 24px;
  border-bottom: 1px solid var(--border-color-light);
}

:deep(.el-tabs__nav-wrap::after) {
  display: none;
}

:deep(.el-tabs__item) {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  padding: 0 20px;
  height: 44px;
  line-height: 44px;
}

:deep(.el-tabs__item.is-active) {
  color: var(--primary-color);
}

:deep(.el-tabs__active-bar) {
  background-color: var(--primary-color);
  height: 3px;
  border-radius: 2px;
}

.tab-content {
  padding: 8px 0;
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
  margin-bottom: 32px;
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
  margin-top: 24px;
  border-top: 1px solid var(--border-color-light);
}

/* 向量管理 */
.vector-info {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
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
@media (max-width: 768px) {
  .settings-tabs {
    padding: 16px;
  }
  
  :deep(.el-tabs__item) {
    padding: 0 12px;
    font-size: 13px;
  }
  
  .form-section {
    padding: 16px;
  }
  
  .vector-info {
    grid-template-columns: 1fr;
  }
  
  .vector-actions,
  .form-actions {
    flex-direction: column;
  }
  
  .vector-actions .el-button,
  .form-actions .el-button {
    width: 100%;
  }
  
  .health-status {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
