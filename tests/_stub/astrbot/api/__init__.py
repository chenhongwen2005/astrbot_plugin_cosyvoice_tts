"""`astrbot.api` 的最小 stub。"""

from __future__ import annotations

import logging
from typing import Any, Dict


class AstrBotConfig(dict):
    """真实实现是带 schema 校验的 dict 子类，这里退化成普通 dict。"""

    def __init__(self, data: Dict[str, Any] | None = None) -> None:
        super().__init__(data or {})


class _Logger:
    def debug(self, msg: str, *a: Any, **k: Any) -> None:
        logging.getLogger("stub").debug(msg)

    def info(self, msg: str, *a: Any, **k: Any) -> None:
        pass

    def warning(self, msg: str, *a: Any, **k: Any) -> None:
        pass

    def error(self, msg: str, *a: Any, **k: Any) -> None:
        pass

    def exception(self, msg: str, *a: Any, **k: Any) -> None:
        pass


logger = _Logger()

__all__ = ["AstrBotConfig", "logger"]
