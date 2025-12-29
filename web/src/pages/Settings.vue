<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted } from 'vue'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import ImageDetailModal from '@/components/ImageDetailModal.vue'
import { toast } from 'vue-sonner'
import { getErrorMessage } from '@/utils/api-error'
import { 
  Save,
  Loader2,
  Eye,
  Brain,
  Cloud,
  ListTodo,
  X,
  ChevronRight,
  RefreshCw,
  Wrench,
  Database,
  FolderSync,
  AlertTriangle,
  CheckCircle,
  RotateCw,
  ChevronDown
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
  { key: 'queue', label: '队列上传', icon: ListTodo, description: '任务并发与上传限制', color: 'text-amber-500 bg-amber-500/10' },
  { key: 'maintenance', label: '系统维护', icon: Wrench, description: '系统设置与存储清理', color: 'text-rose-500 bg-rose-500/10' },
]

// 配置项定义 - 支持 showWhen 条件
interface ConfigDef {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'boolean' | 'select' | 'textarea' | 'combobox'
  description?: string
  options?: { value: string; label: string }[]
  showWhen?: { key: string; value: string }
}

const configDefinitions: Record<string, ConfigDef[]> = {
  vision: [
    { key: 'vision_api_base_url', label: 'API 地址', type: 'text', description: 'OpenAI 兼容端点' },
    { key: 'vision_api_key', label: 'API 密钥', type: 'password' },
    { key: 'vision_model', label: '模型名称', type: 'combobox', description: '可选择或手动输入' },
    { key: 'vision_prompt', label: '分析提示词', type: 'textarea', description: '控制输出格式和风格' },
    { key: 'vision_allowed_extensions', label: '允许的扩展名', type: 'text' },
    { key: 'vision_convert_gif', label: 'GIF 转静态图', type: 'boolean' },
    { key: 'vision_max_image_size', label: '压缩阈值 (KB)', type: 'number' },
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
    { key: 'embedding_api_base_url', label: 'API 地址', type: 'text', showWhen: { key: 'embedding_mode', value: 'api' } },
    { key: 'embedding_api_key', label: 'API 密钥', type: 'password', showWhen: { key: 'embedding_mode', value: 'api' } },
    { key: 'embedding_model', label: 'API 模型', type: 'text', showWhen: { key: 'embedding_mode', value: 'api' } },
    { key: 'embedding_dimensions', label: '向量维度', type: 'number' },
  ],
  queue: [
    { key: 'queue_max_workers', label: '最大并发数', type: 'number' },
    { key: 'queue_batch_interval', label: '批处理间隔 (秒)', type: 'number' },
    { key: 'max_upload_size', label: '最大上传 (MB)', type: 'number' },
  ],
  maintenance: [
    { key: 'allow_register', label: '允许注册', type: 'boolean', description: '关闭后禁止新用户注册' },
  ],
}

const activeCategory = ref<string | null>(null)
const loading = ref(false)
const saving = ref(false)
const configs = ref<Record<string, string>>({})
const originalConfigs = ref<Record<string, string>>({})

// 模型列表（用于 combobox）
const availableModels = ref<string[]>([])
const modelsLoading = ref(false)
const modelsError = ref('')

async function fetchModels() {
  modelsLoading.value = true
  modelsError.value = ''
  
  // 使用表单中的值验证，通过后端代理请求避免 CORS 问题
  const apiBaseUrl = configs.value['vision_api_base_url']
  const apiKey = configs.value['vision_api_key']
  
  if (!apiBaseUrl || !apiKey || apiKey === '******') {
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
    modelsError.value = '获取模型列表失败'
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
    if (current === '******' || original === '******') continue
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
    configs.value = { ...data }
    originalConfigs.value = { ...data }
  } catch (e) {
    console.error('Failed to load configs', e)
  } finally {
    loading.value = false
  }
}

