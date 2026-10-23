"""日志输出格式、级别和重复初始化的回归验证，不启动服务。"""

import io
import logging
import re

import pytest

from imgtag.core import logging_config
from imgtag.core.config import settings


@pytest.fixture
def logging_output(tmp_path, monkeypatch, capsys):
    # 隔离全局 logging 状态，避免影响其他用例的 caplog 与应用处理器。
    monkeypatch.setattr(logging_config, 'LOG_FILE', tmp_path / 'api.log')
    monkeypatch.setattr(logging_config, '_configured', False)
    root = logging.getLogger()
    monkeypatch.setattr(root, 'handlers', [])
    for name in ('imgtag', 'imgtag.logging_test', 'uvicorn', 'uvicorn.error', 'uvicorn.access'):
        logger = logging.getLogger(name)
        for field in ('level', 'handlers', 'propagate', 'disabled'):
            monkeypatch.setattr(logger, field, getattr(logger, field))
    yield capsys
    for handler in root.handlers:
        if getattr(handler, "_imgtag", False):
            handler.close()


def test_application_and_uvicorn_share_format_and_write_once(logging_output, monkeypatch):
    monkeypatch.setattr(settings, 'LOG_LEVEL', 'DEBUG')
    # 模拟 Uvicorn CLI 在加载应用前安装的独立处理器。
    old_output = io.StringIO()
    old_handler = logging.StreamHandler(old_output)
    old_handler.setFormatter(logging.Formatter('OLD %(message)s'))
    logging.getLogger('uvicorn.access').handlers = [old_handler]
    logging.getLogger('uvicorn.access').propagate = False

    for _ in range(3):
        logging_config.configure_logging()
        for number in range(30):
            assert not logging_config.get_logger(f'imgtag.logging_test.module{number}').handlers

    logging_config.get_logger('imgtag.logging_test').debug('查询完成: returned=%s', 7)
    logging.getLogger('uvicorn.error').info('服务已就绪')
    logging.getLogger('uvicorn.access').info('%s - "%s %s HTTP/%s" %d',
                                            '127.0.0.1:60040', 'POST', '/api/v1/images/search', '1.1', 200)
    lines = logging_output.readouterr().err.splitlines()
    assert len(lines) == 3
    assert all(re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - '
                           r'(imgtag\.logging_test|uvicorn\.(access|error)) - (DEBUG|INFO) - .+', line)
               for line in lines)
    assert lines[0].endswith('DEBUG - 查询完成: returned=7')
    assert lines[-1].endswith('请求完成: method=POST path=/api/v1/images/search status=200 '
                              'client=127.0.0.1:60040 protocol=HTTP/1.1')
    assert logging_config.LOG_FILE.read_text(encoding='utf-8').splitlines() == lines
    assert old_output.getvalue() == ""
    assert not (logging_config.LOG_FILE.parent / 'performance.log').exists()
    assert sum(getattr(handler, "_imgtag", False) for handler in logging.getLogger().handlers) == 2


def test_request_formatting_preserves_original_record():
    record = logging.LogRecord('uvicorn.access', logging.INFO, __file__, 1,
                               '%s - "%s %s HTTP/%s" %d',
                               ('127.0.0.1:60040', 'GET', '/api/v1/tags/?size=200', '1.1', 200), None)
    original = record.getMessage()
    formatter = logging_config.UnifiedFormatter()
    assert formatter.format(record) == formatter.format(record)
    assert '请求完成: method=GET path=/api/v1/tags/?size=200 status=200' in formatter.format(record)
    assert record.getMessage() == original


@pytest.mark.parametrize('name,message,args', [
    ('uvicorn.access', '请求日志格式变更: %s', ('保留信息',)),
    ('uvicorn.access', '没有参数的请求日志', ()),
    ('uvicorn.access', '%s %s %s %s %s', ('另一种', '请求', '日志', '应当', '保留')),
    ('imgtag.logging_test', '业务操作: id=%s status=%s', (7, 'ok')),
])
def test_unrelated_log_messages_are_not_rewritten(name, message, args):
    record = logging.LogRecord(name, logging.INFO, __file__, 1, message, args, None)
    assert logging_config.UnifiedFormatter().format(record).endswith(record.getMessage())


@pytest.mark.parametrize('configured,expected', [('INFO', logging.INFO), ('debug', logging.DEBUG),
                                               ('WARNING', logging.WARNING), ('invalid', logging.INFO)])
def test_log_level_applies_to_application_and_requests(logging_output, monkeypatch, configured, expected):
    monkeypatch.setattr(settings, 'LOG_LEVEL', configured)
    logger = logging_config.get_logger('imgtag.logging_test')
    for number, name in enumerate(('imgtag.logging_test', 'uvicorn.access')):
        logger = logging.getLogger(name)
        for level in (logging.DEBUG, logging.INFO, logging.WARNING):
            logger.log(level, '行为 user=%s level=%s', number, level)
    lines = logging_output.readouterr().err.splitlines()
    assert len(lines) == 2 * sum(level >= expected for level in (logging.DEBUG, logging.INFO, logging.WARNING))
    if expected > logging.DEBUG:
        assert all('DEBUG' not in line for line in lines)
    assert all(handler.level == expected for handler in logging.getLogger().handlers
               if getattr(handler, "_imgtag", False))


def test_existing_root_handlers_are_preserved(logging_output, monkeypatch):
    monkeypatch.setattr(settings, 'LOG_LEVEL', 'INFO')
    external_output = io.StringIO()
    external_handler = logging.StreamHandler(external_output)
    logging.getLogger().addHandler(external_handler)
    logging_config.configure_logging()
    logging_config.configure_logging()
    logging_config.get_logger('imgtag.logging_test').warning('测试警告')
    assert external_output.getvalue().splitlines() == ['测试警告']
    assert len(logging_output.readouterr().err.splitlines()) == 1
    assert external_handler in logging.getLogger().handlers
    assert sum(getattr(handler, "_imgtag", False) for handler in logging.getLogger().handlers) == 2
