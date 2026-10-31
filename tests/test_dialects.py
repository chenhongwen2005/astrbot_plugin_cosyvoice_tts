"""方言表自测：别名解析、指令拼接、列表渲染。

覆盖的是「用户随便打一个词，能不能认出来」这件事——这是最容易在真实使用里翻车的地方。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "_stub"))

from cosyvoice import dialects as D  # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"[ok] {name}")
    else:
        print(f"[!!] {name} {detail}")
        FAILED.append(name)


def main() -> int:
    check("11 种方言", len(D.DIALECTS) == 11, str(len(D.DIALECTS)))
    names = [d.name for d in D.DIALECTS]
    expected = ["广东", "闽南", "四川", "东北", "陕西", "山西", "上海", "天津", "山东", "宁夏", "甘肃"]
    check("方言集合与需求一致", names == expected, str(names))

    # 规范名
    for n in names:
        check(f"规范名 {n}", D.resolve(n) is not None and D.resolve(n).name == n)

    cases = {
        "四川话": "四川",
        "成都话": "四川",
        "重庆话": "四川",
        "川渝": "四川",
        "粤语": "广东",
        "广东话": "广东",
        "香港话": "广东",
        "闽南语": "闽南",
        "台语": "闽南",
        "东北腔": "东北",
        "西安话": "陕西",
        "太原话": "山西",
        "沪语": "上海",
        "吴语": "上海",
        "天津腔": "天津",
        "青岛话": "山东",
        "银川话": "宁夏",
        "兰州话": "甘肃",
        "四川方言": "四川",
        "广东语": "广东",
    }
    for word, want in cases.items():
        got = D.resolve(word)
        check(f"别名 {word} → {want}", got is not None and got.name == want,
              "None" if got is None else got.name)

    check("关 → None", D.resolve("关") is None)
    check("普通话 → None", D.resolve("普通话") is None)
    check("关闭方言 → None", D.resolve("关闭方言") is None)

    try:
        D.resolve("火星话")
        check("未知识别报错", False)
    except KeyError:
        check("未知识别报错", True)
    except Exception as e:  # noqa: BLE001
        check("未知识别报错", False, repr(e))

    # 指令拼接
    sc = D.BY_NAME["四川"]
    check("纯方言指令", D.build_instruct(sc) == "用四川话说这句话。", D.build_instruct(sc))
    check("方言+修饰", D.build_instruct(sc, "语速慢一点") == "用四川话说这句话，语速慢一点。",
          D.build_instruct(sc, "语速慢一点"))
    check("只在修饰", D.build_instruct(None, "语速慢一点") == "语速慢一点。", D.build_instruct(None, "语速慢一点"))
    check("都没有", D.build_instruct(None, "") == "", repr(D.build_instruct(None, "")))
    check("尾巴句号不重复", D.build_instruct(sc, "语速慢一点。").count("。") == 1,
          D.build_instruct(sc, "语速慢一点。"))

    for d in D.DIALECTS:
        check(f"{d.name} 指令完整", d.instructs[0].endswith("。") and "说这句话" in d.instructs[0],
              d.instructs[0])
        check(f"{d.name} 有示例台词", bool(d.sample.strip()))
        check(f"{d.name} 有地区说明", bool(d.region.strip()))

    body = D.table_lines("四川")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    check("列表 11 行", len(lines) == 11, str(len(lines)))
    check("当前方言有标记", any(ln.startswith("▶ 四川") for ln in lines))

    print()
    if FAILED:
        print(f"{len(FAILED)} 项失败：{FAILED}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