async function saveConfigs() {
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
      toast.success('保存成功，请根据提示检查是否需要重建向量')
      fetchVectorStatus() // 刷新状态以更新 dimensions_match
    }
  } catch (e: any) {
    alert(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function closeDrawer() {
  if (hasChanges.value && !confirm('有未保存的更改，确定关闭？')) return
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
  } catch (e: any) {
    alert(e.response?.data?.detail || '扫描失败')
  } finally {
    scanning.value = false
  }
}

async function calculateHashes() {
  calculating.value = true
  try {
    const { data } = await apiClient.post('/system/duplicates/calculate-hashes')
    alert(`计算完成: 处理了 ${data.processed || 0} 张图片`)
    imagesWithoutHash.value = data.remaining || 0
  } catch (e: any) {
    alert(e.response?.data?.detail || '计算失败')
  } finally {
    calculating.value = false
  }
}

async function deleteImage(imageId: number) {
  if (!confirm('确定删除这张图片？此操作不可恢复。')) return
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
  } catch (e: any) {
    alert(e.response?.data?.detail || '删除失败')
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
interface VectorStatus {
  image_count: number
  embedding_mode: string
  embedding_model: string
  embedding_dimensions: number
  db_dimensions: number
  dimensions_match: boolean
  rebuild_status: {
    is_running: boolean
    total: number
    processed: number
    failed: number
    message: string
  }
}

const vectorStatus = ref<VectorStatus | null>(null)
const vectorLoading = ref(false)
const rebuilding = ref(false)
const resizing = ref(false)

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
  if (!confirm('确定要重建所有向量吗？这可能需要很长时间，期间搜索功能将受限。')) return
  rebuilding.value = true
  try {
    await apiClient.post('/vectors/rebuild')
    toast.success('重建任务已启动')
    pollRebuildStatus()
  } catch(e: any) {
    alert(e.response?.data?.detail || '启动失败')
    rebuilding.value = false
  }
}

async function resizeVectorTable() {
  if (!confirm('确定要修改数据库向量维度吗？这将清空现有索引，建议随后立即重建向量。')) return
  resizing.value = true
  try {
    const { data } = await apiClient.post('/vectors/resize-table')
    toast.success(data.message)
    await fetchVectorStatus()
  } catch(e: any) {
    alert(e.response?.data?.detail || '修改失败')
  } finally {
    resizing.value = false
  }
}

let pollTimer: any = null
function pollRebuildStatus() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const { data } = await apiClient.get('/vectors/rebuild/status')
      if (vectorStatus.value) {
        vectorStatus.value.rebuild_status = data
      }
      if (!data.is_running) {
        clearInterval(pollTimer)
        pollTimer = null
        rebuilding.value = false
        if (data.processed > 0) toast.success('向量重建完成')
        fetchVectorStatus()
      } else {
        rebuilding.value = true
      }
    } catch {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }, 2000)
}

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

// 监听分类切换
import { watch } from 'vue'
watch(activeCategory, (newVal) => {
  if (newVal === 'embedding') {
    fetchVectorStatus()
  } else if (newVal === 'storage') {
    fetchS3Stats()
  }
})

// ========== 存储同步状态 ==========
interface S3Stats {
  total: number
  with_s3: number
  local_only: number
  s3_only: number
}

const s3Stats = ref<S3Stats | null>(null)
const s3Loading = ref(false)
const s3Syncing = ref(false)

async function fetchS3Stats() {
  s3Loading.value = true
  try {
    const { data } = await apiClient.get<S3Stats>('/storage/status')
    s3Stats.value = data
  } catch (e: any) {
    console.error('获取存储统计失败', e)
  } finally {
    s3Loading.value = false
  }
}

async function syncToS3() {
  s3Syncing.value = true
  try {
    const { data } = await apiClient.post('/storage/sync-to-s3', {})
    toast.success(`已同步 ${data.success} 张图片到 S3`)
    if (data.failed > 0) {
      toast.warning(`${data.failed} 张同步失败`)
    }
    await fetchS3Stats()
  } catch (e: any) {
    toast.error(getErrorMessage(e))
  } finally {
    s3Syncing.value = false
  }
}

onMounted(() => fetchConfigs())
</script>

