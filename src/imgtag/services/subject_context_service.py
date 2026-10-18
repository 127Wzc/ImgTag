"""按图片解析主体资料；与分类提示词、视觉请求组装保持独立。"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories import image_repository, image_subject_repository, subject_repository
from imgtag.services.subject_assignment_service import subject_assignment_service


def subject_context(subject: Any, *, source: str, confirmed: bool) -> dict[str, Any]:
    """创建可序列化的请求快照，不在跨请求缓存中保存主体。"""
    return {
        "subject_id": subject.id,
        "name": subject.name,
        "aliases": subject.aliases or [],
        "definition": subject.description or "",
        "recognition_notes": getattr(subject, "recognition_notes", "") or "",
        "source": source,
        "status": "confirmed" if confirmed else "candidate",
        "version": str(subject.updated_at),
        "definition_revision": getattr(subject, "definition_revision", 0),
    }


class SubjectContextService:
    async def resolve(
        self, session: AsyncSession, image_id: int, *, assign_from_tags: bool = False,
    ) -> list[dict[str, Any]]:
        assignments = await image_subject_repository.get_current(session, image_id)
        contexts = []
        linked_ids = {a.subject_id for a in assignments}
        for assignment in assignments:
            if assignment.state != "confirmed" or not assignment.subject.is_active:
                continue
            context = subject_context(assignment.subject, source=assignment.source, confirmed=True)
            context["assignment_version"] = str(assignment.updated_at)
            contexts.append(context)

        tags = await image_repository.get_image_tags_with_source(session, image_id)
        subjects = await subject_repository.list_matching_tags(
            session, [t["id"] for t in tags if t["level"] == 2],
        )
        manual_ids = {t["id"] for t in tags if t["level"] == 2 and t["source"] == "user"}
        manual_subjects = [
            s for s in subjects
            if {s.primary_tag_id, *(s.alias_tag_ids or [])} & manual_ids
        ]
        if (not assignments and len(manual_subjects) == 1 and assign_from_tags
                and not await image_subject_repository.has_explicit_selection(session, image_id)):
            subject = manual_subjects[0]
            await subject_assignment_service.assign_primary_subject(
                session, image_id=image_id, subject_id=subject.id, actor_id=None,
                confidence=None, source="tag", state="confirmed", add_sample=False,
            )
            return await self.resolve(session, image_id)

        # 人工标签各自唯一命中时可提供可信身份；歧义标签和AI标签仍是候选。
        counts = {tid: sum(tid in {s.primary_tag_id, *(s.alias_tag_ids or [])} for s in subjects) for tid in manual_ids}
        explicit = bool(manual_ids) and await image_subject_repository.has_explicit_selection(session, image_id)
        for subject in subjects:
            if subject.id in linked_ids:
                continue
            trusted = not explicit and any(counts.get(tid) == 1 for tid in {subject.primary_tag_id, *(subject.alias_tag_ids or [])} & manual_ids)
            contexts.append(subject_context(subject, source="user_tag" if trusted else "tag_candidate", confirmed=trusted))
        return contexts


subject_context_service = SubjectContextService()
