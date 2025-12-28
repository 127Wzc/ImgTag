<script setup lang="ts">
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-background">
    <div class="text-center space-y-4">
      <h1 class="text-8xl font-bold text-muted-foreground">404</h1>
      <p class="text-xl text-muted-foreground">页面未找到</p>
      <RouterLink 
        to="/" 
        class="inline-block mt-4 px-6 py-3 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 transition"
      >
        返回首页
      </RouterLink>
    </div>
  </div>
</template>
