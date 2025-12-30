<script setup lang="ts">
/**
 * 统一确认弹窗组件
 * 替代浏览器原生 confirm() 实现一致的 UI 体验
 */
import { computed } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { AlertTriangle, Info, AlertCircle } from 'lucide-vue-next'

export interface ConfirmDialogProps {
  open: boolean
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  variant?: 'default' | 'warning' | 'danger'
  loading?: boolean
  // 可选的复选框
  checkboxLabel?: string
  checkboxChecked?: boolean
}

const props = withDefaults(defineProps<ConfirmDialogProps>(), {
  title: '确认操作',
  confirmText: '确定',
  cancelText: '取消',
  variant: 'default',
  loading: false,
  checkboxLabel: '',
  checkboxChecked: false,
})

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
  (e: 'update:open', value: boolean): void
  (e: 'update:checkboxChecked', value: boolean): void
}>()

const iconComponent = computed(() => {
  switch (props.variant) {
    case 'danger': return AlertCircle
    case 'warning': return AlertTriangle
    default: return Info
  }
})

const iconClass = computed(() => {
  switch (props.variant) {
    case 'danger': return 'text-red-500'
    case 'warning': return 'text-amber-500'
    default: return 'text-blue-500'
  }
})

const confirmButtonVariant = computed(() => {
  return props.variant === 'danger' ? 'destructive' : 'default'
})

function handleConfirm() {
  emit('confirm')
}

function handleCancel() {
  emit('cancel')
  emit('update:open', false)
}

function toggleCheckbox() {
  emit('update:checkboxChecked', !props.checkboxChecked)
}
</script>

<template>
  <Dialog :open="open" @update:open="(v) => { if (!v) handleCancel() }">
    <DialogContent class="sm:max-w-md" :show-close-button="false">
      <DialogHeader>
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-full flex items-center justify-center bg-muted">
            <component :is="iconComponent" class="w-5 h-5" :class="iconClass" />
          </div>
          <DialogTitle>{{ title }}</DialogTitle>
        </div>
      </DialogHeader>
      
      <DialogDescription class="text-foreground/80 leading-relaxed whitespace-pre-line">
        {{ message }}
      </DialogDescription>

      <!-- 可选的复选框 -->
      <div v-if="checkboxLabel" class="flex items-center gap-2 py-2">
        <input
          type="checkbox"
          :checked="checkboxChecked"
          @change="toggleCheckbox"
          class="w-4 h-4 rounded border-border text-primary focus:ring-primary cursor-pointer"
        />
        <label 
          class="text-sm text-foreground/80 cursor-pointer select-none"
          @click="toggleCheckbox"
        >
          {{ checkboxLabel }}
        </label>
      </div>
      
      <DialogFooter class="flex gap-2 sm:justify-end">
        <Button 
          variant="outline" 
          @click="handleCancel"
          :disabled="loading"
        >
          {{ cancelText }}
        </Button>
        <Button 
          :variant="confirmButtonVariant"
          @click="handleConfirm"
          :disabled="loading"
        >
          <span v-if="loading" class="mr-2">
            <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          </span>
          {{ confirmText }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
