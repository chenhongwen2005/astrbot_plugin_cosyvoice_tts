"""长文本切分自测。

目标是：任何输入都不会让单次请求超过上限，也不会把一句完整的话从中间劈开（除非那句
本身超长），并且段数过多时明确报错而不是硬着头皮跑两分钟。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "_stub"))

from cosyvoice import MAX_TEXT, CosyVoiceError, split_text  # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"[ok] {name}")
    else:
        print(f"[!!] {name} {detail}")
        FAILED.append(name)


def main() -> int:
    check("空文本", split_text("") == [])
    check("空白文本", split_text("   \n ") == [])
    check("短句不分段", split_text("今天天气不错。") == ["今天天气不错。"])
    check("刚好到上限", split_text("啊" * MAX_TEXT) == ["啊" * MAX_TEXT])

    long_text = "第一句。第二句！第三句？" * 60
    parts = split_text(long_text)
    check("长文本有切分", len(parts) > 1, str(len(parts)))
    check("每段不超限", all(len(p) <= MAX_TEXT for p in parts),
          str([len(p) for p in parts]))
    check("拼回原文", "".join(parts) == long_text.strip())
    check("在句末切开", all(p.rstrip().endswith(("。", "！", "？")) for p in parts[:-1]),
          str([p[-3:] for p in parts[:-1]]))

    # 单句超长 → 硬切，不能抛错也不可超限
    huge = "啊" * (MAX_TEXT * 2 + 7)
    parts2 = split_text(huge)
    check("单句硬切", "".join(parts2) == huge)
    check("硬切后不超限", all(len(p) <= MAX_TEXT for p in parts2), str([len(p) for p in parts2]))

    # 段数超限 → 报错（2400 字以内还能挤进 4 段，再多就该拒绝）
    check("2400 字仍可合成", 1 < len(split_text("短句。" * 800)) <= 4)
    too_long = "短句。" * 900
    try:
        split_text(too_long)
        check("段数超限报错", False)
    except CosyVoiceError as e:
        check("段数超限报错", "太长" in str(e), str(e))
    except Exception as e:  # noqa: BLE001
        check("段数超限报错", False, repr(e))

    check("换行也当断句", len(split_text("第一行\n第二行\n" * 200)) > 1)

    print()
    if FAILED:
        print(f"{len(FAILED)} 项失败：{FAILED}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
