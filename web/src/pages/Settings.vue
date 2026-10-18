<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted, watch } from 'vue'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import ImageDetailModal from '@/components/ImageDetailModal.vue'
import ModelTestButton from '@/components/ModelTestButton.vue'
import VectorAnomaliesPanel from '@/components/VectorAnomaliesPanel.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError, notifySuccess } from '@/utils/notify'
import { usePromptDefaults } from '@/composables/usePromptDefaults'
import { 
  Settings,
  Save,
  Loader2,
  Eye,
  Brain,
  Cloud,
  X,
  ChevronRight,
  RefreshCw,
  Wrench,
  Database,
  FolderSync,
  AlertTriangle,
  CheckCircle,
  RotateCw,
  ChevronDown,
  Users,
  UserPlus,
  Shield,
  Ban,
  Key,
  HardDrive,
  ListChecks
} from 'lucide-vue-next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select'

const categories = [
  { key: 'vision', label: '视觉模型', icon: Eye, description: 'AI 图片分析和标签提取', color: 'text-violet-500 bg-violet-500/10' },
  { key: 'embedding', label: '向量嵌入', icon: Brain, description: '语义搜索向量化配置', color: 'text-blue-500 bg-blue-500/10' },
  { key: 'users', label: '用户管理', icon: Users, description: '用户账户与权限管理', color: 'text-emerald-500 bg-emerald-500/10' },
  { key: 'maintenance', label: '系统维护', icon: Wrench, description: '系统设置与存储清理', color: 'text-rose-500 bg-rose-500/10' },
]

const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()

// 配置项定义 - 支持 showWhen 条件
interface ConfigDef {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'boolean' | 'select' | 'textarea' | 'combobox'
  description?: string
  placeholder?: string
  options?: { value: string; label: string }[]
  showWhen?: { key: string; value: string }
  min?: number
  max?: number
  step?: number
}

const configDefinitions: Record<string, ConfigDef[]> = {
  vision: [
    { key: 'vision_api_base_url', label: 'API 地址', type: 'text', description: 'OpenAI 兼容端点', placeholder: 'https://api.openai.com/v1' },
    { key: 'vision_api_key', label: 'API 密钥', type: 'password' },
    { key: 'vision_model', label: '模型名称', type: 'combobox', description: '可选择或手动输入' },
    { key: 'vision_prompt', label: '全局分析提示词（含主体融合规则）', type: 'textarea', description: '统一管理通用分析和主体资料使用规则；description 的具体结构优先遵守标签分类提示词。表情包四段格式在标签管理的表情包分类中维护。' },
    { key: 'vision_allowed_extensions', label: '允许的扩展名', type: 'text' },
    { key: 'vision_convert_gif', label: 'GIF 转静态图', type: 'boolean' },
    { key: 'subject_extraction_max_images', label: '主体提炼图片上限', type: 'number', min: 1, max: 3, step: 1, description: '默认3张，可设1–3张' },
    { key: 'vision_max_image_size', label: '压缩阈值 (KB)', type: 'number' },
    { key: 'queue_max_workers', label: '最大并发数', type: 'number', description: '同时分析多少张图片' },
    { key: 'queue_batch_interval', label: '任务间隔 (秒)', type: 'number', description: '每张图片分析后的等待时间' },
  ],
  embedding: [
    { key: 'embedding_mode', label: '嵌入模式', type: 'select', options: [
      { value: 'local', label: '🖥️ 本地模型' },
      { value: 'api', label: '☁️ API 调用' },
    ], description: '本地速度快，API 无需下载' },
    // 本地模式配置
    { key: 'embedding_local_model', label: '本地模型', type: 'text', description: 'HuggingFace 模型名称', showWhen: { key: 'embedding_mode', value: 'local' } },
    { key: 'hf_endpoint', label: 'HF 镜像地址', type: 'text', showWhen: { key: 'embedding_mode', value: 'local' } },
    // API 模式配置
    { key: 'embedding_api_base_url', label: 'API 地址', type: 'text', showWhen: { key: 'embedding_mode', value: 'api' }, placeholder: 'https://api.siliconflow.cn/v1' },
    { key: 'embedding_api_key', label: 'API 密钥', type: 'password', showWhen: { key: 'embedding_mode', value: 'api' } },
    { key: 'embedding_model', label: 'API 模型', type: 'text', showWhen: { key: 'embedding_mode', value: 'api' } },
    { key: 'embedding_dimensions', label: '向量维度', type: 'number' },
  ],
  maintenance: [
    { key: 'max_upload_size', label: '最大上传 (MB)', type: 'number', description: '单张图片上传大小限制' },
    { key: 'allow_register', label: '允许注册', type: 'boolean', description: '关闭后禁止新用户注册' },
  ],
}

const activeCategory = ref<string | null>(null)
const loading = ref(false)
const saving = ref(false)
const configs = ref<Record<string, string>>({})
const originalConfigs = ref<Record<string, string>>({})
const { data: promptDefaults, isError: defaultsError, refetch: reloadDefaults } = usePromptDefaults(computed(() => activeCategory.value === 'vision'))
function resetVisionPrompt() {
  if (!promptDefaults.value || saving.value) return
  configs.value.vision_prompt = promptDefaults.value.vision_prompt
  notifySuccess('已填入默认提示词，保存后生效')
}


type ModelTestKind = 'vision' | 'embedding'
const modelTesting = ref<Record<ModelTestKind, boolean>>({ vision: false, embedding: false })
const modelTestResults = ref<Partial<Record<ModelTestKind, { success: boolean; message: string }>>>({})

function modelRequestKey(kind: ModelTestKind): string | null {
  const key = `${kind}_api_key`
  const current = configs.value[key]
  // 未修改的密钥只传空标记，由后端读取原始值；显式清空则传空字符串。
  return current === originalConfigs.value[key] || current === '******' ? null : current || ''
}

function modelTestConfig(kind: ModelTestKind) {
  const mode = kind === 'embedding' ? configs.value['embedding_mode'] || 'local' : 'api'
  return {
    kind,
    mode,
    model: String(configs.value[mode === 'local' ? 'embedding_local_model' : `${kind}_model`] || ''),
    api_base_url: String(configs.value[`${kind}_api_base_url`] || ''),
    api_key: modelRequestKey(kind),
    ...(kind === 'embedding' ? {
      dimensions: targetDimensions.value,
      hf_endpoint: configs.value['hf_endpoint'] || 'https://hf-mirror.com',
    } : {}),
  }
}

async function testModel(kind: ModelTestKind) {
  if (modelTesting.value[kind]) return
  const payload = modelTestConfig(kind)
  const signature = JSON.stringify(payload)
  modelTesting.value[kind] = true
  delete modelTestResults.value[kind]
  try {
    const { data } = await apiClient.post<{ message: string; elapsed_ms: number }>(
      '/config/test-model', payload, { timeout: payload.mode === 'local' ? 900000 : 90000 },
    )
    if (signature === JSON.stringify(modelTestConfig(kind))) {
      modelTestResults.value[kind] = { success: true, message: `${data.message}（${data.elapsed_ms} ms）` }
    }
  } catch (error) {
    if (signature === JSON.stringify(modelTestConfig(kind))) {
      modelTestResults.value[kind] = { success: false, message: `测试失败：${getErrorMessage(error)}` }
    }
  } finally {
    modelTesting.value[kind] = false
  }
}

