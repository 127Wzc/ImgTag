<script setup lang="ts">
/**
 * UploadDialog - 上传图片弹框
 * 支持拖拽上传、ZIP 压缩包、URL 添加
 */
import { ref, computed, watch, watchEffect } from 'vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useUploadImage, useUploadZip, useUploadFromUrl, useCategories } from '@/api/queries'
import apiClient from '@/api/client'
import { useUserStore } from '@/stores/user'
import type { UploadAnalyzeResponse } from '@/types'
import { 
  Upload as UploadIcon, 
  Image, 
  X, 
  Loader2, 
  CheckCircle, 
  AlertCircle,
  FileArchive,
  Link,
  Folder,
  Sparkles,
  HardDrive,
  Globe,
  Lock,
} from 'lucide-vue-next'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const userStore = useUserStore()
const isAdmin = computed(() => userStore.isAdmin)

// 上传模式
type UploadMode = 'file' | 'zip' | 'url'
const uploadMode = ref<UploadMode>('file')

// 上传选项
const autoAnalyze = ref(false)
const selectedCategoryId = ref<number | null>(null)
const isPublic = ref(true)  // 是否公开，默认公开

// 获取主分类列表
const { data: categories } = useCategories()

// 默认选中"其他"分类
watchEffect(() => {
  if (categories.value && categories.value.length > 0 && selectedCategoryId.value === null) {
    const otherCategory = categories.value.find(c => c.name === '其他')
    if (otherCategory) {
      selectedCategoryId.value = otherCategory.id
    }
  }
})

// 存储端点（仅管理员）
interface StorageEndpoint {
  id: number
  name: string
  provider: string
  role: string
  is_default_upload: boolean
}
const endpoints = ref<StorageEndpoint[]>([])
const selectedEndpointId = ref<number | null>(null)

async function fetchEndpoints() {
  try {
    const { data } = await apiClient.get<StorageEndpoint[]>('/storage/endpoints?enabled_only=true')
    // 过滤掉备份端点，不允许直接上传
    endpoints.value = data.filter(ep => ep.role !== 'backup')
    // 默认选择默认上传端点
    const defaultEp = data.find(ep => ep.is_default_upload)
    if (defaultEp) {
      selectedEndpointId.value = defaultEp.id
    }
  } catch (e) {
    // 忽略错误，使用默认端点
  }
}

// 当 dialog 打开时获取端点列表（管理员）
watch(() => props.open, async (isOpen) => {
  if (isOpen && isAdmin.value && endpoints.value.length === 0) {
    await fetchEndpoints()
  }
}, { immediate: true })

// 当用户登录状态变化时（例如从未登录变为管理员）
watch(isAdmin, async (admin) => {
  if (admin && props.open && endpoints.value.length === 0) {
    await fetchEndpoints()
  }
})

interface FileItem {
  file: File
  id: string
  status: 'pending' | 'uploading' | 'success' | 'error'
  progress: number
  preview: string
  result?: UploadAnalyzeResponse
  error?: string
}

const isDragging = ref(false)
const files = ref<FileItem[]>([])
const urlInput = ref('')
const urlUploading = ref(false)
const urlResults = ref<{ url: string; status: 'pending' | 'success' | 'error'; error?: string }[]>([])

const uploadMutation = useUploadImage()
const zipMutation = useUploadZip()
const urlMutation = useUploadFromUrl()

const shouldAnalyze = computed(() => isAdmin.value && autoAnalyze.value)

// 关闭弹框时清理状态
watch(() => props.open, (open) => {
  if (!open) {
    files.value = []
    urlInput.value = ''
    urlResults.value = []
    uploadMode.value = 'file'
  }
})

function handleDragOver(e: DragEvent) {
  e.preventDefault()
  isDragging.value = true
}

function handleDragLeave() {
  isDragging.value = false
}

