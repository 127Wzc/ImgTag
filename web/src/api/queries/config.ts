import apiClient from '../client'

/** 单个配置项；密钥已设置时，后端返回脱敏值和 has_value。 */
export interface ConfigResponse {
    key: string
    value: string
    has_value?: boolean
}

/** 按配置名读取配置，需要管理员权限；密钥默认返回 ******。 */
export async function getConfig(key: string): Promise<ConfigResponse> {
    if (!key.trim()) {
        throw new Error('配置名不能为空')
    }

    const { data } = await apiClient.get<ConfigResponse>(`/config/${encodeURIComponent(key)}`)
    return data
}
