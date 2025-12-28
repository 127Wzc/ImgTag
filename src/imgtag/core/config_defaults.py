"""Default configuration values.

This module contains all default configuration keys and values.
It's a standalone module with NO dependencies to avoid circular imports.

Both ConfigService and ConfigRepository import from here.
"""

DEFAULT_CONFIG: dict[str, str] = {
    # 视觉模型配置
    "vision_api_base_url": "https://api.openai.com/v1",
    "vision_api_key": "",
    "vision_model": "gpt-4o-mini",
    "vision_max_image_size": "2048",
    "vision_allowed_extensions": "jpg,jpeg,png,webp,bmp",
    "vision_convert_gif": "true",
    "vision_prompt": """请分析这张图片，并按以下格式返回JSON响应:
{
    "tags": ["标签1", "标签2", "标签3", ...],
    "description": "详细的图片描述文本"
}

要求：
1. tags: 提取5-10个关键标签，使用中文
2. description: 用中文详细描述图片内容

请只返回JSON格式，不要添加任何其他文字。""",
    # 嵌入模型配置
    "embedding_mode": "local",
    "embedding_local_model": "BAAI/bge-small-zh-v1.5",
    "hf_endpoint": "https://hf-mirror.com",
    "embedding_api_base_url": "https://api.openai.com/v1",
    "embedding_api_key": "",
    "embedding_model": "text-embedding-3-small",
    "embedding_dimensions": "512",
    # 队列配置
    "queue_max_workers": "2",
    "queue_batch_interval": "1",
    # 上传配置
    "max_upload_size": "10",
    # S3 存储配置
    "s3_enabled": "false",
    "s3_endpoint_url": "",
    "s3_access_key_id": "",
    "s3_secret_access_key": "",
    "s3_bucket_name": "",
    "s3_region": "us-east-1",
    "s3_public_url_prefix": "",
    "s3_path_prefix": "imgtag/",
    "s3_force_reupload": "false",
    "image_url_priority": "auto",
    # 系统配置
    "base_url": "",
    "allow_register": "true",
}