// 模型列表（用于 combobox）
const availableModels = ref<string[]>([])
const modelsLoading = ref(false)
const modelsError = ref('')

async function fetchModels() {
  modelsLoading.value = true
  modelsError.value = ''
  
  // 使用表单中的值验证，通过后端代理请求避免 CORS 问题
  const apiBaseUrl = configs.value['vision_api_base_url']
  const apiKey = modelRequestKey('vision')
  
  if (!apiBaseUrl) {
    modelsError.value = '未配置 API 地址或密钥'
    modelsLoading.value = false
    return
  }
  
  try {
    // 通过后端代理请求，传入临时配置 (JSON body)
    const { data } = await apiClient.post('/system/models', {
      api_base_url: apiBaseUrl,
      api_key: apiKey
    })
    availableModels.value = data.models || []
    if (data.error) modelsError.value = data.error
  } catch (e: any) {
    modelsError.value = `获取模型列表失败：${getErrorMessage(e)}`
  } finally {
    modelsLoading.value = false
  }
}

const hasChanges = computed(() => {
  for (const key of Object.keys(configs.value)) {
    const current = configs.value[key]
    const original = originalConfigs.value[key]
    // 跳过未修改的密码（保持为 ******）
    if (current === original) continue
    if (current === '******') continue
    return true
  }
  return false
})

const activeCategoryInfo = computed(() => categories.find(c => c.key === activeCategory.value))

// 过滤当前分类的配置项（根据 showWhen 条件）
const visibleDefinitions = computed(() => {
  if (!activeCategory.value) return []
  const defs = configDefinitions[activeCategory.value] || []
  return defs.filter(def => {
    if (!def.showWhen) return true
    return configs.value[def.showWhen.key] === def.showWhen.value
  })
})

async function fetchConfigs() {
  loading.value = true
  try {
    const { data } = await apiClient.get('/config/')
    configs.value = { subject_extraction_max_images: '3', ...data }
    originalConfigs.value = { ...configs.value }
  } catch (e) {
    console.error('Failed to load configs', e)
  } finally {
    loading.value = false
  }
}

async function saveConfigs() {
  const limit = Number(configs.value.subject_extraction_max_images)
  if (!Number.isInteger(limit) || limit < 1 || limit > 3) {
    notifyError('主体提炼图片上限必须是1至3之间的整数')
    return
  }
  saving.value = true
  try {
    const changedConfigs: Record<string, string> = {}
    for (const key of Object.keys(configs.value)) {
      if (configs.value[key] !== originalConfigs.value[key]) {
        // Enforce string type for backend compatibility
        changedConfigs[key] = String(configs.value[key])
      }
    }
    if (Object.keys(changedConfigs).length === 0) {
      activeCategory.value = null
      return
    }

    await apiClient.put('/config/', { configs: changedConfigs })
    originalConfigs.value = { ...configs.value }
    // 如果不是 embedding 页面，或者是 embedding 但没有维度变更需要处理，则关闭
    // 实际上为了流畅体验，embedding 页面保存后最好不要关闭，方便用户点击“重建”
    if (activeCategory.value !== 'embedding') {
      activeCategory.value = null
    } else {
      notifySuccess('保存成功，请根据提示检查是否需要重建向量', { once: true })
      fetchVectorStatus() // 刷新状态以更新 dimensions_match
    }
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    saving.value = false
  }
}

async function closeDrawer() {
  if (hasChanges.value) {
    const confirmed = await confirm({
      title: '放弃更改',
      message: '有未保存的更改，确定关闭吗？',
      variant: 'warning',
      confirmText: '关闭',
    })
    if (!confirmed.confirmed) return
  }
  configs.value = { ...originalConfigs.value }
  activeCategory.value = null
}

// ========== 维护功能 ==========
interface DuplicateImage {
  id: number
  image_url: string
  file_path: string
  file_size: number
  width: number
  height: number
  created_at: string
}

interface DuplicateGroup {
  hash: string
  count: number
  images: DuplicateImage[]
}

interface DuplicatesResponse {
  duplicate_groups: DuplicateGroup[]
  total_groups: number
  total_duplicates: number
  images_without_hash: number
}

const duplicateGroups = ref<DuplicateGroup[]>([])
const totalGroups = ref(0)
const imagesWithoutHash = ref(0)
const scanning = ref(false)
const calculating = ref(false)
const deleting = ref<number | null>(null)
const previewImage = ref<DuplicateImage | null>(null)

function openImagePreview(img: DuplicateImage) {
  previewImage.value = img
}

function closeImagePreview() {
  previewImage.value = null
}

async function scanDuplicates() {
  scanning.value = true
  try {
    const { data } = await apiClient.get<DuplicatesResponse>('/system/duplicates')
    duplicateGroups.value = data.duplicate_groups || []
    totalGroups.value = data.total_groups || 0
    imagesWithoutHash.value = data.images_without_hash || 0
    notifySuccess(`扫描完成: 发现 ${data.total_groups} 组重复图片`, { once: true })
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    scanning.value = false
  }
}

async function calculateHashes() {
  calculating.value = true
  try {
    const { data } = await apiClient.post('/system/duplicates/calculate-hashes')
    notifySuccess(`计算完成: 处理了 ${data.processed || 0} 张图片`, { once: true })
    imagesWithoutHash.value = data.remaining || 0
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    calculating.value = false
  }
}

async function deleteImage(imageId: number) {
  const confirmed = await confirm({
    title: '删除图片',
    message: '确定删除这张图片？此操作不可恢复。',
    variant: 'danger',
    confirmText: '删除',
  })
  if (!confirmed.confirmed) return
  
  deleting.value = imageId
  try {
    await apiClient.delete(`/images/${imageId}`)
    // 从列表中移除
    for (const group of duplicateGroups.value) {
      const idx = group.images.findIndex(img => img.id === imageId)
      if (idx !== -1) {
        group.images.splice(idx, 1)
        group.count--
        if (group.count <= 1) {
          // 不再重复，移除该组
          const gIdx = duplicateGroups.value.indexOf(group)
          duplicateGroups.value.splice(gIdx, 1)
          totalGroups.value--
        }
        break
      }
    }
    notifySuccess('图片已删除', { once: true })
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    deleting.value = null
  }
}

function formatFileSize(mb: number): string {
  if (mb < 1) return (mb * 1024).toFixed(0) + ' KB'
  return mb.toFixed(2) + ' MB'
}

function formatDate(iso: string): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

// ========== 向量管理 ==========
interface RebuildStatus {
  is_running: boolean
  total: number
  processed: number
  succeeded: number
  skipped: number
  failed: number
  last_error: string
  message: string
}

