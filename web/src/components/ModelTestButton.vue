<script setup lang="ts">
import { FlaskConical, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

defineProps<{
  loading: boolean
  result?: { success: boolean; message: string }
  description: string
}>()
defineEmits<{ test: [] }>()
</script>

<template>
  <div class="space-y-2 pt-2">
    <Button type="button" variant="outline" size="sm" :disabled="loading" @click="$emit('test')">
      <Loader2 v-if="loading" class="w-4 h-4 mr-1.5 animate-spin" />
      <FlaskConical v-else class="w-4 h-4 mr-1.5" />
      {{ loading ? '测试中...' : '测试模型' }}
    </Button>
    <p class="text-xs text-muted-foreground">{{ description }}，无需先保存配置。</p>
    <p
      v-if="result"
      role="status"
      aria-live="polite"
      class="text-xs break-words"
      :class="result.success ? 'text-green-500' : 'text-destructive'"
    >{{ result.message }}</p>
  </div>
</template>
