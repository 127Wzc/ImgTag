<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError, notifySuccess } from '@/utils/notify'
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
  Check,
  CheckCircle,
  XCircle,
  Star,
  X,
  Save,
  ChevronDown,
  Unlink,
  Square,
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
  public_url_include_bucket: boolean
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
  last_health_check: string | null
  health_check_error: string | null
  has_active_sync: boolean
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
const cancelling = ref<number | null>(null)
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
  public_url_include_bucket: true,
  path_prefix: '',
  path_style: true,
  role: 'primary',
  is_enabled: true,
  is_default_upload: false,
  read_priority: 100,
  read_weight: 1
})

const originalForm = ref({ ...form.value })
const basicLocked = computed(() => !!endpoints.value.find(ep => ep.id === editingEndpoint.value?.id)?.has_active_sync)

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
  const prefix = form.value.public_url_prefix?.replace(/\/+$/, '') || ''
  const pathPrefix = form.value.path_prefix?.replace(/^\/+|\/+$/g, '') || ''
  const example = 'example.jpg'
  const fullPath = pathPrefix ? `${pathPrefix}/${example}` : example
  
  if (prefix) {
    // 有 CDN/公开 URL
    return isLocal.value
      ? `${prefix}/data/${bucket}/${fullPath}`
      : form.value.public_url_include_bucket
        ? `${prefix}/${bucket}/${fullPath}`
        : `${prefix}/${fullPath}`
  } else if (isLocal.value) {
    // 本地相对路径
    return `/data/${bucket}/${fullPath}`
  } else {
    // S3 直接 URL
    const endpoint = form.value.endpoint_url?.replace(/\/+$/, '') || 'https://s3.example.com'
    if (form.value.path_style) {
      return `${endpoint}/${bucket}/${fullPath}`
    }
    try {
      const url = new URL(endpoint)
      url.hostname = `${bucket}.${url.hostname}`
      return `${url.toString().replace(/\/+$/, '')}/${fullPath}`
    } catch {
      // 输入端点地址的过程中可能暂时不是合法 URL。
      return '请输入有效的端点 URL'
    }
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
    notifyError(getErrorMessage(e))
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
    public_url_include_bucket: true,
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
    public_url_include_bucket: ep.public_url_include_bucket ?? true,
    path_prefix: ep.path_prefix,
    path_style: ep.path_style ?? true,
    role: ep.role,
    is_enabled: ep.is_enabled,
    is_default_upload: ep.is_default_upload,
    read_priority: ep.read_priority,
    read_weight: ep.read_weight
  }
  originalForm.value = { ...form.value }
  showDialog.value = true
}

async function saveEndpoint() {
  if (!form.value.name.trim()) {
    notifyError('请输入端点名称', { once: true })
    return
  }
  
  saving.value = true
  try {
    if (editingEndpoint.value) {
      const changed = Object.fromEntries(Object.entries(form.value).filter(
        ([key, value]) => value !== originalForm.value[key as keyof typeof originalForm.value]
      ))
      await apiClient.put(`/storage/endpoints/${editingEndpoint.value.id}`, changed)
      notifySuccess('端点已更新', { once: true })
    } else {
      await apiClient.post('/storage/endpoints', form.value)
      notifySuccess('端点已创建', { once: true })
    }
    showDialog.value = false
    await fetchEndpoints()
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    saving.value = false
  }
}

async function testConnection(ep: StorageEndpoint) {
  testing.value = ep.id
  try {
    const { data } = await apiClient.post(`/storage/endpoints/${ep.id}/test`)
    if (data.success) {
      notifySuccess('连接测试成功', { once: true })
    } else {
      notifyError(data.message || '连接测试失败')
    }
    await fetchEndpoints()
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    testing.value = null
  }
}

async function setDefault(ep: StorageEndpoint) {
  try {
    await apiClient.post(`/storage/endpoints/${ep.id}/set-default`)
    notifySuccess(`已设为默认上传端点: ${ep.name}`, { once: true })
    await fetchEndpoints()
  } catch (e: any) {
    notifyError(getErrorMessage(e))
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
    notifySuccess('端点已删除', { once: true })
    await fetchEndpoints()
  } catch (e: any) {
    notifyError(getErrorMessage(e))
  } finally {
    deleting.value = null
  }
}