<template>
  <div class="p-6 lg:p-8">
    <div class="max-w-4xl mx-auto">
      <h1 class="text-xl font-semibold text-foreground mb-6">系统设置</h1>

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



                <!-- S3 同步状态（保留） -->
                <div class="p-4 bg-muted/50 rounded-xl">
                  <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                      <FolderSync class="w-5 h-5 text-emerald-500" />
                      <h3 class="font-medium text-foreground">同步状态</h3>
                    </div>
                    <Button 
                      variant="outline"
                      size="sm"
                      @click="fetchS3Stats"
                      :disabled="s3Loading"
                    >
                      <Loader2 v-if="s3Loading" class="w-4 h-4 mr-1 animate-spin" />
                      <RefreshCw v-else class="w-4 h-4 mr-1" />
                      刷新
                    </Button>
                  </div>

                  <!-- S3 统计 -->
                  <div v-if="s3Stats" class="grid grid-cols-2 gap-3 mb-4">
                    <div class="p-3 bg-background rounded-lg">
                      <p class="text-2xl font-semibold text-foreground">{{ s3Stats.with_s3 }}</p>
                      <p class="text-xs text-muted-foreground">已同步远程</p>
                    </div>
                    <div class="p-3 bg-background rounded-lg">
                      <p class="text-2xl font-semibold text-amber-500">{{ s3Stats.local_only }}</p>
                      <p class="text-xs text-muted-foreground">仅本地</p>
                    </div>
                  </div>

                  <!-- 同步按钮 -->
                  <div v-if="s3Stats && s3Stats.local_only > 0" class="flex items-center justify-between p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
                    <div>
                      <p class="text-sm font-medium text-foreground">{{ s3Stats.local_only }} 张图片未同步</p>
                      <p class="text-xs text-muted-foreground">同步到默认上传端点</p>
                    </div>
                    <Button 
                      size="sm"
                      @click="syncToS3()"
                      :disabled="s3Syncing"
                    >
                      <Loader2 v-if="s3Syncing" class="w-4 h-4 mr-1 animate-spin" />
                      同步 10 张
                    </Button>
                  </div>

                  <div v-else-if="s3Stats && s3Stats.local_only === 0" class="p-3 bg-green-500/10 border border-green-500/20 rounded-lg flex items-center gap-2">
                    <CheckCircle class="w-4 h-4 text-green-500" />
                    <p class="text-sm text-foreground">所有图片均已同步</p>
                  </div>

                  <div v-else class="text-center py-4 text-muted-foreground text-sm">
                    点击刷新查看同步状态
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
                        placeholder="https://api.openai.com/v1"
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
                        <div class="text-muted-foreground mb-0.5">模型输出维度</div>
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
                         <span v-else>
                           {{ rebuilding ? '重建中...' : '重建所有向量' }}
                         </span>
                      </Button>
                    </div>

                    <!-- 重建进度条 -->
                    <div v-if="vectorStatus.rebuild_status.is_running || rebuilding" class="space-y-1.5 pt-2 border-t border-border/50">
                       <div class="flex justify-between text-xs text-muted-foreground">
                         <span>重建进度</span>
                         <span>{{ vectorStatus.rebuild_status.processed }} / {{ vectorStatus.rebuild_status.total }}</span>
                       </div>
                       <div class="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                         <div 
                           class="h-full bg-primary transition-all duration-500"
                           :style="{ width: `${(vectorStatus.rebuild_status.processed / (vectorStatus.rebuild_status.total || 1)) * 100}%` }"
                         />
                       </div>
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
                    <textarea
                      :id="def.key"
                      v-model="configs[def.key]"
                      rows="6"
                      class="w-full px-3 py-2 bg-muted/50 border border-border rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring resize-none"
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
                            class="w-full px-3 py-1.5 text-sm bg-muted/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
                          />
                        </template>
                      </div>
                    </div>
                  </template>
                </div>
              </template>
            </div>

            <!-- 底部操作 -->
            <div v-if="activeCategory !== 'maintenance'" class="p-6 border-t border-border flex justify-end gap-2">
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
