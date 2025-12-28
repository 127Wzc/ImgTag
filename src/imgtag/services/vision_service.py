#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Vision model service.

Analyzes images using OpenAI-compatible vision APIs via httpx.
"""

import asyncio
import base64
import io
import json
import re
import time
import traceback
import datetime
from dataclasses import dataclass
from typing import Optional

import httpx
from PIL import Image

from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ImageAnalysisResult:
    """Result from image analysis.

    Attributes:
        tags: Extracted image tags.
        description: Image description text.
        raw_response: Raw API response for debugging.
    """

    tags: list[str]
    description: str
    raw_response: Optional[str] = None


class VisionService:
    """Vision model service class.

    Uses httpx to call OpenAI-compatible vision APIs for image analysis.
    """

    def __init__(self) -> None:
        """Initialize the vision service."""
        logger.info("初始化视觉模型服务")

    async def _get_api_config(self) -> tuple[str, str, str]:
        """Get API configuration from database.

        Returns:
            Tuple of (api_base_url, api_key, model_name).

        Raises:
            ValueError: If API key is not configured.
        """
        api_base = await config_cache.get("vision_api_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1"
        api_key = await config_cache.get("vision_api_key", "") or ""
        model = await config_cache.get("vision_model", "gpt-4o-mini") or "gpt-4o-mini"

        if not api_key:
            raise ValueError("视觉模型 API 密钥未配置，请在系统设置中配置")

        return api_base, api_key, model
    
    def _compress_image(self, image_data: bytes, max_size: int = 1024 * 1024, max_dimension: int = 2048) -> tuple:
        """压缩图片到指定大小以内（优化识别效果）
        
        支持格式：JPEG, PNG, GIF（取第一帧）, WebP, BMP 等
        
        压缩策略（按优先级）：
        1. GIF 提取第一帧转为静态图
        2. 缩放到最大边长 2048px（视觉模型内部也会缩放，不影响识别）
        3. 使用 JPEG 质量 85 压缩
        4. 如果仍超限，逐步降低分辨率（优先于降低质量）
        5. 最低质量保持 60，避免影响识别效果
        
        Args:
            image_data: 原始图片字节数据
            max_size: 最大文件大小（字节），默认 1MB
            max_dimension: 最大边长（像素），默认 2048
            
        Returns:
            (压缩后的字节数据, MIME类型)
        """
        
        # 打开图片
        img = Image.open(io.BytesIO(image_data))
        original_size = img.size
        original_format = img.format or "UNKNOWN"
        
        logger.debug(f"原始图片: {original_format}, {original_size[0]}x{original_size[1]}, mode={img.mode}")
        
        # GIF 处理：提取第一帧
        if original_format == 'GIF':
            img.seek(0)  # 确保是第一帧
            logger.debug("GIF 图片，提取第一帧")
        
        # 转换为 RGB（去除透明通道，JPEG 不支持）
        if img.mode in ('RGBA', 'P', 'LA', 'PA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            # 处理带透明通道的图片
            if img.mode in ('RGBA', 'LA', 'PA'):
                try:
                    alpha = img.split()[-1]
                    background.paste(img, mask=alpha)
                except Exception:
                    background.paste(img)
            else:
                background.paste(img)
            img = background
        elif img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        elif img.mode == 'L':
            img = img.convert('RGB')
        
        # 第一步：缩放到最大边长
        width, height = img.size
        if max(width, height) > max_dimension:
            ratio = max_dimension / max(width, height)
            new_size = (int(width * ratio), int(height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logger.debug(f"图片缩放: {width}x{height} -> {new_size[0]}x{new_size[1]}")
        
        # 第二步：尝试高质量压缩
        quality = 85
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        if len(buffer.getvalue()) <= max_size:
            logger.debug(f"压缩成功: quality={quality}, size={len(buffer.getvalue())/1024:.1f}KB")
            return buffer.getvalue(), "image/jpeg"
        
        # 第三步：优先缩小分辨率（保持质量 75）
        scale_steps = [1536, 1280, 1024, 768, 512]
        for target_dim in scale_steps:
            if max(img.size) > target_dim:
                ratio = target_dim / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                resized = img.resize(new_size, Image.Resampling.LANCZOS)
                
                buffer = io.BytesIO()
                resized.save(buffer, format='JPEG', quality=75, optimize=True)
                
                if len(buffer.getvalue()) <= max_size:
                    logger.debug(f"压缩成功（缩小分辨率）: {new_size[0]}x{new_size[1]}, quality=75, size={len(buffer.getvalue())/1024:.1f}KB")
                    return buffer.getvalue(), "image/jpeg"
        
        # 第四步：最后手段 - 降低质量（但不低于 60）
        quality = 65
        while quality >= 60:
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            
            if len(buffer.getvalue()) <= max_size:
                logger.debug(f"压缩成功（降低质量）: quality={quality}, size={len(buffer.getvalue())/1024:.1f}KB")
                return buffer.getvalue(), "image/jpeg"
            
            quality -= 5
        
        # 返回最终结果（使用最小分辨率和质量 60）
        final_img = img.resize((512, int(512 * img.size[1] / img.size[0])), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        final_img.save(buffer, format='JPEG', quality=60, optimize=True)
        logger.warning(f"图片压缩后仍超限: {len(buffer.getvalue())/1024:.1f}KB (原始: {original_format} {original_size})")
        return buffer.getvalue(), "image/jpeg"
    
    async def _get_model(self) -> str:
        """获取视觉模型名称"""
        return await config_cache.get("vision_model", "gpt-4o-mini") or "gpt-4o-mini"
    
    async def _get_prompt(self) -> str:
        """获取分析提示词"""
        default_prompt = """请分析这张图片，并按以下格式返回JSON响应:
{
    "tags": ["标签1", "标签2", "标签3", ...],
    "description": "详细的图片描述文本"
}

