<script setup lang="ts">
/**
 * FloatingUploadButton - 悬浮上传按钮
 * 右下角 FAB 按钮，登录后可见，点击打开上传弹框
 */
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores'
import { Plus } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import UploadDialog from '@/components/UploadDialog.vue'

const route = useRoute()
const userStore = useUserStore()

// 弹框状态
const uploadDialogOpen = ref(false)

// 隐藏的路由（上传页、登录页不显示）
const hiddenRoutes = ['/upload', '/login']

const isVisible = computed(() => {
  return userStore.isLoggedIn && !hiddenRoutes.includes(route.path)
})

function handleClick() {
  uploadDialogOpen.value = true
}
</script>

<template>
  <!-- 悬浮按钮 -->
  <Transition name="fab">
    <button
      v-if="isVisible"
      @click="handleClick"
      class="fixed right-6 bottom-6 z-50 w-14 h-14 rounded-full bg-primary text-primary-foreground shadow-lg hover:shadow-xl hover:scale-105 active:scale-95 transition-all duration-200 flex items-center justify-center group"
      aria-label="上传图片"
    >
      <Plus class="w-6 h-6 group-hover:rotate-90 transition-transform duration-200" />
      
      <!-- Tooltip -->
      <span class="absolute right-full mr-3 px-3 py-1.5 bg-popover text-popover-foreground text-sm rounded-lg shadow-lg opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
        上传图片
      </span>
    </button>
  </Transition>

  <!-- 上传弹框 -->
  <UploadDialog v-model:open="uploadDialogOpen" />
</template>

<style scoped>
.fab-enter-active,
.fab-leave-active {
  transition: all 0.3s ease;
}
.fab-enter-from,
.fab-leave-to {
  opacity: 0;
  transform: scale(0.5) translateY(20px);
}
</style>
