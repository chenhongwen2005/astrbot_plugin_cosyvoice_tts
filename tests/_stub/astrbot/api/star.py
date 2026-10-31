"""`astrbot.api.star` 的最小 stub：Star 基类与 Context。"""

from __future__ import annotations

from typing import Any


class Context:
    def __init__(self) -> None:
        self.provider_manager = None


class Star:
    def __init__(self, context: Context | None = None) -> None:
        self.context = context

    async def terminate(self) -> None:  # noqa: D401 - 与真实接口一致
        return None


__all__ = ["Context", "Star"]
