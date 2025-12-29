<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Button } from '@/components/ui/button'
import { useUploadImage, useUploadZip, useUploadFromUrl, useCategories } from '@/api/queries'
import { useUserStore } from '@/stores/user'
import apiClient from '@/api/client'
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
} from 'lucide-vue-next'

const userStore = useUserStore()
const isAdmin = computed(() => userStore.isAdmin)

// 上传模式
type UploadMode = 'file' | 'zip' | 'url'
const uploadMode = ref<UploadMode>('file')

// 上传选项
const autoAnalyze = ref(true)  // 管理员可选
const selectedCategoryId = ref<number | null>(null)
const selectedEndpointId = ref<number | null>(null)  // 目标存储端点

// 获取主分类列表
const { data: categories } = useCategories()

// 获取启用的存储端点列表
interface StorageEndpoint {
  id: number
  name: string
  provider: string
  is_default_upload: boolean
}
const endpoints = ref<StorageEndpoint[]>([])

async function fetchEndpoints() {
  try {
    const { data } = await apiClient.get<StorageEndpoint[]>('/storage/endpoints?enabled_only=true')
    endpoints.value = data
    // 默认选择默认上传端点
    const defaultEp = data.find(ep => ep.is_default_upload)
    if (defaultEp) {
      selectedEndpointId.value = defaultEp.id
    }
  } catch (e) {
    // 忽略错误，使用默认端点
  }
}

