<template>
  <div class="user-center-page">
    <div class="page-content">
      <!-- 基本信息 -->
      <div class="form-section">
        <h3>
          <el-icon><User /></el-icon>
          基本信息
        </h3>
        <div class="info-grid" v-if="userInfo">
          <div class="info-row">
            <span class="label">用户名</span>
            <span class="value">{{ userInfo.username }}</span>
          </div>
          <div class="info-row">
            <span class="label">邮箱</span>
            <span class="value">{{ userInfo.email || '未设置' }}</span>
          </div>
          <div class="info-row">
            <span class="label">角色</span>
            <span class="value">
              <el-tag :type="userInfo.role === 'admin' ? 'danger' : 'info'" size="small">
                {{ userInfo.role === 'admin' ? '管理员' : '普通用户' }}
              </el-tag>
            </span>
          </div>
          <div class="info-row">
            <span class="label">注册时间</span>
            <span class="value">{{ formatDate(userInfo.created_at) }}</span>
          </div>
          <div class="info-row" v-if="userInfo.last_login_at">
            <span class="label">上次登录</span>
            <span class="value">{{ formatDate(userInfo.last_login_at) }}</span>
          </div>
        </div>
        <el-skeleton :rows="4" animated v-else />
      </div>

      <!-- 修改密码 -->
      <div class="form-section">
        <h3>
          <el-icon><Lock /></el-icon>
          修改密码
        </h3>
        <el-form :model="passwordForm" label-width="100px" style="max-width: 400px;">
          <el-form-item label="当前密码" required>
            <el-input 
              v-model="passwordForm.oldPassword" 
              type="password" 
              placeholder="请输入当前密码"
              show-password
            />
          </el-form-item>
          <el-form-item label="新密码" required>
            <el-input 
              v-model="passwordForm.newPassword" 
              type="password" 
              placeholder="至少6位"
              show-password
            />
          </el-form-item>
          <el-form-item label="确认密码" required>
            <el-input 
              v-model="passwordForm.confirmPassword" 
              type="password" 
              placeholder="再次输入新密码"
              show-password
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" round @click="handleChangePassword" :loading="changingPassword">
              <el-icon><Check /></el-icon>
              修改密码
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- API 密钥 -->
      <div class="form-section">
        <h3>
          <el-icon><Key /></el-icon>
          API 密钥
        </h3>
        <p class="section-desc">
          外部调用需在 Header 或参数中传入 <code>api_key</code>
        </p>
        
        <div class="api-key-content" v-loading="loadingApiKey">
          <div v-if="apiKeyInfo.has_key" class="api-key-display">
            <div class="key-row">
              <span class="key-label">当前密钥:</span>
              <code class="key-value">{{ showFullKey ? fullApiKey : apiKeyInfo.masked_key }}</code>
            </div>
            <div class="key-actions">
              <el-button 
                v-if="showFullKey" 
                type="primary" 
                plain 
                size="small"
                @click="copyApiKey"
              >
                <el-icon><DocumentCopy /></el-icon>
                复制
              </el-button>
              <el-popconfirm
                title="重新生成会使旧密钥失效，确定继续？"
                confirm-button-text="确定"
                cancel-button-text="取消"
                @confirm="handleGenerateApiKey"
              >
                <template #reference>
                  <el-button type="warning" plain size="small" :loading="generatingKey">
                    <el-icon><Refresh /></el-icon>
                    重新生成
                  </el-button>
                </template>
              </el-popconfirm>
              <el-popconfirm
                title="删除后将无法使用该密钥调用 API，确定删除？"
                confirm-button-text="确定"
                cancel-button-text="取消"
                @confirm="handleDeleteApiKey"
              >
                <template #reference>
                  <el-button type="danger" plain size="small" :loading="deletingKey">
                    <el-icon><Delete /></el-icon>
                    删除
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
          <div v-else class="no-key">
            <p>您还没有 API 密钥</p>
            <el-button type="primary" round @click="handleGenerateApiKey" :loading="generatingKey">
              <el-icon><Plus /></el-icon>
              生成密钥
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { User, Lock, Key, Check, Refresh, Delete, Plus, DocumentCopy } from '@element-plus/icons-vue'
import { getCurrentUser, changeMyPassword, getApiKey, generateApiKey, deleteApiKey } from '@/api'

