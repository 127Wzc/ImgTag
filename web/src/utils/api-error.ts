/**
 * API 错误处理工具
 * 提供统一的错误消息提取和处理
 */

export interface APIErrorResponse {
    success: false
    error: {
        code: string
        message: string
        [key: string]: any
    }
}

/**
 * 从 API 错误中提取用户友好的错误消息
 */
export function getErrorMessage(error: any): string {
    // 新格式: { success: false, error: { code, message } }
    if (error.response?.data?.error?.message) {
        return error.response.data.error.message
    }

    // 旧格式: { detail: "..." }
    if (error.response?.data?.detail) {
        return error.response.data.detail
    }

    // Axios 网络错误
    if (error.message) {
        // 常见网络错误翻译
        if (error.message === 'Network Error') {
            return '网络连接失败，请检查网络'
        }
        if (error.code === 'ECONNABORTED') {
            return '请求超时，请稍后重试'
        }
        return error.message
    }

    return '操作失败，请稍后重试'
}

/**
 * 获取错误码（用于程序逻辑判断）
 */
export function getErrorCode(error: any): string | null {
    return error.response?.data?.error?.code || null
}

/**
 * 判断是否为特定错误码
 */
export function isErrorCode(error: any, code: string): boolean {
    return getErrorCode(error) === code
}

/**
 * 常见错误码
 */
export const ErrorCodes = {
    // 验证错误
    VALIDATION_ERROR: 'VALIDATION_ERROR',
    EMPTY_VALUE: 'EMPTY_VALUE',

    // 认证错误
    UNAUTHORIZED: 'UNAUTHORIZED',
    TOKEN_EXPIRED: 'TOKEN_EXPIRED',

    // 权限错误
    FORBIDDEN: 'FORBIDDEN',
    ADMIN_REQUIRED: 'ADMIN_REQUIRED',
    OWNER_REQUIRED: 'OWNER_REQUIRED',

    // 资源错误
    NOT_FOUND: 'NOT_FOUND',
    TAG_NOT_FOUND: 'TAG_NOT_FOUND',
    IMAGE_NOT_FOUND: 'IMAGE_NOT_FOUND',

    // 冲突错误
    CONFLICT: 'CONFLICT',
    DUPLICATE: 'DUPLICATE',
    TAG_EXISTS: 'TAG_EXISTS',

    // 服务器错误
    INTERNAL_ERROR: 'INTERNAL_ERROR',
} as const
