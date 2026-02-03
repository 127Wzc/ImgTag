/**
 * 运行时配置读取
 *
 * 优先级：
 * 1) window.__IMGTAG_CONFIG__（由 /config.js 注入，适合容器运行时改配置）
 * 2) import.meta.env（Vite 构建时注入，适合 Vercel/Pages 等静态部署）
 */

export type RuntimeConfigKey = `VITE_${string}`

declare global {
  interface Window {
    __IMGTAG_CONFIG__?: Partial<Record<string, string | null | undefined>>
  }
}

export function getRuntimeConfig(key: RuntimeConfigKey): string | undefined
export function getRuntimeConfig(key: string): string | undefined
export function getRuntimeConfig(key: string): string | undefined {
  const hasWindow = typeof window !== 'undefined'
  const runtimeConfig = hasWindow ? window.__IMGTAG_CONFIG__ : undefined

  // 运行时配置若“显式包含 key”，则视为 override：
  // - 非空字符串：返回该值
  // - null/undefined/空字符串：返回 undefined 且不再回退到构建期值（用于关闭配置）
  if (runtimeConfig && Object.prototype.hasOwnProperty.call(runtimeConfig, key)) {
    const runtimeValue = runtimeConfig[key]
    if (typeof runtimeValue === 'string') {
      const trimmed = runtimeValue.trim()
      return trimmed ? trimmed : undefined
    }
    return undefined
  }

  const viteEnv = import.meta.env as unknown as Record<string, string | undefined>
  const viteValue = viteEnv[key]
  if (typeof viteValue === 'string' && viteValue.trim()) {
    return viteValue.trim()
  }

  return undefined
}
