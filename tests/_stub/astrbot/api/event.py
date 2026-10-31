"""`astrbot.api.event` 的最小 stub：消息事件、装饰器与消息类型。"""

from __future__ import annotations

import enum
from typing import Any, Callable, List, Optional


class EventMessageType(enum.Flag):
    GROUP_MESSAGE = enum.auto()
    PRIVATE_MESSAGE = enum.auto()
    OTHER_MESSAGE = enum.auto()
    ALL = GROUP_MESSAGE | PRIVATE_MESSAGE | OTHER_MESSAGE


class _MessageObj:
    def __init__(self, components: List[Any] | None = None) -> None:
        self.message = components or []
        self.sender = None
        self.type = None
        self.group_id = ""


class AstrMessageEvent:
    """只实现插件实际用到的成员。"""

    def __init__(
        self,
        message_str: str = "",
        umo: str = "test:FriendMessage:1",
        sender_id: str = "1",
        components: List[Any] | None = None,
    ) -> None:
        self.message_str = message_str
        self.unified_msg_origin = umo
        self.message_obj = _MessageObj(components)
        self._sender_id = sender_id
        self.sent: List[Any] = []
        self.stopped = False
        self.tracked: List[str] = []
        self.typing = 0

    # --- 插件读取 ---
    def get_sender_id(self) -> str:
        return self._sender_id

    def get_messages(self) -> List[Any]:
        return self.message_obj.message

    def get_group_id(self) -> str:
        return ""

    # --- 产出 ---
    def plain_result(self, text: str) -> Any:
        item = ("plain", text)
        self.sent.append(item)
        return item

    def chain_result(self, chain: List[Any]) -> Any:
        item = ("chain", chain)
        self.sent.append(item)
        return item

    # --- 生命周期 ---
    def stop_event(self) -> None:
        self.stopped = True

    async def send_typing(self) -> None:
        self.typing += 1

    def track_temporary_local_file(self, path: str) -> None:
        self.tracked.append(path)


class _Filter:
    def _passthrough(self, *_a: Any, **_k: Any) -> Callable:
        def deco(fn: Callable) -> Callable:
            return fn

        return deco

    def command(self, *_a: Any, **_k: Any) -> Callable:
        return self._passthrough()

    def event_message_type(self, *_a: Any, **_k: Any) -> Callable:
        return self._passthrough()

    def on_llm_request(self, *_a: Any, **_k: Any) -> Callable:
        return self._passthrough()

    EventMessageType = EventMessageType


filter = _Filter()

__all__ = ["AstrMessageEvent", "EventMessageType", "filter", "Optional"]
