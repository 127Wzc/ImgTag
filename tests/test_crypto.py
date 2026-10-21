"""加密初始化、旧数据兼容和密钥轮换；使用内存库，不读取真实凭据。"""

import json
import sqlite3
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import SQLAlchemyError

from imgtag.api.endpoints import config as config_api
from imgtag.api.endpoints.auth import get_current_user
from imgtag.core import crypto
from imgtag.core.config import Settings
from imgtag.core import config_cache as cache_module
from imgtag.core.internal_config import ENCRYPTION_STATE_KEY
from imgtag.db.repositories.config import config_repository
from imgtag.db.repositories.encryption import encryption_repository
from imgtag.models import Config, StorageEndpoint
from imgtag.services import encryption_service as rotation
from imgtag.services import config_service as config_service_module
from imgtag.services.encryption_service import EncryptionInitializationError


class MemoryResult:
    def __init__(self, rows, entity=None):
        self.rows = rows
        self.entity = entity

    def mappings(self):
        return self

    def one_or_none(self):
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        row = self.one_or_none()
        if row is None:
            return None
        return self.entity(**row) if self.entity else next(iter(row.values()))

    def scalar_one(self):
        assert len(self.rows) == 1
        return self.scalar_one_or_none()

    def fetchall(self):
        return [tuple(row.values()) for row in self.rows]

    def scalars(self):
        return SimpleNamespace(all=lambda: [self.entity(**row) for row in self.rows])


class MemoryTransaction:
    def __init__(self, database):
        self.database = database

    async def __aenter__(self):
        self.database.connection.execute('BEGIN')

    async def __aexit__(self, error_type, error, tb):
        if error_type is not None or self.database.fail_commit:
            self.database.connection.rollback()
            if error_type is None:
                raise SQLAlchemyError('simulated-secret-in-commit-error')
        else:
            self.database.connection.commit()


class MemorySession:
    def __init__(self, database):
        self.database = database

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def begin(self):
        return MemoryTransaction(self.database)

    async def get(self, model, key):
        return (await self.execute(select(model).where(model.key == key))).scalar_one_or_none()

    async def execute(self, statement, params=None):
        compiled = statement.compile(dialect=sqlite.dialect(paramstyle='named'),
                                     compile_kwargs={'render_postcompile': True})
        sql = str(compiled)
        if 'pg_try_advisory_xact_lock' in sql:
            assert self.database.connection.in_transaction
            self.database.locks += 1
            return MemoryResult([{'locked': True}])
        def bind(values):
            return {key: json.dumps(value) if isinstance(value, (dict, list)) else value
                    for key, value in (compiled.params | (values or {})).items()}
        if isinstance(params, list):
            cursor = self.database.connection.executemany(sql, [bind(row) for row in params])
        else:
            cursor = self.database.connection.execute(sql, bind(params))
        rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
        for row in rows:
            if isinstance(row.get('payload'), str):
                row['payload'] = json.loads(row['payload'])
        descriptions = getattr(statement, 'column_descriptions', [])
        entity = Config if len(descriptions) == 1 and descriptions[0]['expr'] is Config else None
        return MemoryResult(rows, entity)


