"""启动时登记或轮换加密密钥；全部提交后才启动使用凭据的业务。"""

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pydantic import TypeAdapter
from sqlalchemy.exc import SQLAlchemyError

from imgtag.core.crypto import LEGACY_DEFAULT_SECRET, configure_encryption_key, derive_encryption_key
from imgtag.core.logging_config import get_logger
from imgtag.db.database import async_session_maker
from imgtag.db.repositories.encryption import EncryptionSnapshot, encryption_repository
from imgtag.schemas.task import CallbackHeaders

logger = get_logger(__name__)


class EncryptionInitializationError(RuntimeError):
    """仅包含可安全记录的信息，不附加原始密钥、凭据或 SQL 参数。"""


@dataclass(frozen=True)
class EncryptionResult:
    version: int
    initialized: bool
    rotated: bool
    storage_fields: int = 0
    migrated_callbacks: int = 0


def _fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()


def _stored_key(state: EncryptionSnapshot) -> bytes:
    try:
        key = state.key_material.encode("ascii")
        Fernet(key)
        if not hmac.compare_digest(state.fingerprint, _fingerprint(key)):
            raise ValueError("指纹不匹配")
        return key
    except (ValueError, TypeError, UnicodeError):
        raise EncryptionInitializationError("数据库加密密钥状态损坏，已停止启动") from None


def _tokens(kind: str, rows: list[dict]):
    for row in rows:
        fields = (
            {"callback_headers_encrypted": row["payload"]["callback_headers_encrypted"]}
            if kind == "tasks" else {name: row[name] for name in ("access_key_id", "secret_access_key")}
        )
        for name, value in fields.items():
            if value is None or value == "":
                continue
            if not isinstance(value, str):
                raise EncryptionInitializationError(f"{kind} 记录 {row['id']} 的加密字段格式无效，已停止启动")
            yield row, name, value


def _filter_bootstrap_keys(keys: list[bytes], kind: str, rows: list[dict]) -> tuple[list[bytes], bool]:
    found = False
    for row, _, value in _tokens(kind, rows):
        found = True
        matches = []
        for key in keys:
            try:
                Fernet(key).decrypt(value.encode())
                matches.append(key)
            except InvalidToken:
                continue
        if not matches:
            raise EncryptionInitializationError(
                f"{kind} 记录 {row['id']} 无法使用当前配置或旧默认密钥解密；"
                "首次升级请保持原 IMGTAG_SECRET_KEY，数据未修改"
            ) from None
        keys = matches
    return keys, found


def _rotate_storage_batch(old_key: bytes, new_key: bytes, rows: list[dict]) -> tuple[list[dict], int]:
    old, new = Fernet(old_key), Fernet(new_key)
    rotator = MultiFernet([new, old])
    updates = {}
    count = 0
    for row, name, value in _tokens("storage_endpoints", rows):
        try:
            original = value.encode()
            # 保留 Fernet 时间戳，并验证明文未改变；明文不进入数据库或日志。
            rotated = rotator.rotate(original)
            if not hmac.compare_digest(old.decrypt(original), new.decrypt(rotated)):
                raise InvalidToken
        except (InvalidToken, ValueError):
            raise EncryptionInitializationError(
                f"storage_endpoints 记录 {row['id']} 的密文无法完成轮换，已停止启动"
            ) from None
        if row["id"] not in updates:
            updates[row["id"]] = {
                "_row_id": row["id"], "access_key_id": row["access_key_id"], "secret_access_key": row["secret_access_key"],
            }
        updates[row["id"]][name] = rotated.decode()
        count += 1
    return list(updates.values()), count


def _decode_legacy_callbacks(key: bytes, rows: list[dict]) -> list[dict]:
    updates = []
    for row in rows:
        value = row["payload"]["callback_headers_encrypted"]
        try:
            if value is None or value == "":
                headers = {}
            elif isinstance(value, str):
                headers = TypeAdapter(CallbackHeaders).validate_python(json.loads(Fernet(key).decrypt(value.encode())))
            else:
                raise ValueError
        except (InvalidToken, ValueError, TypeError):
            raise EncryptionInitializationError(f"tasks 记录 {row['id']} 的旧回调头无法迁移，已停止启动") from None
        payload = {name: value for name, value in row["payload"].items() if name != "callback_headers_encrypted"}
        payload["callback_headers"] = json.dumps(headers)
        updates.append({"_row_id": row["id"], "payload": payload})
    return updates


