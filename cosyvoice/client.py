"""CosyVoice2（ModelScope 创空间）的异步客户端。

为什么不用 gradio_client：

1. 它是同步阻塞实现，在协程里要额外开线程池；
2. 清华 PyPI 镜像里根本没有 `gradio-client` 这个包，插件依赖会装不上；
3. ModelScope 的 acw 网关按 User-Agent 拦人，必须自己控制请求头。

所以这里直接实现 Gradio 4.x 的队列协议，只依赖 AstrBot 自带的 aiohttp：

    GET  {base}config                     取依赖表，拿到端点的 fn_index
    POST {base}upload                     上传参考音频，返回服务器临时路径
    POST {base}queue/join                 提交任务，返回 event_id
    GET  {base}queue/data?session_hash=..  SSE 流，按 event_id 取结果
    GET  {base}file=<path>                下载合成结果

`{base}` 末尾带斜杠；若应用配置了 api_prefix，上述路径都会前置该前缀。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp

from .const import (
    DEFAULT_BASE,
    MAX_TEXT,
    MODE_INSTRUCT,
    USER_AGENT,
    CosyVoiceError,
    QueueFull,
)

__all__ = ["CosyVoiceClient", "CosyVoiceError", "QueueFull"]


def normalize_base(url: str) -> str:
    """把用户填的地址规整成 `协议://主机/路径/` 形式。"""
    url = (url or DEFAULT_BASE).strip()
    if not url:
        url = DEFAULT_BASE
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/") + "/"


class CosyVoiceClient:
    """一个无状态（配置缓存除外）的客户端，可并发复用。"""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE,
        *,
        timeout: float = 180.0,
        concurrency: int = 2,
        retries: int = 2,
        user_agent: str = USER_AGENT,
        logger=None,
    ) -> None:
        self.base = normalize_base(base_url)
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.ua = user_agent or USER_AGENT
        self._log = logger
        self._sem = asyncio.Semaphore(max(1, int(concurrency)))
        self._cfg: Optional[Dict[str, Any]] = None
        self._cfg_at = 0.0
        self._cfg_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 基础请求
    # ------------------------------------------------------------------
    def _headers(self, *, sse: bool = False) -> Dict[str, str]:
        h = {"User-Agent": self.ua, "Accept-Language": "zh-CN,zh;q=0.9"}
        h["Accept"] = "text/event-stream" if sse else "application/json"
        return h

    def _session(self, total: Optional[float] = None) -> aiohttp.ClientSession:
        timeout = aiohttp.ClientTimeout(
            total=self.timeout if total is None else total,
            sock_connect=20.0,
            sock_read=None,  # SSE 期间可能长时间没有数据，读超时交给 total 管
        )
        return aiohttp.ClientSession(
            timeout=timeout,
            connector=aiohttp.TCPConnector(limit=8, enable_cleanup_closed=True),
            trust_env=True,  # 允许走系统的 HTTP(S)_PROXY
        )

    def _url(self, path: str) -> str:
        return self.base + path.lstrip("/")

    def _debug(self, msg: str) -> None:
        if self._log:
            try:
                self._log.debug(f"[cosyvoice] {msg}")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 应用元信息
    # ------------------------------------------------------------------
    async def config(self, session: aiohttp.ClientSession, *, force: bool = False) -> Dict[str, Any]:
        """取 `/config`（缓存 10 分钟）。"""
        async with self._cfg_lock:
            if not force and self._cfg and time.monotonic() - self._cfg_at < 600:
                return self._cfg
            try:
                async with session.get(
                    self._url("config"), headers=self._headers(), allow_redirects=True
                ) as r:
                    body = await r.text()
                    if r.status == 403:
                        raise CosyVoiceError(
                            "创空间网关拒绝了请求（403）。通常是 User-Agent 被拦，"
                            "或本机网络/代理出了问题。"
                        )
                    if r.status != 200:
                        raise CosyVoiceError(
                            f"读取应用配置失败：HTTP {r.status}，{body[:120]}"
                        )
                    cfg = json.loads(body)
            except aiohttp.ClientError as e:
                raise CosyVoiceError(f"连不上 {self.base}：{e}") from e
            self._cfg = cfg
            self._cfg_at = time.monotonic()
            return cfg

    @staticmethod
    def fn_index(cfg: Dict[str, Any], api_name: str) -> int:
        """按 api_name 反查 fn_index。端点顺序由应用方决定，不能写死。"""
        name = api_name.lstrip("/")
        for i, dep in enumerate(cfg.get("dependencies") or []):
            if (dep or {}).get("api_name") == name:
                return i
        raise CosyVoiceError(f"应用里没有 {api_name} 这个接口，可能是创空间版本变了。")

    def _prefix(self, cfg: Dict[str, Any]) -> str:
        return (cfg.get("api_prefix") or "").strip("/")

    def _endpoint(self, cfg: Dict[str, Any], path: str) -> str:
        prefix = self._prefix(cfg)
        return self._url(f"{prefix}/{path}" if prefix else path)

    # ------------------------------------------------------------------
    # 上传 / 下载
    # ------------------------------------------------------------------
    async def upload(self, session: aiohttp.ClientSession, path: str) -> Dict[str, Any]:
        """把本地音频传到服务器，返回可直接塞进 data 的 FileData 结构。"""
        cfg = await self.config(session)
        name = os.path.basename(path)
        form = aiohttp.FormData()
        with open(path, "rb") as f:
            form.add_field("files", f, filename=name, content_type="audio/wav")
            async with session.post(
                self._endpoint(cfg, "upload"), data=form, headers=self._headers()
            ) as r:
                body = await r.text()
                if r.status != 200:
                    raise CosyVoiceError(f"上传参考音频失败：HTTP {r.status}，{body[:120]}")
                try:
                    saved = json.loads(body)
                except json.JSONDecodeError as e:
                    raise CosyVoiceError(f"上传返回的不是 JSON：{body[:120]}") from e
        if not saved or not isinstance(saved, list):
            raise CosyVoiceError(f"上传没有拿到服务器路径：{body[:120]}")
        self._debug(f"upload {name} -> {saved[0]}")
        return {
            "path": saved[0],
            "orig_name": name,
            "meta": {"_type": "gradio.FileData"},
        }

    async def _download(self, session: aiohttp.ClientSession, item: Any) -> bytes:
        """下载结果音频。服务端会直接给绝对 url，没有就自己拼 file=。"""
        if isinstance(item, str):
            url, path = (item, None) if item.startswith("http") else (None, item)
        elif isinstance(item, dict):
            url, path = item.get("url"), item.get("path")
        else:
            raise CosyVoiceError("接口返回的音频格式无法识别。")
        if not url:
            if not path:
                raise CosyVoiceError("接口没有返回音频。")
            url = self._url("file=" + quote(str(path), safe="/"))
        async with session.get(url, headers=self._headers()) as r:
            if r.status != 200:
                body = await r.text()
                raise CosyVoiceError(f"下载合成音频失败：HTTP {r.status}，{body[:120]}")
            data = await r.read()
        if not data:
            raise CosyVoiceError("合成音频是空的。")
        return data

    # ------------------------------------------------------------------
    # 队列调用
    # ------------------------------------------------------------------
    async def _call(
        self,
        session: aiohttp.ClientSession,
        cfg: Dict[str, Any],
        api_name: str,
        data: List[Any],
        *,
        budget: float,
    ) -> Any:
        """提交任务并等 SSE 结果，返回 output['data']。"""
        fn = self.fn_index(cfg, api_name)
        sess_hash = uuid.uuid4().hex
        payload = {"data": data, "fn_index": fn, "session_hash": sess_hash}
        join_url = self._endpoint(cfg, "queue/join")

        async with session.post(join_url, json=payload, headers=self._headers()) as r:
            body = await r.text()
            if r.status == 503:
                raise QueueFull("创空间排队满了，稍后再试。")
            if r.status != 200:
                raise CosyVoiceError(f"提交合成任务失败：HTTP {r.status}，{body[:120]}")
            try:
                event_id = (json.loads(body) or {}).get("event_id")
            except json.JSONDecodeError as e:
                raise CosyVoiceError(f"提交返回的不是 JSON：{body[:120]}") from e
        if not event_id:
            raise CosyVoiceError(f"没有拿到任务号：{body[:120]}")
        self._debug(f"{api_name} event={event_id} fn={fn}")

        deadline = time.monotonic() + budget
        stream_url = self._endpoint(cfg, "queue/data")
        async with session.get(
            stream_url, params={"session_hash": sess_hash}, headers=self._headers(sse=True)
        ) as r:
            if r.status != 200:
                body = await r.text()
                raise CosyVoiceError(f"订阅任务结果失败：HTTP {r.status}，{body[:120]}")
            async for raw in r.content:
                if time.monotonic() > deadline:
                    raise asyncio.TimeoutError
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    msg = json.loads(line[5:])
                except json.JSONDecodeError:
                    continue
                if msg.get("event_id") not in (None, event_id):
                    continue
                kind = msg.get("msg")
                if kind == "process_completed":
                    return self._unwrap(msg)
                if kind == "unexpected_error":
                    raise CosyVoiceError(f"服务端出错：{msg.get('message') or msg}")
                if kind in ("close_stream", "server_stopped", "process_stopped"):
                    raise CosyVoiceError("任务被中断（创空间可能刚重启或排队被清）。")
                # estimation / process_starts / process_generating / heartbeat 继续等
        raise CosyVoiceError("连接中断，没有收到合成结果。")

    @staticmethod
    def _unwrap(msg: Dict[str, Any]) -> Any:
        out = msg.get("output") or {}
        if out.get("error"):
            raise CosyVoiceError(f"合成失败：{str(out['error'])[:200]}")
        if msg.get("success") is False:
            raise CosyVoiceError("合成失败，服务端没有给出原因。")
        return out.get("data")

    # ------------------------------------------------------------------
    # 对外能力
    # ------------------------------------------------------------------
    async def synthesize(
        self,
        text: str,
        *,
        ref_wav: Optional[str] = None,
        instruct: str = "",
        prompt_text: str = "",
        mode: str = MODE_INSTRUCT,
        seed: float = 0,
    ) -> bytes:
        """合成一段语音，返回 wav 字节。

        - `mode=MODE_INSTRUCT`：自然语言控制，`instruct` 决定方言/语气
        - `mode=MODE_CLONE`：3s 极速复刻，`prompt_text` 应当与参考音频内容一致
        两种模式都需要 `ref_wav` 提供音色。
        """
        text = (text or "").strip()
        if not text:
            raise CosyVoiceError("没有要合成的文本。")
        if len(text) > MAX_TEXT:
            raise CosyVoiceError(
                f"文本太长了（{len(text)} 字），单次上限 {MAX_TEXT} 字，请分段合成。"
            )
        if not ref_wav:
            raise CosyVoiceError("还没有参考音频。先发一段语音给我，或用 /语音 音色 指定。")
        if not os.path.isfile(ref_wav):
            raise CosyVoiceError(f"参考音频不存在：{ref_wav}")

        last: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                async with self._sem:
                    return await self._synth_once(
                        text,
                        ref_wav=ref_wav,
                        instruct=instruct,
                        prompt_text=prompt_text,
                        mode=mode,
                        seed=seed,
                    )
            except QueueFull as e:
                last = e
                if attempt >= self.retries:
                    break
                await asyncio.sleep(3.0 + 2.0 * attempt)
            except asyncio.TimeoutError as e:
                last = e
                if attempt >= self.retries:
                    break
            except aiohttp.ClientError as e:
                last = e
                if attempt >= self.retries:
                    break
                await asyncio.sleep(1.5 * (attempt + 1))
        if isinstance(last, asyncio.TimeoutError):
            raise CosyVoiceError(f"合成超时（{int(self.timeout)} 秒）。文本短一点会快很多。")
        if last is not None:
            raise CosyVoiceError(f"合成失败：{last}")
        raise CosyVoiceError("合成失败。")

    async def _synth_once(self, text, *, ref_wav, instruct, prompt_text, mode, seed) -> bytes:
        budget = self.timeout
        async with self._session(total=self.timeout + 10) as session:
            cfg = await self.config(session)
            fdata = await self.upload(session, ref_wav)
            data = [
                text,
                mode,
                prompt_text or "",
                fdata,  # prompt_wav_upload
                None,  # prompt_wav_record：只走上传，录制位留空
                instruct or "",
                float(seed or 0),
                "False",  # 是否流式推理；接口只接受 "False"
            ]
            out = await self._call(session, cfg, "/generate_audio", data, budget=budget)
            item = out[0] if isinstance(out, list) and out else out
            return await self._download(session, item)

    async def recognize(self, ref_wav: str) -> str:
        """用创空间自带的 SenseVoice 识别参考音频的文字。失败返回空串。"""
        if not os.path.isfile(ref_wav):
            return ""
        try:
            async with self._session(total=min(90.0, self.timeout)) as session:
                cfg = await self.config(session)
                fdata = await self.upload(session, ref_wav)
                out = await self._call(
                    session, cfg, "/prompt_wav_recognition", [fdata], budget=90.0
                )
            if isinstance(out, list) and out:
                return str(out[0] or "").strip()
            return str(out or "").strip()
        except Exception as e:  # noqa: BLE001 - 识别是锦上添花，不能挡住主流程
            self._debug(f"识别参考文字失败：{e}")
            return ""

    async def probe(self) -> Dict[str, Any]:
        """探活：能不能连上、有哪些接口。给 /语音 状态 用。"""
        t0 = time.monotonic()
        async with self._session(total=min(20.0, self.timeout)) as session:
            cfg = await self.config(session, force=True)
        names = [
            "/" + d["api_name"]
            for d in (cfg.get("dependencies") or [])
            if isinstance(d, dict) and d.get("api_name")
        ]
        return {
            "base": self.base,
            "latency": time.monotonic() - t0,
            "endpoints": names,
            "version": str(cfg.get("version") or ""),
        }
