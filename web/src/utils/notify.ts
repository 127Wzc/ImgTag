import { toast } from 'vue-sonner'
import { getErrorMessage } from '@/utils/api-error'

type NotifyKind = 'success' | 'error' | 'warning' | 'info'

const lastToastAt = new Map<string, number>()

type ToastOptions = { description?: string }

function toastOnce(kind: NotifyKind, message: string, options?: ToastOptions & { withinMs?: number }) {
  const msg = (message || '').trim()
  if (!msg) return
  const desc = (options?.description || '').trim()
  const key = `${kind}:${msg}:${desc}`
  const now = Date.now()
  const last = lastToastAt.get(key) || 0
  // success 提示通常代表“操作完成”，不应被去重吞掉；其他类型默认去重 1.5s 防刷屏
  const withinMs = options?.withinMs ?? (kind === 'success' ? 0 : 1500)
  if (now - last < withinMs) return
  lastToastAt.set(key, now)

  const toastOptions: ToastOptions | undefined = desc ? { description: desc } : undefined
  if (kind === 'success') toast.success(msg, toastOptions)
  else if (kind === 'warning') toast.warning(msg, toastOptions)
  else if (kind === 'info') toast.info(msg, toastOptions)
  else toast.error(msg, toastOptions)
}

export function notifySuccess(message: string, options?: ToastOptions & { once?: boolean }) {
  if (options?.once) return toastOnce('success', message, options)
  toast.success(message, options?.description ? { description: options.description } : undefined)
}

export function notifyWarning(message: string, options?: ToastOptions & { once?: boolean }) {
  if (options?.once) return toastOnce('warning', message, options)
  toast.warning(message, options?.description ? { description: options.description } : undefined)
}

export function notifyInfo(message: string, options?: ToastOptions & { once?: boolean }) {
  if (options?.once) return toastOnce('info', message, options)
  toast.info(message, options?.description ? { description: options.description } : undefined)
}

export function notifyError(error: unknown, options?: ToastOptions & { once?: boolean }) {
  const msg = typeof error === 'string' ? error : getErrorMessage(error as any)
  if (options?.once ?? true) return toastOnce('error', msg, options)
  toast.error(msg, options?.description ? { description: options.description } : undefined)
}