interface VectorStatus {
  image_count: number
  embedding_mode: string
  embedding_model: string
  embedding_dimensions: number
  db_dimensions: number
  dimensions_match: boolean
  rebuild_status: RebuildStatus
}

const vectorStatus = ref<VectorStatus | null>(null)
const vectorLoading = ref(false)
const rebuilding = ref(false)
const resizing = ref(false)
const rebuildPollError = ref('')
const rebuildProgress = computed(() => {
  const status = vectorStatus.value?.rebuild_status
  if (!status?.total) return 0
  return Math.min(100, Math.max(0, status.processed / status.total * 100))
})

const localModelOptions = [
  { value: 'BAAI/bge-small-zh-v1.5', label: 'BAAI BGE Small (推荐, 512维)', dim: 512 },
  { value: 'BAAI/bge-base-zh-v1.5', label: 'BAAI BGE Base (高精度, 768维)', dim: 768 },
  { value: 'shibing624/text2vec-base-chinese', label: 'Text2Vec Base (旧版兼容, 768维)', dim: 768 },
]

// 计算当前表单选择对应的维度
const targetDimensions = computed(() => {
  if (configs.value['embedding_mode'] === 'api') {
    return parseInt(configs.value['embedding_dimensions'] || '1536')
  } else {
    const model = configs.value['embedding_local_model']
    const opt = localModelOptions.find(o => o.value === model)
    if (opt) return opt.dim
    // Fallback detection
    if (model?.includes('bge-base') || model?.includes('text2vec')) return 768
    if (model?.includes('large')) return 1024
    return 512
  }
})

// 是否需要重置维度 (当前 DB 维度 != 目标维度)
const dimensionsMismatch = computed(() => {
  if (!vectorStatus.value) return false
  return vectorStatus.value.db_dimensions !== targetDimensions.value
})

async function fetchVectorStatus() {
  vectorLoading.value = true
  try {
    const { data } = await apiClient.get<VectorStatus>('/vectors/status')
    vectorStatus.value = data
    rebuilding.value = data.rebuild_status?.is_running ?? false
    if (data.rebuild_status?.is_running) {
       rebuilding.value = true
       pollRebuildStatus()
    }
  } catch (e) {
    console.error(e)
  } finally {
    vectorLoading.value = false
  }
}

async function rebuildVectors() {
  const confirmed = await confirm({
    title: '重建向量',
    message: '确定要重建所有向量吗？这可能需要很长时间，期间搜索功能将受限。',
    variant: 'warning',
    confirmText: '开始重建',
  })
  if (!confirmed.confirmed) return
  
  rebuilding.value = true
  try {
    await apiClient.post('/vectors/rebuild')
    notifySuccess('重建任务已启动', { once: true })
    await fetchVectorStatus()
    pollRebuildStatus()
  } catch(e: any) {
    notifyError(getErrorMessage(e))
    rebuilding.value = false
  }
}

async function resizeVectorTable() {
  const confirmed = await confirm({
    title: '修改向量维度',
    message: '确定要修改数据库向量维度吗？这将清空现有索引，建议随后立即重建向量。',
    variant: 'danger',
    confirmText: '修改维度',
  })
  if (!confirmed.confirmed) return
  
  resizing.value = true
  try {
    const { data } = await apiClient.post('/vectors/resize-table')
    notifySuccess(data.message, { once: true })
    await fetchVectorStatus()
  } catch(e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    resizing.value = false
  }
}

let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollActive = false
let pollGeneration = 0

