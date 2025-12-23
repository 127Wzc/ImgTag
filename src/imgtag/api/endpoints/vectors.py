#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
向量管理 API 端点
向量数据的维护和重建
"""

import asyncio
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends

from imgtag.api.endpoints.auth import require_admin

from imgtag.db import db, config_db
from imgtag.services import embedding_service
from imgtag.core.logging_config import get_logger, get_perf_logger

logger = get_logger(__name__)
perf_logger = get_perf_logger()

router = APIRouter()

# 重建状态
rebuild_status = {
    "is_running": False,
    "total": 0,
    "processed": 0,
    "failed": 0,
    "message": ""
}


@router.get("/status", response_model=Dict[str, Any])
async def get_vector_status():
    """获取向量数据状态"""
    try:
        image_count = db.count_images()
        mode = config_db.get("embedding_mode", "local")
        
        if mode == "local":
            model = config_db.get("embedding_local_model", "BAAI/bge-small-zh-v1.5")
            # 根据模型名推断维度
            if "small" in model:
                dimensions = 512
            elif "base" in model:
                dimensions = 768
            else:
                dimensions = 512
        else:
            model = config_db.get("embedding_model", "text-embedding-3-small")
            dimensions = config_db.get_int("embedding_dimensions", 1536)
        
        # 获取数据库表的实际维度
        db_dimensions = get_db_vector_dimensions()
        
        return {
            "image_count": image_count,
            "embedding_mode": mode,
            "embedding_model": model,
            "embedding_dimensions": dimensions,
            "db_dimensions": db_dimensions,
            "dimensions_match": dimensions == db_dimensions,
            "rebuild_status": rebuild_status
        }
    except Exception as e:
        logger.error(f"获取向量状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check-local", response_model=Dict[str, Any])
async def check_local_dependencies(admin: Dict = Depends(require_admin)):
    """检查本地嵌入模型依赖状态（需管理员权限）"""
    result = {
        "installed": False,
        "model_loaded": False,
        "model_name": None,
        "dimensions": None,
        "error": None
    }
    
    try:
        import onnxruntime
        import transformers
        result["installed"] = True
        
        # 尝试加载模型
        model_name = config_db.get("embedding_local_model", "BAAI/bge-small-zh-v1.5")
        result["model_name"] = model_name
        
        try:
            model = embedding_service._get_local_model()
            result["model_loaded"] = True
            result["dimensions"] = model.get_sentence_embedding_dimension()
        except Exception as e:
            result["error"] = f"模型加载失败: {str(e)}"
            
    except ImportError:
        result["error"] = "ONNX 依赖未安装。请运行: uv sync --extra local"
    
    return result


# 安装状态
install_status = {
    "is_running": False,
    "success": None,
    "message": "",
    "output": ""
}


@router.post("/install-local", response_model=Dict[str, Any])
async def install_local_dependencies(background_tasks: BackgroundTasks, admin: Dict = Depends(require_admin)):
    """安装本地嵌入模型依赖（需管理员权限）"""
    global install_status
    
    # 检查是否已安装
    try:
        import onnxruntime
        import transformers
        return {
            "status": "already_installed",
            "message": "ONNX 依赖已安装",
            "installed": True
        }
    except ImportError:
        pass
    
    # 检查是否正在安装
    if install_status["is_running"]:
        return {
            "status": "installing",
            "message": "依赖正在安装中，请稍候...",
            "installed": False
        }
    
    # 启动后台安装任务
    install_status = {
        "is_running": True,
        "success": None,
        "message": "正在安装 ONNX Runtime（约 200MB）...",
        "output": ""
    }
    
    background_tasks.add_task(install_local_task)
    
    return {
        "status": "started",
        "message": "依赖安装已启动，这可能需要几分钟时间...",
        "installed": False
    }


@router.get("/install-local/status", response_model=Dict[str, Any])
async def get_install_status():
    """获取本地依赖安装状态"""
    # 同时检查是否真正安装成功
    installed = False
    try:
        import onnxruntime
        import transformers
        installed = True
    except ImportError:
        pass
    
    return {
        **install_status,
        "installed": installed
    }


async def install_local_task():
    """后台执行依赖安装"""
    global install_status
    import subprocess
    import sys
    
    logger.info("开始安装本地嵌入模型依赖...")
    
    try:
        # 执行 uv sync --extra local
        result = subprocess.run(
            ["uv", "sync", "--extra", "local"],
            capture_output=True,
            text=True,
            timeout=600  # 10 分钟超时
        )
        
        if result.returncode == 0:
            install_status["success"] = True
            install_status["message"] = "依赖安装成功！"
            install_status["output"] = result.stdout
            logger.info("本地嵌入模型依赖安装成功")
        else:
            install_status["success"] = False
            install_status["message"] = f"安装失败: {result.stderr}"
            install_status["output"] = result.stderr
            logger.error(f"依赖安装失败: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        install_status["success"] = False
        install_status["message"] = "安装超时（超过10分钟）"
        logger.error("依赖安装超时")
    except FileNotFoundError:
        install_status["success"] = False
        install_status["message"] = "找不到 uv 命令，请确保 uv 已安装"
        logger.error("找不到 uv 命令")
    except Exception as e:
        install_status["success"] = False
        install_status["message"] = f"安装出错: {str(e)}"
        logger.error(f"依赖安装出错: {str(e)}")
    finally:
        install_status["is_running"] = False


@router.post("/resize-table", response_model=Dict[str, str])
async def resize_vector_table(admin: Dict = Depends(require_admin)):
    """重建向量表以匹配当前配置的维度（需管理员权限）"""
    try:
        mode = config_db.get("embedding_mode", "local")
        
        if mode == "local":
            model_name = config_db.get("embedding_local_model", "BAAI/bge-small-zh-v1.5")
            if "small" in model_name:
                new_dim = 512
            elif "base" in model_name:
                new_dim = 768
            else:
                new_dim = 512
        else:
            new_dim = config_db.get_int("embedding_dimensions", 1536)
        
        current_dim = get_db_vector_dimensions()
        
        if current_dim == new_dim:
            return {"message": f"数据库维度已经是 {new_dim}，无需修改"}
        
        logger.info(f"修改向量维度: {current_dim} -> {new_dim}")
        
        # 修改表结构
        with db._get_connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cursor:
                # 删除旧的索引
                cursor.execute("DROP INDEX IF EXISTS idx_images_embedding;")
                
                # 修改列类型
                cursor.execute(f"""
                ALTER TABLE images 
                ALTER COLUMN embedding TYPE vector({new_dim})
                USING (ARRAY_FILL(0::float, ARRAY[{new_dim}])::vector({new_dim}));
                """)
                
                # 重建索引
                cursor.execute(f"""
                CREATE INDEX idx_images_embedding ON public.images 
                USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
                """)
        
        # 更新配置
        config_db.set("embedding_dimensions", str(new_dim))
        
        logger.info(f"向量维度修改成功: {new_dim}")
        return {"message": f"数据库向量维度已修改为 {new_dim}，请重建向量数据"}
        
    except Exception as e:
        logger.error(f"修改向量维度失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebuild", response_model=Dict[str, str])
async def start_rebuild(background_tasks: BackgroundTasks, admin: Dict = Depends(require_admin)):
    """启动向量数据重建任务（需管理员权限）"""
    global rebuild_status
    
    if rebuild_status["is_running"]:
        raise HTTPException(status_code=400, detail="重建任务正在进行中")
    
    # 获取当前模型期望的维度
    mode = config_db.get("embedding_mode", "local")
    if mode == "local":
        model_name = config_db.get("embedding_local_model", "BAAI/bge-small-zh-v1.5")
        if "small" in model_name:
            expected_dim = 512
        elif "base" in model_name:
            expected_dim = 768
        else:
            expected_dim = 512
    else:
        expected_dim = config_db.get_int("embedding_dimensions", 1536)
    
    db_dim = get_db_vector_dimensions()
    
    # 如果维度不匹配，自动调整
    if expected_dim != db_dim:
        logger.info(f"自动调整向量维度: {db_dim} -> {expected_dim}")
        try:
            with db._get_connection() as conn:
                conn.autocommit = True
                with conn.cursor() as cursor:
                    cursor.execute("DROP INDEX IF EXISTS idx_images_embedding;")
                    cursor.execute(f"""
                    ALTER TABLE images 
                    ALTER COLUMN embedding TYPE vector({expected_dim})
                    USING (ARRAY_FILL(0::float, ARRAY[{expected_dim}])::vector({expected_dim}));
                    """)
                    cursor.execute(f"""
                    CREATE INDEX idx_images_embedding ON public.images 
                    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
                    """)
            config_db.set("embedding_dimensions", str(expected_dim))
            logger.info(f"向量维度调整完成: {expected_dim}")
        except Exception as e:
            logger.error(f"调整维度失败: {str(e)}")
            raise HTTPException(status_code=500, detail=f"调整维度失败: {str(e)}")
    
    # 启动后台任务
    background_tasks.add_task(rebuild_vectors_task)
    
    return {"message": f"向量重建任务已启动 (维度: {expected_dim})"}


@router.get("/rebuild/status", response_model=Dict[str, Any])
async def get_rebuild_status():
    """获取重建任务状态"""
    return rebuild_status


@router.delete("/clear", response_model=Dict[str, str])
async def clear_vectors(admin: Dict = Depends(require_admin)):
    """清空所有向量数据（需管理员权限）"""
    try:
        dimensions = get_db_vector_dimensions()
        zero_vector = [0.0] * dimensions
        
        with db._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                UPDATE images SET embedding = %s::vector, updated_at = NOW();
                """, (zero_vector,))
            conn.commit()
        
        logger.info("向量数据已清空")
        return {"message": "向量数据已清空"}
    except Exception as e:
        logger.error(f"清空向量失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def get_db_vector_dimensions() -> int:
    """获取数据库中向量列的维度"""
    try:
        with db._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                SELECT atttypmod FROM pg_attribute 
                WHERE attrelid = 'images'::regclass 
                AND attname = 'embedding';
                """)
                result = cursor.fetchone()
                if result and result[0]:
                    return result[0]
        return 1536  # 默认
    except Exception:
        return 1536


async def rebuild_vectors_task():
    """后台重建向量任务"""
    global rebuild_status
    
    rebuild_status = {
        "is_running": True,
        "total": 0,
        "processed": 0,
        "failed": 0,
        "message": "正在获取图片列表..."
    }
    
    try:
        # 获取所有图片
        with db._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                SELECT id, tags, description FROM images ORDER BY id;
                """)
                images = cursor.fetchall()
        
        rebuild_status["total"] = len(images)
        rebuild_status["message"] = f"开始重建 {len(images)} 张图片的向量..."
        
        logger.info(f"开始重建向量: 共 {len(images)} 张图片")
        
        for image_id, tags, description in images:
            try:
                # 生成新的向量
                embedding = await embedding_service.get_embedding_combined(
                    description or "",
                    tags or []
                )
                
                # 更新数据库
                with db._get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                        UPDATE images 
                        SET embedding = %s::vector, updated_at = NOW()
                        WHERE id = %s;
                        """, (embedding, image_id))
                    conn.commit()
                
                rebuild_status["processed"] += 1
                rebuild_status["message"] = f"已处理 {rebuild_status['processed']}/{rebuild_status['total']}"
                
            except Exception as e:
                logger.error(f"重建图片 {image_id} 向量失败: {str(e)}")
                rebuild_status["failed"] += 1
        
        rebuild_status["is_running"] = False
        rebuild_status["message"] = f"重建完成: 成功 {rebuild_status['processed']}, 失败 {rebuild_status['failed']}"
        
        logger.info(f"向量重建完成: 成功 {rebuild_status['processed']}, 失败 {rebuild_status['failed']}")
        
    except Exception as e:
        logger.error(f"重建向量任务失败: {str(e)}")
        rebuild_status["is_running"] = False
        rebuild_status["message"] = f"重建失败: {str(e)}"
