<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowUpRight, Check, Copy } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { useUserStore } from '@/stores'
import apiClient from '@/api/client'
import { getRuntimeConfig } from '@/utils/runtime-config'
import { buildMcpConfig, publicMcpInstallLink, type McpClient } from '@/utils/mcp-config'
import { notifyError, notifySuccess } from '@/utils/notify'
import { getErrorMessage } from '@/utils/api-error'

const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const clients: { id: McpClient; name: string; mark: string }[] = [
  { id: 'cursor', name: 'Cursor', mark: '↗' },
  { id: 'vscode', name: 'VS Code', mark: '⌘' },
  { id: 'claude', name: 'Claude Desktop', mark: '✳︎' },
  { id: 'generic', name: '其他客户端', mark: '{ }' },
]
const selected = ref<McpClient>(clients.find(c => c.id === route.query.client)?.id ?? 'cursor')
const personal = ref(userStore.isLoggedIn && route.query.scope !== 'public')
const hasKey = ref<boolean | null>(null)
const statusError = ref(false)
const busy = ref(false)
const baseUrl = (getRuntimeConfig('VITE_API_BASE_URL') || window.location.origin).replace(/\/$/, '')
const endpoint = `${baseUrl}/api/v1/mcp/public`
const clientName = computed(() => clients.find(c => c.id === selected.value)!.name)
const preview = computed(() => JSON.stringify(buildMcpConfig(selected.value, endpoint, personal.value ? 'YOUR_API_KEY' : undefined), null, 2))
const installLink = computed(() => personal.value ? null : publicMcpInstallLink(selected.value, endpoint))
const accessDescription = computed(() => !personal.value ? '仅可访问公开图片，无需登录或密钥。' : userStore.isAdmin ? '使用管理员身份，可读取全部图片。' : '可读取公开图片及你上传的私有图片。')
const copyLabel = computed(() => !personal.value ? '复制配置' : hasKey.value === false ? '生成密钥并复制配置' : '复制配置（含个人密钥）')

async function loadKeyStatus() {
  statusError.value = false
  hasKey.value = null
  try {
    const { data } = await apiClient.get('/auth/me/api-key')
    hasKey.value = data.has_key
  } catch (error) {
    statusError.value = true
    notifyError(getErrorMessage(error))
  }
}
watch(() => userStore.isLoggedIn, (loggedIn) => {
  if (loggedIn) void loadKeyStatus()
  else { personal.value = false; hasKey.value = null }
}, { immediate: true })

function selectScope(value: boolean) {
  if (value && !userStore.isLoggedIn) {
    void router.push({ path: '/login', query: { redirect: `/connect?client=${selected.value}&scope=personal` } })
    return
  }
  personal.value = value
}

