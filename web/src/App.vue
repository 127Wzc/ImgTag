<script setup lang="ts">
import { RouterView } from 'vue-router'
import { MainLayout } from '@/components/layout'
import { Toaster } from 'vue-sonner'
</script>

<template>
  <MainLayout>
    <RouterView />
  </MainLayout>
  <Toaster position="top-center" :duration="3000" rich-colors />
</template>
