from types import SimpleNamespace

import pytest

from imgtag.api.endpoints import auth


def test_user_dict_does_not_contain_secrets() -> None:
    user = SimpleNamespace(
        id=1,
        username="alice",
        email=None,
        role="user",
        is_active=True,
        permissions=7,
        password_hash="secret-hash",
        api_key="secret-api-key",
        created_at=None,
        last_login_at=None,
    )

    data = auth._user_to_dict(user)

    assert "password_hash" not in data
    assert "api_key" not in data


@pytest.mark.asyncio
async def test_get_my_api_key_returns_mask_by_default(monkeypatch) -> None:
    async def fake_get_by_id(session, user_id):
        _ = session, user_id
        return SimpleNamespace(api_key="a" * 64)

    monkeypatch.setattr(auth.user_repository, "get_by_id", fake_get_by_id)

    response = await auth.get_my_api_key(reveal=False, user={"id": 1}, session=None)

    assert response == {"has_key": True, "masked_key": "aaaaaaaa...aaaaaaaa"}


@pytest.mark.asyncio
async def test_get_my_api_key_reveals_only_when_requested(monkeypatch) -> None:
    api_key = "b" * 64

    async def fake_get_by_id(session, user_id):
        _ = session, user_id
        return SimpleNamespace(api_key=api_key)

    monkeypatch.setattr(auth.user_repository, "get_by_id", fake_get_by_id)

    response = await auth.get_my_api_key(reveal=True, user={"id": 1}, session=None)

    assert response["api_key"] == api_key
