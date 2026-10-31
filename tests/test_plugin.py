"""插件链路冒烟测试：在没有 AstrBot 运行时的机器上，把 main.py 真的跑一遍。

为什么需要这个文件：
    其余测试只测 `cosyvoice/` 里的纯逻辑，从不 import `main.py`。而「一装就崩」的原因
    几乎全在 main.py 与 AstrBot 的接口层——属性名写错、装饰器签名不符、事件方法不存在。
    这些只能靠真的 import 一遍、真的走几个指令才能发现。

做法：
    用 `tests/_stub/` 里的最小 astrbot 包顶替真身，把插件当包导入、实例化，
    再把网络部分换成假实现，只验「指令解析 → 状态读写 → 产出语音消息」这条链。

注意：
    stub 只声明插件用到的符号，不模拟行为；它能证明「接口对得上」，
    不能证明「在真 AstrBot 里效果对」。
"""

from __future__ import annotations

import array
import asyncio
import importlib
import io
import os
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
PLUGIN_PKG = os.path.basename(ROOT)

sys.path.insert(0, os.path.join(HERE, "_stub"))
sys.path.insert(0, PARENT)

_TMP = tempfile.mkdtemp(prefix="cv_plugin_")
os.environ["CV_TEST_DATA"] = _TMP

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.message_components import Plain, Record  # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"[ok] {name}")
    else:
        print(f"[!!] {name} {detail}")
        FAILED.append(name)


def wav_bytes(seconds: float = 0.2, sr: int = 16000) -> bytes:
    buf = array.array("h")
    for i in range(int(sr * seconds)):
        buf.append(int(800 * ((i % 40) - 20)))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(buf.tobytes())
    return out.getvalue()


def make_wav_file(path: str, seconds: float = 2.0, sr: int = 16000) -> str:
    with open(path, "wb") as f:
        f.write(wav_bytes(seconds, sr))
    return path


def text_of(result) -> str:
    if isinstance(result, tuple) and result and result[0] == "plain":
        return str(result[1])
    return ""


async def run(agen) -> list:
    return [r async for r in agen]


