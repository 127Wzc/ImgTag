#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
日志配置模块
提供统一的日志记录功能
"""

import logging
import os
from logging.handlers import RotatingFileHandler

try:
    import colorama
    from colorama import Fore, Style
    colorama.init()
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False
    class Fore:
        GREEN = BLUE = YELLOW = CYAN = ""
    class Style:
        RESET_ALL = ""

# 创建日志目录
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 配置基本日志格式
BASE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 标准日志文件
LOG_FILE = os.path.join(LOG_DIR, "api.log")

# 性能日志文件
PERF_LOG_FILE = os.path.join(LOG_DIR, "performance.log")

# 缓存配置以避免循环导入
_log_level = None
_perf_enabled = True


def _get_log_level():
    """延迟获取日志级别"""
    global _log_level
    if _log_level is None:
        try:
            from imgtag.core.config import settings
            _log_level = settings.LOG_LEVEL
        except:
            _log_level = "INFO"
    return _log_level


def get_logger(name: str) -> logging.Logger:
    """获取标准日志记录器
    
    Args:
        name: 日志记录器名称
        
    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    
    # 设置日志级别
    log_level = _get_log_level()
    logger.setLevel(getattr(logging, log_level))
    
    # 如果已经有处理器，不再添加
    if logger.handlers:
        return logger
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level))
    
    # 带颜色的控制台格式
    if HAS_COLORAMA:
        console_format = f"{Fore.GREEN}%(asctime)s{Style.RESET_ALL} - " \
                        f"{Fore.BLUE}%(name)s{Style.RESET_ALL} - " \
                        f"{Fore.YELLOW}%(levelname)s{Style.RESET_ALL} - " \
                        f"%(message)s"
    else:
        console_format = BASE_FORMAT
    
    console_formatter = logging.Formatter(console_format)
    console_handler.setFormatter(console_formatter)
    
    # 文件处理器
    file_handler = RotatingFileHandler(
        LOG_FILE, 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(getattr(logging, log_level))
    file_formatter = logging.Formatter(BASE_FORMAT)
    file_handler.setFormatter(file_formatter)
    
    # 添加处理器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


def get_perf_logger() -> logging.Logger:
    """获取性能日志记录器
    
    Returns:
        性能日志记录器
    """
    if not _perf_enabled:
        # 如果性能日志被禁用，返回空日志记录器
        return logging.getLogger("null")
    
    logger = logging.getLogger("performance")
    
    # 设置日志级别
    logger.setLevel(logging.INFO)
    
    # 如果已经有处理器，不再添加
    if logger.handlers:
        return logger
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 带颜色的控制台格式
    if HAS_COLORAMA:
        console_format = f"{Fore.CYAN}性能日志 - %(asctime)s{Style.RESET_ALL} - %(message)s"
    else:
        console_format = "性能日志 - %(asctime)s - %(message)s"
    
    console_formatter = logging.Formatter(console_format)
    console_handler.setFormatter(console_formatter)
    
    # 文件处理器
    file_handler = RotatingFileHandler(
        PERF_LOG_FILE, 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter("%(asctime)s - 性能数据 - %(message)s")
    file_handler.setFormatter(file_formatter)
    
    # 添加处理器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger
