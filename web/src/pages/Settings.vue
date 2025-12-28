<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
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
  ListTodo,
  HardDrive,
  Settings2,
  X,
  ChevronRight,
  RefreshCw,
  Wrench,
  Database,
  FolderSync,
  AlertTriangle,
  CheckCircle
} from 'lucide-vue-next'

const categories = [
  { key: 'vision', label: '视觉模型', icon: Eye, description: 'AI 图片分析和标签提取', color: 'text-violet-500 bg-violet-500/10' },
  { key: 'embedding', label: '向量嵌入', icon: Brain, description: '语义搜索向量化配置', color: 'text-blue-500 bg-blue-500/10' },
  { key: 'queue', label: '队列上传', icon: ListTodo, description: '任务并发与上传限制', color: 'text-amber-500 bg-amber-500/10' },
  { key: 'storage', label: '存储配置', icon: HardDrive, description: 'S3 兼容对象存储', color: 'text-emerald-500 bg-emerald-500/10' },
  { key: 'system', label: '系统设置', icon: Settings2, description: '基础系统配置项', color: 'text-slate-500 bg-slate-500/10' },
  { key: 'maintenance', label: '系统维护', icon: Wrench, description: '重复检测与存储清理', color: 'text-rose-500 bg-rose-500/10' },
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
  storage: [
    { key: 's3_enabled', label: '启用 S3 存储', type: 'boolean', description: '启用后图片存储到 S3' },
    { key: 's3_endpoint_url', label: '端点地址', type: 'text', showWhen: { key: 's3_enabled', value: 'true' } },
    { key: 's3_access_key_id', label: 'Access Key', type: 'text', showWhen: { key: 's3_enabled', value: 'true' } },
    { key: 's3_secret_access_key', label: 'Secret Key', type: 'password', showWhen: { key: 's3_enabled', value: 'true' } },
    { key: 's3_bucket_name', label: 'Bucket', type: 'text', showWhen: { key: 's3_enabled', value: 'true' } },
    { key: 's3_region', label: '区域', type: 'text', showWhen: { key: 's3_enabled', value: 'true' } },
    { key: 's3_public_url_prefix', label: '公开 URL 前缀', type: 'text', showWhen: { key: 's3_enabled', value: 'true' } },
    { key: 's3_path_prefix', label: '路径前缀', type: 'text', showWhen: { key: 's3_enabled', value: 'true' } },
    { key: 's3_force_reupload', label: '强制重新上传', type: 'boolean', description: '批量同步时覆盖已有 S3 文件', showWhen: { key: 's3_enabled', value: 'true' } },
    { key: 'image_url_priority', label: 'URL 优先级', type: 'select', options: [
      { value: 'auto', label: '自动' },
      { value: 's3', label: 'S3 优先' },
      { value: 'local', label: '本地优先' },
    ] },
  ],
  system: [
    { key: 'base_url', label: '系统基础 URL', type: 'text', description: '用于生成分享链接' },
    { key: 'allow_register', label: '允许注册', type: 'boolean' },
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
  try {
    const { data } = await apiClient.get('/system/models')
    availableModels.value = data.models || []
    if (data.error) modelsError.value = data.error
  } catch {
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
        changedConfigs[key] = configs.value[key]
      }
    }
    if (Object.keys(changedConfigs).length === 0) {
      activeCategory.value = null
      return
    }

    await apiClient.put('/config/', { configs: changedConfigs })
    originalConfigs.value = { ...configs.value }
    activeCategory.value = null
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

// ========== S3 存储管理 ==========
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

                <!-- S3 存储管理 -->
                <div class="p-4 bg-muted/50 rounded-xl">
                  <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                      <HardDrive class="w-5 h-5 text-emerald-500" />
                      <h3 class="font-medium text-foreground">S3 存储管理</h3>
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
                      <p class="text-xs text-muted-foreground">已上传 S3</p>
                    </div>
                    <div class="p-3 bg-background rounded-lg">
                      <p class="text-2xl font-semibold text-amber-500">{{ s3Stats.local_only }}</p>
                      <p class="text-xs text-muted-foreground">仅本地</p>
                    </div>
                  </div>

                  <!-- 同步按钮 -->
                  <div v-if="s3Stats && s3Stats.local_only > 0" class="flex items-center justify-between p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
                    <div>
                      <p class="text-sm font-medium text-foreground">{{ s3Stats.local_only }} 张图片未上传 S3</p>
                      <p class="text-xs text-muted-foreground">点击同步将本地图片上传到 S3</p>
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
                    <p class="text-sm text-foreground">所有图片均已上传 S3</p>
                  </div>

                  <div v-else class="text-center py-4 text-muted-foreground text-sm">
                    点击刷新查看 S3 存储状态
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

                        <!-- Combobox -->
                        <template v-else-if="def.type === 'combobox'">
                          <div class="relative">
                            <input
                              :id="def.key"
                              v-model="configs[def.key]"
                              type="text"
                              list="model-options"
                              class="w-full px-3 py-1.5 text-sm bg-muted/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring pr-8"
                              placeholder="选择或输入"
                            />
                            <button 
                              type="button"
                              @click="fetchModels"
                              :disabled="modelsLoading"
                              class="absolute right-1 top-1/2 -translate-y-1/2 p-1 hover:bg-muted rounded"
                            >
                              <RefreshCw :class="['w-3.5 h-3.5 text-muted-foreground', modelsLoading && 'animate-spin']" />
                            </button>
                            <datalist id="model-options">
                              <option v-for="model in availableModels" :key="model" :value="model" />
                            </datalist>
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