async function cancelTasks(ep: StorageEndpoint) {
  const result = await confirm({
    title: '强制中断任务', variant: 'danger', confirmText: '中断',
    message: `中断端点「${ep.name}」涉及的全部同步、解绑和删除任务？已完成的操作保留，已发出的远程请求可能仍会完成。`,
  })
  if (!result.confirmed) return
  cancelling.value = ep.id
  try {
    const { data } = await apiClient.post(`/storage/endpoints/${ep.id}/cancel-tasks`)
    notifySuccess(data.message, { once: true })
    await fetchEndpoints()
  } catch (error) {
    notifyError(getErrorMessage(error))
  } finally {
    cancelling.value = null
  }
}

const unlinkTarget = ref<StorageEndpoint | null>(null)
const unlinkImpact = ref<{ total_locations: number; unique_images: number } | null>(null)
const impactLoading = ref(false)
const impactError = ref('')
const deleteRemoteFiles = ref(false)
const unlinkHasTask = computed(() => !!endpoints.value.find(ep => ep.id === unlinkTarget.value?.id)?.active_task)
const unlinkDisabled = computed(() => unlinking.value !== null || !unlinkImpact.value ||
  (deleteRemoteFiles.value && (unlinkHasTask.value || unlinkImpact.value.total_locations === 0)))

function setUnlinkOpen(open: boolean) {
  if (!open && unlinking.value === null) unlinkTarget.value = null
}

async function unlinkLocations(ep: StorageEndpoint) {
  unlinkTarget.value = ep
  unlinkImpact.value = null
  impactError.value = ''
  impactLoading.value = true
  deleteRemoteFiles.value = false
  try {
    const { data } = await apiClient.get(`/storage/endpoints/${ep.id}/deletion-impact`)
    if (unlinkTarget.value === ep) unlinkImpact.value = data
  } catch (error) {
    if (unlinkTarget.value === ep) impactError.value = getErrorMessage(error)
  } finally {
    if (unlinkTarget.value === ep) impactLoading.value = false
  }
}

async function submitUnlink() {
  const ep = unlinkTarget.value
  if (!ep || unlinkDisabled.value) return
  unlinking.value = ep.id
  try {
    if (!deleteRemoteFiles.value) {
      await apiClient.post(`/storage/endpoints/${ep.id}/force-cleanup`, {
        confirm: true, endpoint_name: ep.name, remove_endpoint: false,
      })
      notifySuccess('本地关联已清理，端点配置保持不变', { once: true })
    } else {
      await apiClient.delete(`/storage/endpoints/${ep.id}/locations`, {
        data: { confirm: true, delete_files: deleteRemoteFiles.value },
      })
      notifySuccess('已提交解除关联任务', { once: true })
    }
    unlinkTarget.value = null
    await fetchEndpoints()
  } catch (error) {
    notifyError(getErrorMessage(error))
  } finally {
    unlinking.value = null
  }
}

