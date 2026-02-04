<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useUserStore } from '@/stores'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/button'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { getErrorMessage } from '@/utils/api-error'
import { notifyError, notifySuccess } from '@/utils/notify'
import { 
  User, 
  Key, 
  Copy, 
  RefreshCw, 
  Trash2, 
  Check,
  Loader2,
  Shield
} from 'lucide-vue-next'

const userStore = useUserStore()
const { state: confirmState, confirm, handleConfirm, handleCancel } = useConfirmDialog()

// API Key 状态
const apiKeyStatus = ref<{ has_key: boolean; masked_key: string | null }>({ has_key: false, masked_key: null })
const loadingApiKey = ref(false)
const generatingKey = ref(false)
const deletingKey = ref(false)
const copiedKey = ref(false)
const newApiKey = ref<string | null>(null)

// 密码修改
const showPasswordDialog = ref(false)
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const changingPassword = ref(false)
const passwordError = ref('')

async function fetchApiKeyStatus() {
  loadingApiKey.value = true
  try {
    const { data } = await apiClient.get('/auth/me/api-key')
    apiKeyStatus.value = data
  } catch {
    // ignore
  } finally {
    loadingApiKey.value = false
  }
}

async function generateApiKey() {
  generatingKey.value = true
  try {
    const { data } = await apiClient.post('/auth/me/api-key')
    newApiKey.value = data.api_key
    await fetchApiKeyStatus()
    notifySuccess('API 密钥已生成', { once: true })
  } catch {
    notifyError('生成失败')
  } finally {
    generatingKey.value = false
  }
}

async function deleteApiKey() {
  const confirmed = await confirm({
    title: '删除 API 密钥',
    message: '确定要删除 API 密钥吗？删除后外部程序将无法访问。',
    variant: 'warning',
    confirmText: '删除',
  })
  if (!confirmed.confirmed) return
  
  deletingKey.value = true
  try {
    await apiClient.delete('/auth/me/api-key')
    apiKeyStatus.value = { has_key: false, masked_key: null }
    newApiKey.value = null
    notifySuccess('API 密钥已删除', { once: true })
  } catch {
    notifyError('删除失败')
  } finally {
    deletingKey.value = false
  }
}

function copyApiKey() {
  if (newApiKey.value) {
    navigator.clipboard.writeText(newApiKey.value)
    copiedKey.value = true
    setTimeout(() => copiedKey.value = false, 2000)
  }
}

async function handleChangePassword() {
  passwordError.value = ''
  
  if (newPassword.value.length < 6) {
    passwordError.value = '新密码至少6位'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    passwordError.value = '两次密码不一致'
    return
  }
  
  changingPassword.value = true
  try {
    await apiClient.put('/auth/me/password', {
      old_password: oldPassword.value,
      new_password: newPassword.value,
    })
    showPasswordDialog.value = false
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    notifySuccess('密码修改成功', { once: true })
  } catch (e: any) {
    passwordError.value = getErrorMessage(e)
    notifyError(passwordError.value)
  } finally {
    changingPassword.value = false
  }
}

onMounted(() => {
  fetchApiKeyStatus()
})
</script>

