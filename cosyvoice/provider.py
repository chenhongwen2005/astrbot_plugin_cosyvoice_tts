"""把 CosyVoice2 注册成 AstrBot 的原生 TTS Provider。

注册之后，WebUI 的「服务提供商 → 语音转文本(TTS)」里会多出一个
「CosyVoice2 方言 TTS」，把它设为默认并在会话里打开语音回复，
机器人就会用这里配置的方言朗读回复，不用每次打 /语音 指令。

原生 Provider 的 `get_audio(text)` 拿不到会话上下文，因此它只能使用**一份全局音色**：
优先用配置里填的 `ref_wav`，没填就退回 `/语音 音色 全局` 存下的 `_default.wav`。

整个模块是「尽力而为」：AstrBot 的 provider 接口在版本之间会变，
导入或注册失败时只记一条警告，指令侧照常可用。
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from typing import Any, Dict, Optional

from .client import CosyVoiceClient
from .const import DEFAULT_BASE, MODE_CLONE, MODE_INSTRUCT
from .dialects import build_instruct, resolve
from .text import sanitize

#: 注册进 AstrBot 的类型名，配置里以它区分
TYPE_NAME = "cosyvoice2_modelscope"
DISPLAY_NAME = "CosyVoice2 方言 TTS"

#: 由插件实例注入的运行时对象（main.py 的 __init__ 里调 bind）
_STATE: Dict[str, Any] = {"store": None, "logger": None}


def bind(store: Any = None, logger: Any = None) -> None:
    if store is not None:
        _STATE["store"] = store
    if logger is not None:
        _STATE["logger"] = logger


def _ref_path(provider_config: Dict[str, Any]) -> Optional[str]:
    ref = str(provider_config.get("ref_wav") or "").strip()
    if ref and os.path.isfile(ref):
        return ref
    store = _STATE.get("store")
    if store is not None:
        try:
            voice = store.get_default()
            if voice is not None and os.path.isfile(voice.path):
                return voice.path
        except Exception:
            return None
    return None


def _prompt_text(provider_config: Dict[str, Any]) -> str:
    text = str(provider_config.get("prompt_text") or "").strip()
    if text:
        return text
    store = _STATE.get("store")
    if store is not None:
        try:
            voice = store.get_default()
            if voice is not None:
                return voice.prompt_text or ""
        except Exception:
            return ""
    return ""


def _cleanup(directory: str, keep_seconds: float = 3600.0) -> None:
    """清掉一小时前的临时音频，别把磁盘塞满。"""
    try:
        now = time.time()
        for name in os.listdir(directory):
            p = os.path.join(directory, name)
            try:
                if now - os.path.getmtime(p) > keep_seconds:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def _flag(cfg: Dict[str, Any], key: str, default: bool = True) -> bool:
    """provider 配置在 WebUI 里是手写 JSON，布尔可能被写成字符串。"""
    value = cfg.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


def default_config_tmpl() -> Dict[str, Any]:
    return {
        "id": TYPE_NAME,
        "provider": DISPLAY_NAME,
        "type": TYPE_NAME,
        "provider_type": "text_to_speech",
        "enable": False,
        "api_base": DEFAULT_BASE,
        "dialect": "四川",
        "instruct": "",
        "ref_wav": "",
        "prompt_text": "",
        "mode": MODE_INSTRUCT,
        "timeout": 180,
        "strip_brackets": True,
        "strip_emoji": True,
    }


def register() -> bool:
    """把 Provider 注册进 AstrBot。已注册过则直接返回 True。"""
    try:
        from astrbot.core.provider.entities import ProviderType
        from astrbot.core.provider.provider import TTSProvider
        from astrbot.core.provider.register import (
            provider_cls_map,
            register_provider_adapter,
        )
    except Exception as e:  # noqa: BLE001
        log = _STATE.get("logger")
        if log:
            log.warning(f"[cosyvoice] 无法导入 TTSProvider，跳过 Provider 注册：{e}")
        return False

    if TYPE_NAME in provider_cls_map:
        return True

    class CosyVoice2TTSProvider(TTSProvider):
        def __init__(self, provider_config, provider_settings) -> None:
            super().__init__(provider_config, provider_settings)
            cfg = provider_config or {}
            self.cfg = cfg
            self.dialect = str(cfg.get("dialect") or "").strip()
            self.instruct_extra = str(cfg.get("instruct") or "").strip()
            self.mode = cfg.get("mode") or MODE_INSTRUCT
            self.prompt_text = _prompt_text(cfg)
            self.client = CosyVoiceClient(
                str(cfg.get("api_base") or DEFAULT_BASE),
                timeout=float(cfg.get("timeout") or 180),
                concurrency=2,
                logger=_STATE.get("logger"),
            )

        async def get_audio(self, text: str) -> str:
            ref = _ref_path(self.cfg)
            if not ref:
                raise Exception(
                    "CosyVoice2 TTS 还没有参考音频：请在插件里发一段语音设音色，"
                    "或在服务提供商配置里填 ref_wav 的路径。"
                )
            try:
                dialect = resolve(self.dialect) if self.dialect else None
            except KeyError:
                dialect = None
            text = sanitize(
                text,
                brackets=_flag(self.cfg, "strip_brackets", True),
                emoji=_flag(self.cfg, "strip_emoji", True),
            )
            if not text:
                raise Exception("清洗后没有可念的内容了（括号旁白与表情都被删掉）。")
            mode = self.mode
            instruct = build_instruct(dialect, self.instruct_extra) if mode == MODE_INSTRUCT else ""
            prompt_text = self.prompt_text if mode == MODE_CLONE else ""
            if mode == MODE_CLONE and not prompt_text:
                prompt_text = _prompt_text(self.cfg)

            audio = await self.client.synthesize(
                text,
                ref_wav=ref,
                instruct=instruct,
                prompt_text=prompt_text,
                mode=mode,
            )
            out_dir = os.path.join(tempfile.gettempdir(), "astrbot_cosyvoice2")
            os.makedirs(out_dir, exist_ok=True)
            _cleanup(out_dir)
            path = os.path.join(out_dir, f"tts_{uuid.uuid4().hex[:12]}.wav")
            with open(path, "wb") as f:
                f.write(audio)
            return path

    try:
        register_provider_adapter(
            TYPE_NAME,
            "ModelScope CosyVoice2（方言 / 音色复刻）",
            provider_type=ProviderType.TEXT_TO_SPEECH,
            default_config_tmpl=default_config_tmpl(),
            provider_display_name=DISPLAY_NAME,
        )(CosyVoice2TTSProvider)
        return True
    except Exception as e:  # noqa: BLE001
        log = _STATE.get("logger")
        if log:
            log.warning(f"[cosyvoice] 注册 TTS Provider 失败：{e}")
        return False