// 用户信息
const userInfo = ref(null)

// 修改密码
const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})
const changingPassword = ref(false)

// API 密钥
const apiKeyInfo = ref({ has_key: false, masked_key: null })
const fullApiKey = ref('')
const showFullKey = ref(false)
const loadingApiKey = ref(false)
const generatingKey = ref(false)
const deletingKey = ref(false)

// 获取用户信息
const fetchUserInfo = async () => {
  try {
    userInfo.value = await getCurrentUser()
  } catch (e) {
    ElMessage.error('获取用户信息失败: ' + e.message)
  }
}

// 获取 API 密钥状态
const fetchApiKeyInfo = async () => {
  loadingApiKey.value = true
  try {
    apiKeyInfo.value = await getApiKey()
    showFullKey.value = false
    fullApiKey.value = ''
  } catch (e) {
    ElMessage.error('获取 API 密钥信息失败: ' + e.message)
  } finally {
    loadingApiKey.value = false
  }
}

// 修改密码
const handleChangePassword = async () => {
  if (!passwordForm.oldPassword) {
    ElMessage.warning('请输入当前密码')
    return
  }
  if (!passwordForm.newPassword || passwordForm.newPassword.length < 6) {
    ElMessage.warning('新密码至少6位')
    return
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  
  changingPassword.value = true
  try {
    await changeMyPassword(passwordForm.oldPassword, passwordForm.newPassword)
    ElMessage.success('密码修改成功')
    passwordForm.oldPassword = ''
    passwordForm.newPassword = ''
    passwordForm.confirmPassword = ''
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    changingPassword.value = false
  }
}

// 生成 API 密钥
const handleGenerateApiKey = async () => {
  generatingKey.value = true
  try {
    const result = await generateApiKey()
    fullApiKey.value = result.api_key
    showFullKey.value = true
    apiKeyInfo.value = { has_key: true, masked_key: `${result.api_key.slice(0, 8)}...${result.api_key.slice(-8)}` }
    ElMessage.success('API 密钥生成成功，请妥善保存')
  } catch (e) {
    ElMessage.error('生成失败: ' + e.message)
  } finally {
    generatingKey.value = false
  }
}

// 删除 API 密钥
const handleDeleteApiKey = async () => {
  deletingKey.value = true
  try {
    await deleteApiKey()
    apiKeyInfo.value = { has_key: false, masked_key: null }
    fullApiKey.value = ''
    showFullKey.value = false
    ElMessage.success('API 密钥已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + e.message)
  } finally {
    deletingKey.value = false
  }
}

// 复制密钥
const copyApiKey = async () => {
  try {
    await navigator.clipboard.writeText(fullApiKey.value)
    ElMessage.success('已复制到剪贴板')
  } catch (e) {
    ElMessage.error('复制失败')
  }
}

// 格式化日期
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

onMounted(() => {
  fetchUserInfo()
  fetchApiKeyInfo()
})
</script>

<style scoped>
.user-center-page {
  max-width: 800px;
}

.page-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.form-section {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  padding: 24px;
  border: 1px solid var(--border-color-light);
}

.form-section h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 20px 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.section-desc {
  color: var(--text-secondary);
  font-size: 13px;
  margin: 0 0 16px 0;
}

.section-desc code {
  background: var(--bg-secondary);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 12px;
}

.info-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.info-row .label {
  width: 80px;
  color: var(--text-secondary);
  font-size: 14px;
}

.info-row .value {
  color: var(--text-primary);
  font-size: 14px;
}

.api-key-content {
  min-height: 60px;
}

.api-key-display {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.key-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.key-label {
  color: var(--text-secondary);
  font-size: 14px;
}

.key-value {
  background: var(--bg-secondary);
  padding: 8px 12px;
  border-radius: 6px;
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 13px;
  color: var(--text-primary);
  word-break: break-all;
}

.key-actions {
  display: flex;
  gap: 8px;
}

.no-key {
  text-align: center;
  padding: 20px 0;
}

.no-key p {
  margin: 0 0 16px 0;
  color: var(--text-secondary);
}
</style>