def main() -> int:
    mod = importlib.import_module(f"{PLUGIN_PKG}.main")
    ctx = importlib.import_module("astrbot.api.star").Context()

    cfg = {
        "commands_enabled": True,
        "api_base": "https://example.invalid/",
        "mode": "自然语言控制",
        "default_dialect": "",
        "default_instruct": "",
        "auto_bind_voice": True,
        "auto_rebind": False,
        "auto_recognize": True,
        "register_provider": False,  # stub 里没有 provider，跳过注册
        "timeout": 30,
        "concurrency": 1,
        "retries": 0,
    }
    plugin = mod.CosyVoicePlugin(ctx, cfg)

    calls = {"synth": [], "recognize": 0, "probe": 0}

    async def fake_synth(text, *, ref_wav=None, instruct="", prompt_text="", mode="自然语言控制", seed=0):
        calls["synth"].append(
            {"text": text, "instruct": instruct, "prompt_text": prompt_text, "mode": mode, "ref": ref_wav}
        )
        return wav_bytes()

    async def fake_recog(path):
        calls["recognize"] += 1
        return "希望你以后能够做的比我还好呦"

    async def fake_probe():
        calls["probe"] += 1
        return {"base": "https://example.invalid/", "latency": 0.4,
                "endpoints": ["/generate_audio"], "version": "4.31.3"}

    plugin.client.synthesize = fake_synth
    plugin.client.recognize = fake_recog
    plugin.client.probe = fake_probe

    ref = make_wav_file(os.path.join(_TMP, "ref.wav"))

    def ev(text: str, comps=None) -> AstrMessageEvent:
        return AstrMessageEvent(text, umo="test:FriendMessage:7", components=comps or [])

    # --- 帮助 ---
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音"))))
    check("无参数给帮助", "CosyVoice2 方言语音" in text_of(out[0]), text_of(out[0])[:40])
    check("帮助提示先设音色", "先把一段语音发给我" in text_of(out[0]) and "尚未设置音色" in text_of(out[0]))

    # --- 没有音色时合成要提示 ---
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 你好呀"))))
    check("无音色被拦下", "参考音频" in text_of(out[0]), text_of(out[0])[:40])
    check("无音色不调接口", not calls["synth"])

    # --- 方言列表与切换 ---
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 方言"))))
    body = text_of(out[0])
    check("方言列表 11 行", sum(1 for ln in body.splitlines() if ln.startswith(("▶", "·"))) == 11)
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 方言 四川"))))
    check("切四川", "四川" in text_of(out[0]), text_of(out[0]))
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 方言 火星"))))
    check("未识方言给列表", "没认出" in text_of(out[0]))
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 方言 关"))))
    check("关方言", "已关闭方言" in text_of(out[0]))

    # --- 记音色 ---
    class FakeRecord(Record):
        def __init__(self, p: str) -> None:
            super().__init__(path=p)

    msg = ev("", comps=[FakeRecord(ref)])
    out = asyncio.run(run(plugin.on_message(msg)))
    check("记音色有回执", out and "已记下这个音色" in text_of(out[0]), text_of(out[0])[:60])
    check("识别被调用", calls["recognize"] == 1)
    key = plugin._key(msg)
    voice = plugin.store.get(key)
    check("音色已存", voice is not None)
    check("参考文字已存", voice is not None and voice.prompt_text.startswith("希望你"))
    check("顺手设为全局", plugin.store.get_default() is not None)
    check("事件被截停", msg.stopped is True)

    # 已有音色，且不是「换」状态 → 不覆盖
    out = asyncio.run(run(plugin.on_message(ev("", comps=[FakeRecord(ref)]))))
    check("已有音色不重绑", out == [])
    # 带文字的消息不当成设音色
    out = asyncio.run(run(plugin.on_message(ev("这是句话", comps=[FakeRecord(ref), Plain("这是句话")]))))
    check("带文字不重绑", out == [])
    # 说过「换」之后才重绑
    asyncio.run(run(plugin.cosy_cmd(ev("语音 音色 换"))))
    out = asyncio.run(run(plugin.on_message(ev("", comps=[FakeRecord(ref)]))))
    check("换音色后可重绑", out and "已记下这个音色" in text_of(out[0]))

    # --- 正常合成 ---
    asyncio.run(run(plugin.cosy_cmd(ev("语音 方言 四川"))))
    synth_event = ev("语音 今天天气不错，我们出去走走吧。")
    out = asyncio.run(run(plugin.cosy_cmd(synth_event)))
    check("合成返回语音消息", out and out[0][0] == "chain", str(out)[:60])
    if out and out[0][0] == "chain":
        chain = out[0][1]
        check("消息里是 Record", isinstance(chain[0], Record))
        check("音频文件存在", os.path.isfile(chain[0].path))
        check("临时文件被登记回收", len(synth_event.tracked) == 1)
        check("合成前发过 typing", synth_event.typing >= 1)
    last = calls["synth"][-1]
    check("带上四川指令", last["instruct"] == "用四川话说这句话。", last["instruct"])
    check("文本原样传入", last["text"].startswith("今天天气不错"), last["text"])

    # --- 自定义指令叠加 ---
    asyncio.run(run(plugin.cosy_cmd(ev("语音 指令 语速慢一点"))))
    asyncio.run(run(plugin.cosy_cmd(ev("语音 再说一句。"))))
    check("指令叠加", calls["synth"][-1]["instruct"] == "用四川话说这句话，语速慢一点。",
          calls["synth"][-1]["instruct"])
    asyncio.run(run(plugin.cosy_cmd(ev("语音 指令 清空"))))

    # --- 复刻模式 ---
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 复刻 我回来了。"))))
    check("复刻成功", out and out[0][0] == "chain", str(out)[:60])
    check("复刻带参考文字", calls["synth"][-1]["prompt_text"].startswith("希望你"))
    check("复刻模式正确", calls["synth"][-1]["mode"] == "3s极速复刻")

    plugin.store.set_text(key, "")
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 复刻 没文字"))))
    check("复刻缺文字要提示", "参考文字" in text_of(out[0]), text_of(out[0])[:60])
    plugin.store.set_text(key, "补回来")

    # --- 长文本分段 ---
    before = len(calls["synth"])
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 " + "这是一句话。" * 200))))
    check("长文本分多段", len(calls["synth"]) - before > 1, str(len(calls["synth"]) - before))
    check("长文本仍是一条消息", out and out[0][0] == "chain")

    # --- 清洗：括号旁白与表情 ---
    before = len(calls["synth"])
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 （小声）😊今天天气不错。"))))
    check("清洗后照常合成", out and out[0][0] == "chain", str(out)[:60])
    sent = calls["synth"][-1]["text"] if len(calls["synth"]) > before else ""
    check("括号与表情都删掉", sent == "今天天气不错。", repr(sent))

    before = len(calls["synth"])
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 （笑）😊"))))
    check("清成空要提示而不是崩溃", out and "没有可念" in text_of(out[0]), text_of(out[0])[:70])
    check("清成空不调接口", len(calls["synth"]) == before, str(len(calls["synth"]) - before))

    plugin.config["strip_brackets"] = False
    asyncio.run(run(plugin.cosy_cmd(ev("语音 （小声）走了。"))))
    check("关掉括号开关就保留", "（小声）" in calls["synth"][-1]["text"],
          repr(calls["synth"][-1]["text"]))
    plugin.config["strip_brackets"] = True

    plugin.config["strip_emoji"] = False
    asyncio.run(run(plugin.cosy_cmd(ev("语音 走了😊"))))
    check("关掉表情开关就保留", "😊" in calls["synth"][-1]["text"],
          repr(calls["synth"][-1]["text"]))
    plugin.config["strip_emoji"] = True

    # --- 音色信息与状态 ---
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 音色"))))
    check("音色信息", "【音色】" in text_of(out[0]) and "参考文字" in text_of(out[0]))
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 状态"))))
    check("状态探活", calls["probe"] == 1 and "接口状态" in text_of(out[0]), text_of(out[0])[:40])

    # --- 关闭指令 ---
    plugin.config["commands_enabled"] = False
    out = asyncio.run(run(plugin.cosy_cmd(ev("语音 你好"))))
    check("开关关闭后静默", "关闭" in text_of(out[0]))
    plugin.config["commands_enabled"] = True

    # --- 配置里的默认修饰：新会话生效，显式清空后不再回落 ---
    plugin.config["default_instruct"] = "声音低一点"
    fresh = AstrMessageEvent("语音 新会话说一句。", umo="test:FriendMessage:99")
    asyncio.run(run(plugin.cosy_cmd(fresh)))
    check("新会话继承默认修饰", calls["synth"][-1]["instruct"] == "声音低一点。",
          calls["synth"][-1]["instruct"])
    plugin.config["commands_enabled"] = True
    asyncio.run(run(plugin.cosy_cmd(fresh)))
    asyncio.run(run(plugin.cosy_cmd(AstrMessageEvent("语音 指令 清空", umo="test:FriendMessage:99"))))
    asyncio.run(run(plugin.cosy_cmd(AstrMessageEvent("语音 再来一句。", umo="test:FriendMessage:99"))))
    check("清空后不回落默认", calls["synth"][-1]["instruct"] == "",
          repr(calls["synth"][-1]["instruct"]))

    print()
    if FAILED:
        print(f"{len(FAILED)} 项失败：{FAILED}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
