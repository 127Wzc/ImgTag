/**
 * 后端 API 类型定义
 * 与后端 Pydantic Schema 对应 (snake_case 格式)
 */

// ============= 通用分页类型 =============

export interface PaginatedResponse<T> {
    data: T[]
    total: number
    page: number
    size: number
    pages: number
    has_next: boolean
    has_prev: boolean
}

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
    code?: string | null        // 分类代码(用于存储子目录)
    prompt?: string | null      // 分类专用分析提示词
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
    is_public?: boolean
    created_at?: string | null
    updated_at?: string | null
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
    // Page/Size 风格分页
    page?: number
    size?: number
    sort_by?: string
    sort_desc?: boolean
}

// 分页响应 (使用新的 data 结构)
export interface ImageSearchResponse extends PaginatedResponse<ImageResponse> { }

export interface SimilarSearchRequest {
    text: string
    tags?: string[]
    category_id?: number
    resolution_id?: number
    // Page/Size 风格分页
    page?: number
    size?: number
    threshold?: number
    vector_weight?: number
    tag_weight?: number
}

export interface SimilarSearchResponse extends PaginatedResponse<ImageWithSimilarity> { }

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
    updated_at?: string
    completed_at: string | null
}

export interface TaskListResponse extends PaginatedResponse<Task> { }

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
    sort_order?: number
    created_at?: string
    updated_at?: string
}

export interface CollectionListResponse extends PaginatedResponse<Collection> { }

// ============= 审批相关 =============

export interface ApprovalResponse {
    id: number
    type: string
    status: string
    requester_id: number | null
    requester_name: string | null
    target_type: string | null
    target_ids: number[] | null
    payload: Record<string, any>
    reviewer_id: number | null
    review_comment: string | null
    created_at: string
    reviewed_at: string | null
}

export interface ApprovalListResponse extends PaginatedResponse<ApprovalResponse> { }

// ============= 系统配置 =============

export interface SystemConfig {
    [key: string]: string | number | boolean | null
}

export interface PublicConfig {
    allow_register: boolean
}
