#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
项目配置文件
集中管理所有配置项
"""

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 数据库配置
DB_CONNECTION_STRING = os.getenv("PG_CONNECTION_STRING")

# 模型配置
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
MODEL_DIR = "./models"

# 应用配置
DEFAULT_SAMPLE_COUNT = 20
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_SIMILARITY_THRESHOLD = 0.7

# 日志配置
LOG_LEVEL = "INFO"
PERFORMANCE_LOG_ENABLED = True 