<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { MainLayout } from '@/components/layout'
import { Toaster } from 'vue-sonner'
import { useUserStore } from '@/stores'

const userStore = useUserStore()

onMounted(() => {
  userStore.bindAutoRefresh({ minIntervalMs: 2 * 60 * 1000 })
})
</script>

<template>
  <MainLayout>
    <RouterView />
  </MainLayout>
  <Toaster position="top-center" :duration="3000" rich-colors />
</template>
