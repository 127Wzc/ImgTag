<script setup lang="ts">
import { watch, nextTick } from 'vue'
import { Search } from 'lucide-vue-next'
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

// 本地状态（用于 FilterCheckbox 的 v-model）
const pendingOnly = ref(props.modelValue.pendingOnly ?? false)
const duplicatesOnly = ref(props.modelValue.duplicatesOnly ?? false)

// 监听本地 checkbox 状态变化，同步到父组件并触发搜索
watch(pendingOnly, (val) => {
  emit('update:modelValue', { ...props.modelValue, pendingOnly: val })
  if (props.autoSearch) {
    nextTick(() => emit('search'))
  }
})

watch(duplicatesOnly, (val) => {
  emit('update:modelValue', { ...props.modelValue, duplicatesOnly: val })
  if (props.autoSearch) {
    nextTick(() => emit('search'))
  }
})

// 同步父组件的值到本地（当父组件重置时）
watch(() => props.modelValue.pendingOnly, (val) => {
  pendingOnly.value = val ?? false
})

watch(() => props.modelValue.duplicatesOnly, (val) => {
  duplicatesOnly.value = val ?? false
})

// 更新字段（支持自动搜索）
function updateField<K extends keyof FilterState>(key: K, value: FilterState[K]) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
  
  // 如果是自动搜索模式，且不是关键字变化，立即触发搜索
  if (props.autoSearch && key !== 'keyword') {
    nextTick(() => emit('search'))
  }
}

// 关键字输入（不自动搜索，需手动点击搜索按钮）
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
  <div class="p-4 bg-muted/30 rounded-xl border border-border/50">
    <div class="flex flex-wrap items-center gap-3">
      <!-- 分类 -->
      <Select :model-value="modelValue.category" @update:model-value="v => updateField('category', v as string)">
        <SelectTrigger class="w-[140px]"><SelectValue placeholder="全部分类" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部分类</SelectItem>
          <SelectItem v-for="cat in categories" :key="cat.id" :value="String(cat.id)">
            {{ cat.name }} ({{ cat.usage_count || 0 }})
          </SelectItem>
        </SelectContent>
      </Select>

      <!-- 分辨率 -->
      <Select :model-value="modelValue.resolution" @update:model-value="v => updateField('resolution', v as string)">
        <SelectTrigger class="w-[140px]"><SelectValue placeholder="全部分辨率" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部分辨率</SelectItem>
          <SelectItem v-for="res in resolutions" :key="res.id" :value="String(res.id)">
            {{ res.name }} ({{ res.usage_count || 0 }})
          </SelectItem>
        </SelectContent>
      </Select>

      <!-- 关键字 -->
      <Input 
        :model-value="modelValue.keyword" 
        @update:model-value="v => handleKeywordInput(v as string)"
        placeholder="搜索标签或描述" 
        class="flex-1 min-w-[180px]" 
        @keyup.enter="handleSearch" 
      />

      <!-- 待分析筛选（可选）- 使用本地状态 -->
      <FilterCheckbox v-if="showPendingFilter" v-model="pendingOnly" label="待分析" />

      <!-- 重复筛选（可选）- 使用本地状态 -->
      <FilterCheckbox v-if="showDuplicatesFilter" v-model="duplicatesOnly" label="重复" />

      <!-- 操作按钮 -->
      <Button variant="outline" size="sm" @click="handleReset">重置</Button>
      <Button size="sm" @click="handleSearch" class="gap-2"><Search class="w-4 h-4" />搜索</Button>
    </div>
  </div>
</template>
