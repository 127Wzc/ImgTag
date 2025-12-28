<script setup lang="ts">
/**
 * FilterCheckbox - 筛选复选框组件
 * 专为筛选栏设计，确保点击可靠触发状态变化
 */
import { cn } from '@/lib/utils'
import { Check } from 'lucide-vue-next'

const modelValue = defineModel<boolean>({ default: false })

defineProps<{
  label: string
}>()

function toggle() {
  modelValue.value = !modelValue.value
}
</script>

<template>
  <label 
    class="flex items-center gap-1.5 text-sm cursor-pointer hover:text-primary transition-colors whitespace-nowrap select-none"
    @click.prevent="toggle"
  >
    <span
      :class="cn(
        'peer size-4 shrink-0 rounded-[4px] border shadow-xs transition-all flex items-center justify-center',
        modelValue 
          ? 'bg-primary border-primary text-primary-foreground' 
          : 'border-input bg-background hover:border-primary/50'
      )"
    >
      <Check v-if="modelValue" class="size-3" />
    </span>
    <span>{{ label }}</span>
  </label>
</template>
