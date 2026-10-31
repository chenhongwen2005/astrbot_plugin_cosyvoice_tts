"""`astrbot.core.utils.astrbot_path` 的最小 stub。

测试时通过环境变量 CV_TEST_DATA 指定数据根目录，避免写进插件目录。
"""

from __future__ import annotations

import os
import tempfile


def get_astrbot_data_path() -> str:
    return os.environ.get("CV_TEST_DATA") or os.path.join(tempfile.gettempdir(), "cv_stub_data")


def get_astrbot_temp_path() -> str:
    return os.path.join(get_astrbot_data_path(), "temp")


__all__ = ["get_astrbot_data_path", "get_astrbot_temp_path"]
