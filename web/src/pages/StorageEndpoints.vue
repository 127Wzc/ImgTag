<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import { toast } from 'vue-sonner'
import { getErrorMessage } from '@/utils/api-error'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { 
  Plus,
  Loader2,
  HardDrive,
  Cloud,
  Pencil,
  Trash2,
  Play,
  TestTube,
  CheckCircle,
  XCircle,
  Star,
  X,
  Save,
  ChevronDown,
  Unlink,
} from 'lucide-vue-next'

// 端点类型
interface ActiveTaskInfo {
  task_id: string
  task_type: string
  status: string
  progress_percent: number
  success_count: number
  failed_count: number
  total_count: number
}

interface StorageEndpoint {
  id: number
  name: string
  provider: string
  endpoint_url: string | null
  region: string | null
  bucket_name: string | null
  has_credentials: boolean
  access_key_id: string | null  // 明文，前端显示时伪装
  secret_access_key: string | null  // 明文，前端显示时伪装
  public_url_prefix: string | null
  path_prefix: string
  path_style: boolean
  role: string
  is_enabled: boolean
  is_default_upload: boolean
  auto_sync_enabled: boolean
  sync_from_endpoint_id: number | null
  read_priority: number
  read_weight: number
  is_healthy: boolean
  location_count: number
  active_task: ActiveTaskInfo | null
}

const loading = ref(false)
const endpoints = ref<StorageEndpoint[]>([])
const showDialog = ref(false)
const editingEndpoint = ref<StorageEndpoint | null>(null)
const saving = ref(false)
const testing = ref<number | null>(null)
const deleting = ref<number | null>(null)
const unlinking = ref<number | null>(null)  // 解绑位置记录

// 确认弹窗
const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()
// ConfirmDialog 需要的 props
const confirmDialogProps = confirmState

// 同步相关
const syncing = ref(false)
const showSyncDialog = ref(false)
const syncForm = ref({
  source_endpoint_id: 0,
  target_endpoint_id: 0,
  force_overwrite: false
})

// 表单数据
const form = ref({
  name: '',
  provider: 'local',
  endpoint_url: '',
  region: 'auto',
  bucket_name: '',
  access_key_id: '',
  secret_access_key: '',
  public_url_prefix: '',
  path_prefix: '',
  path_style: true,
  role: 'primary',
  is_enabled: true,
  is_default_upload: false,
  read_priority: 100,
  read_weight: 1
})

const providers = [
  { value: 'local', label: '本地存储', icon: HardDrive },
  { value: 's3', label: 'S3 兼容', icon: Cloud },
]

const roles = [
  { value: 'primary', label: '主端点', description: '可直接上传' },
  { value: 'backup', label: '备份端点', description: '自动同步备份' },
]

// 凭据显示状态（默认隐藏，点击可显示明文）
const showCredentials = ref(false)

const isS3Like = computed(() => form.value.provider === 's3')
const isDefaultEndpoint = computed(() => editingEndpoint.value?.id === 1)
const isLocal = computed(() => form.value.provider === 'local')

// URL 预览计算
const urlPreview = computed(() => {
  const bucket = form.value.bucket_name || 'uploads'
  const prefix = form.value.public_url_prefix?.replace(/\/$/, '') || ''
  const pathPrefix = form.value.path_prefix?.replace(/^\/|\/$/g, '') || ''
  const example = 'example.jpg'
  
  if (prefix) {
    // 有 CDN/公开 URL
    return pathPrefix 
      ? `${prefix}/${bucket}/${pathPrefix}/${example}`
      : `${prefix}/${bucket}/${example}`
  } else if (isLocal.value) {
    // 本地相对路径
    return pathPrefix 
      ? `/${bucket}/${pathPrefix}/${example}`
      : `/${bucket}/${example}`
  } else {
    // S3 直接 URL
    const endpoint = form.value.endpoint_url?.replace(/\/$/, '') || 'https://s3.example.com'
    return pathPrefix 
      ? `${endpoint}/${bucket}/${pathPrefix}/${example}`
      : `${endpoint}/${bucket}/${example}`
  }
})

