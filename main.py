"""AstrBot 插件入口：CosyVoice2 方言语音。

三件事：

1. **记音色**——给机器人发一段 3–10 秒的语音，插件把它规整成 16k/单声道、落盘，
   顺带用创空间自带的 SenseVoice 识别出参考文字。
2. **说话**——`/语音 <文本>` 用已记下的音色朗读；方言靠 instruct 指令切换，
   共 11 种：广东、闽南、四川、东北、陕西、山西、上海、天津、山东、宁夏、甘肃。
3. **接进原生 TTS**——注册一个 `cosyvoice2_modelscope` Provider，
   在 WebUI 里选上以后，机器人正常回复就自动变成方言语音。

推理全部走 ModelScope 上的公开创空间 `iic/CosyVoice2-0.5B`，本机不需要显卡和模型权重。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

try:  # 不同版本路径略有差异，取不到就退回插件目录
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path  # type: ignore

    def _data_root() -> str:
        return get_astrbot_data_path()
except Exception:  # pragma: no cover
    def _data_root() -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


try:
    from astrbot.api.message_components import Plain, Record
except Exception:  # pragma: no cover - 兼容更老的版本
    from astrbot.core.message.components import Plain, Record  # type: ignore

from .cosyvoice import (
    DIALECTS,
    MODE_CLONE,
    MODE_INSTRUCT,
    STUDIO_PAGE,
    VERSION,
    CosyVoiceClient,
    CosyVoiceError,
    Prefs,
    VoiceStore,
    build_instruct,
    concat_wavs,
    fmt_seconds,
    key_for,
    normalize,
    resolve,
    split_text,
    table_lines,
)
from .cosyvoice import provider as tts_provider

PLUGIN_NAME = "astrbot_plugin_cosyvoice_tts"

NO_VOICE = (
    "还没有参考音频。先发一段 3–10 秒的**语音**给我（只发语音、别带文字），"
    "我会把音色记下来；发之前最好说一句完整的话。"
)

HELP = """【CosyVoice2 方言语音】{voice_line}

先把一段语音发给我，我会记音色并识别参考文字。

/语音 <文本>          用当前音色朗读
/语音 方言            看 11 种方言
/语音 方言 四川        切换方言（关 = 不带方言）
/语音 音色            看当前音色 / 换一段
/语音 音色 文字 <文字>  修正参考文字（复刻模式要用）
/语音 音色 全局        设为全局默认（原生 TTS 用）
/语音 音色 清除
/语音 指令 <自然语言>   自定义指令，如「用四川话，语速慢一点」
/语音 复刻 <文本>      3s 极速复刻（不切方言）
/语音 示例            用当前方言念一句本地话
/语音 状态            查接口连通性与当前设置

