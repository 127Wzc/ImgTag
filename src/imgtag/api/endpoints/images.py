#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像 API 端点
处理与图像相关的请求
"""

import time
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks, Depends, Header

from imgtag.db import db, config_db
from imgtag.api.endpoints.auth import get_current_user_optional, get_current_user
from imgtag.api.dependencies import verify_api_key, require_api_key
from imgtag.services import vision_service, embedding_service, upload_service
from imgtag.schemas import (
    ImageCreateByUrl,
    ImageCreateManual,
    ImageResponse,
    ImageUpdate,
    ImageSearchRequest,
    ImageSearchResponse,
    UploadAnalyzeResponse,
)
from imgtag.core.logging_config import get_logger, get_perf_logger

logger = get_logger(__name__)
perf_logger = get_perf_logger()

router = APIRouter()


@router.post("/", response_model=Dict[str, Any], status_code=201)
async def create_image_manual(image: ImageCreateManual, user: Dict = Depends(get_current_user)):
    """手动创建图像记录（需登录）"""
    start_time = time.time()
    logger.info(f"创建图像: {image.image_url}")
    
    try:
        # 生成向量嵌入
        embedding_vector = await embedding_service.get_embedding_combined(
            image.description, 
            image.tags
        )
        
        # 插入数据库
        new_id = db.insert_image(
            image_url=image.image_url,
            tags=image.tags,
            embedding=embedding_vector,
            description=image.description,
            original_url=image.image_url
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



@router.post("/analyze-url", response_model=UploadAnalyzeResponse, status_code=201)
async def analyze_and_create_from_url(request: ImageCreateByUrl, background_tasks: BackgroundTasks, user: Dict = Depends(get_current_user)):
    """通过 URL 分析图像并创建记录（需登录）"""
    from imgtag.db import config_db
    from imgtag.services.task_queue import task_queue
    
    start_time = time.time()
    logger.info(f"添加远程图像任务: {request.image_url}")
    
    try:
        # 1. 插入初始记录（未分析状态，embedding 为 NULL）
        tags = request.tags or []
        description = request.description or ""
        
        new_id = db.insert_image(
            image_url=request.image_url,
            tags=tags,
            embedding=None,  # 待分析，暂无向量
            description=description,
            original_url=request.image_url
        )
        
        if not new_id:
            raise HTTPException(status_code=500, detail="数据库插入失败")
            
        # 2. 如果需要自动分析，添加到任务队列
        if request.auto_analyze:
            task_queue.add_tasks([new_id])
            # 启动后台处理
            if not task_queue._running:
                background_tasks.add_task(task_queue.start_processing)
        
        total_time = time.time() - start_time
        perf_logger.info(f"URL 图像添加任务耗时: {total_time:.4f}秒")
        
        return UploadAnalyzeResponse(
            id=new_id,
            image_url=request.image_url,
            tags=tags,
            description=description,
            process_time=f"{total_time:.4f}秒"
        )
    except Exception as e:
        logger.error(f"添加图像任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加任务失败: {str(e)}")


@router.post("/upload", response_model=UploadAnalyzeResponse, status_code=201)
async def upload_and_analyze(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="上传的图片文件"),
    auto_analyze: bool = Form(default=True, description="是否自动分析"),
    skip_analyze: bool = Form(default=False, description="跳过分析，只上传"),
    tags: str = Form(default="", description="手动标签，逗号分隔"),
    description: str = Form(default="", description="手动描述"),
    user: Dict = Depends(get_current_user)
):
    """上传图片文件并分析（需登录）"""
    from imgtag.db import config_db
    from imgtag.services.task_queue import task_queue
    
    start_time = time.time()
    logger.info(f"上传文件: {file.filename}, auto_analyze={auto_analyze}")
    
    try:
        # 读取文件内容
        file_content = await file.read()
        
        # 保存文件（返回真实文件类型和分辨率）
        file_path, access_url, file_type, width, height = await upload_service.save_uploaded_file(
            file_content, 
            file.filename
        )
        
        final_tags = [t.strip() for t in tags.split(",") if t.strip()]
        final_description = description
        
        # 计算文件哈希
        import hashlib
        file_hash = hashlib.md5(file_content).hexdigest()
        
        # 计算文件大小 (MB)
        file_size = round(len(file_content) / (1024 * 1024), 2)
        
        # 1. 插入记录（embedding 为 NULL，待后续分析生成）
        new_id = db.insert_image(
            image_url=access_url,
            tags=final_tags,
            embedding=None,  # 待分析，暂无向量
            description=final_description,
            file_path=file_path,
            file_hash=file_hash,
            file_type=file_type,
            file_size=file_size,
            width=width,
            height=height
        )
        
        if not new_id:
            raise HTTPException(status_code=500, detail="数据库插入失败")
        
        # 2. 添加到分析队列
        if auto_analyze and not skip_analyze:
            task_queue.add_tasks([new_id])
            # 启动后台处理
            if not task_queue._running:
                background_tasks.add_task(task_queue.start_processing)
        
        total_time = time.time() - start_time
        perf_logger.info(f"上传并添加任务耗时: {total_time:.4f}秒")
        
        return UploadAnalyzeResponse(
            id=new_id,
            image_url=access_url,
            tags=final_tags,
            description=final_description,
            process_time=f"{total_time:.4f}秒"
        )
    except Exception as e:
        logger.error(f"上传和添加任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.post("/upload-zip", response_model=Dict[str, Any], status_code=201)
async def upload_zip(
    file: UploadFile = File(..., description="ZIP 压缩包"),
    user: Dict = Depends(get_current_user)
):
    """上传 ZIP 文件，批量解压并保存图片（需登录）"""
    import zipfile
    import io
    import os
    
    start_time = time.time()
    logger.info(f"上传 ZIP 文件: {file.filename}")
    
    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="只支持 .zip 格式文件")
    
    try:
        # 读取 ZIP 内容
        zip_content = await file.read()
        
        # 支持的图片扩展名
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        
        uploaded_ids = []
        failed_files = []
        
        with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as zf:
            for zip_info in zf.infolist():
                # 跳过目录和隐藏文件
                if zip_info.is_dir():
                    continue
                
                filename = os.path.basename(zip_info.filename)
                if filename.startswith('.') or filename.startswith('__'):
                    continue
                
                # 检查是否是图片
                ext = os.path.splitext(filename)[1].lower()
                if ext not in image_extensions:
                    continue
                
                try:
                    # 解压文件
                    file_content = zf.read(zip_info.filename)
                    
                    # 保存文件（返回真实文件类型和分辨率）
                    file_path, access_url, file_type, width, height = await upload_service.save_uploaded_file(
                        file_content,
                        filename
                    )
                    
                    # 计算文件大小 (MB)
                    file_size = round(len(file_content) / (1024 * 1024), 2)
                    
                    # 插入数据库（embedding 为 NULL，待后续分析）
                    new_id = db.insert_image(
                        image_url=access_url,
                        tags=[],
                        embedding=None,  # 待分析，暂无向量
                        description="",
                        file_path=file_path,
                        file_type=file_type,
                        file_size=file_size,
                        width=width,
                        height=height
                    )
                    
                    if new_id:
                        uploaded_ids.append(new_id)
                    else:
                        failed_files.append(filename)
                        
                except Exception as e:
                    logger.error(f"处理 ZIP 内文件 {filename} 失败: {str(e)}")
                    failed_files.append(filename)
        
        total_time = time.time() - start_time
        perf_logger.info(f"ZIP 上传处理耗时: {total_time:.4f}秒, 成功: {len(uploaded_ids)}, 失败: {len(failed_files)}")
        
        return {
            "message": f"ZIP 解压完成: 成功 {len(uploaded_ids)} 张，失败 {len(failed_files)} 张",
            "uploaded_count": len(uploaded_ids),
            "uploaded_ids": uploaded_ids,
            "failed_count": len(failed_files),
            "failed_files": failed_files[:10],  # 只返回前 10 个失败文件名
            "process_time": f"{total_time:.4f}秒"
        }
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的 ZIP 文件")
    except Exception as e:
        logger.error(f"处理 ZIP 文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理 ZIP 失败: {str(e)}")


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(image_id: int):
    """获取单个图像信息"""
    start_time = time.time()
    logger.info(f"获取图像: ID {image_id}")
    
    try:
        image_data = db.get_image(image_id)
        
        if not image_data:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {image_id} 的图像")
        
        # 获取带来源的标签
        tags_with_source = db.get_image_tags_with_source(image_id)
        image_data["tags_with_source"] = tags_with_source
        
        process_time = time.time() - start_time
        perf_logger.info(f"获取图像耗时: {process_time:.4f}秒")
        
        return ImageResponse(**image_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图像失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取图像失败: {str(e)}")


@router.post("/search", response_model=ImageSearchResponse)
async def search_images(request: ImageSearchRequest):
    """高级图像搜索"""
    start_time = time.time()
    logger.info(f"高级图像搜索: {request.model_dump()}")
    
    try:
        results = db.search_images(
            tags=request.tags,
            url_contains=request.url_contains,
            description_contains=request.description_contains,
            keyword=request.keyword,
            pending_only=request.pending_only,
            duplicates_only=request.duplicates_only,
            limit=request.limit,
            offset=request.offset,
            sort_by=request.sort_by,
            sort_desc=request.sort_desc
        )
        
        # 列表页不查询标签来源（性能优化），只在详情页查询
        images = [ImageResponse(**img, tags_with_source=[]) for img in results["images"]]
        
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
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.put("/{image_id}", response_model=Dict[str, Any])
async def update_image(
    image_id: int, 
    image_update: ImageUpdate,
    current_user: Dict = Depends(get_current_user)
):
    """更新图像信息（需登录）"""
    start_time = time.time()
    logger.info(f"更新图像: ID {image_id}")
    
    try:
        # 获取当前图像信息
        current_image = db.get_image(image_id)
        if not current_image:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {image_id} 的图像")
        
        # 检查是否需要重新计算向量
        embedding_vector = None
        if image_update.tags is not None or image_update.description is not None:
            description = image_update.description if image_update.description is not None else current_image.get("description", "")
            tags = image_update.tags if image_update.tags is not None else current_image.get("tags", [])
            
            # 重新生成向量嵌入
            embedding_vector = await embedding_service.get_embedding_combined(
                description, 
                tags
            )
        
        user_id = current_user.get("id") if current_user else None
        
        success = db.update_image(
            image_id=image_id,
            image_url=image_update.image_url,
            tags=image_update.tags,
            description=image_update.description,
            embedding=embedding_vector,
            tag_source="user",
            user_id=user_id,
            original_url=image_update.original_url
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
async def delete_image(image_id: int, user: Dict = Depends(get_current_user)):
    """删除图像（需登录）"""
    import os
    
    start_time = time.time()
    logger.info(f"删除图像: ID {image_id}")
    
    try:
        # 先获取图像信息，用于删除本地文件
        image_data = db.get_image(image_id)
        
        if not image_data:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {image_id} 的图像")
        
        # 删除本地文件（如果是本地上传的）
        file_path = image_data.get("file_path")
        file_deleted = False
        
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                file_deleted = True
                logger.info(f"已删除本地文件: {file_path}")
            except Exception as e:
                logger.warning(f"删除本地文件失败: {file_path}, 错误: {str(e)}")
        
        # 删除数据库记录
        success = db.delete_image(image_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="删除数据库记录失败")
        
        process_time = time.time() - start_time
        perf_logger.info(f"删除图像耗时: {process_time:.4f}秒")
        
        return {
            "message": f"图像 ID:{image_id} 删除成功" + (" (含本地文件)" if file_deleted else ""),
            "file_deleted": file_deleted,
            "process_time": f"{process_time:.4f}秒"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除图像失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除图像失败: {str(e)}")


@router.post("/batch/delete", response_model=Dict[str, Any])
async def batch_delete_images(image_ids: List[int], user: Dict = Depends(get_current_user)):
    """批量删除图像（需登录）"""
    import os
    
    start_time = time.time()
    logger.info(f"批量删除图像: {len(image_ids)} 张")
    
    success_count = 0
    fail_count = 0
    
    for image_id in image_ids:
        try:
            image_data = db.get_image(image_id)
            if not image_data:
                fail_count += 1
                continue
            
            # 删除本地文件
            file_path = image_data.get("file_path")
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            
            if db.delete_image(image_id):
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            logger.error(f"删除图像 {image_id} 失败: {str(e)}")
            fail_count += 1
    
    process_time = time.time() - start_time
    perf_logger.info(f"批量删除耗时: {process_time:.4f}秒")
    
    return {
        "message": f"批量删除完成: 成功 {success_count} 张，失败 {fail_count} 张",
        "success_count": success_count,
        "fail_count": fail_count,
        "process_time": f"{process_time:.4f}秒"
    }

from pydantic import BaseModel

class BatchUpdateTagsRequest(BaseModel):
    image_ids: List[int]
    tags: List[str]
    mode: str = "add"  # add: 追加, replace: 替换


@router.post("/batch/update-tags", response_model=Dict[str, Any])
async def batch_update_tags(
    request: BatchUpdateTagsRequest,
    current_user: Dict = Depends(get_current_user)
):
    """批量更新图像标签（需登录）"""
    start_time = time.time()
    user_id = current_user.get("id")
    logger.info(f"批量更新标签: {len(request.image_ids)} 张, 模式: {request.mode}, 用户: {user_id}")
    
    success_count = 0
    fail_count = 0
    
    for image_id in request.image_ids:
        try:
            image = db.get_image(image_id)
            if not image:
                fail_count += 1
                continue
            
            if request.mode == "add":
                new_tags = list(set((image.get("tags") or []) + request.tags))
            else:
                new_tags = list(request.tags)
            
            # 生成新向量
            description = image.get("description", "")
            embedding = await embedding_service.get_embedding_combined(description, new_tags)
            
            if db.update_image(image_id, tags=new_tags, embedding=embedding, tag_source="user", user_id=user_id):
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            logger.error(f"更新图像 {image_id} 标签失败: {str(e)}")
            fail_count += 1
    
    process_time = time.time() - start_time
    perf_logger.info(f"批量更新标签耗时: {process_time:.4f}秒")
    
    return {
        "message": f"批量更新完成: 成功 {success_count} 张，失败 {fail_count} 张",
        "success_count": success_count,
        "fail_count": fail_count,
        "process_time": f"{process_time:.4f}秒"
    }