// 计算端点在同优先级中的权重占比
function getWeightRatio(ep: StorageEndpoint): number | null {
  // 只对启用的端点计算
  const samePriorityEndpoints = endpoints.value.filter(
    e => e.is_enabled && e.read_priority === ep.read_priority
  )
  if (samePriorityEndpoints.length <= 1) return null
  
  const totalWeight = samePriorityEndpoints.reduce((sum, e) => sum + e.read_weight, 0)
  if (totalWeight === 0) return 0
  
  return Math.round((ep.read_weight / totalWeight) * 100)
}

async function fetchEndpoints() {
  loading.value = true
  try {
    const { data } = await apiClient.get<StorageEndpoint[]>('/storage/endpoints')
    endpoints.value = data
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingEndpoint.value = null
  form.value = {
    name: '',
    provider: 'local',
    endpoint_url: '',
    region: 'auto',
    bucket_name: '',
    access_key_id: '',
    secret_access_key: '',
    public_url_prefix: '',
    path_prefix: '',
    path_style: true,
    role: 'primary',
    is_enabled: true,
    is_default_upload: endpoints.value.length === 0,
    read_priority: 100,
    read_weight: 1
  }
  showDialog.value = true
}

function openEdit(ep: StorageEndpoint) {
  editingEndpoint.value = ep
  showCredentials.value = false  // 默认隐藏密钥
  form.value = {
    name: ep.name,
    provider: ep.provider,
    endpoint_url: ep.endpoint_url || '',
    region: ep.region || 'auto',
    bucket_name: ep.bucket_name || '',
    access_key_id: ep.access_key_id || '',  // 从 API 加载
    secret_access_key: ep.secret_access_key || '',  // 从 API 加载
    public_url_prefix: ep.public_url_prefix || '',
    path_prefix: ep.path_prefix,
    path_style: ep.path_style ?? true,
    role: ep.role,
    is_enabled: ep.is_enabled,
    is_default_upload: ep.is_default_upload,
    read_priority: ep.read_priority,
    read_weight: ep.read_weight
  }
  showDialog.value = true
}

async function saveEndpoint() {
  if (!form.value.name.trim()) {
    toast.error('请输入端点名称')
    return
  }
  
  saving.value = true
  try {
    if (editingEndpoint.value) {
      await apiClient.put(`/storage/endpoints/${editingEndpoint.value.id}`, form.value)
      toast.success('端点已更新')
    } else {
      await apiClient.post('/storage/endpoints', form.value)
      toast.success('端点已创建')
    }
    showDialog.value = false
    await fetchEndpoints()
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    saving.value = false
  }
}

async function testConnection(ep: StorageEndpoint) {
  testing.value = ep.id
  try {
    const { data } = await apiClient.post(`/storage/endpoints/${ep.id}/test`)
    if (data.success) {
      toast.success('连接测试成功')
    } else {
      toast.error(data.message || '连接测试失败')
    }
    await fetchEndpoints()
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    testing.value = null
  }
}

async function setDefault(ep: StorageEndpoint) {
  try {
    await apiClient.post(`/storage/endpoints/${ep.id}/set-default`)
    toast.success(`已设为默认上传端点: ${ep.name}`)
    await fetchEndpoints()
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  }
}

async function deleteEndpoint(ep: StorageEndpoint) {
  const confirmed = await confirm({
    title: '删除端点',
    message: `确定删除端点 "${ep.name}" 吗？`,
    variant: 'danger',
    confirmText: '删除',
  })
  if (!confirmed.confirmed) return
  
  deleting.value = ep.id
  try {
    await apiClient.delete(`/storage/endpoints/${ep.id}`)
    toast.success('端点已删除')
    await fetchEndpoints()
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    deleting.value = null
  }
}

// 解绑端点位置记录
async function unlinkLocations(ep: StorageEndpoint) {
  const result = await confirm({
    title: '解除关联',
    message: `确定解除端点 "${ep.name}" 的所有 ${ep.location_count} 张图片关联吗？此操作不可恢复！`,
    variant: 'danger',
    confirmText: '解除',
    checkboxLabel: '同时删除物理文件',
    checkboxDefault: false,
  })
  if (!result.confirmed) return
  
  unlinking.value = ep.id
  try {
    const { data } = await apiClient.delete(`/storage/endpoints/${ep.id}/locations`, {
      data: { 
        confirm: true,
        delete_files: result.checkboxChecked,
      }
    })
    toast.success(data.message || '位置记录已解除关联')
    await fetchEndpoints()
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    unlinking.value = null
  }
}

// 同步功能
function openSyncDialog() {
  if (endpoints.value.length < 2) {
    toast.error('需要至少 2 个端点才能同步')
    return
  }
  syncForm.value = {
    source_endpoint_id: endpoints.value[0]?.id || 0,
    target_endpoint_id: endpoints.value[1]?.id || 0,
    force_overwrite: false
  }
  showSyncDialog.value = true
}

async function startSync() {
  if (syncForm.value.source_endpoint_id === syncForm.value.target_endpoint_id) {
    toast.error('源端点和目标端点不能相同')
    return
  }
  syncing.value = true
  try {
    const { data } = await apiClient.post('/storage/sync/start', syncForm.value)
    toast.success(`已启动 ${data.task_ids.length} 个同步任务`)
    showSyncDialog.value = false
    // 可以轮询任务进度
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    syncing.value = false
  }
}

function getProviderIcon(provider: string) {
  const p = providers.find(x => x.value === provider)
  return p?.icon || Cloud
}

function getProviderLabel(provider: string) {
  const p = providers.find(x => x.value === provider)
  return p?.label || provider
}

// 轮询间隔（如有活动任务，30秒刷新一次）
const POLL_INTERVAL_MS = 30000
let pollTimer: ReturnType<typeof setInterval> | null = null

// 检查是否有端点正在执行任务
const hasActiveTask = computed(() => 
  endpoints.value.some(ep => ep.active_task !== null)
)

// 启动/停止轮询
function updatePolling() {
  if (hasActiveTask.value && !pollTimer) {
    // 有活动任务，启动轮询
    pollTimer = setInterval(fetchEndpoints, POLL_INTERVAL_MS)
  } else if (!hasActiveTask.value && pollTimer) {
    // 无活动任务，停止轮询
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(async () => {
  await fetchEndpoints()
  updatePolling()
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <div class="p-6 lg:p-8">
    <div class="max-w-5xl mx-auto">
      <!-- 标题 -->
      <div class="flex items-center justify-between mb-8">
        <div>
          <h1 class="text-2xl font-bold text-foreground">存储端点管理</h1>
          <p class="text-muted-foreground mt-1">管理多个存储后端，支持 S3/R2/MinIO 等</p>
        </div>
        <div class="flex gap-2">
          <Button variant="outline" @click="openSyncDialog" :disabled="endpoints.length < 2">
            <Play class="w-4 h-4 mr-2" />
            同步
          </Button>
          <Button @click="openCreate">
            <Plus class="w-4 h-4 mr-2" />
            添加端点
          </Button>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="flex items-center justify-center py-20">
        <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
      </div>

      <!-- 端点列表 -->
      <div v-else-if="endpoints.length === 0" class="text-center py-20">
        <HardDrive class="w-12 h-12 mx-auto text-muted-foreground mb-4" />
        <p class="text-muted-foreground mb-4">暂无存储端点</p>
        <Button @click="openCreate">
          <Plus class="w-4 h-4 mr-2" />
          创建第一个端点
        </Button>
      </div>

      <div v-else class="space-y-4">
        <div 
          v-for="ep in endpoints" 
          :key="ep.id"
          class="bg-card border border-border rounded-xl p-5 hover:border-primary/30 transition-colors"
        >
          <div class="flex items-start gap-4">
            <!-- 图标 -->
            <div class="w-12 h-12 rounded-xl flex items-center justify-center text-primary" 
                 :class="ep.is_healthy ? 'bg-green-500/10' : 'bg-red-500/10'">
              <component :is="getProviderIcon(ep.provider)" class="w-6 h-6" 
                         :class="ep.is_healthy ? 'text-green-500' : 'text-red-500'" />
            </div>

            <!-- 信息 -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <h3 class="font-semibold text-foreground">{{ ep.name }}</h3>
                <span v-if="ep.is_default_upload" 
                      class="px-2 py-0.5 text-xs bg-primary/10 text-primary rounded-full flex items-center gap-1">
                  <Star class="w-3 h-3" />
                  默认
                </span>
                <span v-if="!ep.is_enabled" 
                      class="px-2 py-0.5 text-xs bg-muted text-muted-foreground rounded-full">
                  已禁用
                </span>
              </div>
              <p class="text-sm text-muted-foreground">
                {{ getProviderLabel(ep.provider) }}
                <template v-if="ep.bucket_name"> · {{ ep.bucket_name }}</template>
              </p>
              <div class="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                <span class="flex items-center gap-1">
                  <component :is="ep.is_healthy ? CheckCircle : XCircle" 
                             :class="ep.is_healthy ? 'text-green-500' : 'text-red-500'" 
                             class="w-3.5 h-3.5" />
                  {{ ep.is_healthy ? '健康' : '异常' }}
                </span>
                <span>{{ ep.location_count }} 张图片</span>
                <span :title="`优先级 ${ep.read_priority}：数值越小越优先`">
                  优先级: {{ ep.read_priority }}
                </span>
                <span :title="`负载权重 ${ep.read_weight}：同优先级端点按权重随机选择`"
                      class="flex items-center gap-1">
                  权重: {{ ep.read_weight }}
                  <span v-if="getWeightRatio(ep) !== null" class="text-primary">
                    ({{ getWeightRatio(ep) }}%)
                  </span>
                </span>
              </div>
              
              <!-- 进行中任务进度条 -->
              <div v-if="ep.active_task" class="mt-2">
                <div class="flex items-center gap-2 text-xs">
                  <Loader2 class="w-3 h-3 animate-spin text-primary" />
                  <span class="text-muted-foreground">
                    {{ ep.active_task.task_type === 'storage_sync' ? '同步中' : 
                       ep.active_task.task_type === 'storage_delete' ? '删除中' : '解除关联中' }}
                  </span>
                  <span class="text-primary font-medium">
                    {{ ep.active_task.progress_percent.toFixed(1) }}%
                  </span>
                  <span class="text-muted-foreground">
                    ({{ ep.active_task.success_count }}/{{ ep.active_task.total_count }})
                  </span>
                </div>
                <div class="mt-1 h-1 bg-muted rounded-full overflow-hidden">
                  <div 
                    class="h-full bg-primary rounded-full transition-all duration-300"
                    :style="{ width: `${ep.active_task.progress_percent}%` }"
                  />
                </div>
              </div>
            </div>

            <!-- 操作按钮 -->
            <div class="flex items-center gap-1">
              <Button 
                variant="ghost" 
                size="sm"
                @click="testConnection(ep)"
                :disabled="testing === ep.id || !!ep.active_task"
                title="测试连接"
              >
                <Loader2 v-if="testing === ep.id" class="w-4 h-4 animate-spin" />
                <TestTube v-else class="w-4 h-4" />
              </Button>
              <Button 
                v-if="!ep.is_default_upload"
                variant="ghost" 
                size="sm"
                @click="setDefault(ep)"
                :disabled="!!ep.active_task"
                title="设为默认上传端点"
              >
                <Star class="w-4 h-4" />
              </Button>
              <Button 
                variant="ghost" 
                size="sm"
                @click="openEdit(ep)"
                :disabled="!!ep.active_task"
                title="编辑配置"
              >
                <Pencil class="w-4 h-4" />
              </Button>
              <!-- 解绑位置记录按钮 -->
              <Button 
                v-if="ep.location_count > 0 && ep.id !== 1"
                variant="ghost" 
                size="sm"
                class="text-amber-600 hover:text-amber-600"
                @click="unlinkLocations(ep)"
                :disabled="unlinking === ep.id || !!ep.active_task"
                :title="ep.active_task ? '有任务进行中' : '解除关联'"
              >
                <Loader2 v-if="unlinking === ep.id" class="w-4 h-4 animate-spin" />
                <Unlink v-else class="w-4 h-4" />
              </Button>
              <Button 
                variant="ghost" 
                size="sm"
                class="text-destructive hover:text-destructive"
                @click="deleteEndpoint(ep)"
                :disabled="deleting === ep.id || ep.location_count > 0 || ep.id === 1 || !!ep.active_task"
                :title="ep.id === 1 ? '默认本地端点无法删除' : ep.active_task ? '有任务进行中' : ep.location_count > 0 ? '有图片关联，请先解除关联' : '删除端点'"
              >
                <Loader2 v-if="deleting === ep.id" class="w-4 h-4 animate-spin" />
                <Trash2 v-else class="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 创建/编辑对话框 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showDialog" class="fixed inset-0 z-50 flex items-center justify-center">
          <div class="absolute inset-0 bg-black/50" @click="showDialog = false" />
          <div class="relative bg-card border border-border rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto m-4">
            <!-- 头部 -->
            <div class="flex items-center justify-between p-5 border-b border-border">
              <h2 class="text-lg font-semibold text-foreground">
                {{ editingEndpoint ? '编辑端点' : '创建端点' }}
              </h2>
              <button @click="showDialog = false" class="p-2 hover:bg-muted rounded-lg">
                <X class="w-5 h-5 text-muted-foreground" />
              </button>
            </div>

            <!-- 表单 -->
            <div class="p-5 space-y-4">
              <!-- 默认端点提示 -->
              <div v-if="isDefaultEndpoint" class="p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl text-sm text-amber-600 dark:text-amber-400">
                默认本地端点只能修改 Bucket 和公开 URL 前缀
              </div>

              <!-- 名称 -->
              <div class="space-y-1.5">
                <label class="block text-sm font-medium">端点名称</label>
                <input 
                  v-model="form.name"
                  type="text"
                  class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 disabled:cursor-not-allowed"
                  placeholder="如: 阿里云主存储"
                  :disabled="isDefaultEndpoint"
                />
              </div>

              <!-- 类型 (隐藏默认端点的类型选择) -->
              <div v-if="!isDefaultEndpoint" class="space-y-1.5">
                <label class="block text-sm font-medium">存储类型</label>
                <div class="grid grid-cols-3 gap-2">
                  <button
                    v-for="p in providers"
                    :key="p.value"
                    @click="form.provider = p.value"
                    class="p-3 rounded-xl border text-center transition-all text-sm"
                    :class="form.provider === p.value 
                      ? 'bg-primary/10 border-primary' 
                      : 'bg-muted/30 border-border hover:bg-muted/50'"
                  >
                    <component :is="p.icon" class="w-5 h-5 mx-auto mb-1" />
                    {{ p.label.split(' ')[0] }}
                  </button>
                </div>
              </div>

              <!-- S3 专属配置 -->
              <template v-if="isS3Like && !isDefaultEndpoint">
                <div class="space-y-1.5">
                  <label class="block text-sm font-medium">端点 URL</label>
                  <input 
                    v-model="form.endpoint_url"
                    type="text"
                    class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    placeholder="https://s3.amazonaws.com"
                  />
                </div>

                <div class="space-y-1.5">
                  <label class="block text-sm font-medium">区域</label>
                  <input 
                    v-model="form.region"
                    type="text"
                    class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    placeholder="auto"
                  />
                </div>

                <div class="grid grid-cols-2 gap-4">
                  <div class="space-y-1.5">
                    <label class="block text-sm font-medium">Access Key ID</label>
                    <input 
                      v-model="form.access_key_id"
                      :type="showCredentials ? 'text' : 'password'"
                      class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring font-mono"
                      placeholder=""
                    />
                  </div>
                  <div class="space-y-1.5">
                    <label class="block text-sm font-medium">Secret Access Key</label>
                    <input 
                      v-model="form.secret_access_key"
                      :type="showCredentials ? 'text' : 'password'"
                      class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring font-mono"
                      placeholder=""
                    />
                  </div>
                </div>
                <label class="flex items-center gap-2 cursor-pointer text-sm text-muted-foreground">
                  <input 
                    v-model="showCredentials"
                    type="checkbox"
                    class="w-3.5 h-3.5 rounded border-border"
                  />
                  <span>显示密钥</span>
                </label>

                <label class="flex items-center gap-3 cursor-pointer">
                  <input 
                    v-model="form.path_style"
                    type="checkbox"
                    class="w-4 h-4 rounded border-border"
                  />
                  <div>
                    <span class="text-sm">使用路径风格 (Path Style)</span>
                    <p class="text-xs text-muted-foreground">MinIO/R2/OSS 等推荐开启</p>
                  </div>
                </label>
              </template>

              <!-- 通用存储配置 (所有端点) -->
              <div class="space-y-4 pt-2 border-t border-border/50">
                <div class="grid grid-cols-2 gap-4">
                  <div class="space-y-1.5">
                    <label class="block text-sm font-medium">
                      {{ isLocal ? '存储目录 (Bucket)' : 'Bucket 名称' }}
                    </label>
                    <input 
                      v-model="form.bucket_name"
                      type="text"
                      class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 disabled:cursor-not-allowed"
                      :placeholder="isLocal ? 'uploads' : 'my-bucket'"
                      :disabled="!!(editingEndpoint && editingEndpoint.location_count > 0)"
                    />
                    <p class="text-xs text-muted-foreground">
                      <template v-if="editingEndpoint && editingEndpoint.location_count > 0">
                        <span class="text-amber-500">⚠ 有 {{ editingEndpoint.location_count }} 张关联图片，无法修改</span>
                      </template>
                      <template v-else>
                        {{ isLocal ? '相对于项目根目录的存储路径' : 'S3 存储桶名称' }}
                      </template>
                    </p>
                  </div>
                  <div v-if="!isDefaultEndpoint" class="space-y-1.5">
                    <label class="block text-sm font-medium">路径前缀</label>
                    <input 
                      v-model="form.path_prefix"
                      type="text"
                      class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                      placeholder="images/"
                    />
                  </div>
                </div>

                <div class="space-y-1.5">
                  <label class="block text-sm font-medium">公开 URL 前缀</label>
                  <input 
                    v-model="form.public_url_prefix"
                    type="text"
                    class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    placeholder="https://cdn.example.com"
                  />
                  <p class="text-xs text-muted-foreground">
                    {{ isLocal 
                      ? 'CDN 或反向代理地址，留空则使用相对路径 (如 /uploads/...)' 
                      : 'CDN 地址，留空则使用 S3 端点直接访问' 
                    }}
                  </p>
                </div>

                <!-- URL 预览 -->
                <div class="p-3 bg-muted/30 rounded-xl">
                  <p class="text-xs text-muted-foreground mb-1">生成的访问 URL 示例：</p>
                  <code class="text-xs text-primary break-all">{{ urlPreview }}</code>
                </div>
              </div>

              <!-- 读取策略配置 (所有端点通用) -->
              <div class="space-y-4 pt-2 border-t border-border/50">
                <p class="text-xs text-muted-foreground">读取策略：优先级相同时按权重随机负载均衡</p>
                <div class="grid grid-cols-2 gap-4">
                  <div class="space-y-1.5">
                    <label class="block text-sm font-medium">读取优先级</label>
                    <input 
                      v-model.number="form.read_priority"
                      type="number"
                      class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                    <p class="text-xs text-muted-foreground">数值越小优先级越高</p>
                  </div>
                  <div class="space-y-1.5">
                    <label class="block text-sm font-medium">负载权重</label>
                    <input 
                      v-model.number="form.read_weight"
                      type="number"
                      min="0"
                      class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                    <p class="text-xs text-muted-foreground">权重越大越容易被选中 (0=不参与)</p>
                  </div>
                </div>
              </div>

              <!-- 开关选项 (非默认端点) -->
              <div v-if="!isDefaultEndpoint" class="space-y-4 pt-2 border-t border-border/50">
                <!-- 角色选择 -->
                <div class="space-y-1.5">
                  <label class="block text-sm font-medium">端点角色</label>
                  <div class="grid grid-cols-3 gap-2">
                    <button
                      v-for="r in roles"
                      :key="r.value"
                      @click="form.role = r.value"
                      class="p-2 rounded-xl border text-center transition-all text-sm"
                      :class="form.role === r.value 
                        ? 'bg-primary/10 border-primary' 
                        : 'bg-muted/30 border-border hover:bg-muted/50'"
                    >
                      <div class="font-medium">{{ r.label }}</div>
                      <div class="text-xs text-muted-foreground">{{ r.description }}</div>
                    </button>
                  </div>
                </div>

                <!-- 备份端点提示 -->
                <div v-if="form.role === 'backup'" class="p-3 bg-blue-500/10 border border-blue-500/30 rounded-xl">
                  <p class="text-sm text-blue-600 dark:text-blue-400">
                    💾 备份端点会自动同步所有上传到主端点的图片。系统仅允许一个备份端点。
                  </p>
                </div>

                <!-- 其他开关 -->
                <label class="flex items-center gap-3 cursor-pointer">
                  <input 
                    v-model="form.is_enabled"
                    type="checkbox"
                    class="w-4 h-4 rounded border-border"
                  />
                  <span class="text-sm">启用此端点</span>
                </label>
                <label class="flex items-center gap-3 cursor-pointer">
                  <input 
                    v-model="form.is_default_upload"
                    type="checkbox"
                    class="w-4 h-4 rounded border-border"
                  />
                  <span class="text-sm">设为默认上传端点</span>
                </label>
              </div>
            </div>

            <!-- 底部按钮 -->
            <div class="flex justify-end gap-2 p-5 border-t border-border">
              <Button variant="outline" @click="showDialog = false">取消</Button>
              <Button @click="saveEndpoint" :disabled="saving">
                <Loader2 v-if="saving" class="w-4 h-4 mr-2 animate-spin" />
                <Save v-else class="w-4 h-4 mr-2" />
                保存
              </Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 同步对话框 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showSyncDialog" class="fixed inset-0 z-50 flex items-center justify-center">
          <div class="absolute inset-0 bg-black/50" @click="showSyncDialog = false" />
          <div class="relative bg-card border border-border rounded-2xl shadow-2xl w-full max-w-md m-4">
            <div class="flex items-center justify-between p-5 border-b border-border">
              <h2 class="text-lg font-semibold text-foreground">同步存储</h2>
              <button @click="showSyncDialog = false" class="p-2 hover:bg-muted rounded-lg">
                <X class="w-5 h-5 text-muted-foreground" />
              </button>
            </div>

            <div class="p-5 space-y-4">
              <p class="text-xs text-muted-foreground bg-muted/50 p-2 rounded-lg">
                💡 支持双向同步：Local ↔ S3。同步会复制源端点的文件到目标端点。
              </p>
              
              <div class="space-y-1.5">
                <label class="block text-sm font-medium">源端点</label>
                <select 
                  v-model="syncForm.source_endpoint_id"
                  class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option 
                    v-for="ep in endpoints" 
                    :key="ep.id" 
                    :value="ep.id"
                  >
                    {{ ep.name }} ({{ ep.provider === 'local' ? '本地' : 'S3' }}, {{ ep.location_count }} 张)
                  </option>
                </select>
              </div>

              <div class="flex justify-center">
                <ChevronDown class="w-5 h-5 text-muted-foreground" />
              </div>

              <div class="space-y-1.5">
                <label class="block text-sm font-medium">目标端点</label>
                <select 
                  v-model="syncForm.target_endpoint_id"
                  class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option 
                    v-for="ep in endpoints.filter(e => e.id !== syncForm.source_endpoint_id)" 
                    :key="ep.id" 
                    :value="ep.id"
                  >
                    {{ ep.name }} ({{ ep.provider === 'local' ? '本地' : 'S3' }})
                  </option>
                </select>
              </div>


              <label class="flex items-center gap-3 cursor-pointer">
                <input 
                  v-model="syncForm.force_overwrite"
                  type="checkbox"
                  class="w-4 h-4 rounded border-border"
                />
                <span class="text-sm">强制覆盖已存在的文件</span>
              </label>
            </div>

            <div class="flex justify-end gap-2 p-5 border-t border-border">
              <Button variant="outline" @click="showSyncDialog = false">取消</Button>
              <Button @click="startSync" :disabled="syncing">
                <Loader2 v-if="syncing" class="w-4 h-4 mr-2 animate-spin" />
                <Play v-else class="w-4 h-4 mr-2" />
                开始同步
              </Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 确认弹窗 -->
    <ConfirmDialog
      :open="confirmDialogProps.open"
      :title="confirmDialogProps.title"
      :message="confirmDialogProps.message"
      :confirm-text="confirmDialogProps.confirmText"
      :cancel-text="confirmDialogProps.cancelText"
      :variant="confirmDialogProps.variant"
      :loading="confirmDialogProps.loading"
      :checkbox-label="confirmDialogProps.checkboxLabel"
      :checkbox-checked="confirmDialogProps.checkboxChecked"
      @update:checkbox-checked="confirmDialogProps.checkboxChecked = $event"
      @confirm="handleConfirm"
      @cancel="handleCancel"
    />
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
