#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像API端点
处理与图像相关的请求
"""

import time
from fastapi import APIRouter, HTTPException, Depends, Path, Query
from typing import List, Optional, Dict, Any

from app.models.image import ImageCreate, ImageResponse, ImageUpdate, ImageSearchRequest, ImageSearchResponse
from app.db.pg_vector import PGVectorDB
from app.services.text_embedding import TextEmbedding
from app.core.logging_config import get_logger, get_perf_logger
from app.core.config import settings

# 获取日志记录器
logger = get_logger(__name__)
perf_logger = get_perf_logger()

# 创建全局实例
db = PGVectorDB()
embedding_tool = TextEmbedding()

router = APIRouter()

# 依赖项
def get_db():
    """依赖项：获取数据库连接"""
    return db

def get_embedding():
    """依赖项：获取文本嵌入工具"""
    return embedding_tool

@router.post("/", response_model=Dict[str, Any], status_code=201)
async def create_image(
    image: ImageCreate,
    db: PGVectorDB = Depends(get_db),
    embedding_tool: TextEmbedding = Depends(get_embedding)
):
    """创建图像记录
    
    为图像生成向量嵌入并存储到数据库
    """
    start_time = time.time()
    logger.info(f"创建图像: {image.image_url}")
    
    try:
        # 生成向量嵌入
        vector_gen_start = time.time()
        if image.description:
            embedding_vector = embedding_tool.get_embedding_combined(
                image.description, 
                image.tags
            ).tolist()
        else:
            # 如果没有描述，只使用标签生成向量
            tags_text = ", ".join(image.tags)
            embedding_vector = embedding_tool.get_embedding(tags_text).tolist()
        
        vector_gen_time = time.time() - vector_gen_start
        perf_logger.info(f"向量生成耗时: {vector_gen_time:.4f}秒")
        
        # 插入数据库
        new_id = db.insert_image(
            image.image_url,
            image.tags,
            embedding_vector,
            image.description
        )
        
        if not new_id:
            raise HTTPException(status_code=500, detail="数据库插入失败")
        
        total_time = time.time() - start_time
        perf_logger.info(f"图像创建总耗时: {total_time:.4f}秒")
        
        return {
            "id": new_id,
            "message": "图像创建成功",
            "process_time": f"{total_time:.4f}秒"
        }
    except Exception as e:
        logger.error(f"创建图像失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建图像失败: {str(e)}")

@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(
    image_id: int = Path(..., description="图像ID", gt=0),
    db: PGVectorDB = Depends(get_db)
):
    """获取单个图像信息
    
    根据ID获取图像详细信息
    """
    start_time = time.time()
    logger.info(f"获取图像: ID {image_id}")
    
    try:
        # 从数据库获取图像
        image_data = db.get_image(image_id)
        
        if not image_data:
            raise HTTPException(status_code=404, detail=f"未找到ID为{image_id}的图像")
        
        # 构建响应
        image = ImageResponse(
            id=image_data["id"],
            image_url=image_data["image_url"],
            tags=image_data["tags"],
            description=image_data["description"]
        )
        
        process_time = time.time() - start_time
        perf_logger.info(f"获取图像耗时: {process_time:.4f}秒")
        
        return image
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图像失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取图像失败: {str(e)}")

@router.post("/search", response_model=ImageSearchResponse)
async def search_images(
    request: ImageSearchRequest,
    db: PGVectorDB = Depends(get_db)
):
    """高级图像搜索
    
    支持多种搜索条件：标签列表、URL包含文本、描述包含文本等
    还支持分页和排序
    """
    start_time = time.time()
    logger.info(f"高级图像搜索: {request.dict()}")
    
    try:
        # 调用数据库搜索方法
        results = db.search_images(
            tags=request.tags,
            url_contains=request.url_contains,
            description_contains=request.description_contains,
            limit=request.limit,
            offset=request.offset,
            sort_by=request.sort_by,
            sort_desc=request.sort_desc
        )
        
        # 转换为响应模型
        images = []
        for img in results["images"]:
            images.append(ImageResponse(
                id=img["id"],
                image_url=img["image_url"],
                tags=img["tags"],
                description=img["description"]
            ))
        
        # 构建响应对象
        response = ImageSearchResponse(
            images=images,
            total=results["total"],
            limit=results["limit"],
            offset=results["offset"]
        )
        
        process_time = time.time() - start_time
        perf_logger.info(f"高级搜索耗时: {process_time:.4f}秒")
        
        return response
    except Exception as e:
        logger.error(f"高级搜索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"高级搜索失败: {str(e)}")

@router.put("/{image_id}", response_model=Dict[str, Any])
async def update_image(
    image_id: int = Path(..., description="图像ID", gt=0),
    image_update: ImageUpdate = None,
    db: PGVectorDB = Depends(get_db),
    embedding_tool: TextEmbedding = Depends(get_embedding)
):
    """更新图像信息
    
    更新图像的URL、标签或描述，如果更新了标签或描述，则重新计算向量嵌入
    """
    start_time = time.time()
    logger.info(f"更新图像: ID {image_id}")
    
    if not image_update:
        return {
            "message": "没有提供需要更新的字段",
            "process_time": f"{time.time() - start_time:.4f}秒"
        }
    
    try:
        # 检查是否有需要更新的字段
        has_updates = False
        for field, value in image_update.dict(exclude_unset=True).items():
            if value is not None:
                has_updates = True
                break
        
        if not has_updates:
            return {
                "message": "没有提供需要更新的字段",
                "process_time": f"{time.time() - start_time:.4f}秒"
            }
        
        # 检查是否需要重新计算向量嵌入
        needs_embedding_update = image_update.tags is not None or image_update.description is not None
        embedding_vector = None
        
        # 如果需要更新向量嵌入，先获取当前图像信息
        if needs_embedding_update:
            # 获取当前图像信息
            current_image = None
            with db._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT image_url, tags, description FROM images WHERE id = %s",
                        (image_id,)
                    )
                    result = cursor.fetchone()
                    if result:
                        current_image = {
                            "image_url": result[0],
                            "tags": result[1],
                            "description": result[2]
                        }
            
            if not current_image:
                raise HTTPException(status_code=404, detail=f"未找到ID为{image_id}的图像")
            
            # 准备用于生成向量的数据
            description = image_update.description if image_update.description is not None else current_image["description"]
            tags = image_update.tags if image_update.tags is not None else current_image["tags"]
            
            # 生成新的向量嵌入
            vector_gen_start = time.time()
            if description:
                embedding_vector = embedding_tool.get_embedding_combined(
                    description, 
                    tags
                ).tolist()
            else:
                # 如果没有描述，只使用标签生成向量
                tags_text = ", ".join(tags)
                embedding_vector = embedding_tool.get_embedding(tags_text).tolist()
            
            vector_gen_time = time.time() - vector_gen_start
            perf_logger.info(f"更新向量生成耗时: {vector_gen_time:.4f}秒")
        
        # 更新图像信息
        success = db.update_image(
            image_id=image_id,
            image_url=image_update.image_url,
            tags=image_update.tags,
            description=image_update.description,
            embedding=embedding_vector
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="更新图像失败")
        
        process_time = time.time() - start_time
        perf_logger.info(f"图像更新总耗时: {process_time:.4f}秒")
        
        return {
            "message": "图像更新成功",
            "process_time": f"{process_time:.4f}秒"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新图像失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新图像失败: {str(e)}")

@router.delete("/{image_id}", response_model=Dict[str, Any])
async def delete_image(
    image_id: int = Path(..., description="图像ID", gt=0),
    db: PGVectorDB = Depends(get_db)
):
    """删除图像
    
    根据ID删除图像记录
    """
    start_time = time.time()
    logger.info(f"删除图像: ID {image_id}")
    
    try:
        # 从数据库删除图像
        success = db.delete_image(image_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"未找到ID为{image_id}的图像")
        
        process_time = time.time() - start_time
        perf_logger.info(f"删除图像耗时: {process_time:.4f}秒")
        
        return {
            "message": f"图像ID:{image_id}删除成功",
            "process_time": f"{process_time:.4f}秒"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除图像失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除图像失败: {str(e)}")