function handleDrop(e: DragEvent) {
  e.preventDefault()
  isDragging.value = false
  const droppedFiles = Array.from(e.dataTransfer?.files || [])
  
  const zipFile = droppedFiles.find(f => f.name.toLowerCase().endsWith('.zip'))
  if (zipFile) {
    uploadMode.value = 'zip'
    addFiles([zipFile])
  } else {
    uploadMode.value = 'file'
    addFiles(droppedFiles.filter(f => f.type.startsWith('image/')))
  }
}

function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement
  addFiles(Array.from(target.files || []))
  target.value = ''
}

function handleZipSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files?.[0]) addFiles([target.files[0]])
  target.value = ''
}

function addFiles(newFiles: File[]) {
  const items: FileItem[] = newFiles.map(file => ({
    file,
    id: Math.random().toString(36).slice(2),
    status: 'pending',
    progress: 0,
    preview: file.type.startsWith('image/') ? window.URL.createObjectURL(file) : '',
  }))
  files.value.push(...items)
}

function removeFile(id: string) {
  files.value = files.value.filter(f => f.id !== id)
}

async function uploadSingle(item: FileItem) {
  item.status = 'uploading'
  item.progress = 0
  
  const progressInterval = setInterval(() => {
    if (item.progress < 90) item.progress += 10
  }, 200)
  
  try {
    if (item.file.name.toLowerCase().endsWith('.zip')) {
      const result = await zipMutation.mutateAsync({
        file: item.file,
        categoryId: selectedCategoryId.value ?? undefined,
      })
      clearInterval(progressInterval)
      item.progress = 100
      item.status = 'success'
      item.result = {
        id: 0,
        image_url: '',
        tags: [],
        description: `成功上传 ${result.uploaded_count} 张图片`,
        process_time: '',
      }
    } else {
      const result = await uploadMutation.mutateAsync({
        file: item.file,
        autoAnalyze: shouldAnalyze.value,
        skipAnalyze: !shouldAnalyze.value,
        categoryId: selectedCategoryId.value ?? undefined,
        endpointId: selectedEndpointId.value ?? undefined,
        isPublic: isPublic.value,
      })
      clearInterval(progressInterval)
      item.progress = 100
      item.status = 'success'
      item.result = result
    }
  } catch (error: any) {
    clearInterval(progressInterval)
    item.status = 'error'
    item.error = error.response?.data?.detail || error.message || '上传失败'
  }
}

async function uploadAll() {
  for (const item of files.value.filter(f => f.status === 'pending')) {
    await uploadSingle(item)
  }
}

