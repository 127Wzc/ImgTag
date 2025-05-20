#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
日志配置模块 - 简化版，直接输出到终端
"""

import logging

# 创建日志格式
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)

# 控制台处理器 - 显示所有日志
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# 性能日志格式 - 使用不同颜色或标记
perf_formatter = logging.Formatter(
    '\033[92m%(asctime)s - PERF - %(message)s\033[0m'  # 绿色显示性能日志
)

# 性能日志控制台处理器
perf_console_handler = logging.StreamHandler()
perf_console_handler.setLevel(logging.INFO)
perf_console_handler.setFormatter(perf_formatter)

# 配置根日志记录器
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)

# 创建性能日志记录器
perf_logger = logging.getLogger('performance')
perf_logger.setLevel(logging.INFO)
perf_logger.handlers = []  # 清除可能的默认处理器
perf_logger.addHandler(perf_console_handler)
perf_logger.propagate = False  # 防止日志传播到根记录器

# 获取日志记录器的函数
def get_logger(name=None):
    """获取日志记录器
    
    Args:
        name: 日志记录器名称，默认为root
        
    Returns:
        日志记录器实例
    """
    return logging.getLogger(name)

def get_perf_logger():
    """获取性能日志记录器
    
    Returns:
        性能日志记录器实例
    """
    return logging.getLogger('performance') 