class EncryptionService:
    BATCH_SIZE = 100

    async def _batches(self, session):
        after = 0
        while rows := await encryption_repository.storage_batch(session, after, self.BATCH_SIZE):
            yield "storage_endpoints", rows
            after = rows[-1]["id"]

    async def _legacy_callback_batches(self, session):
        after = ""
        # 只做一次兼容转换，大回调头逐条解密，避免累计整批明文与密文。
        while rows := await encryption_repository.task_batch(session, after, 1):
            yield rows
            after = rows[-1]["id"]

    async def _bootstrap_key(self, session, configured: bytes | None) -> bytes:
        legacy = await asyncio.to_thread(derive_encryption_key, LEGACY_DEFAULT_SECRET)
        # 旧版只在变量不存在时使用默认值，显式空字符串也可能生成过密文。
        legacy_empty = await asyncio.to_thread(derive_encryption_key, "")
        candidates = list(dict.fromkeys([configured, legacy, legacy_empty] if configured else [legacy, legacy_empty]))
        found = False
        async for kind, rows in self._batches(session):
            candidates, batch_found = await asyncio.to_thread(_filter_bootstrap_keys, candidates, kind, rows)
            found = found or batch_found
        async for rows in self._legacy_callback_batches(session):
            candidates, batch_found = await asyncio.to_thread(_filter_bootstrap_keys, candidates, "tasks", rows)
            found = found or batch_found
        if found:
            return candidates[0]
        return configured or Fernet.generate_key()

    async def initialize(self, configured_secret: str | None = None) -> EncryptionResult:
        try:
            configured = await asyncio.to_thread(derive_encryption_key, configured_secret) if configured_secret else None
            async with async_session_maker() as session:
                async with session.begin():
                    await encryption_repository.lock(session)
                    state = await encryption_repository.get_state(session)
                    old_key = _stored_key(state) if state else await self._bootstrap_key(session, configured)
                    new_key = configured or old_key
                    rotated = not hmac.compare_digest(old_key, new_key)
                    storage_fields = migrated_callbacks = 0
                    if rotated:
                        async for _, rows in self._batches(session):
                            updates, count = await asyncio.to_thread(_rotate_storage_batch, old_key, new_key, rows)
                            await encryption_repository.update_storage(session, updates)
                            storage_fields += count
                    if state is None or not state.callbacks_migrated:
                        async for rows in self._legacy_callback_batches(session):
                            updates = await asyncio.to_thread(_decode_legacy_callbacks, old_key, rows)
                            await encryption_repository.update_tasks(session, updates)
                            migrated_callbacks += len(updates)
                    version = state.version + int(rotated) if state else 1
                    if state is None or rotated or not state.callbacks_migrated:
                        await encryption_repository.save_state(
                            session, key_material=new_key.decode(), fingerprint=_fingerprint(new_key),
                            version=version, exists=state is not None,
                        )
                # 提交失败时不会执行：禁止内存已换新密钥、数据库却仍为旧密文。
                configure_encryption_key(new_key)
            result = EncryptionResult(version, state is None, rotated, storage_fields, migrated_callbacks)
            logger.info("加密自检完成: version=%s, rotated=%s, storage_fields=%s, migrated_callbacks=%s",
                        result.version, result.rotated, result.storage_fields, result.migrated_callbacks)
            return result
        except EncryptionInitializationError as exc:
            logger.error("加密自检失败: %s", exc)
            raise
        except (SQLAlchemyError, ValueError, TypeError, UnicodeError, TimeoutError) as exc:
            logger.error("加密自检失败: %s", type(exc).__name__)
            raise EncryptionInitializationError("加密自检失败，已停止启动，请检查数据库和密钥配置") from None


encryption_service = EncryptionService()