function stopRebuildPolling() {
  pollActive = false
  pollGeneration++
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

function pollRebuildStatus() {
  if (pollActive) return
  pollActive = true
  const generation = ++pollGeneration
  // 上一次请求完成后再安排下一次，避免慢请求重叠、旧响应覆盖新进度。
  async function poll() {
    try {
      const { data } = await apiClient.get<RebuildStatus>('/vectors/rebuild/status')
      if (generation !== pollGeneration) return
      rebuildPollError.value = ''
      if (vectorStatus.value) {
        vectorStatus.value.rebuild_status = data
      }
      if (!data.is_running) {
        stopRebuildPolling()
        rebuilding.value = false
        if (data.failed > 0 || data.last_error) {
          notifyError(data.message, { once: true })
        } else {
          notifySuccess(data.message || '向量重建完成', { once: true })
        }
        await fetchVectorStatus()
      } else {
        rebuilding.value = true
      }
    } catch {
      if (generation !== pollGeneration) return
      rebuildPollError.value = '进度刷新暂时失败，正在自动重试…'
    } finally {
      if (pollActive && generation === pollGeneration) pollTimer = setTimeout(poll, 2000)
    }
  }
  void poll()
}

onUnmounted(() => {
  stopRebuildPolling()
})

// ========== 用户管理 ==========
import { getAllPermissions, hasPermission, type PermissionType } from '@/constants/permissions'

interface UserItem {
  id: number
  username: string
  email: string | null
  role: 'admin' | 'user'
  is_active: boolean
  permissions: number
  created_at: string
}

// 获取当前登录用户 ID（用于保护自己不被修改）
import { useUserStore } from '@/stores'
const userStore = useUserStore()
const currentUserId = computed(() => userStore.user?.id)

const userList = ref<UserItem[]>([])
const usersLoading = ref(false)
const userActionLoading = ref<number | null>(null)

// 新建用户表单
const showCreateUser = ref(false)
const newUser = ref({ username: '', password: '', email: '', role: 'user' })
const creatingUser = ref(false)

// 修改密码
const showChangePassword = ref<number | null>(null)
const newPassword = ref('')
const changingPassword = ref(false)

// 权限编辑
const showPermissions = ref<number | null>(null)
const editingPermissions = ref<number>(0)
const savingPermissions = ref(false)

// 权限选项列表
const permissionOptions = getAllPermissions()

function openPermissionsDialog(user: UserItem) {
  showPermissions.value = user.id
  editingPermissions.value = user.permissions || 0
}

function togglePermission(perm: PermissionType) {
  if (hasPermission(editingPermissions.value, perm)) {
    editingPermissions.value &= ~perm
  } else {
    editingPermissions.value |= perm
  }
}

async function savePermissions() {
  if (!showPermissions.value) return
  savingPermissions.value = true
  try {
    await apiClient.put(`/auth/users/${showPermissions.value}`, null, {
      params: { permissions: editingPermissions.value }
    })
    const user = userList.value.find(u => u.id === showPermissions.value)
    if (user) user.permissions = editingPermissions.value
    notifySuccess('权限已更新', { once: true })
    showPermissions.value = null
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    savingPermissions.value = false
  }
}

async function fetchUsers() {
  usersLoading.value = true
  try {
    const { data } = await apiClient.get('/auth/users')
    userList.value = data.users || []
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    usersLoading.value = false
  }
}

async function toggleUserActive(user: UserItem) {
  userActionLoading.value = user.id
  try {
    await apiClient.put(`/auth/users/${user.id}`, null, { 
      params: { is_active: !user.is_active } 
    })
    user.is_active = !user.is_active
    notifySuccess(user.is_active ? '用户已启用' : '用户已禁用', { once: true })
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    userActionLoading.value = null
  }
}

async function changeUserRole(user: UserItem, newRole: 'admin' | 'user') {
  if (user.role === newRole) return
  userActionLoading.value = user.id
  try {
    await apiClient.put(`/auth/users/${user.id}`, null, { 
      params: { role: newRole } 
    })
    user.role = newRole
    notifySuccess('角色已更新', { once: true })
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    userActionLoading.value = null
  }
}

async function createUser() {
  if (!newUser.value.username || !newUser.value.password) {
    notifyError('用户名和密码不能为空', { once: true })
    return
  }
  creatingUser.value = true
  try {
    await apiClient.post('/auth/users', {
      username: newUser.value.username,
      password: newUser.value.password,
      email: newUser.value.email || undefined,
      role: newUser.value.role,
    })
    notifySuccess('用户创建成功', { once: true })
    showCreateUser.value = false
    newUser.value = { username: '', password: '', email: '', role: 'user' }
    await fetchUsers()
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    creatingUser.value = false
  }
}

async function changePassword(userId: number) {
  if (!newPassword.value || newPassword.value.length < 6) {
    notifyError('密码至少 6 位', { once: true })
    return
  }
  changingPassword.value = true
  try {
    await apiClient.put(`/auth/admin/users/${userId}/password`, null, {
      params: { new_password: newPassword.value }
    })
    notifySuccess('密码已修改', { once: true })
    showChangePassword.value = null
    newPassword.value = ''
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    changingPassword.value = false
  }
}

async function deleteUser(user: UserItem) {
  const confirmed = await confirm({
    title: '删除用户',
    message: `确定删除用户 "${user.username}"？此操作不可恢复。`,
    variant: 'danger',
    confirmText: '删除',
  })
  if (!confirmed.confirmed) return
  
  userActionLoading.value = user.id
  try {
    await apiClient.delete(`/auth/users/${user.id}`)
    userList.value = userList.value.filter(u => u.id !== user.id)
    notifySuccess('用户已删除', { once: true })
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    userActionLoading.value = null
  }
}

// 监听分类切换
watch(activeCategory, (newVal) => {
  if (newVal === 'embedding') {
    fetchVectorStatus()
  } else if (newVal === 'users') {
    fetchUsers()
  }
})

for (const kind of ['vision', 'embedding'] as const) {
  watch(() => JSON.stringify(modelTestConfig(kind)), () => { delete modelTestResults.value[kind] })
}

onMounted(() => fetchConfigs())
</script>

<template>
  <div class="p-6 lg:p-8">
    <!-- 标题区 -->
    <div class="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div>
        <h1 class="text-xl font-bold text-foreground flex items-center gap-2">
          <Settings class="w-5 h-5 text-primary" />系统设置
        </h1>
        <p class="text-sm text-muted-foreground mt-1">管理系统参数、模型配置与用户权限</p>
      </div>
    </div>

    <div class="max-w-6xl mx-auto">

      <!-- 加载 -->
      <div v-if="loading" class="flex items-center justify-center py-20">
        <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
      </div>

      <!-- 分类卡片网格 -->
      <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <button
          v-for="cat in categories"
          :key="cat.key"
          @click="activeCategory = cat.key"
          class="group p-5 text-left bg-card border border-border rounded-2xl hover:border-primary/50 hover:shadow-lg hover:shadow-primary/5 transition-all"
        >
          <div class="flex items-start gap-4">
            <div :class="['w-10 h-10 rounded-xl flex items-center justify-center', cat.color]">
              <component :is="cat.icon" class="w-5 h-5" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between">
                <h3 class="font-medium text-foreground">{{ cat.label }}</h3>
                <ChevronRight class="w-4 h-4 text-muted-foreground group-hover:text-foreground transition-colors" />
              </div>
              <p class="text-sm text-muted-foreground mt-1">{{ cat.description }}</p>
            </div>
          </div>
        </button>
      </div>
    </div>

    <!-- 右侧抽屉 -->
    <Teleport to="body">
      <Transition name="drawer">
        <div 
          v-if="activeCategory"
          class="fixed inset-0 z-50 flex justify-end"
        >
          <!-- 遮罩 -->
          <div class="absolute inset-0 bg-black/40" @click="closeDrawer" />
          
          <!-- 抽屉内容 -->
          <div class="relative w-full max-w-lg bg-card shadow-2xl flex flex-col">
            <!-- 头部 -->
            <div class="flex items-center justify-between p-6 border-b border-border">
              <div class="flex items-center gap-3">
                <div :class="['w-9 h-9 rounded-lg flex items-center justify-center', activeCategoryInfo?.color]">
                  <component :is="activeCategoryInfo?.icon" class="w-4 h-4" />
                </div>
                <div>
                  <h2 class="font-semibold text-foreground">{{ activeCategoryInfo?.label }}</h2>
                  <p class="text-xs text-muted-foreground">{{ activeCategoryInfo?.description }}</p>
                </div>
              </div>
              <button @click="closeDrawer" class="p-2 hover:bg-muted rounded-lg">
                <X class="w-5 h-5 text-muted-foreground" />
              </button>
            </div>

            <!-- 表单内容 -->
            <div class="flex-1 overflow-y-auto p-6 space-y-5">
              <!-- 维护分类：特殊面板 -->
              <template v-if="activeCategory === 'maintenance'">
                <VectorAnomaliesPanel />
                <!-- 重复文件检测 -->
                <div class="p-4 bg-muted/50 rounded-xl">
                  <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                      <FolderSync class="w-5 h-5 text-muted-foreground" />
                      <h3 class="font-medium text-foreground">重复文件检测</h3>
                    </div>
                    <Button 
                      variant="outline"
                      size="sm"
                      @click="scanDuplicates"
                      :disabled="scanning"
                    >
                      <Loader2 v-if="scanning" class="w-4 h-4 mr-1 animate-spin" />
                      <RefreshCw v-else class="w-4 h-4 mr-1" />
                      扫描
                    </Button>
                  </div>
                  
                  <!-- 结果概览 -->
                  <div v-if="totalGroups > 0" class="p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg flex items-start gap-2 mb-3">
                    <AlertTriangle class="w-4 h-4 text-yellow-500 shrink-0 mt-0.5" />
                    <div>
                      <p class="text-sm font-medium text-foreground">发现 {{ totalGroups }} 组重复图片</p>
                      <p class="text-xs text-muted-foreground">点击下方图片可删除，首张通常建议保留</p>
                    </div>
                  </div>
                  <div v-else-if="!scanning && duplicateGroups.length === 0" class="p-3 bg-green-500/10 border border-green-500/20 rounded-lg flex items-center gap-2">
                    <CheckCircle class="w-4 h-4 text-green-500" />
                    <p class="text-sm text-foreground">暂无重复文件，点击扫描开始检测</p>
                  </div>
                </div>

                <!-- 重复组列表 -->
                <div v-if="duplicateGroups.length > 0" class="space-y-4">
                  <div 
                    v-for="(group, idx) in duplicateGroups" 
                    :key="group.hash"
                    class="p-4 bg-muted/30 rounded-xl border border-border"
                  >
                    <div class="flex items-center justify-between mb-3">
                      <span class="text-xs font-mono text-muted-foreground">
                        组 #{{ idx + 1 }} · {{ group.count }} 张相同
                      </span>
                      <span class="text-xs text-muted-foreground">
                        Hash: {{ group.hash?.slice(0, 8) }}...
                      </span>
                    </div>
                    <div class="grid grid-cols-2 sm:grid-cols-3 gap-3">
                      <div 
                        v-for="(img, imgIdx) in group.images" 
                        :key="img.id"
                        class="relative group cursor-pointer"
                        @click="openImagePreview(img)"
                      >
                        <img 
                          :src="img.image_url" 
                          :alt="`重复图${imgIdx + 1}`"
                          class="w-full aspect-square object-cover rounded-lg"
                        />
                        <div class="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg flex flex-col items-center justify-center gap-1">
                          <span class="text-white text-xs">{{ formatFileSize(img.file_size) }}</span>
                          <span class="text-white/70 text-xs">{{ formatDate(img.created_at) }}</span>
                          <Button 
                            v-if="imgIdx > 0"
                            size="sm" 
                            variant="destructive"
                            class="mt-1"
                            @click.stop="deleteImage(img.id)"
                            :disabled="deleting === img.id"
                          >
                            <Loader2 v-if="deleting === img.id" class="w-3 h-3 animate-spin" />
                            <span v-else>删除</span>
                          </Button>
                          <span v-else class="text-green-400 text-xs font-medium mt-1">建议保留</span>
                        </div>
                        <!-- 首张标记 -->
                        <span 
                          v-if="imgIdx === 0" 
                          class="absolute top-1 left-1 px-1.5 py-0.5 bg-green-500 text-white text-xs rounded"
                        >
                          最早
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 哈希计算 -->
                <div class="p-4 bg-muted/50 rounded-xl">
                  <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                      <Database class="w-5 h-5 text-muted-foreground" />
                      <div>
                        <h3 class="font-medium text-foreground">文件哈希计算</h3>
                        <p class="text-xs text-muted-foreground">
                          {{ imagesWithoutHash > 0 ? `${imagesWithoutHash} 张图片待计算` : '为新图片生成指纹' }}
                        </p>
                      </div>
                    </div>
                    <Button 
                      variant="outline"
                      size="sm"
                      @click="calculateHashes"
                      :disabled="calculating"
                    >
                      <Loader2 v-if="calculating" class="w-4 h-4 mr-1 animate-spin" />
                      计算
                    </Button>
                  </div>
                </div>

                <!-- 通用配置项 -->
                <div 
                  v-for="def in visibleDefinitions" 
                  :key="def.key"
                  class="space-y-1.5"
                >
                  <label class="block text-sm font-medium text-foreground">{{ def.label }}</label>
                  <p v-if="def.description" class="text-xs text-muted-foreground mb-1">{{ def.description }}</p>
                  
                  <!-- Number -->
                  <input
                    v-if="def.type === 'number'"
                    v-model="configs[def.key]"
                    type="number"
                    class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  
                  <!-- Boolean -->
                  <div v-else-if="def.type === 'boolean'" class="flex items-center gap-2">
                    <button
                      @click="configs[def.key] = configs[def.key] === 'true' ? 'false' : 'true'"
                      class="w-12 h-6 rounded-full transition-colors relative"
                      :class="configs[def.key] === 'true' ? 'bg-primary' : 'bg-muted'"
                    >
                      <div 
                        class="absolute top-1 w-4 h-4 bg-white rounded-full transition-transform"
                        :class="configs[def.key] === 'true' ? 'translate-x-7' : 'translate-x-1'"
                      />
                    </button>
                    <span class="text-sm text-muted-foreground">{{ configs[def.key] === 'true' ? '开启' : '关闭' }}</span>
                  </div>
                </div>
              </template>

              <!-- 用户管理面板 -->
              <template v-else-if="activeCategory === 'users'">
                <!-- 加载中 -->
                <div v-if="usersLoading" class="flex items-center justify-center py-10">
                  <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
                </div>

                <div v-else class="space-y-4">
                  <!-- 新建用户按钮 -->
                  <div class="flex justify-end">
                    <Button size="sm" @click="showCreateUser = !showCreateUser">
                      <UserPlus class="w-4 h-4 mr-1" />
                      新建用户
                    </Button>
                  </div>

                  <!-- 新建用户表单 -->
                  <div v-if="showCreateUser" class="p-4 bg-muted/50 rounded-xl space-y-3 animate-in fade-in">
                    <div class="grid grid-cols-2 gap-3">
                      <div class="space-y-1">
                        <label class="text-xs text-muted-foreground">用户名 *</label>
                        <input
                          v-model="newUser.username"
                          type="text"
                          class="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                          placeholder="用户名"
                        />
                      </div>
                      <div class="space-y-1">
                        <label class="text-xs text-muted-foreground">密码 *</label>
                        <input
                          v-model="newUser.password"
                          type="password"
                          class="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                          placeholder="至少 6 位"
                        />
                      </div>
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                      <div class="space-y-1">
                        <label class="text-xs text-muted-foreground">邮箱（可选）</label>
                        <input
                          v-model="newUser.email"
                          type="email"
                          class="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                          placeholder="email@example.com"
                        />
                      </div>
                      <div class="space-y-1">
                        <label class="text-xs text-muted-foreground">角色</label>
                        <select
                          v-model="newUser.role"
                          class="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                        >
                          <option value="user">普通用户</option>
                          <option value="admin">管理员</option>
                        </select>
                      </div>
                    </div>
                    <div class="flex justify-end gap-2">
                      <Button variant="ghost" size="sm" @click="showCreateUser = false">取消</Button>
                      <Button size="sm" @click="createUser" :disabled="creatingUser">
                        <Loader2 v-if="creatingUser" class="w-4 h-4 mr-1 animate-spin" />
                        创建
                      </Button>
                    </div>
                  </div>

                  <!-- 用户列表 -->
                  <div class="space-y-2">
                    <div
                      v-for="user in userList"
                      :key="user.id"
                      class="p-3 bg-muted/30 rounded-xl border border-border flex items-center gap-3"
                    >
                      <!-- 用户信息 -->
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="font-medium text-foreground">{{ user.username }}</span>
                          <span
                            class="px-1.5 py-0.5 rounded text-xs font-medium"
                            :class="user.role === 'admin' ? 'bg-violet-500/10 text-violet-500' : 'bg-muted text-muted-foreground'"
                          >
                            <Shield v-if="user.role === 'admin'" class="w-3 h-3 inline mr-0.5" />
                            {{ user.role === 'admin' ? '管理员' : '用户' }}
                          </span>
                          <span
                            v-if="!user.is_active"
                            class="px-1.5 py-0.5 rounded text-xs font-medium bg-red-500/10 text-red-500"
                          >
                            <Ban class="w-3 h-3 inline mr-0.5" />
                            已禁用
                          </span>
                        </div>
                        <div class="text-xs text-muted-foreground mt-0.5">
                          {{ user.email || '无邮箱' }} · ID: {{ user.id }}
                        </div>
                      </div>

                      <!-- 操作按钮 -->
                      <div class="flex items-center gap-1">
                        <!-- 修改密码 -->
                        <Button
                          v-if="user.id !== 1 || currentUserId === 1"
                          variant="ghost"
                          size="icon"
                          class="w-8 h-8"
                          @click="showChangePassword = showChangePassword === user.id ? null : user.id"
                          title="修改密码"
                        >
                          <Key class="w-4 h-4" />
                        </Button>
                        
                        <!-- 切换角色 -->
                        <Button
                          v-if="user.id !== currentUserId && user.id !== 1"
                          variant="ghost"
                          size="icon"
                          class="w-8 h-8"
                          @click="changeUserRole(user, user.role === 'admin' ? 'user' : 'admin')"
                          :disabled="userActionLoading === user.id"
                          :title="user.role === 'admin' ? '设为普通用户' : '设为管理员'"
                        >
                          <Shield class="w-4 h-4" :class="user.role === 'admin' ? 'text-violet-500' : ''" />
                        </Button>

                        <!-- 禁用/启用 -->
                        <Button
                          v-if="user.id !== currentUserId && user.id !== 1"
                          variant="ghost"
                          size="icon"
                          class="w-8 h-8"
                          @click="toggleUserActive(user)"
                          :disabled="userActionLoading === user.id"
                          :title="user.is_active ? '禁用用户' : '启用用户'"
                        >
                          <Ban class="w-4 h-4" :class="!user.is_active ? 'text-red-500' : ''" />
                        </Button>

                        <!-- 权限设置 -->
                        <Button
                          v-if="user.id !== currentUserId && user.id !== 1 && user.role !== 'admin'"
                          variant="ghost"
                          size="icon"
                          class="w-8 h-8"
                          @click="openPermissionsDialog(user)"
                          :disabled="userActionLoading === user.id"
                          title="权限设置"
                        >
                          <ListChecks class="w-4 h-4" :class="showPermissions === user.id ? 'text-primary' : ''" />
                        </Button>

                        <!-- 删除 -->
                        <Button
                          v-if="user.id !== currentUserId && user.id !== 1"
                          variant="ghost"
                          size="icon"
                          class="w-8 h-8 text-red-500 hover:text-red-600"
                          @click="deleteUser(user)"
                          :disabled="userActionLoading === user.id"
                          title="删除用户"
                        >
                          <X class="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  </div>

                  <!-- 修改密码弹出框 -->
                  <div
                    v-if="showChangePassword"
                    class="p-4 bg-muted/50 rounded-xl space-y-3 animate-in fade-in"
                  >
                    <div class="flex items-center gap-2 text-sm font-medium">
                      <Key class="w-4 h-4" />
                      修改密码 - {{ userList.find(u => u.id === showChangePassword)?.username }}
                    </div>
                    <input
                      v-model="newPassword"
                      type="password"
                      class="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                      placeholder="新密码（至少 6 位）"
                    />
                    <div class="flex justify-end gap-2">
                      <Button variant="ghost" size="sm" @click="showChangePassword = null; newPassword = ''">取消</Button>
                      <Button size="sm" @click="changePassword(showChangePassword!)" :disabled="changingPassword">
                        <Loader2 v-if="changingPassword" class="w-4 h-4 mr-1 animate-spin" />
                        确认修改
                      </Button>
                    </div>
                  </div>

                  <!-- 权限编辑弹出框 -->
                  <div
                    v-if="showPermissions"
                    class="p-4 bg-muted/50 rounded-xl space-y-3 animate-in fade-in"
                  >
                    <div class="flex items-center gap-2 text-sm font-medium">
                      <ListChecks class="w-4 h-4" />
                      权限设置 - {{ userList.find(u => u.id === showPermissions)?.username }}
                    </div>
                    <p class="text-xs text-muted-foreground">
                      管理员自动拥有所有权限。以下设置仅对普通用户生效。
                    </p>
                    <div class="space-y-2">
                      <label
                        v-for="perm in permissionOptions"
                        :key="perm.value"
                        class="flex items-center gap-2 cursor-pointer p-2 rounded-lg hover:bg-muted/50"
                      >
                        <input
                          type="checkbox"
                          :checked="hasPermission(editingPermissions, perm.value)"
                          @change="togglePermission(perm.value)"
                          class="w-4 h-4 rounded accent-primary"
                        />
                        <span class="text-sm">{{ perm.name }}</span>
                      </label>
                    </div>
                    <div class="flex justify-end gap-2">
                      <Button variant="ghost" size="sm" @click="showPermissions = null">取消</Button>
                      <Button size="sm" @click="savePermissions" :disabled="savingPermissions">
                        <Loader2 v-if="savingPermissions" class="w-4 h-4 mr-1 animate-spin" />
                        保存权限
                      </Button>
                    </div>
                  </div>

                  <!-- 空状态 -->
                  <div v-if="userList.length === 0 && !usersLoading" class="text-center py-10 text-muted-foreground">
                    暂无用户
                  </div>
                </div>
              </template>

              <!-- 向量配置：特殊面板 -->
              <template v-else-if="activeCategory === 'embedding'">
                <!-- 模式选择 -->
                <div class="space-y-4">
                  <div class="space-y-1.5">
                    <label class="block text-sm font-medium text-foreground">嵌入模式</label>
                    <div class="grid grid-cols-2 gap-3">
                      <button
                        @click="configs['embedding_mode'] = 'local'"
                        class="p-3 rounded-xl border flex items-center gap-3 transition-all"
                        :class="configs['embedding_mode'] === 'local' ? 'bg-primary/5 border-primary ring-1 ring-primary' : 'bg-muted/30 border-border hover:bg-muted/50'"
                      >
                        <div class="w-8 h-8 rounded-lg bg-blue-500/10 text-blue-500 flex items-center justify-center">
                          <HardDrive class="w-4 h-4" />
                        </div>
                        <div class="text-left">
                          <div class="text-sm font-medium">本地模型 (ONNX)</div>
                          <div class="text-xs text-muted-foreground">速度快，隐私安全</div>
                        </div>
                      </button>

                      <button
                        @click="configs['embedding_mode'] = 'api'"
                        class="p-3 rounded-xl border flex items-center gap-3 transition-all"
                        :class="configs['embedding_mode'] === 'api' ? 'bg-primary/5 border-primary ring-1 ring-primary' : 'bg-muted/30 border-border hover:bg-muted/50'"
                      >
                        <div class="w-8 h-8 rounded-lg bg-violet-500/10 text-violet-500 flex items-center justify-center">
                          <Cloud class="w-4 h-4" />
                        </div>
                        <div class="text-left">
                          <div class="text-sm font-medium">在线 API</div>
                          <div class="text-xs text-muted-foreground">精度高，无需显存</div>
                        </div>
                      </button>
                    </div>
                  </div>

                  <!-- 本地模型配置 -->
                  <div v-if="configs['embedding_mode'] === 'local'" class="space-y-4 animate-in fade-in slide-in-from-right-2">
                    <div class="space-y-1.5">
                      <label class="block text-sm font-medium text-foreground">模型选择</label>
                      <select
                        v-model="configs['embedding_local_model']"
                        class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                      >
                        <option v-for="opt in localModelOptions" :key="opt.value" :value="opt.value">
                          {{ opt.label }}
                        </option>
                      </select>
                      <p class="text-xs text-muted-foreground">初次使用会自动下载模型（约 200MB）</p>
                    </div>

                    <div class="space-y-1.5">
                      <label class="block text-sm font-medium text-foreground">HF 镜像地址</label>
                      <input
                        v-model="configs['hf_endpoint']"
                        type="text"
                        class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        placeholder="https://hf-mirror.com"
                      />
                    </div>
                  </div>

                  <!-- API 模式配置 -->
                  <div v-else class="space-y-4 animate-in fade-in slide-in-from-right-2">
                    <div class="space-y-1.5">
                      <label class="block text-sm font-medium text-foreground">API 地址</label>
                      <input
                        v-model="configs['embedding_api_base_url']"
                        type="text"
                        class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        placeholder="https://api.siliconflow.cn/v1"
                      />
                    </div>
                    <div class="space-y-1.5">
                      <label class="block text-sm font-medium text-foreground">API 密钥</label>
                      <input
                        v-model="configs['embedding_api_key']"
                        type="password"
                        class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        placeholder="sk-..."
                      />
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                       <div class="space-y-1.5">
                        <label class="block text-sm font-medium text-foreground">模型名称</label>
                        <input
                          v-model="configs['embedding_model']"
                          type="text"
                          class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                          placeholder="text-embedding-3-small"
                        />
                      </div>
                      <div class="space-y-1.5">
                        <label class="block text-sm font-medium text-foreground">维度</label>
                        <input
                          v-model="configs['embedding_dimensions']"
                          type="number"
                          class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      </div>
                    </div>
                  </div>

                  <ModelTestButton
                    :loading="modelTesting.embedding"
                    :result="modelTestResults.embedding"
                    description="使用当前配置生成一条测试向量"
                    @test="testModel('embedding')"
                  />

                  <!-- 向量状态卡片 -->
                  <div v-if="vectorStatus" class="mt-4 p-4 bg-muted/50 rounded-xl space-y-3">
                    <div class="flex items-center justify-between">
                       <h3 class="font-medium text-sm text-foreground flex items-center gap-2">
                         <Database class="w-4 h-4 text-muted-foreground" />
                         向量库状态
                       </h3>
                       <div class="flex items-center gap-2">
                          <span 
                            class="px-2 py-0.5 rounded text-xs font-medium"
                            :class="!dimensionsMismatch ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'"
                          >
                            {{ !dimensionsMismatch ? '维度匹配' : '维度不匹配' }}
                          </span>
                       </div>
                    </div>

                    <div class="grid grid-cols-2 gap-2 text-xs">
                      <div class="p-2 bg-background rounded-lg border border-border/50">
                        <div class="text-muted-foreground mb-0.5">数据库维度</div>
                        <div class="font-mono">{{ vectorStatus.db_dimensions }}</div>
                      </div>
                      <div class="p-2 bg-background rounded-lg border border-border/50">
                        <div class="text-muted-foreground mb-0.5">配置向量维度</div>
                        <div class="font-mono transition-colors" :class="{'text-amber-500 font-bold': dimensionsMismatch}">
                          {{ targetDimensions }}
                          <span v-if="hasChanges" class="text-[10px] font-normal opacity-70">(未保存)</span>
                        </div>
                      </div>
                    </div>

                    <!-- 状态操作栏 -->
                    <div class="flex gap-2 pt-1">
                      <Button 
                        v-if="dimensionsMismatch"
                        size="sm" 
                        variant="destructive" 
                        class="w-full h-8 text-xs"
                        @click="resizeVectorTable"
                        :disabled="resizing || hasChanges"
                        :title="hasChanges ? '请先保存配置' : '重置数据库维度'"
                      >
                         <RotateCw v-if="resizing" class="w-3.5 h-3.5 mr-1.5 animate-spin" />
                         <span v-else>{{ hasChanges ? '请先保存配置' : '重置数据库维度' }}</span>
                      </Button>
                      
                      <Button 
                        size="sm" 
                        variant="secondary" 
                        class="w-full h-8 text-xs bg-background hover:bg-muted border border-border/50"
                        @click="rebuildVectors"
                        :disabled="rebuilding || dimensionsMismatch || hasChanges"
                      >
                         <Loader2 v-if="rebuilding" class="w-3.5 h-3.5 mr-1.5 animate-spin" />
                         <span>
                           {{ rebuilding ? '重建中...' : '重建所有向量' }}
                         </span>
                      </Button>
                    </div>

                    <!-- 重建进度条 -->
                    <div v-if="vectorStatus.rebuild_status.message || rebuilding" class="space-y-1.5 pt-2 border-t border-border/50">
                       <div class="flex justify-between text-xs text-muted-foreground">
                         <span>重建进度</span>
                         <span>{{ vectorStatus.rebuild_status.processed }} / {{ vectorStatus.rebuild_status.total }} · {{ Math.round(rebuildProgress) }}%</span>
                       </div>
                       <div
                         role="progressbar"
                         aria-label="向量重建进度"
                         :aria-valuenow="Math.round(rebuildProgress)"
                         :aria-valuemin="0"
                         :aria-valuemax="100"
                         class="h-1.5 w-full bg-muted rounded-full overflow-hidden"
                       >
                         <div 
                           class="h-full bg-primary transition-all duration-500"
                           :style="{ width: `${rebuildProgress}%` }"
                         />
                       </div>
                       <p class="text-xs text-muted-foreground" role="status" aria-live="polite">
                         {{ vectorStatus.rebuild_status.message }}
                       </p>
                       <p v-if="vectorStatus.rebuild_status.last_error" class="text-xs text-destructive break-words">
                         最近一次错误：{{ vectorStatus.rebuild_status.last_error }}
                       </p>
                       <p v-if="rebuildPollError" class="text-xs text-amber-500">{{ rebuildPollError }}</p>
                    </div>
                  </div>
                </div>
              </template>

              <!-- 其他分类：配置表单 -->
              <template v-else>
                <div 
                  v-for="def in visibleDefinitions" 
                  :key="def.key"
                  class="animate-in fade-in slide-in-from-right-2 duration-200"
                >
                  <!-- Textarea -->
                  <template v-if="def.type === 'textarea'">
                    <label :for="def.key" class="block text-sm font-medium text-foreground mb-1.5">
                      {{ def.label }}
                    </label>
                    <p v-if="def.description" class="text-xs text-muted-foreground mb-2">
                      {{ def.description }}
                    </p>
                    <div v-if="def.key === 'vision_prompt'" class="flex items-center gap-3 mb-2">
                      <Button type="button" variant="outline" size="sm" :disabled="!promptDefaults || saving" @click="resetVisionPrompt">重置为默认提示词</Button>
                      <span class="text-xs text-muted-foreground">仅修改当前表单，保存后生效</span>
                    </div>
                    <p v-if="def.key === 'vision_prompt' && defaultsError" class="text-xs text-destructive mb-2">默认提示词加载失败。<button type="button" class="underline" @click="reloadDefaults()">重试</button></p>
                    <textarea
                      :id="def.key"
                      v-model="configs[def.key]"
                      rows="16"
                      class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring resize-y"
                    />
                  </template>

                  <!-- 其他控件 -->
                  <template v-else>
                    <div class="flex items-center justify-between gap-4">
                      <div class="flex-1">
                        <label :for="def.key" class="block text-sm font-medium text-foreground">
                          {{ def.label }}
                        </label>
                        <p v-if="def.description" class="text-xs text-muted-foreground mt-0.5">
                          {{ def.description }}
                        </p>
                      </div>

                      <div class="w-44 shrink-0">
                        <!-- Boolean -->
                        <template v-if="def.type === 'boolean'">
                          <button
                            @click="configs[def.key] = configs[def.key] === 'true' ? 'false' : 'true'"
                            class="relative w-11 h-6 rounded-full transition-colors"
                            :class="configs[def.key] === 'true' ? 'bg-green-500' : 'bg-muted'"
                          >
                            <span 
                              class="absolute top-1 w-4 h-4 bg-white rounded-full transition-all shadow"
                              :class="configs[def.key] === 'true' ? 'left-6' : 'left-1'"
                            />
                          </button>
                        </template>
                        
                        <!-- Select -->
                        <template v-else-if="def.type === 'select'">
                          <select
                            :id="def.key"
                            v-model="configs[def.key]"
                            class="w-full px-3 py-1.5 text-sm bg-muted/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
                          >
                            <option v-for="opt in def.options" :key="opt.value" :value="opt.value">
                              {{ opt.label }}
                            </option>
                          </select>
                        </template>

                        <!-- Combobox (Text + Quick Select) -->
                        <template v-else-if="def.type === 'combobox'">
                          <div class="relative flex gap-2">
                             <div class="relative flex-1">
                                <input
                                  :id="def.key"
                                  v-model="configs[def.key]"
                                  type="text"
                                  class="w-full px-3 py-1.5 text-sm bg-muted/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring pr-8"
                                  placeholder="选择推荐模型或手动输入"
                                />
                                <button 
                                  type="button"
                                  @click="fetchModels"
                                  :disabled="modelsLoading"
                                  class="absolute right-1 top-1/2 -translate-y-1/2 p-1 hover:bg-muted rounded"
                                  title="刷新模型列表"
                                >
                                  <RefreshCw :class="['w-3.5 h-3.5 text-muted-foreground', modelsLoading && 'animate-spin']" />
                                </button>
                             </div>
                             
                             <!-- Quick Select Dropdown -->
                             <Select 
                               @update:model-value="(v) => configs[def.key] = String(v)"
                             >
                                <SelectTrigger class="w-[40px] px-2 bg-muted/50 border-border">
                                   <ChevronDown class="w-4 h-4 text-muted-foreground" />
                                </SelectTrigger>
                                <SelectContent>
                                   <SelectItem 
                                     v-for="model in availableModels" 
                                     :key="model" 
                                     :value="model"
                                   >
                                     {{ model }}
                                   </SelectItem>
                                   <div v-if="availableModels.length === 0" class="p-2 text-xs text-muted-foreground text-center">
                                      {{ modelsLoading ? '加载中...' : '无可用模型' }}
                                   </div>
                                </SelectContent>
                             </Select>
                          </div>
                          <p v-if="modelsError" class="text-xs text-destructive mt-1">{{ modelsError }}</p>
                        </template>

                        <!-- Password -->
                        <template v-else-if="def.type === 'password'">
                          <input
                            :id="def.key"
                            v-model="configs[def.key]"
                            type="password"
                            class="w-full px-3 py-1.5 text-sm bg-muted/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
                            placeholder="••••••"
                          />
                        </template>
                        
                        <!-- Text/Number -->
                        <template v-else>
                          <input
                            :id="def.key"
                            v-model="configs[def.key]"
                            :type="def.type"
                            :min="def.min"
                            :max="def.max"
                            :step="def.step"
                            :placeholder="def.placeholder"
                            class="w-full px-3 py-1.5 text-sm bg-muted/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
                          />
                        </template>
                      </div>
                    </div>
                  </template>
                  <ModelTestButton
                    v-if="def.key === 'vision_model'"
                    :loading="modelTesting.vision"
                    :result="modelTestResults.vision"
                    description="使用当前配置发送一条文本测试请求"
                    @test="testModel('vision')"
                  />
                </div>
              </template>
            </div>

            <!-- 底部操作 -->
            <div v-if="activeCategory !== 'users'" class="p-6 border-t border-border flex justify-end gap-2">
              <Button variant="outline" @click="closeDrawer">取消</Button>
              <Button @click="saveConfigs" :disabled="!hasChanges || saving">
                <Loader2 v-if="saving" class="w-4 h-4 mr-1 animate-spin" />
                <Save v-else class="w-4 h-4 mr-1" />
                保存
              </Button>
            </div>
            <div v-else class="p-6 border-t border-border flex justify-end">
              <Button variant="outline" @click="closeDrawer">关闭</Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 图片预览弹窗 -->
    <ImageDetailModal
      :image="previewImage"
      @close="closeImagePreview"
    />

    <!-- 确认弹窗 -->
    <ConfirmDialog
      :open="confirmState.open"
      :title="confirmState.title"
      :message="confirmState.message"
      :confirm-text="confirmState.confirmText"
      :cancel-text="confirmState.cancelText"
      :variant="confirmState.variant"
      :loading="confirmState.loading"
      @confirm="handleConfirm"
      @cancel="handleCancel"
    />
  </div>
</template>

<style scoped>
.drawer-enter-active,
.drawer-leave-active {
  transition: all 0.3s ease;
}
.drawer-enter-active > div:last-child,
.drawer-leave-active > div:last-child {
  transition: transform 0.3s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from > div:last-child,
.drawer-leave-to > div:last-child {
  transform: translateX(100%);
}

.animate-in {
  animation-fill-mode: both;
}
.fade-in {
  animation-name: fadeIn;
}
.slide-in-from-right-2 {
  --tw-translate-x: 0.5rem;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateX(var(--tw-translate-x, 0)); }
  to { opacity: 1; transform: translateX(0); }
}

/* 图片预览弹窗动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
