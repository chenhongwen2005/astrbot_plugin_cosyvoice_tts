"""无需 AstrBot 的链路演示。

    python demo.py                     # 只跑本地部分：方言表、指令拼接、切分
    python demo.py --ref ref.wav       # 再真合成两句，产物写到 out/
    python demo.py --ref ref.wav --dialect 广东

本地部分不需要网络，用来确认「指令是怎么拼出来的」；
带 --ref 的部分才会真的请求创空间。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from cosyvoice import (  # noqa: E402
    DIALECTS,
    CosyVoiceClient,
    CosyVoiceError,
    MODE_CLONE,
    MODE_INSTRUCT,
    build_instruct,
    normalize,
    probe,
    resolve,
    sanitize,
    split_text,
    table_lines,
)

BAR = "═" * 74


def section(title: str) -> None:
    print(f"\n{BAR}\n{title}\n{BAR}")


def local_demo() -> None:
    section("1. 11 种方言")
    print(table_lines("四川"))

    section("2. instruct 是怎么拼的")
    sc = resolve("四川")
    gd = resolve("粤语")
    for label, d, extra in [
        ("只有方言", sc, ""),
        ("方言 + 修饰", sc, "语速慢一点"),
        ("粤语 + 修饰", gd, "语气别太夸张"),
        ("只有修饰", None, "慢慢说，声音低一点"),
        ("什么都不给", None, ""),
    ]:
        print(f"  {label:12s} → {build_instruct(d, extra) or '(空，等同纯音色复刻)'}")

    section("3. 合成前会删掉什么")
    for raw in [
        "（轻轻叹气）你说得对。😔",
        "他（小声（几乎听不见））说：走吧。",
        "【旁白】她笑了（笑",
        "今天不错😊，明天更好 👍",
        "我读了《红楼梦》，他说「走吧」——然后走了……",
    ]:
        print(f"  {raw}")
        print(f"    → {sanitize(raw)!r}")

    section("4. 长文本怎么切")
    text = "今天天气不错，我们出去走走吧。顺便买点菜回来，晚上做火锅。" * 30
    parts = split_text(text)
    print(f"  原文 {len(text)} 字 → {len(parts)} 段：" + "、".join(str(len(p)) for p in parts))
    print(f"  第一段：{parts[0][:40]}…")


async def live_demo(ref: str, dialect_word: str, out_dir: str) -> int:
    client = CosyVoiceClient(timeout=300, concurrency=1)
    info = await client.probe()
    section(f"接口 {info['base']}（{info['version']}，握手 {info['latency']:.1f}s）")
    print("  端点：" + "、".join(info["endpoints"]))

    os.makedirs(out_dir, exist_ok=True)
    ref_path, notes = normalize(ref, out_path=os.path.join(out_dir, "_ref_norm.wav"))
    meta = probe(ref_path) or {}
    print(f"  参考音频：{ref_path}｜{meta.get('seconds', 0):.1f}s｜{meta.get('sr')}Hz")
    if notes:
        print("  处理：" + "；".join(notes))

    t0 = time.time()
    prompt_text = await client.recognize(ref_path)
    print(f"  自动识别参考文字（{time.time() - t0:.1f}s）：{prompt_text or '(识别失败)'}")

    d = resolve(dialect_word) if dialect_word else resolve("四川")
    section(f"合成演示（{d.region if d else '标准'}）")
    for label, text, mode, instruct in [
        ("自然语言控制", d.sample if d else "今天的天气不错，我们出去走走吧。", MODE_INSTRUCT,
         build_instruct(d, "")),
        ("3s 极速复刻", "我也没别的意思，就是想问问你最近过得怎么样。", MODE_CLONE, ""),
    ]:
        t0 = time.time()
        try:
            data = await client.synthesize(
                text, ref_wav=ref_path, instruct=instruct, prompt_text=prompt_text, mode=mode
            )
        except CosyVoiceError as e:
            print(f"  {label} 失败：{e}")
            continue
        cost = time.time() - t0
        path = os.path.join(out_dir, f"demo_{mode}.wav")
        with open(path, "wb") as f:
            f.write(data)
        info2 = probe(path) or {}
        print(f"  {label}：{cost:.1f}s｜{info2.get('seconds', 0):.1f}s｜{len(data) // 1024}KB → {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="", help="参考音频路径；给了才会真的合成")
    ap.add_argument("--dialect", default="四川")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    local_demo()
    if not args.ref:
        print("\n（要真合成，加 --ref 你的参考音频.wav）")
        return 0
    return asyncio.run(live_demo(args.ref, args.dialect, args.out))


if __name__ == "__main__":
    sys.exit(main())