class MemoryDatabase:
    def __init__(self):
        self.connection = sqlite3.connect(':memory:', isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.locks = 0
        self.fail_commit = False
        self.connection.executescript('''
            CREATE TABLE storage_endpoints (id INTEGER PRIMARY KEY, access_key_id TEXT,
                secret_access_key TEXT, name TEXT DEFAULT 'endpoint', updated_at TEXT DEFAULT '2001-01-01 00:00:00');
            CREATE TABLE tasks (id TEXT PRIMARY KEY, payload TEXT, status TEXT, updated_at TEXT DEFAULT '2001-01-01 00:00:00');
            CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT, description TEXT,
                is_secret BOOLEAN, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')

    def session(self):
        return MemorySession(self)

    def state(self):
        row = self.connection.execute('SELECT value FROM config WHERE key=?', (ENCRYPTION_STATE_KEY,)).fetchone()
        return json.loads(row['value']) if row else None

    def seed(self, key, count=3):
        cipher = Fernet(key)
        for index in range(1, count + 1):
            self.connection.execute('INSERT INTO storage_endpoints(id,access_key_id,secret_access_key) VALUES (?,?,?)', (
                index, cipher.encrypt(f'access-test-{index}'.encode()).decode(),
                cipher.encrypt(f'secret-test-{index}'.encode()).decode(),
            ))
        for index, status in enumerate(['pending', 'processing', 'failed', 'completed'], 1):
            payload = {'image_id': index, 'callback_url': 'https://example.com/hook', 'other': ['keep', index],
                       'callback_headers_encrypted': cipher.encrypt(json.dumps({'Authorization': f'Bearer test-{index}'}).encode()).decode()}
            self.connection.execute('INSERT INTO tasks(id,payload,status) VALUES (?,?,?)', (f'task-{index}', json.dumps(payload), status))
        self.connection.execute("INSERT INTO tasks(id,payload,status) VALUES ('no-header','{}','pending')")

    def snapshot(self):
        return {table: [tuple(row) for row in self.connection.execute(f'SELECT * FROM {table} ORDER BY 1')]
                for table in ('config', 'storage_endpoints', 'tasks')}


@pytest.fixture(scope='module')
def keys():
    return {name: crypto.derive_encryption_key(name) for name in
            ('old-test-secret', 'new-test-secret', 'third-test-secret', crypto.LEGACY_DEFAULT_SECRET, '')}


@pytest.fixture
def database(monkeypatch):
    database = MemoryDatabase()
    monkeypatch.setattr(rotation, 'async_session_maker', database.session)
    monkeypatch.setattr(rotation.encryption_service, 'BATCH_SIZE', 1)
    yield database
    database.connection.close()


def assert_data_readable(database, key):
    cipher = Fernet(key)
    for row in database.connection.execute('SELECT * FROM storage_endpoints'):
        assert cipher.decrypt(row['access_key_id'].encode()).decode() == f'access-test-{row["id"]}'
        assert cipher.decrypt(row['secret_access_key'].encode()).decode() == f'secret-test-{row["id"]}'
        endpoint = StorageEndpoint(_access_key_id=row['access_key_id'], _secret_access_key=row['secret_access_key'])
        assert endpoint.access_key_id == f'access-test-{row["id"]}'
    for row in database.connection.execute('SELECT * FROM tasks'):
        payload = json.loads(row['payload'])
        if row['id'] == 'no-header':
            assert payload == {}
            continue
        index = payload['image_id']
        assert payload['callback_url'] == 'https://example.com/hook' and payload['other'] == ['keep', index]
        assert json.loads(payload['callback_headers']) == {'Authorization': f'Bearer test-{index}'}
        assert 'callback_headers_encrypted' not in payload


async def test_new_database_generates_independent_key_and_keeps_it_without_environment(database, keys):
    first = await rotation.encryption_service.initialize()
    key = database.state()['key_material'].encode()
    assert first.initialized and not first.rotated and first.version == 1
    assert key != keys[crypto.LEGACY_DEFAULT_SECRET]
    token = crypto.encrypt('test-value')
    before = database.snapshot()
    result = await rotation.encryption_service.initialize('')
    assert not result.initialized and not result.rotated and result.version == 1
    assert database.snapshot() == before
    assert crypto.decrypt(token) == 'test-value'
    assert database.locks == 2


@pytest.mark.parametrize('target', [None, 'new-test-secret'])
@pytest.mark.parametrize('legacy_secret', [crypto.LEGACY_DEFAULT_SECRET, ''])
async def test_bootstrap_recognizes_legacy_default_key(database, keys, target, legacy_secret):
    database.seed(keys[legacy_secret])
    result = await rotation.encryption_service.initialize(target)
    expected = keys[target if target is not None else legacy_secret]
    assert database.state()['key_material'].encode() == expected
    assert result.rotated is (target is not None)
    assert_data_readable(database, expected)


async def test_custom_legacy_key_registration_repeated_rotation_and_unchanged_startup(database, keys):
    database.seed(keys['old-test-secret'])
    first = await rotation.encryption_service.initialize('old-test-secret')
    assert first.initialized and not first.rotated
    assert first.migrated_callbacks == 4
    original = database.snapshot()
    assert_data_readable(database, keys['old-test-secret'])
    for version, secret in [(2, 'new-test-secret'), (3, 'third-test-secret')]:
        result = await rotation.encryption_service.initialize(secret)
        assert result.version == version and result.rotated
        assert result.storage_fields == 6 and result.migrated_callbacks == 0
        assert database.state()['key_material'].encode() == keys[secret]
        assert_data_readable(database, keys[secret])
        before = database.snapshot()
        unchanged = await rotation.encryption_service.initialize(secret)
        assert not unchanged.rotated and database.snapshot() == before
    assert [row[2] for row in original['tasks']] == [row[2] for row in database.snapshot()['tasks']]
    for table in ('tasks', 'storage_endpoints'):
        assert [row[-1] for row in original[table]] == [row[-1] for row in database.snapshot()[table]]
    first_cipher = database.snapshot()['storage_endpoints'][0][1]
    with pytest.raises(InvalidToken):
        Fernet(keys['old-test-secret']).decrypt(first_cipher.encode())
    await rotation.encryption_service.initialize(None)
    assert_data_readable(database, keys['third-test-secret'])


@pytest.mark.parametrize('supplied', [None, 'new-test-secret'])
async def test_unregistered_custom_key_must_be_provided_on_first_upgrade(database, keys, supplied, caplog):
    database.seed(keys['old-test-secret'])
    before = database.snapshot()
    previous_cipher = crypto.get_fernet()
    with pytest.raises(EncryptionInitializationError, match='首次升级') as error:
        await rotation.encryption_service.initialize(supplied)
    assert database.snapshot() == before and crypto.get_fernet() is previous_cipher
    assert 'new-test-secret' not in ''.join(traceback.format_exception(error.type, error.value, error.tb))
    assert 'new-test-secret' not in caplog.text


@pytest.mark.parametrize('failure', [
    'storage_cipher', 'task_cipher', 'task_type', 'task_json', 'task_header',
    'commit', 'state', 'state_json', 'state_version',
])
async def test_rotation_is_atomic_and_never_logs_credentials(database, keys, caplog, failure):
    database.seed(keys['old-test-secret'])
    await rotation.encryption_service.initialize('old-test-secret')
    marker = 'secret-not-to-log'
    if failure == 'storage_cipher':
        database.connection.execute('UPDATE storage_endpoints SET secret_access_key=? WHERE id=3', (marker,))
    elif failure.startswith('task_'):
        payload = json.loads(database.connection.execute("SELECT payload FROM tasks WHERE id='task-4'").fetchone()[0])
        invalid = {
            'task_cipher': marker,
            'task_type': [marker],
            'task_json': Fernet(keys['old-test-secret']).encrypt(marker.encode()).decode(),
            'task_header': Fernet(keys['old-test-secret']).encrypt(json.dumps({'Authorization': [marker]}).encode()).decode(),
        }
        payload['callback_headers_encrypted'] = invalid[failure]
        database.connection.execute("UPDATE tasks SET payload=? WHERE id='task-4'", (json.dumps(payload),))
        state = database.state() | {'callbacks_migrated': False}
        database.connection.execute('UPDATE config SET value=? WHERE key=?', (json.dumps(state), ENCRYPTION_STATE_KEY))
    elif failure.startswith('state'):
        state = database.state()
        if failure == 'state':
            state['fingerprint'] = 'damaged'
        elif failure == 'state_version':
            state['version'] = True
        value = marker if failure == 'state_json' else json.dumps(state)
        database.connection.execute('UPDATE config SET value=? WHERE key=?', (value, ENCRYPTION_STATE_KEY))
    else:
        database.fail_commit = True
    before = database.snapshot()
    previous_cipher = crypto.get_fernet()
    configured_secret = 'new-test-secret'
    with pytest.raises(EncryptionInitializationError) as error:
        await rotation.encryption_service.initialize(configured_secret)
    assert database.snapshot() == before
    assert crypto.get_fernet() is previous_cipher
    output = caplog.text + ''.join(traceback.format_exception(error.type, error.value, error.tb))
    for secret in (marker, 'new-test-secret', keys['old-test-secret'].decode(), 'simulated-secret-in-commit-error'):
        assert secret not in output
    if failure == 'commit':
        database.fail_commit = False
        await rotation.encryption_service.initialize('new-test-secret')
        assert_data_readable(database, keys['new-test-secret'])


def test_encryption_requires_startup_initialization(monkeypatch):
    monkeypatch.setattr(crypto, '_fernet', None)
    with pytest.raises(RuntimeError, match='启动初始化'):
        crypto.encrypt('value')
    assert crypto.encrypt('') == crypto.decrypt('') == ''


def test_settings_load_secret_from_dotenv_without_exposing_it(tmp_path, monkeypatch):
    monkeypatch.delenv('IMGTAG_SECRET_KEY', raising=False)
    env = tmp_path / '.env'
    env.write_text('IMGTAG_SECRET_KEY=dotenv-test-secret\n')
    settings = Settings(_env_file=env)
    assert settings.IMGTAG_SECRET_KEY.get_secret_value() == 'dotenv-test-secret'
    assert 'dotenv-test-secret' not in repr(settings.IMGTAG_SECRET_KEY)
    monkeypatch.setenv('IMGTAG_SECRET_KEY', 'process-test-secret')
    assert Settings(_env_file=env).IMGTAG_SECRET_KEY.get_secret_value() == 'process-test-secret'


async def test_key_material_is_hidden_and_cannot_be_modified_through_config_api(database, keys):
    await rotation.encryption_service.initialize('new-test-secret')
    database.connection.execute("INSERT INTO config(key,value,is_secret) VALUES ('safe-option','visible',false)")
    app = FastAPI()
    app.include_router(config_api.router, prefix='/config')
    app.dependency_overrides[get_current_user] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[config_api.get_async_session] = database.session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/config/')
        assert (await client.get(f'/config/{ENCRYPTION_STATE_KEY}')).status_code == 404
        normal = await client.get('/config/safe-option')
        assert normal.status_code == 200 and normal.json()['value'] == 'visible'
        before = database.snapshot()
        single = await client.put(f'/config/{ENCRYPTION_STATE_KEY}', params={'value': 'forged'})
        assert single.status_code == 400
        for value in ('forged', '******'):
            batch = await client.put('/config/', json={'configs': {
                'safe-option': 'changed', ENCRYPTION_STATE_KEY: value,
            }})
            assert batch.status_code == 400
        assert database.snapshot() == before
    assert response.status_code == 200 and response.json() == {'safe-option': 'visible'}
    snapshot = await encryption_repository.get_state(database.session())
    assert keys['new-test-secret'].decode() not in repr(snapshot) + response.text
    row = database.connection.execute('SELECT is_secret FROM config WHERE key=?', (ENCRYPTION_STATE_KEY,)).fetchone()
    assert row['is_secret'] == 1


async def test_internal_state_is_excluded_from_cache_and_general_config_operations(database, monkeypatch):
    await rotation.encryption_service.initialize('new-test-secret')
    database.connection.execute("INSERT INTO config(key,value,is_secret) VALUES ('safe-option','visible',false)")
    monkeypatch.setattr(cache_module, 'async_session_maker', database.session)
    monkeypatch.setattr(cache_module.config_cache, '_cache', {})
    monkeypatch.setattr(cache_module.config_cache, '_cache_time', 0)
    await cache_module.config_cache.preload()
    assert cache_module.config_cache._cache == {'safe-option': 'visible'}
    assert await cache_module.config_cache.get(ENCRYPTION_STATE_KEY, fresh=True) is None
    assert cache_module.config_cache.get_sync(ENCRYPTION_STATE_KEY) is None
    assert await config_repository.get_all_configs(database.session(), include_secrets=True) == {'safe-option': 'visible'}
    monkeypatch.setattr(config_service_module, 'async_session_maker', database.session)
    service = config_service_module.config_service
    assert await service.get_all(include_secrets=True) == {'safe-option': 'visible'}
    for operation in (
        lambda: config_repository.set_value(database.session(), ENCRYPTION_STATE_KEY, 'forged'),
        lambda: config_repository.update_multiple(database.session(), {'safe-option': 'changed', ENCRYPTION_STATE_KEY: 'forged'}),
        lambda: service.set(ENCRYPTION_STATE_KEY, 'forged'),
        lambda: service.set_multiple({'safe-option': 'changed', ENCRYPTION_STATE_KEY: 'forged'}),
    ):
        before = database.snapshot()
        with pytest.raises(ValueError, match='内部配置'):
            await operation()
        assert database.snapshot() == before


async def test_advisory_lock_uses_one_bigint_transaction_lock():
    statements = []

    async def execute(statement):
        statements.append(statement)
        return MemoryResult([{'locked': True}])

    await encryption_repository.lock(SimpleNamespace(execute=execute))
    compiled = statements[0].compile(dialect=postgresql.dialect())
    assert 'pg_try_advisory_xact_lock' in str(compiled)
    assert 0 < next(iter(compiled.params.values())) < 2 ** 63


async def test_advisory_lock_retries_without_blocking_a_database_query(monkeypatch):
    execute = AsyncMock(side_effect=[MemoryResult([{'locked': value}]) for value in [False, False, True]])
    sleep = AsyncMock()
    monkeypatch.setattr('imgtag.db.repositories.encryption.asyncio.sleep', sleep)
    await encryption_repository.lock(SimpleNamespace(execute=execute))
    assert execute.await_count == 3 and sleep.await_count == 2


async def test_initialization_timeout_is_sanitized_and_rolls_back(database, monkeypatch, caplog):
    secret = 'timeout-details-not-for-logs'
    monkeypatch.setattr(encryption_repository, 'lock', AsyncMock(side_effect=TimeoutError(secret)))
    before = database.snapshot()
    with pytest.raises(EncryptionInitializationError) as error:
        await rotation.encryption_service.initialize()
    assert database.snapshot() == before
    assert secret not in caplog.text + ''.join(traceback.format_exception(error.type, error.value, error.tb))


async def test_old_state_converts_headers_once_then_rotates_only_s3(database, keys, monkeypatch):
    database.seed(keys['old-test-secret'])
    # 兼容上一实现已经登记过密钥、尚未解除 Header 加密的状态。
    old_state = {'key_material': keys['old-test-secret'].decode(),
                 'fingerprint': rotation._fingerprint(keys['old-test-secret']), 'version': 1}
    database.connection.execute('INSERT INTO config(key,value,is_secret) VALUES (?,?,true)',
                                (ENCRYPTION_STATE_KEY, json.dumps(old_state)))
    result = await rotation.encryption_service.initialize('new-test-secret')
    assert result.migrated_callbacks == 4 and result.rotated
    assert database.state()['callbacks_migrated'] is True
    assert_data_readable(database, keys['new-test-secret'])
    before = database.snapshot()['tasks']
    monkeypatch.setattr(encryption_repository, 'task_batch', AsyncMock(side_effect=AssertionError('不应再次扫描任务')))
    result = await rotation.encryption_service.initialize('third-test-secret')
    assert result.migrated_callbacks == 0 and result.rotated
    assert database.snapshot()['tasks'] == before


async def test_callback_only_legacy_database_migrates_without_s3_credentials(database, keys):
    database.seed(keys['old-test-secret'], count=0)
    result = await rotation.encryption_service.initialize('old-test-secret')
    assert result.storage_fields == 0 and result.migrated_callbacks == 4
    assert_data_readable(database, keys['old-test-secret'])


async def test_failed_key_self_check_prevents_task_recovery(monkeypatch):
    from imgtag import main

    monkeypatch.setattr(main, 'run_migrations_sync', lambda: True)
    initialize = AsyncMock(side_effect=EncryptionInitializationError('safe-startup-error'))
    recover = AsyncMock()
    preload = AsyncMock()
    monkeypatch.setattr(main.encryption_service, 'initialize', initialize)
    monkeypatch.setattr(main.task_repository, 'get_pending_and_processing', recover)
    monkeypatch.setattr(main.config_cache, 'preload', preload)
    with pytest.raises(EncryptionInitializationError, match='safe-startup-error'):
        async with main.lifespan(main.app):
            pytest.fail('密钥自检失败时不能对外提供服务')
    recover.assert_not_awaited()
    preload.assert_not_awaited()
