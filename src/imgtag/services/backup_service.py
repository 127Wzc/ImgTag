"""备份服务。

自动将图片同步到备份端点的服务。支持：
1. 上传后即时触发备份（轻量，单张）
2. 每天凌晨定时补充备份（批量）
"""

import asyncio
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import BATCH_CONFIG, EndpointRole
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    image_location_repository,
    storage_endpoint_repository,
)
from imgtag.models.image import Image
from imgtag.models.image_location import ImageLocation
from imgtag.services.storage_service import storage_service

logger = get_logger(__name__)


async def trigger_backup_for_image(image_id: int, source_endpoint_id: int) -> None:
    """上传完成后触发备份到所有备份端点。
    
    轻量级操作，仅处理单张图片。
    
    Args:
        image_id: 刚上传的图片ID
        source_endpoint_id: 上传到的源端点ID
    """
    try:
        async with async_session_maker() as session:
            # 获取所有备份端点
            backup_endpoints = await storage_endpoint_repository.get_backup_endpoints(session)
            
            if not backup_endpoints:
                return  # 没有备份端点
            
            # 获取源图片的 location
            source_location = await image_location_repository.get_by_image_and_endpoint(
                session, image_id, source_endpoint_id
            )
            if not source_location:
                logger.warning(f"未找到图片 {image_id} 在端点 {source_endpoint_id} 的位置记录")
                return
            
            # 获取源端点
            source_endpoint = await storage_endpoint_repository.get_by_id(session, source_endpoint_id)
            if not source_endpoint:
                return
            
            # 跳过备份端点作为源端点的情况
            if source_endpoint.role == EndpointRole.BACKUP.value:
                return
            
            for backup_ep in backup_endpoints:
                # 检查是否已存在
                existing = await image_location_repository.get_by_image_and_endpoint(
                    session, image_id, backup_ep.id
                )
                if existing:
                    continue  # 已备份
                
                # 执行同步（copy_between_endpoints 会创建 location 记录）
                try:
                    success = await storage_service.copy_between_endpoints(
                        session=session,
                        image_id=image_id,
                        source_endpoint=source_endpoint,
                        target_endpoint=backup_ep,
                        object_key=source_location.object_key,
                    )
                    if success:
                        logger.debug(f"图片 {image_id} 已备份到端点 {backup_ep.name}")
                except Exception as e:
                    logger.warning(f"备份图片 {image_id} 到 {backup_ep.name} 失败: {e}")
            
            await session.commit()
    except Exception as e:
        logger.error(f"触发备份失败: {e}")


async def run_scheduled_backup() -> dict:
    """定时任务：备份所有不在备份端点的图片。
    
    使用批处理和限流，避免系统过载。
    
    Returns:
        dict: 备份结果统计
    """
    logger.info("开始执行定时备份任务")
    stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0}
    
    try:
        async with async_session_maker() as session:
            # 获取所有备份端点
            backup_endpoints = await storage_endpoint_repository.get_backup_endpoints(session)
            
            if not backup_endpoints:
                logger.info("没有配置备份端点，跳过备份任务")
                return stats
            
            # 批量获取所有启用的主端点（一次查询，避免后续 N+1）
            all_endpoints = await storage_endpoint_repository.get_enabled(session)
            endpoint_map = {ep.id: ep for ep in all_endpoints}
            
            for backup_ep in backup_endpoints:
                # 查找不在此备份端点的图片（子查询优化）
                subquery = (
                    select(ImageLocation.image_id)
                    .where(ImageLocation.endpoint_id == backup_ep.id)
                )
                
                # 主查询：有 primary location 但不在备份端点的图片
                stmt = (
                    select(Image.id, ImageLocation.endpoint_id, ImageLocation.object_key)
                    .join(ImageLocation, Image.id == ImageLocation.image_id)
                    .where(Image.id.not_in(subquery))
                    .where(ImageLocation.is_primary == True)
                    .limit(BATCH_CONFIG.batch_size)
                )
                
                result = await session.execute(stmt)
                rows = result.all()
                
                if not rows:
                    continue
                
                stats["total"] += len(rows)
                logger.info(f"备份端点 {backup_ep.name}: 发现 {len(rows)} 张待备份图片")
                
                # 批量处理（带限流）
                for image_id, source_endpoint_id, object_key in rows:
                    source_endpoint = endpoint_map.get(source_endpoint_id)
                    if not source_endpoint:
                        stats["skipped"] += 1
                        continue
                    
                    # 跳过从备份端点复制（理论上不应该有，但防御性检查）
                    if source_endpoint.role == EndpointRole.BACKUP.value:
                        stats["skipped"] += 1
                        continue
                    
                    try:
                        success = await storage_service.copy_between_endpoints(
                            session=session,
                            image_id=image_id,
                            source_endpoint=source_endpoint,
                            target_endpoint=backup_ep,
                            object_key=object_key,
                        )
                        if success:
                            stats["success"] += 1
                        else:
                            stats["failed"] += 1
                    except Exception as e:
                        logger.warning(f"定时备份图片 {image_id} 失败: {e}")
                        stats["failed"] += 1
                    
                    # 限流
                    await asyncio.sleep(BATCH_CONFIG.rate_limit_seconds)
                
                await session.commit()
        
        logger.info(f"定时备份完成: {stats}")
        return stats
    except Exception as e:
        logger.error(f"定时备份任务失败: {e}")
        return stats


async def schedule_daily_backup() -> None:
    """调度器：每天凌晨1点（本地时间）执行备份任务。"""
    TARGET_HOUR = 1  # 凌晨1点
    
    while True:
        now = datetime.now()
        target_time = datetime.combine(now.date(), time(hour=TARGET_HOUR))
        
        # 如果今天的1点已过，等待明天
        if now.hour >= TARGET_HOUR:
            target_time += timedelta(days=1)
        
        wait_seconds = (target_time - now).total_seconds()
        
        if wait_seconds > 0:
            hours = wait_seconds / 3600
            logger.info(f"定时备份任务将在 {hours:.1f} 小时后执行 ({target_time.strftime('%Y-%m-%d %H:%M')})")
            await asyncio.sleep(wait_seconds)
        
        # 执行备份
        try:
            await run_scheduled_backup()
        except Exception as e:
            logger.error(f"定时备份执行失败: {e}")
        
        # 等待1分钟后进入下一个周期（避免边界条件重复触发）
        await asyncio.sleep(60)
