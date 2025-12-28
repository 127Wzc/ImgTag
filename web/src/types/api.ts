/**
 * 后端 API 类型定义
 * 与后端 Pydantic Schema 对应
 */

// ============= 用户相关 =============

export interface User {
    id: number
    username: string
    email: string | null
    role: 'admin' | 'user'
    api_key: string | null
}

export interface LoginResponse {
    access_token: string
    token_type: string
    user: User
}

// ============= 标签相关 =============

export interface TagWithSource {
    id: number           // 标签 ID（必需）
    name: string
    source: 'user' | 'ai' | 'system'
    level: 0 | 1 | 2  // 0=主分类, 1=分辨率, 2=普通
}

export interface Tag {
    id: number
    name: string
    parent_id: number | null
    source: 'system' | 'ai' | 'user'
    description: string | null
    level: 0 | 1 | 2
    usage_count: number
    sort_order: number
    image_count?: number
}

// ============= 图片相关 =============

export interface ImageResponse {
    id: number
    image_url: string
    tags: TagWithSource[]
    description: string | null
    original_url: string | null
    width: number | null
    height: number | null
    file_size: number | null
    uploaded_by: number | null  // 上传者用户ID
}

export interface ImageWithSimilarity extends ImageResponse {
    similarity: number
}

export interface ImageSearchRequest {
    tags?: string[]
    url_contains?: string
    description_contains?: string
    keyword?: string
    category_id?: number
    resolution_id?: number
    pending_only?: boolean
    duplicates_only?: boolean
    limit?: number
    offset?: number
    sort_by?: string
    sort_desc?: boolean
}

export interface ImageSearchResponse {
    images: ImageResponse[]
    total: number
    limit: number
    offset: number
}

export interface SimilarSearchRequest {
    text: string
    tags?: string[]
    category_id?: number
    resolution_id?: number
    limit?: number
    threshold?: number
    vector_weight?: number
    tag_weight?: number
}

export interface SimilarSearchResponse {
    images: ImageWithSimilarity[]
    total: number
}

export interface UploadAnalyzeResponse {
    id: number
    image_url: string
    tags: string[]
    description: string
    process_time: string
}

// ============= 任务相关 =============

export interface Task {
    id: string
    type: string
    status: 'pending' | 'processing' | 'completed' | 'failed'
    payload: Record<string, any> | null
    result: Record<string, any> | null
    error: string | null
    created_at: string
    completed_at: string | null
}

export interface TaskResponse {
    tasks: Task[]
    total: number
}

// ============= 收藏夹相关 =============

export interface Collection {
    id: number
    name: string
    description: string | null
    cover_image_id: number | null
    parent_id: number | null
    user_id: number | null
    is_public: boolean
    image_count?: number
}

// ============= 系统配置 =============

export interface SystemConfig {
    [key: string]: string | number | boolean | null
}

export interface PublicConfig {
    allow_register: boolean
}