// 同步功能
function openSyncDialog() {
  if (endpoints.value.length < 2) {
    notifyError('需要至少 2 个端点才能同步', { once: true })
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
    notifyError('源端点和目标端点不能相同', { once: true })
    return
  }
  syncing.value = true
  try {
    const { data } = await apiClient.post('/storage/sync/start', syncForm.value)
    notifySuccess(`已启动 ${data.task_ids.length} 个同步任务`, { once: true })
    showSyncDialog.value = false
    // 可以轮询任务进度
  } catch (e: any) {
    notifyError(getErrorMessage(e))
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

// 仅有活动任务时，每 10 秒刷新进度。
const POLL_INTERVAL_MS = 10000
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

watch(hasActiveTask, updatePolling)

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
      <!-- 标题区 -->
      <div class="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-foreground flex items-center gap-2">
            <HardDrive class="w-5 h-5 text-primary" />存储端点管理
          </h1>
          <p class="text-sm text-muted-foreground mt-1">配置与管理多个存储后端，支持 S3 兼容存储与自动同步</p>
        </div>
        <div class="flex items-center gap-2">
          <Button variant="outline" size="sm" class="h-9" @click="openSyncDialog" :disabled="endpoints.length < 2">
            <Play class="w-4 h-4 mr-2" />
            同步
          </Button>
          <Button size="sm" class="h-9" @click="openCreate">
            <Plus class="w-4 h-4 mr-2" />
            添加端点
          </Button>
        </div>
      </div>

      <div class="max-w-6xl mx-auto">

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
                <span class="text-xs text-muted-foreground">{{ ep.role === 'backup' ? '备份端点' : '主端点' }}</span>
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
                <span class="flex items-center gap-1" :title="ep.last_health_check ? `${new Date(ep.last_health_check).toLocaleString()} ${ep.health_check_error || ''}` : '尚未手动测试连接'">
                  <component :is="ep.is_healthy ? CheckCircle : XCircle" 
                             :class="ep.is_healthy ? 'text-green-500' : 'text-red-500'" 
                             class="w-3.5 h-3.5" />
                  {{ !ep.last_health_check ? '未测试' : ep.is_healthy ? '上次测试成功' : '上次测试失败' }}
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
                    {{ ['cancelled', 'failed', 'completed'].includes(ep.active_task.status) ? '等待远程删除收尾' : ep.active_task.status === 'pending' ? '排队中' : ep.active_task.task_type === 'storage_sync' ? '同步中' :
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
                :disabled="testing === ep.id"
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
                :disabled="ep.role === 'backup'"
                title="设为默认上传端点（备份端点需先切换为主端点）"
              >
                <Star class="w-4 h-4" />
              </Button>
              <Button 
                variant="ghost" 
                size="sm"
                @click="openEdit(ep)"
                title="编辑配置"
              >
                <Pencil class="w-4 h-4" />
              </Button>
              <Button v-if="ep.active_task" variant="ghost" size="sm"
                      @click="cancelTasks(ep)" :disabled="cancelling === ep.id" title="强制中断全部相关任务">
                <Square class="w-4 h-4" />
                <span class="sr-only">强制中断</span>
              </Button>
              <Button v-if="ep.id !== 1" variant="ghost" size="sm"
                      class="text-amber-600 hover:text-amber-600" @click="unlinkLocations(ep)"
                      :disabled="unlinking === ep.id" title="解除关联">
                <Loader2 v-if="unlinking === ep.id" class="w-4 h-4 animate-spin" />
                <Unlink v-else class="w-4 h-4" />
                <span class="sr-only">解除关联</span>
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
          <div role="dialog" aria-modal="true" aria-labelledby="endpoint-dialog-title" class="relative flex flex-col bg-card border border-border rounded-lg shadow-lg w-full max-w-3xl max-h-[calc(100dvh-2rem)] overflow-hidden m-4">
            <!-- 头部 -->
            <div class="flex shrink-0 items-center justify-between px-5 py-3 border-b border-border">
              <h2 id="endpoint-dialog-title" class="text-lg font-semibold text-foreground">
                {{ editingEndpoint ? '编辑端点' : '创建端点' }}
              </h2>
              <button @click="showDialog = false" class="p-1.5 hover:bg-muted rounded-lg" aria-label="关闭">
                <X class="w-5 h-5 text-muted-foreground" />
              </button>
            </div>

            <!-- 表单 -->
            <div class="min-h-0 overflow-y-auto px-4 py-3 sm:px-5 space-y-2.5">
              <p v-if="basicLocked" class="text-xs text-amber-600 dark:text-amber-400">
                同步中，基础配置已锁定；仍可调整读取策略、启停和主备角色。主备切换仅影响后续任务。
              </p>
              <fieldset :disabled="basicLocked" class="min-w-0 space-y-2.5">
                <div class="grid gap-3 sm:grid-cols-2">
                  <!-- 名称与类型 -->
                  <div class="space-y-1" :class="{ 'sm:col-span-2': isDefaultEndpoint }">
                    <label for="endpoint-name" class="block text-sm font-medium">端点名称</label>
                    <Input
                      id="endpoint-name"
                      v-model="form.name"
                      type="text"
                      placeholder="如: 阿里云主存储"
                      :disabled="isDefaultEndpoint"
                    />
                  </div>

                  <!-- 类型 (隐藏默认端点的类型选择) -->
                  <div v-if="!isDefaultEndpoint" class="space-y-1">
                    <label class="block text-sm font-medium">存储类型</label>
                    <div class="grid grid-cols-2 gap-2">
                      <Button
                        v-for="p in providers"
                        :key="p.value"
                        @click="form.provider = p.value"
                        :aria-pressed="form.provider === p.value"
                        type="button"
                        :variant="form.provider === p.value ? 'default' : 'outline'"
                        class="relative w-full px-6"
                      >
                        <component :is="p.icon" class="w-4 h-4" />
                        {{ p.label.split(' ')[0] }}
                        <Check v-if="form.provider === p.value" class="absolute right-2 w-3.5 h-3.5" aria-hidden="true" />
                      </Button>
                    </div>
                  </div>

                </div>

                <!-- S3 专属配置 -->
                <template v-if="isS3Like && !isDefaultEndpoint">
                  <div class="grid grid-cols-[minmax(0,1fr)_6rem] sm:grid-cols-[minmax(0,1fr)_8rem] gap-3">
                    <div class="min-w-0 space-y-1">
                      <label for="endpoint-url" class="block text-sm font-medium">端点 URL</label>
                      <Input
                        id="endpoint-url"
                        v-model="form.endpoint_url"
                        type="text"
                        placeholder="https://s3.amazonaws.com"
                      />
                    </div>

                    <div class="space-y-1">
                      <label for="endpoint-region" class="block text-sm font-medium">区域</label>
                      <Input
                        id="endpoint-region"
                        v-model="form.region"
                        type="text"
                        placeholder="auto"
                      />
                    </div>

                  </div>

                  <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div class="space-y-1">
                      <label for="endpoint-access-key" class="block text-sm font-medium">Access Key ID</label>
                      <Input
                        id="endpoint-access-key"
                        v-model="form.access_key_id"
                        :type="showCredentials ? 'text' : 'password'"
                        class="font-mono"
                        placeholder=""
                      />
                    </div>
                    <div class="space-y-1">
                      <label for="endpoint-secret-key" class="block text-sm font-medium">Secret Access Key</label>
                      <Input
                        id="endpoint-secret-key"
                        v-model="form.secret_access_key"
                        :type="showCredentials ? 'text' : 'password'"
                        class="font-mono"
                        placeholder=""
                      />
                    </div>
                  </div>
                  <div class="flex flex-wrap items-center gap-x-6 gap-y-2">
                    <label class="flex items-center gap-2 cursor-pointer text-sm text-muted-foreground">
                      <Checkbox :model-value="showCredentials" @update:model-value="showCredentials = $event === true" />
                      <span>显示密钥</span>
                    </label>

                    <label class="flex items-center gap-2 cursor-pointer" title="控制 S3 请求中的桶名位置，不影响公开地址类型">
                      <Checkbox :model-value="form.path_style" @update:model-value="form.path_style = $event === true" />
                      <span class="text-sm">路径风格 (Path Style)</span>
                    </label>
                  </div>
                </template>

                <!-- 通用存储配置 (所有端点) -->
                <div class="space-y-2.5 pt-3 border-t border-border/50">
                  <div class="grid grid-cols-2 gap-3">
                    <div class="space-y-1" :class="{ 'col-span-2': isDefaultEndpoint }">
                      <label for="endpoint-bucket" class="block text-sm font-medium">
                        {{ isLocal ? '存储目录 (Bucket)' : 'Bucket 名称' }}
                      </label>
                      <Input
                        id="endpoint-bucket"
                        v-model="form.bucket_name"
                        type="text"
                        :placeholder="isLocal ? 'uploads' : 'my-bucket'"
                        :disabled="!!(editingEndpoint && editingEndpoint.location_count > 0)"
                      />
                    </div>
                    <div v-if="!isDefaultEndpoint" class="space-y-1">
                      <label for="endpoint-path-prefix" class="block text-sm font-medium">路径前缀</label>
                      <Input
                        id="endpoint-path-prefix"
                        v-model="form.path_prefix"
                        type="text"
                        placeholder="可选，如 images/"
                        :disabled="!!(editingEndpoint && editingEndpoint.location_count > 0)"
                      />
                    </div>
                  </div>

                  <p v-if="editingEndpoint && editingEndpoint.location_count > 0" class="text-xs text-amber-600 dark:text-amber-400">
                    已关联 {{ editingEndpoint.location_count }} 张图片，存储目录与路径前缀已锁定
                  </p>

                  <div class="grid gap-3" :class="{ 'sm:grid-cols-[minmax(0,1fr)_14rem]': isS3Like && form.public_url_prefix }">
                    <div class="min-w-0 space-y-1">
                      <label for="endpoint-public-url" class="block text-sm font-medium">公开 URL 前缀</label>
                      <Input
                        id="endpoint-public-url"
                        v-model="form.public_url_prefix"
                        type="text"
                        placeholder="https://cdn.example.com"
                      />
                    </div>
                    <div v-if="isS3Like && form.public_url_prefix" class="space-y-1">
                      <label for="public-url-type" class="block text-sm font-medium">公开地址类型</label>
                      <Select
                        :model-value="form.public_url_include_bucket ? 'service' : 'bucket'"
                        @update:model-value="form.public_url_include_bucket = $event === 'service'"
                      >
                        <SelectTrigger id="public-url-type" class="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="service">服务地址（追加桶名）</SelectItem>
                          <SelectItem value="bucket">桶专属地址（不追加桶名）</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <p class="text-xs text-muted-foreground">
                    {{ isLocal ? '留空使用本站地址' : 'R2 填写公开域名，选择桶专属地址' }}
                  </p>

                  <!-- URL 预览 -->
                  <div class="px-3 py-2 bg-muted/40 rounded-md">
                    <p class="text-xs text-muted-foreground mb-1">访问地址示例</p>
                    <code class="block text-xs text-foreground break-all">{{ urlPreview }}</code>
                  </div>
                </div>

              </fieldset>
              <details class="group pt-3 border-t border-border/50">
                <summary class="flex items-center justify-between cursor-pointer list-none text-sm">
                  <span class="font-medium">高级设置</span>
                  <span class="flex items-center gap-2 text-xs text-muted-foreground">
                    读取策略{{ !isDefaultEndpoint ? '、端点角色' : '' }}
                    <ChevronDown class="w-4 h-4 transition-transform group-open:rotate-180" />
                  </span>
                </summary>
                <!-- 读取策略配置 (所有端点通用) -->
                <div class="space-y-3 mt-3">
                  <div class="grid grid-cols-2 gap-3">
                    <div class="space-y-1">
                      <label for="endpoint-priority" class="block text-sm font-medium">读取优先级</label>
                      <Input
                        id="endpoint-priority"
                        v-model.number="form.read_priority"
                        type="number"
                      />
                      <p class="text-xs text-muted-foreground">数值越小越优先</p>
                    </div>
                    <div class="space-y-1">
                      <label for="endpoint-weight" class="block text-sm font-medium">负载权重</label>
                      <Input
                        id="endpoint-weight"
                        v-model.number="form.read_weight"
                        type="number"
                        min="0"
                      />
                      <p class="text-xs text-muted-foreground">同优先级按权重分配</p>
                    </div>
                  </div>
                </div>

                <!-- 开关选项 (非默认端点) -->
                <div v-if="!isDefaultEndpoint" class="space-y-3 mt-3">
                  <!-- 角色选择 -->
                  <div class="space-y-1">
                    <label class="block text-sm font-medium">端点角色</label>
                    <div class="grid grid-cols-2 gap-2">
                      <Button
                        v-for="r in roles"
                        :key="r.value"
                        @click="form.role = r.value; if (r.value === 'backup') form.is_default_upload = false"
                        :aria-pressed="form.role === r.value"
                        :title="r.description"
                        type="button"
                        :variant="form.role === r.value ? 'default' : 'outline'"
                        class="relative w-full px-6"
                      >
                        <div class="font-medium">{{ r.label }}</div>
                        <Check v-if="form.role === r.value" class="absolute right-2 w-3.5 h-3.5" aria-hidden="true" />
                      </Button>
                    </div>
                  </div>

                  <!-- 备份端点提示 -->
                  <p v-if="form.role === 'backup'" class="text-xs text-muted-foreground">
                    自动同步主端点图片；切换为备份后，原备份端点将转为主端点。正在执行的同步方向保持不变。
                  </p>

                </div>
              </details>

              <!-- 其他开关 -->
              <div v-if="!isDefaultEndpoint" class="flex flex-wrap items-center gap-x-6 gap-y-2">
                <label class="flex items-center gap-3 cursor-pointer">
                  <Checkbox :model-value="form.is_enabled" @update:model-value="form.is_enabled = $event === true" />
                  <span class="text-sm">启用端点</span>
                </label>
                <label class="flex items-center gap-3 cursor-pointer">
                  <Checkbox :model-value="form.is_default_upload" :disabled="form.role === 'backup'" @update:model-value="form.is_default_upload = $event === true" />
                  <span class="text-sm">默认上传</span>
                </label>
              </div>
            </div>

            <!-- 底部按钮 -->
            <div class="flex shrink-0 justify-end gap-2 px-5 py-3 border-t border-border">
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

    <Dialog :open="unlinkTarget !== null" @update:open="setUnlinkOpen">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>解除关联</DialogTitle>
          <DialogDescription>
            <template v-if="deleteRemoteFiles">删除「{{ unlinkTarget?.name }}」的远程文件，并解除对应关联。</template>
            <template v-else>解除「{{ unlinkTarget?.name }}」的图片位置关联，不删除远程文件。</template>
          </DialogDescription>
        </DialogHeader>
        <div class="space-y-4 text-sm">
          <p v-if="impactLoading" class="text-muted-foreground">正在统计关联…</p>
          <p v-else-if="impactError" class="text-destructive" role="alert">{{ impactError }}</p>
          <p v-else-if="unlinkImpact" class="text-muted-foreground">
            共 {{ unlinkImpact.total_locations }} 条关联。
            <span v-if="unlinkImpact.unique_images > 0" class="text-destructive">
              其中 {{ unlinkImpact.unique_images }} 张图片仅位于此端点，{{ deleteRemoteFiles ? '文件删除成功后将同时删除图库记录' : '解除后将无可用地址' }}。
            </span>
          </p>
          <label for="unlink-delete-files" class="flex items-center gap-3">
            <Checkbox id="unlink-delete-files" :model-value="deleteRemoteFiles" :disabled="unlinking !== null"
                      @update:model-value="deleteRemoteFiles = $event === true" />
            <span>同时删除远程文件</span>
          </label>
          <p v-if="deleteRemoteFiles" class="text-xs text-destructive">文件删除成功后，无其他副本的图片将从图库删除；有其他副本则保留。此操作不可恢复，失败项保留关联。</p>
          <p v-if="!deleteRemoteFiles" class="text-xs text-muted-foreground">
            仅清理本地关联并中断相关任务，不访问远程存储，端点配置保持不变。如有远程删除在途，请确认请求结束后再操作。
          </p>
          <p v-else-if="unlinkHasTask" class="text-xs text-destructive">端点有进行中的任务，请先中断任务再删除远程文件。</p>
        </div>
        <DialogFooter>
          <Button variant="outline" :disabled="unlinking !== null" @click="setUnlinkOpen(false)">取消</Button>
          <Button variant="destructive" :disabled="unlinkDisabled" @click="submitUnlink">
            <Loader2 v-if="unlinking !== null" class="mr-2 h-4 w-4 animate-spin" />
            解除关联
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

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
