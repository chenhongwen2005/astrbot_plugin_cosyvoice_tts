"""参考音色与会话偏好的落盘。

一个会话（AstrBot 的 unified_msg_origin）对应一组文件：

    voices/<key>.wav    规整后的参考音频
    voices/<key>.json   {name, prompt_text, seconds, sample_rate, created}
    voices/_default.*   全局默认音色，供原生 TTS Provider 使用

`/语音 音色 全局` 就是把当前会话的音色复制成 `_default`，因为 TTS Provider 的
`get_audio(text)` 拿不到会话上下文，只能用一份全局音色。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from .audio import fmt_seconds, probe

DEFAULT_KEY = "_default"


def key_for(umo: str) -> str:
    """会话键 → 稳定短哈希（不能直接用 umo，里面可能有 / 和冒号）。"""
    return hashlib.sha1((umo or "default").encode("utf-8")).hexdigest()[:16]


@dataclass
class Voice:
    key: str
    path: str
    prompt_text: str = ""
    name: str = ""
    seconds: float = 0.0
    sample_rate: int = 0
    created: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        parts = [self.name or os.path.basename(self.path)]
        if self.seconds:
            parts.append(fmt_seconds(self.seconds))
        if self.sample_rate:
            parts.append(f"{self.sample_rate // 1000}kHz")
        if self.prompt_text:
            parts.append(f"「{self.prompt_text[:24]}{'…' if len(self.prompt_text) > 24 else ''}」")
        return " · ".join(parts)


class VoiceStore:
    def __init__(self, root: str) -> None:
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    # ------------------------------------------------------------------
    def _wav(self, key: str) -> str:
        return os.path.join(self.root, f"{key}.wav")

    def _meta(self, key: str) -> str:
        return os.path.join(self.root, f"{key}.json")

    def get(self, key: str) -> Optional[Voice]:
        wav, meta = self._wav(key), self._meta(key)
        if not os.path.isfile(wav):
            return None
        data: Dict[str, Any] = {}
        if os.path.isfile(meta):
            try:
                with open(meta, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        info = probe(wav) or {}
        return Voice(
            key=key,
            path=wav,
            prompt_text=str(data.get("prompt_text") or ""),
            name=str(data.get("name") or ""),
            seconds=float(data.get("seconds") or info.get("seconds") or 0.0),
            sample_rate=int(data.get("sample_rate") or info.get("sr") or 0),
            created=float(data.get("created") or 0.0),
            extra=dict(data.get("extra") or {}),
        )

    def get_default(self) -> Optional[Voice]:
        return self.get(DEFAULT_KEY)

    def put(
        self,
        key: str,
        src_path: str,
        *,
        name: str = "",
        prompt_text: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Voice:
        """把 src_path 复制成该会话的参考音色（覆盖旧的）。"""
        wav = self._wav(key)
        tmp = wav + ".tmp"
        shutil.copyfile(src_path, tmp)
        os.replace(tmp, wav)
        info = probe(wav) or {}
        voice = Voice(
            key=key,
            path=wav,
            prompt_text=prompt_text or "",
            name=name or "",
            seconds=float(info.get("seconds") or 0.0),
            sample_rate=int(info.get("sr") or 0),
            created=time.time(),
            extra=dict(extra or {}),
        )
        self._write_meta(voice)
        return voice

    def copy_to_default(self, key: str) -> Optional[Voice]:
        """把某个会话的音色设为全局默认。"""
        src = self.get(key)
        if src is None:
            return None
        return self.put(
            DEFAULT_KEY,
            src.path,
            name=src.name,
            prompt_text=src.prompt_text,
            extra=src.extra,
        )

    def set_text(self, key: str, text: str) -> Optional[Voice]:
        voice = self.get(key)
        if voice is None:
            return None
        voice.prompt_text = (text or "").strip()
        self._write_meta(voice)
        return voice

    def delete(self, key: str) -> bool:
        touched = False
        for p in (self._wav(key), self._meta(key)):
            if os.path.isfile(p):
                try:
                    os.remove(p)
                    touched = True
                except OSError:
                    pass
        return touched

    def _write_meta(self, voice: Voice) -> None:
        data = {
            "prompt_text": voice.prompt_text,
            "name": voice.name,
            "seconds": voice.seconds,
            "sample_rate": voice.sample_rate,
            "created": voice.created,
            "extra": voice.extra,
        }
        path = self._meta(voice.key)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)


class Prefs:
    """会话级偏好：方言、自定义指令、自定义参考文字。全放一个 json 里。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self._data: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f) or {}
        except Exception:
            self._data = {}

    def save(self) -> None:
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def get(self, key: str) -> Dict[str, Any]:
        return dict(self._data.get(key) or {})

    def set(self, key: str, **kw: Any) -> Dict[str, Any]:
        cur = dict(self._data.get(key) or {})
        for k, v in kw.items():
            if v is None:
                cur.pop(k, None)
            else:
                cur[k] = v
        if cur:
            self._data[key] = cur
        else:
            self._data.pop(key, None)
        self.save()
        return cur
