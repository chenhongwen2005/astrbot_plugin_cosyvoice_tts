"""长文本切分。

接口一次能吃多少字没有硬性文档，但超过几百字会明显变慢、也更容易被网关掐断，
所以按标点切成不超过 `MAX_TEXT` 的段，合成完再把 wav 拼回去。
"""

from __future__ import annotations

import re
from typing import List

from .const import MAX_TEXT, CosyVoiceError

_SENT_END = re.compile(r"(?<=[。！？!?；;…\n])")


def split_text(text: str, limit: int = MAX_TEXT, max_parts: int = 4) -> List[str]:
    """按句切分，保证每段不超过 limit 字。

    段数超过 max_parts 时抛错——一句话把机器人卡住几十秒，不如直接告诉用户分开发。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    parts: List[str] = []
    cur = ""
    for seg in _SENT_END.split(text):
        if not seg:
            continue
        if len(seg) > limit:  # 单句超长，硬切
            if cur:
                parts.append(cur)
                cur = ""
            for i in range(0, len(seg), limit):
                parts.append(seg[i : i + limit])
            continue
        if len(cur) + len(seg) > limit and cur:
            parts.append(cur)
            cur = seg
        else:
            cur += seg
    if cur:
        parts.append(cur)

    if len(parts) > max_parts:
        raise CosyVoiceError(
            f"文本太长（{len(text)} 字，要合成 {len(parts)} 段）。"
            f"一次最多 {max_parts} 段，请分几条发。"
        )
    return parts
