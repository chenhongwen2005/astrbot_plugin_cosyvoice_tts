"""CosyVoice2 方言语音插件的内核。

对外只暴露这几样：客户端、方言表、音色存储、文本切分。
"""

from __future__ import annotations

from .audio import concat_wavs, fmt_seconds, normalize, probe
from .client import CosyVoiceClient, CosyVoiceError, QueueFull
from .const import (
    DEFAULT_BASE,
    MAX_TEXT,
    MODE_CLONE,
    MODE_INSTRUCT,
    STUDIO_PAGE,
    VERSION,
)
from .dialects import DIALECTS, Dialect, build_instruct, resolve, table_lines
from .store import DEFAULT_KEY, Prefs, Voice, VoiceStore, key_for
from .text import sanitize, split_text, strip_brackets, strip_emoji, tidy

__all__ = [
    "CosyVoiceClient",
    "CosyVoiceError",
    "QueueFull",
    "DEFAULT_BASE",
    "DEFAULT_KEY",
    "DIALECTS",
    "Dialect",
    "MAX_TEXT",
    "MODE_CLONE",
    "MODE_INSTRUCT",
    "Prefs",
    "STUDIO_PAGE",
    "VERSION",
    "Voice",
    "VoiceStore",
    "build_instruct",
    "concat_wavs",
    "fmt_seconds",
    "key_for",
    "normalize",
    "probe",
    "resolve",
    "sanitize",
    "split_text",
    "strip_brackets",
    "strip_emoji",
    "table_lines",
    "tidy",
]
