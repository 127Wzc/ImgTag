import pytest

from imgtag.services.subject_memory_service import subject_memory_service


@pytest.mark.asyncio
async def test_match_primary_subject_disabled(monkeypatch) -> None:
    async def fake_get(key: str, default=None):
        if key == "subject_memory_enabled":
            return "false"
        return default

    monkeypatch.setattr("imgtag.services.subject_memory_service.config_cache.get", fake_get)

    result = await subject_memory_service.match_primary_subject(
        image_id=1,
        image_data=b"fake",
        mime_type="image/jpeg",
    )
    assert result["status"] == "disabled"
    assert result["subject_id"] is None


@pytest.mark.asyncio
async def test_match_primary_subject_high_conf(monkeypatch) -> None:
    async def fake_get(key: str, default=None):
        mapping = {
            "subject_memory_enabled": "true",
            "subject_matcher_backend": "stub",
            "subject_max_candidates": "3",
            "subject_high_threshold": "0.50",
            "subject_low_threshold": "0.40",
            "subject_auto_apply_high_conf": "true",
        }
        return mapping.get(key, default)

    async def fake_match(**kwargs):
        _ = kwargs
        return {
            "status": "raw",
            "subject_id": 7,
            "subject_name": "张三",
            "confidence": 0.9,
            "candidates": [],
            "reason": "mock",
        }

    monkeypatch.setattr("imgtag.services.subject_memory_service.config_cache.get", fake_get)
    monkeypatch.setattr(
        "imgtag.services.subject_memory_service.subject_matcher_stub.match_primary_subject",
        fake_match,
    )

    result = await subject_memory_service.match_primary_subject(
        image_id=2,
        image_data=b"fake",
        mime_type="image/jpeg",
    )
    assert result["status"] == "high_conf"
    assert result["subject_id"] == 7
    assert "张三" in (result["hint_text"] or "")


@pytest.mark.asyncio
async def test_match_primary_subject_low_conf(monkeypatch) -> None:
    async def fake_get(key: str, default=None):
        mapping = {
            "subject_memory_enabled": "true",
            "subject_matcher_backend": "stub",
            "subject_max_candidates": "3",
            "subject_high_threshold": "0.50",
            "subject_low_threshold": "0.40",
            "subject_auto_apply_high_conf": "true",
        }
        return mapping.get(key, default)

    async def fake_match(**kwargs):
        _ = kwargs
        return {
            "subject_id": 8,
            "subject_name": "李四",
            "confidence": 0.45,
            "candidates": [],
            "reason": "mock",
        }

    monkeypatch.setattr("imgtag.services.subject_memory_service.config_cache.get", fake_get)
    monkeypatch.setattr(
        "imgtag.services.subject_memory_service.subject_matcher_stub.match_primary_subject",
        fake_match,
    )

    result = await subject_memory_service.match_primary_subject(
        image_id=3,
        image_data=b"fake",
        mime_type="image/jpeg",
    )
    assert result["status"] == "low_conf"
    assert result["subject_id"] == 8
