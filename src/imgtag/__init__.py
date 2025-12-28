#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""ImgTag 后端包

版本号从 pyproject.toml 读取，实现统一管理。
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("imgtag")
except PackageNotFoundError:
    # 开发模式下可能未安装包
    __version__ = "0.0.5"
