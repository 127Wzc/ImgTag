import axios from 'axios'

// 创建 axios 实例
const api = axios.create({
    baseURL: '/api/v1',
    timeout: 60000, // 60秒超时（视觉模型可能需要较长时间）
    headers: {
        'Content-Type': 'application/json'
    }
})

// 请求拦截器 - 自动添加 Authorization 头
api.interceptors.request.use(
    config => {
        const token = localStorage.getItem('token')
        if (token) {
            config.headers.Authorization = `Bearer ${token}`
        }
        return config
    },
    error => Promise.reject(error)
)

// 响应拦截器
api.interceptors.response.use(
    response => response.data,
    error => {
        const message = error.response?.data?.detail || error.message || '请求失败'

        // 401 未授权 - 清除 token
        if (error.response?.status === 401) {
            localStorage.removeItem('token')
        }

        return Promise.reject(new Error(message))
    }
)

// ============ 图像 API ============

// 获取图像列表
export const getImages = (params = {}) => {
    return api.post('/images/search', {
        tags: params.tags || null,
        url_contains: params.urlContains || null,
        description_contains: params.descriptionContains || null,
        keyword: params.keyword || null,
        pending_only: params.pendingOnly || false,
        duplicates_only: params.duplicatesOnly || false,
        limit: params.limit || 20,
        offset: params.offset || 0,
        sort_by: params.sortBy || 'id',
        sort_desc: params.sortDesc ?? true
    })
}

// 获取单个图像
export const getImage = (id) => {
    return api.get(`/images/${id}`)
}

// 手动创建图像
export const createImage = (data) => {
    return api.post('/images/', data)
}

// 通过 URL 分析图像
export const analyzeImageByUrl = (imageUrl, autoAnalyze = true) => {
    return api.post('/images/analyze-url', {
        image_url: imageUrl,
        auto_analyze: autoAnalyze
    })
}

// 上传并分析图像
export const uploadAndAnalyze = (file, autoAnalyze = true) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('auto_analyze', autoAnalyze)

    return api.post('/images/upload', formData, {
        headers: {
            'Content-Type': 'multipart/form-data'
        }
    })
}

// 更新图像
export const updateImage = (id, data) => {
    return api.put(`/images/${id}`, data)
}

// 删除图像
export const deleteImage = (id) => {
    return api.delete(`/images/${id}`)
}

// 批量删除图像
export const batchDeleteImages = (imageIds) => {
    return api.post('/images/batch/delete', imageIds)
}

// 批量更新标签
export const batchUpdateTags = (imageIds, tags, mode = 'add') => {
    return api.post('/images/batch/update-tags', {
        image_ids: imageIds,
        tags: tags,
        mode: mode
    })
}

// ============ 搜索 API ============

// 相似度搜索
export const searchSimilar = (text, tags = [], limit = 10, threshold = 0.5, vectorWeight = 0.7, tagWeight = 0.3) => {
    return api.post('/search/similar', {
        text,
        tags: tags.length > 0 ? tags : null,
        limit,
        threshold,
        vector_weight: vectorWeight,
        tag_weight: tagWeight
    })
}

// ============ 系统 API ============

// 获取系统状态
export const getSystemStatus = () => {
    return api.get('/system/status')
}

// 健康检查
export const healthCheck = () => {
    return api.get('/system/health')
}

// 获取系统配置
export const getSystemConfig = () => {
    return api.get('/system/config')
}

// 导出数据库
export const exportDatabase = () => {
    return api.get('/system/export', {
        responseType: 'blob'
    })
}

// 导入数据库
export const importDatabase = (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/system/import', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
    })
}

// 获取可用模型列表
export const getAvailableModels = () => {
    return api.get('/system/models')
}

// 获取重复图片
export const getDuplicates = () => {
    return api.get('/system/duplicates')
}

// 计算缺失的文件哈希
export const calculateHashes = (limit = 100) => {
    return api.post('/system/duplicates/calculate-hashes', null, { params: { limit } })
}

// ============ 配置管理 API ============

// 获取所有配置
export const getAllConfigs = () => {
    return api.get('/config/')
}

// 更新配置
export const updateConfigs = (configs) => {
    return api.put('/config/', { configs })
}

// ============ 向量管理 API ============

// 获取向量状态
export const getVectorStatus = () => {
    return api.get('/vectors/status')
}

// 检查本地依赖
export const checkLocalDeps = () => {
    return api.get('/vectors/check-local')
}

// 调整数据库维度
export const resizeVectorTable = () => {
    return api.post('/vectors/resize-table')
}

// 启动向量重建
export const startRebuildVectors = () => {
    return api.post('/vectors/rebuild')
}

// 获取重建状态
export const getRebuildStatus = () => {
    return api.get('/vectors/rebuild/status')
}

// 清空向量数据
export const clearVectors = () => {
    return api.delete('/vectors/clear')
}

// 安装本地嵌入模型依赖
export const installLocalDeps = () => {
    return api.post('/vectors/install-local')
}

// 获取本地依赖安装状态
export const getInstallStatus = () => {
    return api.get('/vectors/install-local/status')
}

// ============ 队列管理 API ============

