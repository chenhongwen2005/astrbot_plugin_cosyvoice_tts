"""`astrbot.api.message_components` 的最小 stub。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List


class BaseMessageComponent:
    pass


class Plain(BaseMessageComponent):
    def __init__(self, text: str = "") -> None:
        self.text = text


class Record(BaseMessageComponent):
    """真实实现的 `convert_to_file_path` 会下载并转 wav；stub 直接给本地路径。"""

    def __init__(self, file: str = "", path: str | None = None, **_: Any) -> None:
        self.file = file
        self.path = path
        self.url = ""

    @staticmethod
    def fromFileSystem(path: str, **_: Any) -> "Record":
        p = Path(path).resolve()
        return Record(file=p.as_uri(), path=str(p))

    async def convert_to_file_path(self) -> str:
        return self.path or ""


__all__ = ["BaseMessageComponent", "Plain", "Record"]
