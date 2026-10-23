"""统一应用与 Uvicorn 的日志格式、级别和输出位置。"""

import logging
from copy import copy
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock

from imgtag.core.config import settings

BASE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_FILE = Path("logs/api.log")
_lock = Lock()
_configured = False


class UnifiedFormatter(logging.Formatter):
    """在同一出口渲染外层格式和 Uvicorn 请求摘要，不改写原始记录。"""

    def __init__(self):
        super().__init__(BASE_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        if (
            record.name == "uvicorn.access"
            and record.msg == '%s - "%s %s HTTP/%s" %d'
            and isinstance(record.args, tuple)
            and len(record.args) == 5
        ):
            client, method, path, protocol, status = record.args
            record = copy(record)
            record.msg = "请求完成: method=%s path=%s status=%s client=%s protocol=HTTP/%s"
            record.args = (method, path, status, client, protocol)
        return super().format(record)


def configure_logging() -> None:
    """共用一组控制台/轮转文件处理器；重复初始化不会重复写日志。"""
    global _configured
    level = logging.getLevelName(settings.LOG_LEVEL.upper())
    if not isinstance(level, int):
        level = logging.INFO
    with _lock:
        root = logging.getLogger()
        handlers = [handler for handler in root.handlers if getattr(handler, "_imgtag", False)]
        if not handlers:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            handlers = [
                logging.StreamHandler(),
                RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"),
            ]
            for handler in handlers:
                handler._imgtag = True
                root.addHandler(handler)

        for handler in handlers:
            handler.setLevel(level)
            handler.setFormatter(UnifiedFormatter())

        logging.getLogger("imgtag").setLevel(level)
        # Uvicorn CLI 先安装自己的处理器；应用启动时将其接入统一输出。
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            server_logger = logging.getLogger(name)
            server_logger.handlers.clear()
            server_logger.propagate = True
            server_logger.setLevel(level)
        _configured = True


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        configure_logging()
    return logging.getLogger(name)
