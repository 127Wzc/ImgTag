#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
视觉模型服务
使用 OpenAI 兼容的 API 分析图像
"""

import base64
import json
import re
from dataclasses import dataclass
from typing import List, Optional

from openai import AsyncOpenAI

from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ImageAnalysisResult:
    """图像分析结果"""
    tags: List[str]
    description: str
    raw_response: Optional[str] = None


class VisionService:
    """视觉模型服务类"""
    
    def __init__(self):
        """初始化视觉模型服务"""
        logger.info("初始化视觉模型服务")
    
    def _get_client(self) -> AsyncOpenAI:
        """获取 OpenAI 客户端（从数据库配置）"""
        from imgtag.db import config_db
        
        api_base = config_db.get("vision_api_base_url", "https://api.openai.com/v1")
        api_key = config_db.get("vision_api_key", "")
        
        if not api_key:
            raise ValueError("视觉模型 API 密钥未配置，请在系统设置中配置")
        
        return AsyncOpenAI(
            api_key=api_key,
            base_url=api_base
        )
    
    def _get_model(self) -> str:
        """获取模型名称"""
        from imgtag.db import config_db
        return config_db.get("vision_model", "gpt-4o-mini")
    
    def _get_prompt(self) -> str:
        """获取分析提示词"""
        from imgtag.db import config_db
        return config_db.get("vision_prompt", """请分析这张图片，并按以下格式返回JSON响应:
{
    "tags": ["标签1", "标签2", "标签3", ...],
    "description": "详细的图片描述文本"
}

要求：
1. tags: 提取5-10个关键标签，使用中文
2. description: 用中文详细描述图片内容

请只返回JSON格式，不要添加任何其他文字。""")
    
    async def analyze_image_url(self, image_url: str) -> ImageAnalysisResult:
        """分析远程图像 URL"""
        logger.info(f"分析远程图像: {image_url[:50]}...")
        
        try:
            client = self._get_client()
            model = self._get_model()
            prompt = self._get_prompt()
            
            # DEBUG: 打印请求参数
            from imgtag.db import config_db
            api_base = config_db.get("vision_api_base_url", "https://api.openai.com/v1")
            logger.debug(f"视觉模型 API 请求参数:")
            logger.debug(f"  - API Base: {api_base}")
            logger.debug(f"  - Model: {model}")
            logger.debug(f"  - Image URL: {image_url}")
            logger.debug(f"  - Prompt: {prompt[:100]}...")
            logger.debug(f"  - stream: False")
            
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}}
                        ]
                    }
                ],
                stream=False,  # 明确禁用流式响应
            )
            
            # DEBUG: 打印响应元数据
            logger.debug(f"视觉模型 API 响应:")
            logger.debug(f"  - Model: {getattr(response, 'model', None)}")
            
            # 检查响应是否有效
            if not response or not response.choices or len(response.choices) == 0:
                raise ValueError(f"视觉模型 API 返回空响应，请检查 API 配置和模型名称是否正确")
            
            logger.debug(f"  - Finish Reason: {response.choices[0].finish_reason}")
            if response.usage:
                logger.debug(f"  - Usage: prompt_tokens={response.usage.prompt_tokens}, completion_tokens={response.usage.completion_tokens}, total={response.usage.total_tokens}")
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("视觉模型返回内容为空")
                
            return self._parse_response(content)
            
        except Exception as e:
            logger.error(f"视觉模型分析失败: {str(e)}")
            raise
    
    async def analyze_image_base64(self, image_data: bytes, mime_type: str = "image/jpeg") -> ImageAnalysisResult:
        """分析 Base64 编码的图像"""
        logger.info(f"分析 Base64 图像, 类型: {mime_type}")
        
        try:
            client = self._get_client()
            model = self._get_model()
            prompt = self._get_prompt()
            
            base64_image = base64.b64encode(image_data).decode("utf-8")
            data_url = f"data:{mime_type};base64,{base64_image}"
            
            # DEBUG: 打印请求参数
            from imgtag.db import config_db
            api_base = config_db.get("vision_api_base_url", "https://api.openai.com/v1")
            logger.debug(f"视觉模型 API 请求参数:")
            logger.debug(f"  - API Base: {api_base}")
            logger.debug(f"  - Model: {model}")
            logger.debug(f"  - Image: Base64 ({len(image_data)} bytes, {mime_type})")
            logger.debug(f"  - Prompt: {prompt[:100]}...")
            logger.debug(f"  - stream: False")
            
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}}
                        ]
                    }
                ],
                stream=False,  # 明确禁用流式响应
            )
            
            # DEBUG: 打印响应元数据
            logger.debug(f"视觉模型 API 响应:")
            logger.debug(f"  - Model: {getattr(response, 'model', None)}")
            
            # 检查响应是否有效
            if not response or not response.choices or len(response.choices) == 0:
                raise ValueError(f"视觉模型 API 返回空响应，请检查 API 配置和模型名称是否正确")
            
            logger.debug(f"  - Finish Reason: {response.choices[0].finish_reason}")
            if response.usage:
                logger.debug(f"  - Usage: prompt_tokens={response.usage.prompt_tokens}, completion_tokens={response.usage.completion_tokens}, total={response.usage.total_tokens}")
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("视觉模型返回内容为空")
                
            return self._parse_response(content)
            
        except Exception as e:
            logger.error(f"视觉模型分析失败: {str(e)}")
            raise
    
    def _parse_response(self, content: str) -> ImageAnalysisResult:
        """解析模型响应"""
        # DEBUG: 打印原始响应内容
        logger.debug(f"视觉模型原始响应内容:\n{content}")
        
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                json_str = json_match.group()
                logger.debug(f"提取到的 JSON 字符串:\n{json_str}")
                data = json.loads(json_str)
                logger.debug(f"JSON 解析成功: tags={len(data.get('tags', []))}个, description长度={len(data.get('description', ''))}")
                return ImageAnalysisResult(
                    tags=data.get("tags", []),
                    description=data.get("description", ""),
                    raw_response=content
                )
            else:
                logger.debug("未能从响应中提取到 JSON 格式内容")
        except json.JSONDecodeError as e:
            logger.debug(f"JSON 解析失败: {str(e)}")
        
        # 降级处理
        logger.warning(f"无法解析 JSON 响应，使用降级处理。原始内容: {content[:200]}...")
        return ImageAnalysisResult(
            tags=[],
            description=content.strip(),
            raw_response=content
        )


# 全局实例
vision_service = VisionService()
