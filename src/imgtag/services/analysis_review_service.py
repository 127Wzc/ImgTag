"""图片分析直接生效，替换前备份旧内容。"""
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories import image_repository, image_tag_repository, tag_repository, subject_repository
from imgtag.db.repositories.analysis_version import analysis_version_repository as versions
from imgtag.services.subject_context_service import subject_context_service


def check_snapshot(current: dict, expected: dict):
    if current != expected:
        raise HTTPException(409, "当前内容或主体已变化，请刷新后再保存")


class AnalysisReviewService:
    async def current(self, session: AsyncSession, image_id: int) -> dict:
        image = await image_repository.get_by_id(session, image_id)
        if image is None:
            raise HTTPException(404, "图片不存在")
        tags = await image_repository.get_image_tags_with_source(session, image_id)
        return {"description": image.description or "", "tags": sorted(t["name"] for t in tags if t["level"] == 2),
                "tag_sources": sorted([{k: t[k] for k in ("id", "source", "level")} for t in tags], key=lambda t: t["id"]),
                "subjects": await subject_context_service.resolve(session, image_id)}

    async def history(self, session: AsyncSession, image, current: dict, *, allow_empty: bool = False):
        if not allow_empty and not current.get("description") and not current.get("tags"):
            return
        await versions.create(session, image_id=image.id, state="history", pending=False, revision=0,
            description=current["description"], tags=current["tags"], subject_analysis=image.subject_analysis,
            base_snapshot=current, metadata_snapshot={})
        await versions.prune_history(session, image.id)

    @staticmethod
    def clean_tags(tags):
        values = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
        if any(len(t) > 100 for t in values):
            raise HTTPException(400, "单个标签不能超过100字")
        return values

    async def write_current(self, session, image, current, description, tags, *, preserve_manual, assessment=None):
        await self.history(session, image, current, allow_empty=True)
        names = self.clean_tags(tags)
        levels = await tag_repository.get_name_levels(session, names)
        if any(level != 2 for level in levels.values()):
            raise HTTPException(400, "分类和分辨率标签请在图片分类中修改")
        if preserve_manual:
            await image_tag_repository.set_image_tags(session, image.id, names, source="ai")
        else:
            resolved = [await tag_repository.get_or_create(session, name, source="user", level=2) for name in names]
            await image_tag_repository.set_image_tags_by_ids(session, image.id, [t.id for t in resolved], source="user")
        image.description = description
        image.subject_analysis = assessment
        # 保存内容后失效旧向量，与重建任务一并提交。
        image.embedding = None
        # task_queue 已依赖本服务，此处仅为打破运行时循环依赖。
        from imgtag.services.task_queue import task_queue
        await session.flush()
        await task_queue.add_tasks([image.id], task_type="rebuild_vector", force_analyze=True, session=session)
        await session.flush()

    async def locked_current(self, session, image_id):
        current = await self.current(session, image_id)
        await subject_repository.lock_by_ids(session, [c["subject_id"] for c in current.get("subjects", [])])
        return await self.current(session, image_id)

    async def delete_history(self, session, image_id, version_id):
        image = await image_repository.get_by_id_for_update(session, image_id)
        if image is None:
            raise HTTPException(404, "图片不存在")
        source = await versions.get_history(session, image_id, version_id)
        if source is None:
            raise HTTPException(404, "历史备份不存在或已被清理，请刷新")
        await versions.delete(session, source)

    async def restore(self, session, image_id, version_id, expected_snapshot):
        image = await image_repository.get_by_id_for_update(session, image_id)
        if image is None:
            raise HTTPException(404, "图片不存在")
        current = await self.locked_current(session, image_id)
        check_snapshot(current, expected_snapshot)
        source = await versions.get_history(session, image_id, version_id)
        if source is None:
            raise HTTPException(404, "历史备份不存在或已被清理，请刷新")
        # 最早一份备份可能在写入当前备份时被清理，先取出要恢复的完整值。
        description, tags, assessment = source.description, list(source.tags), source.subject_analysis
        await self.write_current(session, image, current, description, tags,
                                 preserve_manual=False, assessment=assessment)
        return await self.current(session, image_id)

    async def save_current(self, session, image_id, data):
        image = await image_repository.get_by_id_for_update(session, image_id)
        current = await self.locked_current(session, image_id)
        check_snapshot(current, data.expected_snapshot)
        await self.write_current(session, image, current, data.description, data.tags, preserve_manual=False)
        return await self.current(session, image_id)


analysis_review_service = AnalysisReviewService()
