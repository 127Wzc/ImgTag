"""启动加密自检和旧回调头转存的数据访问；避免触发模型的解密属性。"""

import asyncio
import json
from dataclasses import asdict, dataclass, field

from sqlalchemy import bindparam, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.internal_config import ENCRYPTION_STATE_KEY
from imgtag.models.config import Config
from imgtag.models.storage_endpoint import StorageEndpoint
from imgtag.models.task import Task


@dataclass(frozen=True)
class EncryptionSnapshot:
    key_material: str = field(repr=False)
    fingerprint: str
    version: int
    callbacks_migrated: bool = False


class EncryptionRepository:
    async def lock(self, session: AsyncSession) -> None:
        # 事务级锁同时覆盖首次无状态行的初始化，提交或回滚后自动释放。
        # 非阻塞尝试，避免其他实例的一次长轮换耗尽当前实例的查询超时。
        while not (await session.execute(select(func.pg_try_advisory_xact_lock(0x496D675461674B)))).scalar_one():
            await asyncio.sleep(0.25)

    async def get_state(self, session: AsyncSession) -> EncryptionSnapshot | None:
        row = (await session.execute(select(Config.value).where(
            Config.key == ENCRYPTION_STATE_KEY,
        ).with_for_update())).mappings().one_or_none()
        if row is None:
            return None
        state = json.loads(row["value"])
        required = {"key_material", "fingerprint", "version"}
        if (not isinstance(state, dict) or not required.issubset(state)
                or set(state) - required - {"callbacks_migrated"}
                or not isinstance(state["key_material"], str) or not isinstance(state["fingerprint"], str)
                or type(state["version"]) is not int or state["version"] < 1
                or not isinstance(state.get("callbacks_migrated", False), bool)):
            raise ValueError("内部加密配置格式无效")
        return EncryptionSnapshot(**state)

    async def save_state(self, session: AsyncSession, *, key_material: str, fingerprint: str, version: int, exists: bool) -> None:
        values = {
            "value": json.dumps(asdict(EncryptionSnapshot(key_material, fingerprint, version, callbacks_migrated=True))),
            "is_secret": True,
            "description": "内部加密密钥状态，仅由启动自检维护",
        }
        statement = (
            update(Config).where(Config.key == ENCRYPTION_STATE_KEY).values(**values)
            if exists else insert(Config).values(key=ENCRYPTION_STATE_KEY, **values)
        )
        await session.execute(statement)

    async def storage_batch(self, session: AsyncSession, after: int, size: int) -> list[dict]:
        rows = (await session.execute(select(
            StorageEndpoint.id,
            StorageEndpoint._access_key_id.label("access_key_id"),
            StorageEndpoint._secret_access_key.label("secret_access_key"),
        ).where(StorageEndpoint.id > after, or_(
            StorageEndpoint._access_key_id.is_not(None), StorageEndpoint._secret_access_key.is_not(None),
        )).order_by(StorageEndpoint.id).limit(size))).mappings().all()
        return [dict(row) for row in rows]

    async def task_batch(self, session: AsyncSession, after: str, size: int) -> list[dict]:
        rows = (await session.execute(select(Task.id, Task.payload).where(
            Task.id > after, Task.payload["callback_headers_encrypted"].astext.is_not(None),
        ).order_by(Task.id).limit(size))).mappings().all()
        return [dict(row) for row in rows]

    async def update_storage(self, session: AsyncSession, rows: list[dict]) -> None:
        if rows:
            await session.execute(update(StorageEndpoint.__table__).where(
                StorageEndpoint.id == bindparam("_row_id"),
            ).values(access_key_id=bindparam("access_key_id"), secret_access_key=bindparam("secret_access_key"),
                     updated_at=StorageEndpoint.updated_at), rows)

    async def update_tasks(self, session: AsyncSession, rows: list[dict]) -> None:
        if rows:
            await session.execute(update(Task.__table__).where(
                Task.id == bindparam("_row_id"),
            ).values(payload=bindparam("payload"), updated_at=Task.updated_at), rows)


encryption_repository = EncryptionRepository()