async function uploadFromUrl() {
  const urls = urlInput.value
    .split('\n')
    .map(u => u.trim())
    .filter(u => u && (u.startsWith('http://') || u.startsWith('https://')))
  
  if (urls.length === 0) return
  
  urlUploading.value = true
  urlResults.value = urls.map(url => ({ url, status: 'pending' as const }))
  
  for (let i = 0; i < urls.length; i++) {
    try {
      await urlMutation.mutateAsync({
        imageUrl: urls[i],
        autoAnalyze: shouldAnalyze.value,
        categoryId: selectedCategoryId.value ?? undefined,
      })
      urlResults.value[i].status = 'success'
    } catch (e: any) {
      urlResults.value[i].status = 'error'
      urlResults.value[i].error = e.response?.data?.detail || e.message || '添加失败'
    }
  }
  
  urlUploading.value = false
  urlInput.value = ''
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

const hasUploading = computed(() => files.value.some(f => f.status === 'uploading'))
const pendingCount = computed(() => files.value.filter(f => f.status === 'pending').length)
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
      <DialogHeader>
        <DialogTitle>上传图片</DialogTitle>
      </DialogHeader>
      
      <div class="flex-1 overflow-y-auto space-y-4 pr-1">
        <!-- 上传模式切换 -->
        <div class="flex gap-2">
          <button
            @click="uploadMode = 'file'"
            class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors"
            :class="uploadMode === 'file' 
              ? 'bg-primary text-primary-foreground' 
              : 'bg-muted text-muted-foreground hover:text-foreground'"
          >
            <Image class="w-4 h-4" />图片
          </button>
          <button
            @click="uploadMode = 'zip'"
            class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors"
            :class="uploadMode === 'zip' 
              ? 'bg-primary text-primary-foreground' 
              : 'bg-muted text-muted-foreground hover:text-foreground'"
          >
            <FileArchive class="w-4 h-4" />ZIP
          </button>
          <button
            @click="uploadMode = 'url'"
            class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors"
            :class="uploadMode === 'url' 
              ? 'bg-primary text-primary-foreground' 
              : 'bg-muted text-muted-foreground hover:text-foreground'"
          >
            <Link class="w-4 h-4" />URL
          </button>
        </div>

        <!-- 上传选项 -->
        <div class="flex flex-wrap items-center gap-3 p-3 bg-muted/50 rounded-xl text-sm">
          <div class="flex items-center gap-2">
            <Folder class="w-4 h-4 text-muted-foreground" />
            <select
              v-model="selectedCategoryId"
              class="px-2 py-1 text-sm bg-background border border-border rounded-lg focus:outline-none"
            >
              <option v-for="cat in categories" :key="cat.id" :value="cat.id">{{ cat.name }}</option>
            </select>
          </div>
          <!-- 存储端点选择（仅管理员且有多个端点） -->
          <div v-if="isAdmin && endpoints.length > 1" class="flex items-center gap-2">
            <HardDrive class="w-4 h-4 text-muted-foreground" />
            <select
              v-model="selectedEndpointId"
              class="px-2 py-1 text-sm bg-background border border-border rounded-lg focus:outline-none"
            >
              <option v-for="ep in endpoints" :key="ep.id" :value="ep.id">
                {{ ep.name }}{{ ep.is_default_upload ? ' (默认)' : '' }}
              </option>
            </select>
          </div>
          <!-- 公开/私有选择 -->
          <div class="flex items-center gap-2">
            <component :is="isPublic ? Globe : Lock" class="w-4 h-4 text-muted-foreground" />
            <span class="text-muted-foreground">可见性</span>
            <button
              @click="isPublic = !isPublic"
              class="relative w-9 h-5 rounded-full transition-colors"
              :class="isPublic ? 'bg-green-500' : 'bg-amber-500'"
            >
              <span 
                class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all shadow"
                :class="isPublic ? 'left-[18px]' : 'left-0.5'"
              />
            </button>
            <span class="text-xs" :class="isPublic ? 'text-green-500' : 'text-amber-500'">
              {{ isPublic ? '公开' : '私有' }}
            </span>
          </div>
          <div v-if="isAdmin" class="flex items-center gap-2">
            <Sparkles class="w-4 h-4 text-muted-foreground" />
            <span class="text-muted-foreground">AI 分析</span>
            <button
              @click="autoAnalyze = !autoAnalyze"
              class="relative w-9 h-5 rounded-full transition-colors"
              :class="autoAnalyze ? 'bg-primary' : 'bg-muted-foreground/30'"
            >
              <span 
                class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all shadow"
                :class="autoAnalyze ? 'left-[18px]' : 'left-0.5'"
              />
            </button>
          </div>
        </div>

        <!-- URL 输入模式 -->
        <template v-if="uploadMode === 'url'">
          <div class="space-y-3">
            <div class="flex flex-col gap-2">
              <textarea
                v-model="urlInput"
                placeholder="输入图片 URL（每行一个）"
                rows="4"
                class="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                :disabled="urlUploading"
              />
              <div class="flex items-center justify-between">
                <span class="text-xs text-muted-foreground">支持多个 URL，每行一个</span>
                <Button size="sm" @click="uploadFromUrl" :disabled="!urlInput.trim() || urlUploading">
                  <Loader2 v-if="urlUploading" class="w-4 h-4 mr-1 animate-spin" />
                  批量添加
                </Button>
              </div>
            </div>
            <!-- URL 上传结果 -->
            <div v-if="urlResults.length" class="space-y-1.5 max-h-32 overflow-y-auto">
              <div 
                v-for="(item, idx) in urlResults" 
                :key="idx"
                class="flex items-center gap-2 p-2 bg-muted/50 rounded-lg text-sm"
              >
                <CheckCircle v-if="item.status === 'success'" class="w-4 h-4 text-green-500 shrink-0" />
                <AlertCircle v-else-if="item.status === 'error'" class="w-4 h-4 text-destructive shrink-0" />
                <Loader2 v-else class="w-4 h-4 animate-spin text-primary shrink-0" />
                <span class="flex-1 truncate text-xs">{{ item.url }}</span>
                <span v-if="item.error" class="text-xs text-destructive">{{ item.error }}</span>
              </div>
            </div>
          </div>
        </template>

        <!-- 拖拽上传区 -->
        <template v-else>
          <div
            @dragover="handleDragOver"
            @dragleave="handleDragLeave"
            @drop="handleDrop"
            class="border-2 border-dashed rounded-xl p-6 text-center transition-colors cursor-pointer"
            :class="isDragging 
              ? 'border-primary bg-primary/5' 
              : 'border-border hover:border-primary/50'"
          >
            <input v-if="uploadMode === 'file'" type="file" multiple accept="image/*" class="hidden" id="file-dialog" @change="handleFileSelect" />
            <input v-else type="file" accept=".zip" class="hidden" id="zip-dialog" @change="handleZipSelect" />
            <label :for="uploadMode === 'file' ? 'file-dialog' : 'zip-dialog'" class="cursor-pointer">
              <div class="w-10 h-10 bg-muted rounded-full flex items-center justify-center mx-auto mb-2">
                <component :is="uploadMode === 'zip' ? FileArchive : UploadIcon" class="w-5 h-5 text-muted-foreground" />
              </div>
              <p class="text-sm text-foreground">拖拽{{ uploadMode === 'zip' ? ' ZIP' : '图片' }}到这里</p>
              <p class="text-xs text-muted-foreground mt-1">或 <span class="text-primary underline">点击选择</span></p>
            </label>
          </div>
        </template>

        <!-- 文件列表 -->
        <div v-if="files.length > 0" class="space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-sm font-medium">文件列表 <span v-if="pendingCount" class="text-muted-foreground font-normal">({{ pendingCount }} 待上传)</span></span>
            <Button v-if="pendingCount" size="sm" :disabled="hasUploading" @click="uploadAll">
              <Loader2 v-if="hasUploading" class="w-4 h-4 mr-1 animate-spin" />
              <UploadIcon v-else class="w-4 h-4 mr-1" />
              全部上传
            </Button>
          </div>
          <div class="space-y-1.5 max-h-48 overflow-y-auto">
            <div v-for="item in files" :key="item.id" class="flex items-center gap-2 p-2 bg-muted/50 rounded-lg">
              <div class="w-10 h-10 bg-muted rounded flex items-center justify-center overflow-hidden shrink-0">
                <FileArchive v-if="item.file.name.endsWith('.zip')" class="w-5 h-5 text-muted-foreground" />
                <img v-else-if="item.preview" :src="item.preview" class="w-full h-full object-cover" />
                <Image v-else class="w-5 h-5 text-muted-foreground" />
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-sm truncate">{{ item.file.name }}</p>
                <p class="text-xs text-muted-foreground">{{ formatSize(item.file.size) }}</p>
                <div v-if="item.status === 'uploading'" class="h-1 bg-muted rounded-full overflow-hidden mt-1">
                  <div class="h-full bg-primary transition-all" :style="{ width: item.progress + '%' }" />
                </div>
                <p v-if="item.status === 'error'" class="text-xs text-destructive mt-0.5">{{ item.error }}</p>
              </div>
              <CheckCircle v-if="item.status === 'success'" class="w-5 h-5 text-green-500 shrink-0" />
              <AlertCircle v-else-if="item.status === 'error'" class="w-5 h-5 text-destructive shrink-0" />
              <Loader2 v-else-if="item.status === 'uploading'" class="w-5 h-5 animate-spin text-primary shrink-0" />
              <button v-else @click="removeFile(item.id)" class="p-1 hover:bg-muted rounded shrink-0">
                <X class="w-4 h-4 text-muted-foreground" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
