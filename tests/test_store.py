"""音色存储与偏好自测。

音色是每个会话一条记录，写盘是 `wav + json` 两个文件；这里验证覆盖、复制成全局、
改参考文字、删除、以及偏好读写。
"""

from __future__ import annotations

import array
import math
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "_stub"))

import wave  # noqa: E402

from cosyvoice import Prefs, VoiceStore, key_for  # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"[ok] {name}")
    else:
        print(f"[!!] {name} {detail}")
        FAILED.append(name)


def make_wav(path: str, seconds: float = 1.0, sr: int = 16000, ch: int = 1) -> str:
    n = int(sr * seconds)
    buf = array.array("h")
    for i in range(n):
        v = int(8000 * math.sin(2 * math.pi * 220 * i / sr))
        buf.extend([v] * ch)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(buf.tobytes())
    return path


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="cv_store_")
    try:
        src = make_wav(os.path.join(tmp, "ref.wav"), 1.5)
        store = VoiceStore(os.path.join(tmp, "voices"))

        check("会话键稳定", key_for("qq:FriendMessage:1") == key_for("qq:FriendMessage:1"))
        check("不同会话键不同", key_for("a") != key_for("b"))
        check("初始为空", store.get("k1") is None)
        check("初始无全局", store.get_default() is None)

        v = store.put("k1", src, name="测试音色", prompt_text="你好呀")
        check("落盘成功", os.path.isfile(v.path))
        check("元信息带上", v.prompt_text == "你好呀" and v.name == "测试音色")
        check("时长读出来", abs(v.seconds - 1.5) < 0.05, str(v.seconds))
        check("采样率读出来", v.sample_rate == 16000, str(v.sample_rate))

        again = store.get("k1")
        check("读回一致", again is not None and again.prompt_text == "你好呀")
        check("摘要可读", "测试音色" in again.summary() and "1.5s" in again.summary(), again.summary())

        # 覆盖
        src2 = make_wav(os.path.join(tmp, "ref2.wav"), 2.0)
        v2 = store.put("k1", src2, name="第二段", prompt_text="换一句")
        check("覆盖后时长更新", abs(v2.seconds - 2.0) < 0.05, str(v2.seconds))
        check("覆盖后文字更新", store.get("k1").prompt_text == "换一句")

        # 改参考文字
        v3 = store.set_text("k1", "  改写后的句子  ")
        check("改文字", v3 is not None and v3.prompt_text == "改写后的句子")
        check("改文字落盘", store.get("k1").prompt_text == "改写后的句子")
        check("改不存在的", store.set_text("nope", "x") is None)

        # 设为全局
        g = store.copy_to_default("k1")
        check("复制成全局", g is not None and store.get_default() is not None)
        check("全局保留文字", store.get_default().prompt_text == "改写后的句子")
        check("全局是独立文件", store.get_default().path != store.get("k1").path)

        # 删除
        check("删除成功", store.delete("k1") is True)
        check("删除后读不到", store.get("k1") is None)
        check("全局还在", store.get_default() is not None)
        check("重复删除", store.delete("k1") is False)

        # 偏好
        prefs = Prefs(os.path.join(tmp, "prefs.json"))
        check("偏好初始为空", prefs.get("k1") == {})
        prefs.set("k1", dialect="四川")
        check("写方言", prefs.get("k1").get("dialect") == "四川")
        prefs.set("k1", instruct="语速慢一点")
        check("叠加字段", prefs.get("k1") == {"dialect": "四川", "instruct": "语速慢一点"})
        prefs.set("k1", dialect=None)
        check("置 None 删字段", "dialect" not in prefs.get("k1"))
        prefs.set("k1", instruct=None)
        check("清空后不留空记录", prefs.get("k1") == {})

        prefs2 = Prefs(os.path.join(tmp, "prefs.json"))
        check("重新加载", prefs2.get("k1") == {})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILED:
        print(f"{len(FAILED)} 项失败：{FAILED}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