原生 TTS：WebUI → 服务提供商 → 语音转文本(TTS) 里选「CosyVoice2 方言 TTS」，
再用 /tts 或会话里的语音回复开关，正常回复就会变成方言语音。"""


class CosyVoicePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config: Dict[str, Any] = dict(config or {})
        base = os.path.join(_data_root(), "plugin_data", PLUGIN_NAME)
        os.makedirs(base, exist_ok=True)
        self.data_dir = base
        self.store = VoiceStore(os.path.join(base, "voices"))
        self.prefs = Prefs(os.path.join(base, "prefs.json"))
        self.tmp_dir = os.path.join(base, "tmp")
        os.makedirs(self.tmp_dir, exist_ok=True)

        self.client = CosyVoiceClient(
            str(self.config.get("api_base") or ""),
            timeout=float(self.config.get("timeout") or 180),
            concurrency=int(self.config.get("concurrency") or 2),
            retries=int(self.config.get("retries") or 2),
            logger=logger if self.config.get("debug") else None,
        )
        self._pending: Dict[str, float] = {}  # 会话键 → 等待上传音色的截止时间

        tts_provider.bind(self.store, logger)
        self.provider_ready = False
        if self.config.get("register_provider", True):
            self.provider_ready = tts_provider.register()
        logger.info(
            f"[cosyvoice] v{VERSION} 已加载｜方言 {len(DIALECTS)} 种｜"
            f"Provider {'已注册' if self.provider_ready else '未注册'}｜数据目录 {base}"
        )

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    def _key(self, event: AstrMessageEvent) -> str:
        return key_for(getattr(event, "unified_msg_origin", "") or "")

    def _rest(self, event: AstrMessageEvent) -> str:
        """取指令名之后的原文（保留空格，长文本要原样念）。"""
        raw = (event.message_str or "").strip().replace("／", "/")
        if raw.startswith("/"):
            raw = raw[1:]
        names = {"语音", "tts", "语音合成", "朗读", "cosyvoice"}
        first, sep, rest = raw.partition(" ")
        if first in names:
            return rest.strip()
        if first.startswith("tts") and len(first) > 3:  # /tts你好
            return first[3:].strip() + ((" " + rest) if rest else "")
        return raw.strip()

    def _default_mode(self) -> str:
        mode = str(self.config.get("mode") or MODE_INSTRUCT).strip()
        return mode if mode in (MODE_INSTRUCT, MODE_CLONE) else MODE_INSTRUCT

    def _temp_audio(self, data: bytes) -> str:
        path = os.path.join(tempfile.gettempdir(), "astrbot_cosyvoice2")
        os.makedirs(path, exist_ok=True)
        out = os.path.join(path, f"cv_{uuid.uuid4().hex[:12]}.wav")
        with open(out, "wb") as f:
            f.write(data)
        return out

    def _dialect_of(self, key: str):
        prefs = self.prefs.get(key)
        name = str(prefs.get("dialect") or self.config.get("default_dialect") or "").strip()
        if not name:
            return None
        try:
            return resolve(name)
        except KeyError:
            return None

    def _instruct_of(self, key: str, override: Optional[str] = None) -> str:
        """当前会话最终要发出去的 instruct。

        优先级：本次调用显式给的 > 会话里设的 > 配置里的默认。
        会话里被 `/语音 指令 清空` 写成空串时不再回落默认——用户明确说要清掉。
        """
        if override is None:
            extra = self.prefs.get(key).get("instruct")
            if extra is None:
                extra = self.config.get("default_instruct") or ""
        else:
            extra = override
        return build_instruct(self._dialect_of(key), str(extra or ""))

    def _voice_of(self, key: str):
        return self.store.get(key) or self.store.get_default()

    def _help_text(self, key: str) -> str:
        voice = self._voice_of(key)
        if voice is None:
            line = "｜尚未设置音色"
        else:
            cur = self._dialect_of(key)
            line = f"｜音色 {voice.name or '已上传'}｜方言 {cur.name if cur else '未指定'}"
        return HELP.format(voice_line=line)

    # ------------------------------------------------------------------
    # 合成
    # ------------------------------------------------------------------
    async def _synthesize(self, key: str, text: str, *, mode: str, instruct: str, prompt_text: str) -> bytes:
        voice = self._voice_of(key)
        if voice is None:
            raise CosyVoiceError(NO_VOICE)
        chunks = split_text(text)
        parts: List[bytes] = []
        for chunk in chunks:
            parts.append(
                await self.client.synthesize(
                    chunk,
                    ref_wav=voice.path,
                    instruct=instruct if mode == MODE_INSTRUCT else "",
                    prompt_text=prompt_text if mode == MODE_CLONE else "",
                    mode=mode,
                )
            )
        return concat_wavs(parts)

    def _clone_text(self, key: str) -> str:
        voice = self._voice_of(key)
        return (voice.prompt_text if voice else "") or ""

    async def _speak(self, event: AstrMessageEvent, key: str, text: str, *, mode: Optional[str] = None,
                     instruct: Optional[str] = None):
        """合成并按语音消息发回去；出错时退回文字说明。"""
        mode = mode or self._default_mode()
        prompt_text = self._clone_text(key)
        if mode == MODE_CLONE and not prompt_text:
            return event.plain_result(
                "复刻模式需要「参考文字」——即参考音频里说的那句话。\n"
                "用 /语音 音色 文字 <那句话> 补上，或者直接走自然语言控制模式（不需要文字）。"
            )
        try:
            await event.send_typing()
        except Exception:
            pass
        try:
            data = await self._synthesize(
                key,
                text,
                mode=mode,
                instruct=self._instruct_of(key, instruct),
                prompt_text=prompt_text,
            )
        except CosyVoiceError as e:
            return event.plain_result(f"合成失败：{e}")
        except asyncio.TimeoutError:
            return event.plain_result("合成超时了，接口这会儿可能排着队，过一会儿再试。")
        except Exception as e:  # noqa: BLE001
            logger.exception("[cosyvoice] 合成异常")
            return event.plain_result(f"合成失败：{e}")

        path = self._temp_audio(data)
        try:
            event.track_temporary_local_file(path)
        except Exception:
            pass
        return event.chain_result([Record.fromFileSystem(path)])

    # ------------------------------------------------------------------
    # 记音色
    # ------------------------------------------------------------------
    async def _bind_voice(self, event: AstrMessageEvent, rec: Any) -> Any:
        key = self._key(event)
        try:
            src = await rec.convert_to_file_path()
        except Exception as e:  # noqa: BLE001
            return event.plain_result(f"这个语音我拿不到本地文件：{e}")
        raw = os.path.join(self.tmp_dir, f"in_{uuid.uuid4().hex[:8]}.wav")
        notes: List[str] = []
        try:
            path, notes = normalize(src, out_path=raw)
        except CosyVoiceError as e:
            return event.plain_result(f"参考音频不能用：{e}")

        text = ""
        if self.config.get("auto_recognize", True):
            try:
                await event.send_typing()
            except Exception:
                pass
            text = await self.client.recognize(path)

        stamp = time.strftime("%m-%d %H:%M")
        voice = self.store.put(key, path, name=f"语音消息 {stamp}", prompt_text=text)
        self._pending.pop(key, None)
        if not self.store.get_default():
            # 第一个音色顺手做成全局默认，原生 TTS 开箱即用
            self.store.copy_to_default(key)

        lines = [f"已记下这个音色：{voice.summary()}"]
        if text:
            lines.append(f"参考文字（自动识别）：{text}")
        else:
            lines.append("没能识别出参考文字——自然语言控制不影响，要用复刻模式得手动补：/语音 音色 文字 <文字>")
        if notes:
            lines.append("处理：" + "；".join(notes))
        cur = self._dialect_of(key)
        if cur:
            lines.append(f"当前方言：{cur.name}（{cur.region}）")
        else:
            lines.append("当前未指定方言，用 /语音 方言 四川 之类的指令切过去。")
        lines.append("现在可以 /语音 你好，试一句。")
        return event.plain_result("\n".join(lines))

    # ------------------------------------------------------------------
    # 指令
    # ------------------------------------------------------------------
    @filter.command("语音", alias={"tts", "语音合成", "朗读", "cosyvoice"})
    async def cosy_cmd(self, event: AstrMessageEvent):
        """方言语音合成：朗读文本、切换 11 种方言、管理参考音色。"""
        if not self.config.get("commands_enabled", True):
            yield event.plain_result("语音指令已在配置里关闭。")
            return
        key = self._key(event)
        rest = self._rest(event)
        sub = rest.split()[0] if rest.split() else ""
        tail = rest[len(sub):].strip() if sub else ""

        # --- 帮助 ---
        if sub in ("", "帮助", "help", "?", "？"):
            yield event.plain_result(self._help_text(key))
            return

        # --- 方言 ---
        if sub in ("方言", "口音", "dialect"):
            if not tail:
                cur = self._dialect_of(key)
                body = table_lines(cur.name if cur else None)
                yield event.plain_result(
                    "【方言】▶ 为当前\n" + body + "\n\n切换：/语音 方言 四川｜关闭：/语音 方言 关"
                )
                return
            try:
                d = resolve(tail)
            except KeyError:
                yield event.plain_result(
                    "没认出这个方言。可用的有：" + "、".join(d.name for d in DIALECTS) + "；关掉用「关」。"
                )
                return
            self.prefs.set(key, dialect=d.name if d else "")
            if d is None:
                yield event.plain_result("已关闭方言，回到纯音色复刻 + 自然语言控制。")
            else:
                msg = f"已切到{d.region}（{d.name}）。"
                if d.note:
                    msg += f"\n提示：{d.note}"
                yield event.plain_result(msg)
            return

        # --- 音色 ---
        if sub in ("音色", "参考", "voice"):
            act = tail.split()[0] if tail.split() else ""
            if act in ("文字", "text", "参考文字"):
                new_text = tail[len(act):].strip()
                voice = self._voice_of(key)
                if voice is None:
                    yield event.plain_result(NO_VOICE)
                elif not new_text:
                    yield event.plain_result(
                        f"当前参考文字：{voice.prompt_text or '（空）'}\n修改：/语音 音色 文字 那句话原文"
                    )
                else:
                    self.store.set_text(voice.key, new_text)
                    yield event.plain_result(f"参考文字已更新：{new_text[:60]}")
                return
            if act in ("全局", "默认", "default"):
                v = self.store.copy_to_default(key)
                yield event.plain_result(
                    "已设为全局默认音色，原生 TTS Provider 会用它。"
                    if v else NO_VOICE
                )
                return
            if act in ("清除", "删除", "clear", "重置"):
                ok = self.store.delete(key)
                yield event.plain_result("已清除本会话的音色。" if ok else "本会话本来就没有单独的音色。")
                return
            if act in ("换", "更换", "上传", "重设"):
                self._pending[key] = time.time() + 600
                yield event.plain_result("好，发一段 3–10 秒的语音过来（只发语音，别带文字）。")
                return
            voice = self._voice_of(key)
            if voice is None:
                self._pending[key] = time.time() + 600
                yield event.plain_result(NO_VOICE)
                return
            own = self.store.get(key)
            src = "本会话上传" if own else "全局默认"
            cur = self._dialect_of(key)
            yield event.plain_result(
                "\n".join(
                    [
                        f"【音色】{voice.summary()}",
                        f"来源：{src}",
                        f"参考文字：{voice.prompt_text or '（空，复刻模式需要）'}",
                        f"方言：{cur.name + '·' + cur.region if cur else '未指定'}",
                        f"文件：{voice.path}",
                        "换音色：/语音 音色 换｜设为全局：/语音 音色 全局｜清除：/语音 音色 清除",
                    ]
                )
            )
            return

        # --- 自定义指令 ---
        if sub in ("指令", "instruct", "风格"):
            if not tail:
                prefs = self.prefs.get(key)
                yield event.plain_result(
                    f"当前自定义指令：{prefs.get('instruct') or '（空）'}\n"
                    "设置：/语音 指令 语速慢一点｜清空：/语音 指令 清空\n"
                    "它会被拼在方言指令后面，变成「用四川话说这句话，语速慢一点。」"
                )
                return
            if tail in ("清空", "清除", "关", "无"):
                self.prefs.set(key, instruct="")
                yield event.plain_result("已清空自定义指令。")
                return
            self.prefs.set(key, instruct=tail)
            yield event.plain_result(f"已设置指令：{self._instruct_of(key)}")
            return

        # --- 全量设置 ---
        if sub in ("设置", "设定", "config"):
            prefs = self.prefs.get(key)
            cur = self._dialect_of(key)
            voice = self._voice_of(key)
            yield event.plain_result(
                "\n".join(
                    [
                        f"【当前设置】会话 {key}",
                        f"机型/接口：{self.client.base}",
                        f"模式：{self._default_mode()}",
                        f"方言：{cur.region if cur else '未指定'}",
                        f"自定义指令：{prefs.get('instruct') or '（空）'}",
                        f"音色：{voice.summary() if voice else '未设置'}",
                        f"Provider：{'已注册' if self.provider_ready else '未注册'}",
                    ]
                )
            )
            return

        # --- 探活 ---
        if sub in ("状态", "status", "ping"):
            try:
                info = await self.client.probe()
            except Exception as e:  # noqa: BLE001
                yield event.plain_result(f"连不上创空间：{e}")
                return
            yield event.plain_result(
                "\n".join(
                    [
                        "【接口状态】正常",
                        f"地址：{info['base']}",
                        f"版本：{info['version']}",
                        f"握手耗时：{info['latency']:.1f}s",
                        "接口：" + "、".join(info["endpoints"]),
                        f"当前队列上限：并发 {self.config.get('concurrency', 2)}，超时 {int(self.client.timeout)}s",
                    ]
                )
            )
            return

        # --- 示例台词 ---
        if sub in ("示例", "sample", "试听"):
            cur = self._dialect_of(key)
            if cur is None:
                sample = "今天的天气不错，我们出去走走吧。"
                hint = "当前没选方言，这句按普通话念。用 /语音 方言 四川 切换后再试。"
            else:
                sample = cur.sample
                hint = f"{cur.region}示例原文：{sample}"
            yield event.plain_result(hint)
            yield await self._speak(event, key, sample)
            return

        # --- 复刻模式 ---
        if sub in ("复刻", "clone", "原声"):
            if not tail:
                yield event.plain_result("用法：/语音 复刻 <文本>，会用参考文字做零样本复刻，不切方言。")
                return
            yield await self._speak(event, key, tail, mode=MODE_CLONE)
            return

        # --- 其余全部当正文 ---
        yield await self._speak(event, key, rest)

    # ------------------------------------------------------------------
    # 收到语音消息 → 记音色
    # ------------------------------------------------------------------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self.config.get("auto_bind_voice", True):
            return
        comps = []
        try:
            comps = event.get_messages() or []
        except Exception:
            comps = list(getattr(getattr(event, "message_obj", None), "message", []) or [])
        rec = next((c for c in comps if isinstance(c, Record)), None)
        if rec is None:
            return
        if any(isinstance(c, Plain) and (c.text or "").strip() for c in comps):
            return  # 带文字的消息不当成「设音色」

        key = self._key(event)
        has_voice = self.store.get(key) is not None
        pending = self._pending.get(key, 0) > time.time()
        if has_voice and not pending and not self.config.get("auto_rebind", False):
            return  # 已经有音色了，别把用户日常发的语音也当成换音色

        result = await self._bind_voice(event, rec)
        try:
            event.stop_event()
        except Exception:
            pass
        yield result

    # ------------------------------------------------------------------
    async def terminate(self):
        """插件卸载时的清理。"""
        self._pending.clear()
        logger.info("[cosyvoice] 已卸载")
