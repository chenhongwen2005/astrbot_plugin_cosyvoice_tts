"""文本清洗自测。

合成前要删两类「模型爱写、念出来一定出事」的东西：括号里的舞台提示，和表情符号。
这里逐条钉住边界——该删的删干净，不该动的（书名号、引号、箭头、℃）一点都别碰。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "_stub"))

from cosyvoice import sanitize, split_text, strip_brackets, strip_emoji, tidy  # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"[ok] {name}")
    else:
        print(f"[!!] {name} {detail}")
        FAILED.append(name)


def main() -> int:
    # ---------------- 括号 ----------------
    check("中文括号连内容删掉", strip_brackets("（小声）他说") == "他说")
    check("句中括号不粘标点", sanitize("他说（笑），走了") == "他说，走了")
    check("方头括号", strip_brackets("【旁白】开场") == "开场")
    check("半角圆括号", sanitize("(laugh) hello") == "hello", repr(sanitize("(laugh) hello")))
    check("半角方括号", strip_brackets("[停顿]") == "")
    check("直角/方角括号", strip_brackets("〔注〕正文〖附〗尾巴") == "正文尾巴")
    check("嵌套一起吞", strip_brackets("他（小声（几乎听不见））说") == "他说")
    check("未闭合且很短整段丢", strip_brackets("他笑了（笑") == "他笑了")
    check("未闭合但内容长则保留正文",
          strip_brackets("前面少了个右括号但后面还有一整句话没写完") ==
          "前面少了个右括号但后面还有一整句话没写完")
    long_unclosed = "他（这里忘了写右括号然后一直说下去说了很久很久才停下"
    check("长未闭合保留正文", strip_brackets(long_unclosed) == long_unclosed.replace("（", ""),
          strip_brackets(long_unclosed))
    check("孤立右括号删掉", strip_brackets("你好）世界") == "你好世界")
    check("括号里套括号但只在一边", strip_brackets("（甲（乙）") == "")
    check("书名号不动", strip_brackets("我读了《红楼梦》") == "我读了《红楼梦》")
    check("引号不动", strip_brackets("他说「走吧」") == "他说「走吧」")
    check("破折号省略号不动", strip_brackets("他——走了……") == "他——走了……")

    # ---------------- 表情 ----------------
    check("基本表情", strip_emoji("今天天气不错😊") == "今天天气不错")
    check("带变体选择符的心", strip_emoji("❤️好的") == "好的")
    check("零宽连接符一家三口", strip_emoji("👨‍👩‍👧一家") == "一家")
    check("旗帜序列", strip_emoji("🇨🇳中国") == "中国")
    check("装饰符号", strip_emoji("✅完成 ⭐好 ✨亮") == "完成 好 亮",
          repr(strip_emoji("✅完成 ⭐好 ✨亮")))
    check("箭头保留", strip_emoji("A→B") == "A→B")
    check("摄氏度保留", strip_emoji("25℃") == "25℃")
    check("商标符号保留", strip_emoji("AstrBot™") == "AstrBot™")

    check("表情删完剩空", sanitize("😊😊😊") == "")
    check("括号加表情", sanitize("（叹气）😮‍💨 算了") == "算了")
    check("表情后不留多余空格", sanitize("你好 😊 今天") == "你好今天",
          repr(sanitize("你好 😊 今天")))

    # ---------------- 收尾 ----------------
    check("重复标点压缩", tidy("你好，，世界") == "你好，世界")
    check("句末前的逗号删掉", tidy("他说什么，。") == "他说什么。")
    check("句末后的逗号删掉", tidy("好！，继续") == "好！继续")
    check("行首逗号删掉", tidy("，开头就跑偏") == "开头就跑偏")
    check("汉字间空格删掉", tidy("他说 走了") == "他说走了")
    check("英文空格保留", tidy("hello world") == "hello world")
    check("空行不留给模型", tidy("第一段\n\n\n\n第二段") == "第一段\n第二段",
          repr(tidy("第一段\n\n\n\n第二段")))
    check("括号删完接空行也收干净", sanitize("（笑）\n\n\n他说") == "他说")
    check("纯空白变空", tidy(" \n\t\u3000 ") == "")
    check("正常文本原样", sanitize("正常的一段话。没有任何需要删的东西！") ==
          "正常的一段话。没有任何需要删的东西！")

    # ---------------- 开关 ----------------
    check("关掉括号保留原样",
          sanitize("（小声）他说", brackets=False) == "（小声）他说")
    check("关掉表情保留原样",
          sanitize("你好😊", emoji=False) == "你好😊")
    check("都关掉等于原样",
          sanitize("（小声）你好😊", brackets=False, emoji=False) == "（小声）你好😊")

    # ---------------- 幂等 ----------------
    sample = "（小声）他说「我不知道」😮，然后（停顿）走了。"
    once = sanitize(sample)
    check("清洗幂等", sanitize(once) == once, f"{once!r} → {sanitize(once)!r}")

    # ---------------- 与切分配合 ----------------
    check("清洗后不影响切分", split_text(sanitize("（笑）今天天气不错。")) == ["今天天气不错。"])
    check("清成空则切出空列表", split_text(sanitize("（笑）😊")) == [])

    # ---------------- 真实场景 ----------------
    model_reply = (
        "（轻轻叹气）你说得对。😔\n\n"
        "我**建议**你先睡一觉（别熬太晚），明天再看这件事。"
    )
    got = sanitize(model_reply)
    check("模型回复里的旁白清掉", "叹气" not in got and "别熬太晚" not in got, repr(got))
    check("模型回复正文保留", "你说得对。" in got and "明天再看这件事。" in got, repr(got))
    check("模型回复里的表情清掉", "😔" not in got, repr(got))

    print()
    if FAILED:
        print(f"{len(FAILED)} 项失败：{FAILED}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