// 获取队列状态
export const getQueueStatus = () => {
    return api.get('/queue/status')
}

// 添加任务到队列
export const addToQueue = (imageIds) => {
    return api.post('/queue/add', { image_ids: imageIds })
}

// 添加未打标签的图片到队列
export const addUntaggedToQueue = () => {
    return api.post('/queue/add-untagged')
}

// 启动队列
export const startQueue = () => {
    return api.post('/queue/start')
}

// 停止队列
export const stopQueue = () => {
    return api.post('/queue/stop')
}

// 清空队列
export const clearQueue = () => {
    return api.delete('/queue/clear')
}

// 配置队列线程数
export const setQueueWorkers = (maxWorkers) => {
    return api.put('/queue/config', { max_workers: maxWorkers })
}

// 批量上传（跳过分析）
export const uploadOnly = (file) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('skip_analyze', true)

    return api.post('/images/upload', formData, {
        headers: {
            'Content-Type': 'multipart/form-data'
        }
    })
}

// 上传 ZIP 文件
export const uploadZip = (file) => {
    const formData = new FormData()
    formData.append('file', file)

    return api.post('/images/upload-zip', formData, {
        headers: {
            'Content-Type': 'multipart/form-data'
        },
        timeout: 300000  // 5 分钟超时（大文件）
    })
}

export default api


// 收藏夹相关 API
export const getCollections = () => {
    return api.get('/collections/')
}

export const createCollection = (data) => {
    return api.post('/collections/', data)
}

export const getCollection = (id) => {
    return api.get(`/collections/${id}`)
}

export const updateCollection = (id, data) => {
    return api.put(`/collections/${id}`, data)
}

export const deleteCollection = (id) => {
    return api.delete(`/collections/${id}`)
}

export const addImageToCollection = (collectionId, imageId) => {
    return api.post(`/collections/${collectionId}/images`, { image_id: imageId })
}

export const removeImageFromCollection = (collectionId, imageId) => {
    return api.delete(`/collections/${collectionId}/images/${imageId}`)
}

export const getCollectionImages = (collectionId, params = {}) => {
    return api.get(`/collections/${collectionId}/images`, { params })
}

// 标签相关 API
export const getTags = (params = {}) => {
    return api.get('/tags/', { params })
}

export const syncTags = () => {
    return api.post('/tags/sync')
}

export const renameTag = (oldName, newName) => {
    return api.put(`/tags/${encodeURIComponent(oldName)}`, { new_name: newName })
}

export const deleteTag = (tagName) => {
    return api.delete(`/tags/${encodeURIComponent(tagName)}`)
}

// 任务相关 API
export const getTasks = (params = {}) => {
    return api.get('/tasks/', { params })
}

export const cleanupTasks = (days = 7) => {
    return api.post('/tasks/cleanup', null, { params: { days } })
}

// ============ 认证 API ============

// 用户登录
export const login = (username, password) => {
    return api.post('/auth/login', { username, password })
}

// 用户注册
export const register = (username, password, email = null) => {
    return api.post('/auth/register', { username, password, email })
}

// 获取当前用户信息
export const getCurrentUser = () => {
    return api.get('/auth/me')
}

// 登出
export const logout = () => {
    return api.post('/auth/logout')
}

// ============ 用户管理 API （管理员）============

// 获取所有用户
export const getUsers = () => {
    return api.get('/auth/users')
}

// 创建用户
export const createUser = (username, password, email = null) => {
    return api.post('/auth/users', { username, password, email })
}

// 更新用户
export const updateUser = (userId, data) => {
    return api.put(`/auth/users/${userId}`, null, { params: data })
}

// 删除用户  
export const deleteUser = (userId) => {
    return api.delete(`/auth/users/${userId}`)
}

// 修改用户密码
export const changeUserPassword = (userId, newPassword) => {
    return api.put(`/auth/users/${userId}/password`, null, { params: { new_password: newPassword } })
}

// ============ 个人中心 API ============

// 修改自己的密码
export const changeMyPassword = (oldPassword, newPassword) => {
    return api.put('/auth/me/password', { old_password: oldPassword, new_password: newPassword })
}

// 生成 API 密钥
export const generateApiKey = () => {
    return api.post('/auth/me/api-key')
}

// 获取 API 密钥（脱敏）
export const getApiKey = () => {
    return api.get('/auth/me/api-key')
}

// 删除 API 密钥
export const deleteApiKey = () => {
    return api.delete('/auth/me/api-key')
}

// ============ 审批 API ============

// 获取待审批列表
export const getPendingApprovals = (params = {}) => {
    return api.get('/approvals/', { params })
}

// 获取审批详情
export const getApproval = (id) => {
    return api.get(`/approvals/${id}`)
}

// 批准审批请求
export const approveRequest = (id, comment = null) => {
    return api.post(`/approvals/${id}/approve`, { comment })
}

// 拒绝审批请求
export const rejectRequest = (id, comment = null) => {
    return api.post(`/approvals/${id}/reject`, { comment })
}

// 批量批准
export const batchApprove = (approvalIds, comment = null) => {
    return api.post('/approvals/batch-approve', { approval_ids: approvalIds, comment })
}