要求：
1. tags: 提取5-10个关键标签，使用中文
2. description: 用中文详细描述图片内容

请只返回JSON格式，不要添加任何其他文字。"""
        return await config_cache.get("vision_prompt", default_prompt) or default_prompt
    
    async def analyze_image_url(self, image_url: str) -> ImageAnalysisResult:
        """Analyze a remote image by URL.
        
        Downloads the image first, then analyzes using base64 method.
        This ensures compatibility with all vision APIs.

        Args:
            image_url: URL of the image to analyze.

        Returns:
            ImageAnalysisResult with tags and description.

        Raises:
            ValueError: If download fails or API is not configured.
        """
        logger.info(f"分析远程图像: {image_url[:50]}...")

        try:
            # 下载远程图片
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(image_url)
                
                if response.status_code != 200:
                    raise ValueError(f"下载图片失败: HTTP {response.status_code}")
                
                image_data = response.content
                
                # 检测 MIME 类型
                content_type = response.headers.get("content-type", "image/jpeg")
                if ";" in content_type:
                    content_type = content_type.split(";")[0].strip()
                
                # 如果无法确定类型，尝试从 URL 推断
                if content_type == "application/octet-stream" or not content_type.startswith("image/"):
                    url_lower = image_url.lower()
                    if ".png" in url_lower:
                        content_type = "image/png"
                    elif ".gif" in url_lower:
                        content_type = "image/gif"
                    elif ".webp" in url_lower:
                        content_type = "image/webp"
                    else:
                        content_type = "image/jpeg"
                
                logger.debug(f"下载图片成功: {len(image_data)} bytes, {content_type}")
            
            # 使用 base64 方法分析
            return await self.analyze_image_base64(image_data, content_type)

        except httpx.ConnectError as e:
            logger.error(f"下载图片连接失败: {e}")
            raise ValueError(f"无法连接到图片服务器") from e
        except httpx.TimeoutException as e:
            logger.error(f"下载图片超时: {e}")
            raise ValueError("下载图片超时") from e
        except Exception as e:
            logger.error(f"远程图片分析失败: {e}")
            raise
    
    async def analyze_image_base64(self, image_data: bytes, mime_type: str = "image/jpeg") -> ImageAnalysisResult:
        """分析 Base64 编码的图像（支持 OpenAI 和 Gemini 原生格式）"""
        original_size = len(image_data)
        logger.info(f"分析 Base64 图像, 类型: {mime_type}, 原始大小: {original_size/1024:.1f} KB")
        
        # 从配置读取压缩阈值（KB），默认 2048KB = 2MB
        max_size_str = await config_cache.get("vision_max_image_size", "2048")
        max_image_size_kb = int(max_size_str) if max_size_str else 2048
        max_image_size = max_image_size_kb * 1024  # 转为字节
        
        # 图片过大时自动压缩
        if original_size > max_image_size:
            logger.info(f"图片过大 ({original_size/1024:.1f} KB > {max_image_size_kb} KB)，正在压缩...")
            # 图片压缩是 CPU 密集型操作，使用线程池避免阻塞
            image_data, mime_type = await asyncio.to_thread(
                self._compress_image, image_data, max_image_size
            )
            logger.info(f"压缩后: {len(image_data)/1024:.1f} KB, 类型: {mime_type}")
        
        try:
            # 使用异步方法确保能从数据库读取配置
            api_base = await config_cache.get("vision_api_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1"
            api_key = await config_cache.get("vision_api_key", "") or ""
            model = await self._get_model()
            prompt = await self._get_prompt()
            
            if not api_key:
                raise ValueError("视觉模型 API 密钥未配置")
            
            base64_image = base64.b64encode(image_data).decode("utf-8")
            data_url = f"data:{mime_type};base64,{base64_image}"
            
            # 完整请求 URL
            request_url = f"{api_base.rstrip('/')}/chat/completions"
            
            # DEBUG: 打印请求参数（含 API Key 脱敏）
            api_key_preview = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "****"
            logger.debug(f"视觉模型 API 请求参数:")
            logger.debug(f"  - Request URL: {request_url}")
            logger.debug(f"  - API Key: {api_key_preview}")
            logger.debug(f"  - Model: {model}")
            logger.debug(f"  - Image: Base64 ({len(image_data)} bytes, {mime_type})")
            logger.debug(f"  - Prompt: {prompt[:100]}...")
            
            # 使用 httpx 直接请求，支持原生 Gemini 响应
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    request_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": data_url}}
                                ]
                            }
                        ],
                        "stream": False
                    }
                )
                
                # 检查响应状态
                if response.status_code != 200:
                    error_text = response.text[:500] if response.text else "无响应内容"
                    logger.error(f"API 请求失败: HTTP {response.status_code}, 响应: {error_text}")
                    raise ValueError(f"API 请求失败: HTTP {response.status_code}")
                
                response_data = response.json()
            
            # DEBUG: 打印响应
            logger.debug(f"视觉模型 API 响应: {json.dumps(response_data, ensure_ascii=False, default=str)[:500]}...")
            
            # 提取内容（支持 OpenAI 和 Gemini 格式）
            content = self._extract_content_from_response(response_data)
            logger.debug(f"  - Extracted content length: {len(content)}")
                
            return self._parse_response(content)
            
        except httpx.ConnectError as e:
            logger.error(f"视觉模型 API 连接失败: {api_base} - {str(e)}")
            raise ValueError(f"无法连接到 API: {api_base}")
        except httpx.ReadError as e:
            logger.error(f"视觉模型 API 读取错误（服务器断开连接）: {str(e)}")
            raise ValueError(f"API 读取错误，服务器可能不可用或响应异常")
        except httpx.TimeoutException as e:
            logger.error(f"视觉模型 API 请求超时: {str(e)}")
            raise ValueError("API 请求超时")
        except Exception as e:
            logger.error(f"视觉模型分析失败: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}")
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