async function copyConfig(includeKey: boolean) {
  if (busy.value) return
  busy.value = true
  // 固定本次点击的选择，避免异步请求期间切换客户端改变复制内容。
  const client = selected.value
  const withIdentity = personal.value
  try {
    if (!navigator.clipboard) throw new Error('当前浏览器无法复制，请使用 HTTPS 或 localhost 访问。')
    const content = async () => {
      let key = withIdentity ? 'YOUR_API_KEY' : undefined
      if (withIdentity && includeKey) {
        if (!userStore.isLoggedIn || hasKey.value === null) throw new Error('请先确认个人密钥状态。')
        // 已有密钥只读取，不重新生成，避免使原有连接失效。
        const { data } = hasKey.value
          ? await apiClient.get('/auth/me/api-key', { params: { reveal: true } })
          : await apiClient.post('/auth/me/api-key')
        if (!data.api_key) throw new Error('未获取到个人密钥，请刷新状态后重试。')
        hasKey.value = true
        key = data.api_key
      }
      return JSON.stringify(buildMcpConfig(client, endpoint, key), null, 2)
    }
    // 保留用户点击手势，兼容需要在手势内调用剪贴板的浏览器。
    if (typeof ClipboardItem !== 'undefined' && navigator.clipboard.write) {
      await navigator.clipboard.write([new ClipboardItem({ 'text/plain': content().then(text => new Blob([text], { type: 'text/plain' })) })])
    } else {
      await navigator.clipboard.writeText(await content())
    }
    notifySuccess(withIdentity && includeKey ? '已复制含个人密钥的配置，请粘贴到自己的客户端。' : '配置已复制')
  } catch (error) {
    notifyError(getErrorMessage(error))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 pb-10 sm:px-6" :class="userStore.isLoggedIn ? 'pt-8 sm:pt-10' : 'pt-24'">
    <div class="mb-6">
      <h1 class="text-xl font-semibold tracking-tight">连接 MCP</h1>
      <p class="mt-2 text-sm text-muted-foreground">选择客户端和图片范围，复制配置即可接入。</p>
    </div>

    <section class="min-w-0 rounded-xl border border-border bg-card p-5 sm:p-6">
      <fieldset :disabled="busy">
        <legend class="mb-3 text-sm font-medium">客户端</legend>
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <button v-for="client in clients" :key="client.id" :aria-pressed="selected === client.id" class="flex min-h-11 items-center justify-center gap-2 rounded-lg border px-2 py-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" :class="selected === client.id ? 'border-foreground/40 bg-muted font-medium' : 'border-border text-muted-foreground hover:bg-muted/50'" @click="selected = client.id">
            <span aria-hidden="true">{{ client.mark }}</span>{{ client.name }}
          </button>
        </div>
      </fieldset>

      <fieldset :disabled="busy" class="mt-6">
        <legend class="mb-3 text-sm font-medium">图片范围</legend>
        <div class="grid gap-2 sm:grid-cols-2">
          <button :aria-pressed="!personal" class="flex items-center justify-between rounded-lg border px-4 py-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" :class="!personal ? 'border-foreground/40 bg-muted font-medium' : 'border-border text-muted-foreground hover:bg-muted/50'" @click="selectScope(false)">公开图库<Check v-if="!personal" class="h-4 w-4" /></button>
          <button :aria-pressed="personal" class="flex items-center justify-between gap-2 rounded-lg border px-4 py-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" :class="personal ? 'border-foreground/40 bg-muted font-medium' : 'border-border text-muted-foreground hover:bg-muted/50'" @click="selectScope(true)">
            {{ userStore.isAdmin ? '全部图库（管理员）' : '公开图库 + 我的私有图片' }}
            <Check v-if="personal" class="h-4 w-4 shrink-0" /><span v-else-if="!userStore.isLoggedIn" class="shrink-0 text-xs">登录 ↗</span>
          </button>
        </div>
        <p class="mt-2 text-xs leading-5 text-muted-foreground">{{ accessDescription }}当前连接仅提供查询。</p>
      </fieldset>

      <div class="mt-6 border-t border-border pt-5">
        <div v-if="personal && (hasKey !== true || statusError)" class="mb-3 text-xs text-muted-foreground" role="status">
          {{ statusError ? '密钥状态读取失败' : hasKey === null ? '正在读取密钥状态…' : '尚无个人密钥，点击下方按钮生成并复制。' }}
          <button v-if="statusError" class="ml-2 underline" @click="loadKeyStatus">重试</button>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button v-if="installLink" as-child class="gap-2"><a :href="installLink" @click="notifySuccess('已请求打开客户端，请在客户端确认添加；未打开时可复制配置。')"><ArrowUpRight class="h-4 w-4" />添加到 {{ clientName }}</a></Button>
          <Button :variant="installLink ? 'outline' : 'default'" :disabled="busy || (personal && hasKey === null)" class="gap-2" @click="copyConfig(true)"><Copy class="h-4 w-4" />{{ busy ? '正在处理…' : copyLabel }}</Button>
        </div>
        <p class="mt-3 text-xs leading-5 text-muted-foreground">{{ selected === 'claude' ? '需安装 Node.js，粘贴至 Claude Desktop 开发者设置中的配置文件，合并后重启。' : selected === 'vscode' ? '粘贴至 VS Code 的 MCP 用户配置，合并 servers。' : selected === 'cursor' ? '粘贴至 Cursor 的 MCP 配置，合并 mcpServers。' : '按客户端要求填写服务地址与认证请求头。' }}</p>
      </div>

      <div class="mt-5 border-t border-border pt-4">
        <h2 class="text-xs font-medium text-muted-foreground">配置参数{{ personal ? '（密钥使用占位符）' : '' }}</h2>
        <div class="mt-3 overflow-hidden rounded-lg border border-border">
          <pre class="overflow-x-auto bg-muted/30 p-4 text-xs leading-6">{{ preview }}</pre>
        </div>
        <div v-if="personal" class="mt-3 flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" :disabled="busy" @click="copyConfig(false)">复制配置（自行填写密钥）</Button>
          <span class="text-xs text-muted-foreground">个人密钥沿用账号权限，仅粘贴到可信客户端。</span>
        </div>
      </div>
    </section>
    <div class="mt-4 flex gap-4 text-xs text-muted-foreground">
      <RouterLink v-if="userStore.isLoggedIn" to="/user-center" class="hover:text-foreground">管理密钥</RouterLink>
      <a href="https://github.com/127Wzc/ImgTag/blob/main/docs/external-api.md#mcp-配置" target="_blank" rel="noopener noreferrer" class="hover:text-foreground">接入文档 ↗</a>
    </div>
  </div>
</template>
