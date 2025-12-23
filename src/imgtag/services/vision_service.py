#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
视觉模型服务
使用 OpenAI 兼容的 API 分析图像
"""

import base64
import json
import re
import time
import datetime
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
            logger.debug(f"  - Response Type: {type(response)}")
            
            # 使用统一的内容提取方法（支持 OpenAI 和 Google 格式）
            content = self._extract_content_from_response(response)
            logger.debug(f"  - Extracted content length: {len(content)}")
                
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
            logger.debug(f"  - Response Type: {type(response)}")
            
            # 使用统一的内容提取方法（支持 OpenAI 和 Google 格式）
            content = self._extract_content_from_response(response)
            logger.debug(f"  - Extracted content length: {len(content)}")
                
            return self._parse_response(content)
            
        except Exception as e:
            logger.error(f"视觉模型分析失败: {str(e)}")
            raise

    def _convert_google_to_openai(self, google_response: dict) -> dict:
        """将 Google Gemini 原生响应转换为 OpenAI 标准 Chat Completion 响应格式"""
        
        # 1. 提取核心数据层
        data = google_response.get("response", google_response)
        
        # 2. 处理时间戳
        created_timestamp = int(time.time())
        if "createTime" in data:
            try:
                dt = datetime.datetime.strptime(data["createTime"].split(".")[0], "%Y-%m-%dT%H:%M:%S")
                created_timestamp = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
            except Exception:
                pass

        # 3. 映射 Finish Reason
        finish_reason_map = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "OTHER": "stop"
        }

        # 4. 构建 Choices 列表
        choices = []
        if "candidates" in data:
            for index, candidate in enumerate(data["candidates"]):
                content_parts = candidate.get("content", {}).get("parts", [])
                full_text = "".join([part.get("text", "") for part in content_parts])
                
                g_finish = candidate.get("finishReason", "STOP")
                o_finish = finish_reason_map.get(g_finish, "stop")

                choice = {
                    "index": index,
                    "message": {
                        "role": "assistant",
                        "content": full_text
                    },
                    "finish_reason": o_finish
                }
                choices.append(choice)

        # 5. 处理 Usage
        usage_meta = data.get("usageMetadata", {})
        usage = {
            "prompt_tokens": usage_meta.get("promptTokenCount", 0),
            "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
            "total_tokens": usage_meta.get("totalTokenCount", 0)
        }

        # 6. 组装最终 OpenAI 格式
        openai_response = {
            "id": f"chatcmpl-{data.get('responseId', 'unknown')}",
            "object": "chat.completion",
            "created": created_timestamp,
            "model": data.get("modelVersion", "gemini-model"),
            "choices": choices,
            "usage": usage,
            "system_fingerprint": data.get("responseId")
        }

        return openai_response

    def _extract_content_from_response(self, response) -> str:
        """从响应中提取内容，支持 OpenAI 和 Google Gemini 格式"""
        
        # 尝试 OpenAI 格式（标准路径）
        if hasattr(response, 'choices') and response.choices and len(response.choices) > 0:
            choice = response.choices[0]
            if hasattr(choice, 'message') and choice.message:
                content = getattr(choice.message, 'content', None)
                if content:
                    logger.debug(f"从 OpenAI 格式提取内容成功")
                    return content
        
        # 尝试将 OpenAI 对象转为字典
        response_dict = None
        if hasattr(response, 'model_dump'):
            response_dict = response.model_dump()
            logger.debug(f"使用 model_dump() 转换响应: {list(response_dict.keys())}")
        elif hasattr(response, '__dict__'):
            response_dict = response.__dict__
            logger.debug(f"使用 __dict__ 转换响应")
        elif isinstance(response, dict):
            response_dict = response
        
        if response_dict:
            # 打印原始响应用于调试
            logger.debug(f"原始响应字典: {json.dumps(response_dict, ensure_ascii=False, default=str)[:500]}...")
            
            # 检查是否是 Google Gemini 格式（包含 response.candidates）
            if "response" in response_dict and isinstance(response_dict["response"], dict):
                inner = response_dict["response"]
                if "candidates" in inner:
                    logger.debug("检测到 Google Gemini 响应格式（内层），正在提取...")
                    for candidate in inner.get("candidates", []):
                        parts = candidate.get("content", {}).get("parts", [])
                        for part in parts:
                            text = part.get("text", "")
                            if text:
                                logger.debug(f"提取到文本内容，长度: {len(text)}")
                                return text
            
            # 直接检查 candidates（无外层包装）
            if "candidates" in response_dict:
                logger.debug("检测到 Google Gemini 响应格式（外层），正在提取...")
                for candidate in response_dict.get("candidates", []):
                    parts = candidate.get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            logger.debug(f"提取到文本内容，长度: {len(text)}")
                            return text
            
            # 检查 choices（字典格式）
            if "choices" in response_dict and response_dict["choices"]:
                for choice in response_dict["choices"]:
                    msg = choice.get("message", {})
                    content = msg.get("content", "")
                    if content:
                        logger.debug(f"从 choices 字典提取内容成功")
                        return content
        
        raise ValueError("无法从响应中提取内容，请检查 API 配置")

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
