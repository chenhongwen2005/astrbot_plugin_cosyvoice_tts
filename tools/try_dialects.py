"""真机批量试听：拿一段参考音频，把 11 种方言各合成一遍。

    python tools/try_dialects.py --ref path/to/ref.wav
    python tools/try_dialects.py --ref ref.wav --dialect 四川 广东 --text "自定义台词"
    python tools/try_dialects.py --ref ref.wav --clone       # 走 3s 极速复刻
    python tools/try_dialects.py --check                    # 只探活，不合成

产物落在 `out/<方言>.wav`，同时打印耗时、时长、采样率。要判断方言像不像，只能自己听。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from cosyvoice import (  # noqa: E402
    DIALECTS,
    MODE_CLONE,
    MODE_INSTRUCT,
    CosyVoiceClient,
    CosyVoiceError,
    build_instruct,
    normalize,
    probe,
    resolve,
)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", help="参考音频路径（16kHz 以上）")
    ap.add_argument("--text", default="", help="要合成的文本，默认用各地方言自带示例")
    ap.add_argument("--dialect", nargs="*", default=[], help="只跑指定方言")
    ap.add_argument("--base", default="", help="自定义创空间地址")
    ap.add_argument("--clone", action="store_true", help="用 3s 极速复刻模式")
    ap.add_argument("--instruct", default="", help="附加指令，如「语速慢一点」")
    ap.add_argument("--out", default="out", help="输出目录")
    ap.add_argument("--check", action="store_true", help="只探活")
    args = ap.parse_args()

    client = CosyVoiceClient(args.base or None, timeout=300, concurrency=1)
    info = await client.probe()
    print(f"接口 {info['base']}｜版本 {info['version']}｜握手 {info['latency']:.1f}s")
    print("端点：" + "、".join(info["endpoints"]))
    if args.check:
        return 0
    if not args.ref:
        print("需要 --ref 指定参考音频")
        return 2

    os.makedirs(args.out, exist_ok=True)
    ref, notes = normalize(args.ref, out_path=os.path.join(args.out, "_ref_norm.wav"))
    meta = probe(ref) or {}
    print(f"参考音频 {ref}｜{meta.get('seconds', 0):.1f}s｜{meta.get('sr')}Hz")
    if notes:
        print("  处理：" + "；".join(notes))

    prompt_text = ""
    if args.clone:
        t0 = time.time()
        prompt_text = await client.recognize(ref)
        print(f"参考文字（{time.time() - t0:.1f}s）：{prompt_text!r}")
        if not prompt_text:
            print("识别不出参考文字，复刻模式可能效果很差")

    wanted = [resolve(w) for w in args.dialect] if args.dialect else list(DIALECTS)
    ok = 0
    for d in wanted:
        text = args.text or d.sample
        instruct = build_instruct(d, args.instruct) if not args.clone else ""
        mode = MODE_CLONE if args.clone else MODE_INSTRUCT
        tag = d.name if d else "标准"
        t0 = time.time()
        try:
            data = await client.synthesize(
                text, ref_wav=ref, instruct=instruct, prompt_text=prompt_text, mode=mode
            )
        except CosyVoiceError as e:
            print(f"  {tag:4s} 失败：{e}")
            continue
        cost = time.time() - t0
        path = os.path.join(args.out, f"{tag}.wav")
        with open(path, "wb") as f:
            f.write(data)
        info2 = probe(path) or {}
        ok += 1
        print(
            f"  {tag:4s} {cost:5.1f}s  {info2.get('seconds', 0):5.1f}s  "
            f"{len(data) // 1024:4d}KB  {instruct or '(复刻)'}  → {path}"
        )
    print(f"\n完成 {ok}/{len(wanted)}，产物在 {os.path.abspath(args.out)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
