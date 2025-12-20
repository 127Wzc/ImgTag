#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""core 模块"""

from .config import settings
from .logging_config import get_logger, get_perf_logger

__all__ = ["settings", "get_logger", "get_perf_logger"]