<template>
  <div class="p-6 lg:p-8">
      <!-- 标题区 -->
      <div class="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 class="text-xl font-bold text-foreground flex items-center gap-2">
            <User class="w-5 h-5 text-primary" />用户中心
          </h1>
          <p class="text-sm text-muted-foreground mt-1">管理个人信息和安全设置</p>
        </div>
      </div>

      <div class="max-w-6xl mx-auto">

      <!-- 用户信息卡片 -->
      <div class="bg-card border border-border rounded-xl p-6 mb-6">
        <div class="flex items-center gap-4 mb-6">
          <div class="w-16 h-16 bg-primary/10 rounded-full flex items-center justify-center">
            <User class="w-8 h-8 text-primary" />
          </div>
          <div>
            <h2 class="text-xl font-semibold text-foreground">{{ userStore.username }}</h2>
            <div class="flex items-center gap-2 mt-1">
              <Shield class="w-4 h-4 text-muted-foreground" />
              <span class="text-sm text-muted-foreground">
                {{ userStore.isAdmin ? '管理员' : '普通用户' }}
              </span>
            </div>
          </div>
        </div>

        <div class="flex gap-3">
          <Button variant="outline" @click="showPasswordDialog = true">
            修改密码
          </Button>
          <Button variant="outline" @click="userStore.logout(); $router.push('/')">
            退出登录
          </Button>
        </div>
      </div>

      <!-- API 密钥管理 -->
      <div class="bg-card border border-border rounded-xl p-6">
        <div class="flex items-center gap-3 mb-4">
          <Key class="w-5 h-5 text-muted-foreground" />
          <h3 class="text-lg font-semibold text-foreground">个人 API 密钥</h3>
        </div>
        
        <p class="text-sm text-muted-foreground mb-4">
          API 密钥可用于外部程序访问 ImgTag API，请妥善保管。
        </p>

        <!-- 加载中 -->
        <div v-if="loadingApiKey" class="flex items-center gap-2 text-muted-foreground">
          <Loader2 class="w-4 h-4 animate-spin" />
          加载中...
        </div>

        <!-- 新生成的密钥 -->
        <div v-else-if="newApiKey" class="mb-4">
          <div class="p-4 bg-green-500/10 border border-green-500/20 rounded-lg mb-4">
            <p class="text-sm text-green-600 dark:text-green-400 mb-2">
              ⚠️ 请立即复制保存，此密钥只显示一次！
            </p>
            <div class="flex items-center gap-2">
              <code class="flex-1 px-3 py-2 bg-muted rounded text-sm font-mono text-foreground break-all">
                {{ newApiKey }}
              </code>
              <Button variant="outline" size="icon" @click="copyApiKey">
                <Check v-if="copiedKey" class="w-4 h-4 text-green-500" />
                <Copy v-else class="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>

        <!-- 已有密钥 -->
        <div v-else-if="apiKeyStatus.has_key" class="mb-4">
          <div class="flex items-center gap-2 p-3 bg-muted rounded-lg">
            <code class="text-sm font-mono text-muted-foreground">
              {{ apiKeyStatus.masked_key }}
            </code>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="flex gap-3">
          <Button 
            @click="generateApiKey"
            :disabled="generatingKey"
          >
            <RefreshCw v-if="generatingKey" class="w-4 h-4 mr-2 animate-spin" />
            <Key v-else class="w-4 h-4 mr-2" />
            {{ apiKeyStatus.has_key ? '重新生成' : '生成密钥' }}
          </Button>
          <Button 
            v-if="apiKeyStatus.has_key"
            variant="outline"
            @click="deleteApiKey"
            :disabled="deletingKey"
          >
            <Trash2 class="w-4 h-4 mr-2" />
            删除密钥
          </Button>
        </div>
      </div>
    </div>

    <!-- 修改密码弹窗 -->
    <Teleport to="body">
      <Transition name="fade">
        <div 
          v-if="showPasswordDialog"
          class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
          @click.self="showPasswordDialog = false"
        >
          <div class="bg-card rounded-2xl p-6 w-full max-w-md shadow-xl">
            <h3 class="text-lg font-semibold text-foreground mb-4">修改密码</h3>
            
            <div class="space-y-4">
              <div>
                <label class="block text-sm font-medium text-foreground mb-2">当前密码</label>
                <input
                  v-model="oldPassword"
                  type="password"
                  placeholder="输入当前密码"
                  class="w-full px-4 py-2 bg-muted border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-foreground mb-2">新密码</label>
                <input
                  v-model="newPassword"
                  type="password"
                  placeholder="输入新密码（至少6位）"
                  class="w-full px-4 py-2 bg-muted border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-foreground mb-2">确认新密码</label>
                <input
                  v-model="confirmPassword"
                  type="password"
                  placeholder="再次输入新密码"
                  class="w-full px-4 py-2 bg-muted border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  @keyup.enter="handleChangePassword"
                />
              </div>
              
              <p v-if="passwordError" class="text-sm text-destructive">{{ passwordError }}</p>
            </div>

            <div class="flex justify-end gap-2 mt-6">
              <Button variant="outline" @click="showPasswordDialog = false">取消</Button>
              <Button 
                @click="handleChangePassword"
                :disabled="changingPassword"
              >
                <Loader2 v-if="changingPassword" class="w-4 h-4 mr-2 animate-spin" />
                确认修改
              </Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 确认弹窗 -->
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

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
