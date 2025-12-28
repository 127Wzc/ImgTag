<script setup lang="ts">
defineProps<{
  title?: string
}>()
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-background">
    <div class="text-center space-y-4">
      <h1 class="text-4xl font-bold text-foreground">{{ title || '页面开发中' }}</h1>
      <p class="text-muted-foreground">此页面正在开发中，敬请期待...</p>
    </div>
  </div>
</template>
