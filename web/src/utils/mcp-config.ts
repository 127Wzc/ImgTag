export type McpClient = 'cursor' | 'vscode' | 'claude' | 'generic'

export function buildMcpConfig(client: McpClient, url: string, key?: string) {
  const name = key ? 'imgtag-personal' : 'imgtag-public'
  const server = client === 'claude'
    ? {
        command: 'npx',
        args: ['-y', 'mcp-remote', url, ...(url.startsWith('http:') ? ['--allow-http'] : []),
          ...(key ? ['--header', 'Authorization:${IMGTAG_AUTH}'] : [])],
        ...(key ? { env: { IMGTAG_AUTH: `Bearer ${key}` } } : {}),
      }
    : { ...(client === 'vscode' ? { type: 'http' } : {}), url,
        ...(key ? { headers: { Authorization: `Bearer ${key}` } } : {}) }
  return { [client === 'vscode' ? 'servers' : 'mcpServers']: { [name]: server } }
}

// 安装链接只用于公开配置，个人密钥仅通过显式复制交付。
export function publicMcpInstallLink(client: McpClient, url: string): string | null {
  if (client === 'cursor') {
    const encoded = btoa(Array.from(new TextEncoder().encode(JSON.stringify({ url })), byte => String.fromCharCode(byte)).join(''))
    return `cursor://anysphere.cursor-deeplink/mcp/install?name=imgtag-public&config=${encodeURIComponent(encoded)}`
  }
  if (client === 'vscode') {
    return `vscode:mcp/install?${encodeURIComponent(JSON.stringify({ name: 'imgtag-public', type: 'http', url }))}`
  }
  return null
}
