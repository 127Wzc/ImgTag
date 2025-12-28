<script setup lang="ts">
/**
 * CopyToast - 复制成功提示组件
 * 在页面中上方显示一个短暂的复制成功提示
 */
import { watch } from 'vue'

const props = defineProps<{
  show: boolean
  message?: string
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

// 自动隐藏
watch(() => props.show, (val) => {
  if (val) {
    setTimeout(() => {
      emit('update:show', false)
    }, 1500)
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div 
        v-if="show"
        class="fixed inset-0 flex items-start justify-center pt-32 z-[200] pointer-events-none"
      >
        <div class="px-6 py-3 bg-black/80 text-white rounded-xl shadow-2xl flex items-center gap-2 backdrop-blur-sm">
          <svg class="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
          <span class="font-medium">{{ message || '复制成功' }}</span>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
