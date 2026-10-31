"""参考音频的体检与规整。

CosyVoice2 对参考音频有两条硬要求：**采样率不低于 16kHz**、**长度不超过 30 秒**。
用户发来的语音五花八门（8k 电话音、44.1k 双声道、mp3 转过好几手的 wav），
所以在落盘前统一过一遍这里：

- 低于 16k → 线性插值补到 16k（升采样不会混叠，纯 Python 就够）
- 双声道 → 取均值合成单声道
- 超过 30 秒 → 掐掉尾部（掐完再做识别，保证参考文字和音频对得上）
- 不是 16bit PCM → 有 ffmpeg 就让 ffmpeg 转，没有就明确报错

不做降采样：44.1k 直接交给服务端比本地粗暴抽取更安全。
"""

from __future__ import annotations

import array
import os
import shutil
import subprocess
import wave
from typing import Any, Dict, List, Optional, Tuple

from .const import MAX_REF_SEC, MIN_REF_SEC, TARGET_SR, CosyVoiceError

__all__ = ["probe", "normalize", "fmt_seconds", "concat_wavs"]


def probe(path: str) -> Optional[Dict[str, Any]]:
    """读取 wav 参数；不是 wav 或无法解析时返回 None。"""
    try:
        with wave.open(path, "rb") as w:
            sr = w.getframerate()
            frames = w.getnframes()
            return {
                "sr": sr,
                "ch": w.getnchannels(),
                "width": w.getsampwidth(),
                "frames": frames,
                "seconds": frames / float(sr) if sr else 0.0,
            }
    except Exception:
        return None


def fmt_seconds(sec: float) -> str:
    if sec < 1:
        return f"{sec * 1000:.0f}ms"
    if sec < 60:
        return f"{sec:.1f}s"
    return f"{sec / 60:.1f}min"


def _ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def _to_wav16k(src: str, dst: str) -> bool:
    """用 ffmpeg 转成 16k 单声道 16bit PCM。"""
    exe = _ffmpeg()
    if not exe:
        return False
    try:
        subprocess.run(
            [exe, "-y", "-loglevel", "error", "-i", src,
             "-ac", "1", "-ar", str(TARGET_SR), "-acodec", "pcm_s16le", dst],
            check=True,
            timeout=60,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return os.path.isfile(dst) and os.path.getsize(dst) > 44
    except Exception:
        return False


def _read_pcm16(path: str) -> Tuple[List[int], int, int]:
    """返回 (单声道样本, 原采样率, 原始时长秒)。"""
    with wave.open(path, "rb") as w:
        ch, sr, width, n = w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width != 2:
        raise CosyVoiceError(
            f"参考音频是 {width * 8}bit 采样，这里只处理 16bit PCM。"
            "装个 ffmpeg 再试，或先转成 16bit wav。"
        )
    samples = array.array("h")
    samples.frombytes(raw[: (len(raw) // 2) * 2])
    if ch > 1:
        mono = [
            int(sum(samples[i : i + ch]) / ch)
            for i in range(0, len(samples) - ch + 1, ch)
        ]
    else:
        mono = list(samples)
    return mono, sr, (len(mono) / float(sr) if sr else 0.0)


def _write_pcm16(path: str, samples: List[int], sr: int = TARGET_SR) -> None:
    buf = array.array("h", samples)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(buf.tobytes())


def _resample_linear(samples: List[int], src_sr: int, dst_sr: int) -> List[int]:
    if src_sr == dst_sr or not samples:
        return samples
    ratio = dst_sr / float(src_sr)
    out_len = int(len(samples) * ratio)
    last = len(samples) - 1
    out = [0] * out_len
    for i in range(out_len):
        pos = i / ratio
        a = int(pos)
        if a >= last:
            out[i] = samples[last]
            continue
        frac = pos - a
        out[i] = int(samples[a] * (1.0 - frac) + samples[a + 1] * frac)
    return out


def normalize(
    path: str,
    *,
    out_path: Optional[str] = None,
    max_sec: float = MAX_REF_SEC,
    min_sec: float = MIN_REF_SEC,
) -> Tuple[str, List[str]]:
    """把参考音频规整到「16k 以上、单声道、≤30s、16bit PCM」。

    返回 (可用路径, 说明列表)。说明是给用户看的，比如「已补采样到 16k」。
    不需要改动时原样返回入参路径。
    """
    if not path or not os.path.isfile(path):
        raise CosyVoiceError("参考音频文件不存在。")
    notes: List[str] = []
    info = probe(path)
    if info is None:
        # 不是 wav（mp3/m4a/silk 等），交给 ffmpeg
        target = out_path or path + ".16k.wav"
        if _to_wav16k(path, target):
            notes.append("已转成 16k 单声道 wav")
            return target, notes
        raise CosyVoiceError("这个音频格式我读不了，转成 wav（16kHz 以上）再发一次。")

    if info["seconds"] < min_sec:
        raise CosyVoiceError(
            f"参考音频太短（{fmt_seconds(info['seconds'])}），至少给 1 秒，最好 3–10 秒。"
        )

    need_mono = info["ch"] > 1
    need_upsample = info["sr"] < TARGET_SR
    need_cut = info["seconds"] > max_sec
    if not (need_mono or need_upsample or need_cut):
        return path, notes

    try:
        samples, sr, seconds = _read_pcm16(path)
    except CosyVoiceError:
        target = out_path or path + ".16k.wav"
        if _to_wav16k(path, target):
            notes.append("已转成 16k 单声道 wav")
            return target, notes
        raise

    if need_mono:
        notes.append("已合成立体声 → 单声道")
    if need_upsample:
        samples = _resample_linear(samples, sr, TARGET_SR)
        notes.append(f"已补采样 {sr} → {TARGET_SR}Hz")
        sr = TARGET_SR
    if need_cut:
        keep = int(max_sec * sr)
        samples = samples[:keep]
        notes.append(f"原音频 {fmt_seconds(seconds)}，已截到 {int(max_sec)} 秒")

    target = out_path or path + ".norm.wav"
    _write_pcm16(target, samples, sr)
    return target, notes


def concat_wavs(chunks: List[bytes]) -> bytes:
    """把多段 wav 字节拼成一段。参数不一致时只保住第一段的格式。"""
    import io

    if not chunks:
        return b""
    if len(chunks) == 1:
        return chunks[0]

    def _open(b: bytes):
        return wave.open(io.BytesIO(b), "rb")

    first = _open(chunks[0])
    params = first.getparams()
    frames = [first.readframes(first.getnframes())]
    for b in chunks[1:]:
        try:
            w = _open(b)
            if (w.getnchannels(), w.getframerate(), w.getsampwidth()) != (
                params.nchannels,
                params.framerate,
                params.sampwidth,
            ):
                continue  # 格式对不上就跳过，宁可少一段也不要产出一个坏文件
            frames.append(w.readframes(w.getnframes()))
        except Exception:
            continue
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(b"".join(frames))
    return out.getvalue()