onMounted(() => {
  if (isAdmin.value) {
    fetchEndpoints()
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

const uploadMutation = useUploadImage()
const zipMutation = useUploadZip()
const urlMutation = useUploadFromUrl()

// 根据用户角色决定是否分析
const shouldAnalyze = computed(() => isAdmin.value && autoAnalyze.value)

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
  
  // 检查是否有 ZIP 文件
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
  const selectedFiles = Array.from(target.files || [])
  addFiles(selectedFiles)
  target.value = ''
}

function handleZipSelect(e: Event) {
  const target = e.target as HTMLInputElement
  const zipFile = target.files?.[0]
  if (zipFile) {
    addFiles([zipFile])
  }
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
      // ZIP 上传
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
      // 普通图片上传
      const result = await uploadMutation.mutateAsync({
        file: item.file,
        autoAnalyze: shouldAnalyze.value,
        skipAnalyze: !shouldAnalyze.value,
        categoryId: selectedCategoryId.value ?? undefined,
        endpointId: selectedEndpointId.value ?? undefined,
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
  const pendingFiles = files.value.filter(f => f.status === 'pending')
  for (const item of pendingFiles) {
    await uploadSingle(item)
  }
}

async function uploadFromUrl() {
  if (!urlInput.value.trim()) return
  
  try {
    await urlMutation.mutateAsync({
      imageUrl: urlInput.value.trim(),
      autoAnalyze: shouldAnalyze.value,
      categoryId: selectedCategoryId.value ?? undefined,
    })
    urlInput.value = ''
    alert('添加成功')
  } catch (e: any) {
    alert(e.response?.data?.detail || '添加失败')
  }
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
  <div class="p-6 lg:p-8">
    <div class="max-w-4xl mx-auto">
      <h1 class="text-xl font-semibold text-foreground mb-2">上传图片</h1>
      <p class="text-sm text-muted-foreground mb-6">
        {{ isAdmin ? '上传后可选择自动进行 AI 分析' : '上传图片到图库' }}
      </p>

      <!-- 上传模式切换 -->
      <div class="flex gap-2 mb-4">
        <button
          @click="uploadMode = 'file'"
          class="flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-colors"
          :class="uploadMode === 'file' 
            ? 'bg-primary text-primary-foreground' 
            : 'bg-muted text-muted-foreground hover:text-foreground'"
        >
          <Image class="w-4 h-4" />
          图片
        </button>
        <button
          @click="uploadMode = 'zip'"
          class="flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-colors"
          :class="uploadMode === 'zip' 
            ? 'bg-primary text-primary-foreground' 
            : 'bg-muted text-muted-foreground hover:text-foreground'"
        >
          <FileArchive class="w-4 h-4" />
          ZIP 压缩包
        </button>
        <button
          @click="uploadMode = 'url'"
          class="flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-colors"
          :class="uploadMode === 'url' 
            ? 'bg-primary text-primary-foreground' 
            : 'bg-muted text-muted-foreground hover:text-foreground'"
        >
          <Link class="w-4 h-4" />
          网络图片
        </button>
      </div>

      <!-- 上传选项 -->
      <div class="flex flex-wrap items-center gap-4 mb-6 p-4 bg-muted/50 rounded-xl">
        <!-- 主分类选择 -->
        <div class="flex items-center gap-2">
          <Folder class="w-4 h-4 text-muted-foreground" />
          <select
            v-model="selectedCategoryId"
            class="px-3 py-1.5 text-sm bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option :value="null">不指定分类</option>
            <option v-for="cat in categories" :key="cat.id" :value="cat.id">
              {{ cat.name }}
            </option>
          </select>
        </div>

        <!-- 存储端点选择（仅管理员） -->
        <div v-if="isAdmin && endpoints.length > 0" class="flex items-center gap-2">
          <HardDrive class="w-4 h-4 text-muted-foreground" />
          <select
            v-model="selectedEndpointId"
            class="px-3 py-1.5 text-sm bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option :value="null">默认端点</option>
            <option v-for="ep in endpoints" :key="ep.id" :value="ep.id">
              {{ ep.name }} ({{ ep.provider === 'local' ? '本地' : 'S3' }})
            </option>
          </select>
        </div>

        <!-- AI 分析开关（仅管理员） -->
        <div v-if="isAdmin" class="flex items-center gap-2">
          <Sparkles class="w-4 h-4 text-muted-foreground" />
          <span class="text-sm text-muted-foreground">AI 分析</span>
          <button
            @click="autoAnalyze = !autoAnalyze"
            class="relative w-10 h-5 rounded-full transition-colors"
            :class="autoAnalyze ? 'bg-primary' : 'bg-muted'"
          >
            <span 
              class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all shadow"
              :class="autoAnalyze ? 'left-5' : 'left-0.5'"
            />
          </button>
        </div>
        
        <p v-if="!isAdmin" class="text-xs text-muted-foreground">
          提示：图片上传后需管理员审核分析
        </p>
      </div>

      <!-- URL 输入模式 -->
      <template v-if="uploadMode === 'url'">
        <div class="flex gap-2">
          <input
            v-model="urlInput"
            type="url"
            placeholder="输入图片 URL（支持 http/https）"
            class="flex-1 px-4 py-3 bg-muted border border-border rounded-xl text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            @keyup.enter="uploadFromUrl"
          />
          <Button 
            @click="uploadFromUrl" 
            :disabled="!urlInput.trim() || urlMutation.isPending.value"
          >
            <Loader2 v-if="urlMutation.isPending.value" class="w-4 h-4 mr-1 animate-spin" />
            添加
          </Button>
        </div>
      </template>

      <!-- 文件/ZIP 拖拽上传区 -->
      <template v-else>
        <div
          @dragover="handleDragOver"
          @dragleave="handleDragLeave"
          @drop="handleDrop"
          class="border-2 border-dashed rounded-2xl p-10 text-center transition-colors cursor-pointer"
          :class="[
            isDragging 
              ? 'border-primary bg-primary/5' 
              : 'border-border hover:border-primary/50 hover:bg-muted/50'
          ]"
        >
          <input
            v-if="uploadMode === 'file'"
            type="file"
            multiple
            accept="image/*"
            class="hidden"
            id="file-upload"
            @change="handleFileSelect"
          />
          <input
            v-else
            type="file"
            accept=".zip"
            class="hidden"
            id="zip-upload"
            @change="handleZipSelect"
          />
          <label :for="uploadMode === 'file' ? 'file-upload' : 'zip-upload'" class="cursor-pointer">
            <div class="w-14 h-14 bg-muted rounded-full flex items-center justify-center mx-auto mb-4">
              <component :is="uploadMode === 'zip' ? FileArchive : UploadIcon" class="w-7 h-7 text-muted-foreground" />
            </div>
            <p class="font-medium text-foreground mb-1">
              拖拽{{ uploadMode === 'zip' ? ' ZIP 文件' : '图片' }}到这里上传
            </p>
            <p class="text-sm text-muted-foreground">
              或 <span class="text-primary underline">点击选择</span>
            </p>
            <p class="text-xs text-muted-foreground mt-2">
              {{ uploadMode === 'zip' ? '支持 .zip 压缩包，自动解压上传' : '支持 JPG, PNG, GIF, WebP' }}
            </p>
          </label>
        </div>
      </template>

      <!-- 文件列表 -->
      <div v-if="files.length > 0" class="mt-6">
        <div class="flex items-center justify-between mb-3">
          <h2 class="font-medium text-foreground">
            文件列表 
            <span v-if="pendingCount > 0" class="text-muted-foreground font-normal text-sm">
              ({{ pendingCount }} 个待上传)
            </span>
          </h2>
          <Button 
            v-if="pendingCount > 0"
            size="sm"
            :disabled="hasUploading"
            @click="uploadAll"
          >
            <Loader2 v-if="hasUploading" class="w-4 h-4 mr-1 animate-spin" />
            <UploadIcon v-else class="w-4 h-4 mr-1" />
            {{ hasUploading ? '上传中...' : '全部上传' }}
          </Button>
        </div>

        <div class="space-y-2">
          <div 
            v-for="item in files" 
            :key="item.id"
            class="flex items-center gap-3 p-3 bg-card border border-border rounded-xl"
          >
            <div class="w-12 h-12 bg-muted rounded-lg flex items-center justify-center overflow-hidden shrink-0">
              <FileArchive v-if="item.file.name.endsWith('.zip')" class="w-6 h-6 text-muted-foreground" />
              <img v-else-if="item.preview" :src="item.preview" class="w-full h-full object-cover" />
              <Image v-else class="w-6 h-6 text-muted-foreground" />
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium text-foreground truncate">{{ item.file.name }}</p>
              <p class="text-xs text-muted-foreground">{{ formatSize(item.file.size) }}</p>
              
              <!-- 进度条 -->
              <div v-if="item.status === 'uploading'" class="mt-1.5">
                <div class="h-1 bg-muted rounded-full overflow-hidden">
                  <div class="h-full bg-primary transition-all" :style="{ width: item.progress + '%' }" />
                </div>
              </div>
              
              <!-- 成功结果 -->
              <div v-if="item.status === 'success' && item.result?.tags?.length" class="mt-1.5 flex flex-wrap gap-1">
                <span 
                  v-for="tag in item.result.tags.slice(0, 4)" 
                  :key="tag"
                  class="px-1.5 py-0.5 bg-primary/10 text-primary text-xs rounded"
                >
                  {{ tag }}
                </span>
                <span v-if="(item.result.tags?.length || 0) > 4" class="text-xs text-muted-foreground">
                  +{{ item.result.tags.length - 4 }}
                </span>
              </div>
              <p v-else-if="item.status === 'success' && item.result?.description" class="text-xs text-green-600 mt-1">
                {{ item.result.description }}
              </p>
              
              <!-- 错误 -->
              <p v-if="item.status === 'error'" class="text-xs text-destructive mt-1">
                {{ item.error }}
              </p>
            </div>
            
            <div class="shrink-0">
              <CheckCircle v-if="item.status === 'success'" class="w-5 h-5 text-green-500" />
              <AlertCircle v-else-if="item.status === 'error'" class="w-5 h-5 text-destructive" />
              <Loader2 v-else-if="item.status === 'uploading'" class="w-5 h-5 animate-spin text-primary" />
              <button v-else @click="removeFile(item.id)" class="p-1 hover:bg-muted rounded">
                <X class="w-4 h-4 text-muted-foreground" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
