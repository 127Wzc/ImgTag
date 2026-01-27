<script setup lang="ts">
import { watch, nextTick } from 'vue'
import { Search, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FilterCheckbox } from '@/components/ui/filter-checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCategories, useResolutions } from '@/api/queries'
import { computed, ref } from 'vue'

export interface FilterState {
  category: string
  resolution: string
  keyword: string
  pendingOnly?: boolean
  duplicatesOnly?: boolean
}

const props = withDefaults(defineProps<{
  modelValue: FilterState
  autoSearch?: boolean
  showPendingFilter?: boolean
  showDuplicatesFilter?: boolean
}>(), {
  autoSearch: false,
  showPendingFilter: false,
  showDuplicatesFilter: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: FilterState]
  search: []
  reset: []
}>()

// 数据查询
const { data: categoriesData } = useCategories()
const { data: resolutionsData } = useResolutions()

const categories = computed(() => categoriesData.value || [])
const resolutions = computed(() => resolutionsData.value || [])

// 本地状态
const pendingOnly = ref(props.modelValue.pendingOnly ?? false)
const duplicatesOnly = ref(props.modelValue.duplicatesOnly ?? false)

// 监听本地 checkbox 状态变化
watch(pendingOnly, (val) => {
  emit('update:modelValue', { ...props.modelValue, pendingOnly: val })
  if (props.autoSearch) nextTick(() => emit('search'))
})

watch(duplicatesOnly, (val) => {
  emit('update:modelValue', { ...props.modelValue, duplicatesOnly: val })
  if (props.autoSearch) nextTick(() => emit('search'))
})

// 同步父组件的值
watch(() => props.modelValue.pendingOnly, (val) => { pendingOnly.value = val ?? false })
watch(() => props.modelValue.duplicatesOnly, (val) => { duplicatesOnly.value = val ?? false })

function updateField<K extends keyof FilterState>(key: K, value: FilterState[K]) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
  if (props.autoSearch && key !== 'keyword') {
    nextTick(() => emit('search'))
  }
}

function handleKeywordInput(value: string) {
  emit('update:modelValue', { ...props.modelValue, keyword: value })
}

function handleReset() {
  pendingOnly.value = false
  duplicatesOnly.value = false
  emit('update:modelValue', {
    category: 'all',
    resolution: 'all',
    keyword: '',
    pendingOnly: false,
    duplicatesOnly: false,
  })
  emit('reset')
}

function handleSearch() {
  emit('search')
}
</script>

<template>
  <div class="flex flex-col sm:flex-row flex-wrap items-start sm:items-center gap-3">
    <!-- 关键字搜索 -->
    <div class="relative flex-1 min-w-[200px] w-full sm:w-auto">
      <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
      <Input
        :model-value="modelValue.keyword"
        @update:model-value="v => handleKeywordInput(v as string)"
        placeholder="搜索文件名、标签或描述..."
        class="pl-9 h-9 bg-background border-border/50 hover:border-border transition-colors focus:ring-1 focus:ring-primary/20"
        @keyup.enter="handleSearch"
      />
      <button
        v-if="modelValue.keyword"
        @click="updateField('keyword', '')"
        class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
      >
        <X class="w-3.5 h-3.5" />
      </button>
    </div>

    <div class="flex flex-wrap items-center gap-2 w-full sm:w-auto">
      <!-- 分类 -->
      <Select :model-value="modelValue.category" @update:model-value="v => updateField('category', v as string)">
        <SelectTrigger class="w-[130px] h-9 bg-background border-border/50 text-xs">
          <SelectValue placeholder="分类" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部分类</SelectItem>
          <SelectItem v-for="cat in categories" :key="cat.id" :value="String(cat.id)">
            {{ cat.name }}
          </SelectItem>
        </SelectContent>
      </Select>

      <!-- 分辨率 -->
      <Select :model-value="modelValue.resolution" @update:model-value="v => updateField('resolution', v as string)">
        <SelectTrigger class="w-[130px] h-9 bg-background border-border/50 text-xs">
          <SelectValue placeholder="分辨率" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部分辨率</SelectItem>
          <SelectItem v-for="res in resolutions" :key="res.id" :value="String(res.id)">
            {{ res.name }}
          </SelectItem>
        </SelectContent>
      </Select>
    </div>

    <!-- Checkboxes -->
    <div class="flex items-center gap-3 ml-1">
      <FilterCheckbox v-if="showPendingFilter" v-model="pendingOnly" label="待分析" />
      <FilterCheckbox v-if="showDuplicatesFilter" v-model="duplicatesOnly" label="重复项" />
    </div>

    <!-- 按钮 -->
    <div class="flex items-center gap-2 ml-auto sm:ml-0">
      <Button
        v-if="!autoSearch"
        size="sm"
        @click="handleSearch"
        class="h-9 px-4 gap-2 shadow-sm"
      >
        搜索
      </Button>
      <Button
        variant="ghost"
        size="sm"
        @click="handleReset"
        class="h-9 text-muted-foreground hover:text-foreground"
      >
        重置
      </Button>
    </div>
  </div>
</template>
