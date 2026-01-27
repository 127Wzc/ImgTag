<script setup lang="ts">
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { toast } from 'vue-sonner'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import {
  Folder,
  Plus,
  Trash2,
  Image as ImageIcon,
  Loader2,
  FolderOpen,
  ArrowRight
} from 'lucide-vue-next'
import type { Collection } from '@/types'

const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()

const loading = ref(false)
const collections = ref<Collection[]>([])

async function fetchCollections() {
  loading.value = true
  try {
    const { data } = await apiClient.get('/collections/')
    collections.value = data
  } catch {
    // ignore
  } finally {
    loading.value = false
  }
}

// 新建收藏夹
const showCreateDialog = ref(false)
const newCollectionName = ref('')
const newCollectionDesc = ref('')
const creating = ref(false)

async function handleCreate() {
  if (!newCollectionName.value.trim()) return
  creating.value = true
  try {
    await apiClient.post('/collections/', {
      name: newCollectionName.value.trim(),
      description: newCollectionDesc.value.trim() || null,
    })
    newCollectionName.value = ''
    newCollectionDesc.value = ''
    showCreateDialog.value = false
    toast.success('Collection created')
    await fetchCollections()
  } catch (e: any) {
    toast.error(e.response?.data?.detail || 'Failed to create')
  } finally {
    creating.value = false
  }
}

async function handleDelete(collection: Collection) {
  const confirmed = await confirm({
    title: 'Delete Collection',
    message: `Are you sure you want to delete "${collection.name}"?`,
    variant: 'danger',
    confirmText: 'Delete',
  })
  if (!confirmed.confirmed) return

  try {
    await apiClient.delete(`/collections/${collection.id}`)
    toast.success('Collection deleted')
    await fetchCollections()
  } catch (e: any) {
    toast.error(e.response?.data?.detail || 'Failed to delete')
  }
}

onMounted(() => {
  fetchCollections()
})
</script>

<template>
  <div class="min-h-screen p-6 lg:p-10 max-w-[1600px] mx-auto">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-10 pb-6 border-b border-border/40">
      <div>
        <h1 class="text-2xl font-bold tracking-tight">Collections</h1>
        <p class="text-muted-foreground mt-1">Organize your images into folders</p>
      </div>
      <Button @click="showCreateDialog = true" class="shadow-lg shadow-primary/20">
        <Plus class="w-4 h-4 mr-2" />
        New Collection
      </Button>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="flex items-center justify-center py-40">
      <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
    </div>

    <!-- Empty State -->
    <div v-else-if="collections.length === 0" class="flex flex-col items-center justify-center py-40 border-2 border-dashed border-border/50 rounded-2xl bg-muted/5">
      <div class="w-16 h-16 bg-muted/50 rounded-full flex items-center justify-center mb-4">
        <FolderOpen class="w-8 h-8 text-muted-foreground" />
      </div>
      <h3 class="text-lg font-medium">No Collections</h3>
      <p class="text-muted-foreground mt-1 mb-6 max-w-sm text-center">Create collections to group related images together for easier access.</p>
      <Button variant="outline" @click="showCreateDialog = true">Create Collection</Button>
    </div>

    <!-- Collection Grid -->
    <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
      <div
        v-for="collection in collections"
        :key="collection.id"
        class="group relative bg-card border border-border/50 rounded-2xl overflow-hidden hover:border-primary/20 hover:shadow-xl transition-all duration-300"
      >
        <!-- Card Content -->
        <div class="p-6">
          <div class="flex items-start justify-between mb-4">
            <div class="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center text-primary group-hover:scale-110 transition-transform duration-300">
              <Folder class="w-6 h-6" />
            </div>
            <div class="opacity-0 group-hover:opacity-100 transition-opacity">
               <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-destructive" @click="handleDelete(collection)">
                 <Trash2 class="w-4 h-4" />
               </Button>
            </div>
          </div>

          <h3 class="font-semibold text-lg text-foreground group-hover:text-primary transition-colors line-clamp-1">
            {{ collection.name }}
          </h3>
          <p class="text-sm text-muted-foreground mt-1 h-10 line-clamp-2 leading-relaxed">
            {{ collection.description || 'No description provided.' }}
          </p>

          <div class="mt-6 flex items-center justify-between pt-4 border-t border-border/30">
            <div class="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <ImageIcon class="w-3.5 h-3.5" />
              <span>{{ collection.image_count || 0 }} items</span>
            </div>
            <div class="w-8 h-8 rounded-full flex items-center justify-center bg-muted/50 text-muted-foreground group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
               <ArrowRight class="w-4 h-4 -ml-0.5" />
            </div>
          </div>
        </div>

        <!-- Hover Gradient -->
        <div class="absolute inset-0 bg-gradient-to-br from-primary/5 via-transparent to-transparent opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity duration-500" />
      </div>
    </div>

    <!-- Create Dialog -->
    <Dialog v-model:open="showCreateDialog">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>New Collection</DialogTitle>
          <DialogDescription>
            Create a collection to organize your images.
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="space-y-2">
            <label class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Name</label>
            <Input v-model="newCollectionName" placeholder="e.g. Wallpapers, Project Assets" />
          </div>
          <div class="space-y-2">
            <label class="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Description (Optional)</label>
            <Input v-model="newCollectionDesc" placeholder="Brief description of this collection" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showCreateDialog = false">Cancel</Button>
          <Button @click="handleCreate" :disabled="!newCollectionName.trim() || creating">
            <Loader2 v-if="creating" class="w-4 h-4 mr-2 animate-spin" />
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Confirm Dialog -->
    <ConfirmDialog
      :open="confirmState.open"
      :title="confirmState.title"
      :message="confirmState.message"
      :confirm-text="confirmState.confirmText"
      :cancel-text="confirmState.cancelText"
      :variant="confirmState.variant"
      :loading="confirmState.loading"
      @confirm="handleConfirm"
      @cancel="handleCancel"
    />
  </div>
</template>
