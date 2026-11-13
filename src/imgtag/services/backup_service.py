"""备份服务。

自动将图片同步到备份端点的服务。支持：
1. 上传后即时触发备份（轻量，单张）
2. 每天凌晨定时补充备份（批量）
"""

import asyncio
from datetime import datetime, time, timedelta

from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import BATCH_CONFIG, EndpointRole
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    image_location_repository,
    storage_endpoint_repository,
)
from imgtag.services.storage_sync_service import storage_sync_service

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
                if existing and existing.sync_status == "synced":
                    continue  # 已备份
                
                try:
                    await storage_sync_service.start_batch_sync(source_endpoint.id, backup_ep.id, [image_id], automatic_backup=True)
                except ValueError as error:
                    logger.info("备份配置不可用或正在清理，等待后续补备份: %s", error)

            await session.commit()
    except Exception as e:
        logger.error(f"触发备份失败: {e}")


async def run_scheduled_backup() -> dict:
    """分页补齐备份待办；实际传输由存储任务执行，端点忙时待办仍保留。"""
    stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0}
    try:
        async with async_session_maker() as session:
            backups = await storage_endpoint_repository.get_backup_endpoints(session)
            backup_ids = [endpoint.id for endpoint in backups]
        for backup_id in backup_ids:
            after_image_id = 0
            while True:
                async with async_session_maker() as session:
                    rows = await image_location_repository.get_missing_backup_batch(
                        session, backup_id, after_image_id, BATCH_CONFIG.batch_size
                    )
                if not rows:
                    break
                after_image_id = rows[-1][0]
                stats["total"] += len(rows)
                grouped = {}
                for image_id, source_id in rows:
                    grouped.setdefault(source_id, []).append(image_id)
                for source_id, image_ids in grouped.items():
                    try:
                        await storage_sync_service.start_batch_sync(
                            source_id, backup_id, image_ids, automatic_backup=True
                        )
                        stats["success"] += len(image_ids)
                    except ValueError as error:
                        logger.info("备份配置不可用或正在清理，延后补备份: %s", error)
                        stats["skipped"] += len(image_ids)
        logger.info("定时备份入队完成: %s", stats)
    except Exception:
        logger.exception("定时备份入队失败")
        stats["failed"] += 1
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
