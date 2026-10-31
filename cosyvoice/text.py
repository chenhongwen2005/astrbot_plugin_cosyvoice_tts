"""文本清洗与长文本切分。

合成之前先过一遍 `sanitize()`：把括号连同括号里的舞台提示去掉，把表情符号去掉，
再把删干净之后留下的空标点、空行、夹在汉字中间的空格收一收。这两步都是「删了不心疼」
的东西——CosyVoice 念「（小声）」只会念出「小声」两个字，念 😊 会直接不出声或者吐杂音。

`split_text()` 只负责按句切段，不做清洗；调用方应当先 `sanitize()` 再切。
"""

from __future__ import annotations

import re
from typing import Dict, List

from .const import MAX_TEXT, CosyVoiceError

_SENT_END = re.compile(r"(?<=[。！？!?；;…\n])")

# ----------------------------------------------------------------------
# 括号
# ----------------------------------------------------------------------

#: 开括号 → 闭括号。书名号《》不在表里：那是作品名，念出来是有意义的。
BRACKET_PAIRS: Dict[str, str] = {
    "（": "）",
    "(": ")",
    "【": "】",
    "[": "]",
    "〔": "〕",
    "［": "］",
    "｛": "｝",
    "{": "}",
    "〖": "〗",
    "〘": "〙",
    "〚": "〛",
    "〈": "〉",
}

_CLOSERS = set(BRACKET_PAIRS.values())

#: 未闭合的开括号，如果它后面一共只剩这么点内容，就当成「（笑」「（叹气」整段丢掉；
#: 超过这个长度说明是句正经话被少了右括号，只把括号符号删掉、内容留着。
UNCLOSED_TAIL = 12


def strip_brackets(text: str, *, unclosed_tail: int = UNCLOSED_TAIL) -> str:
    """删掉括号及括号内的内容，支持嵌套。

    - `（小声）他说` → `他说`
    - `他说（小声（几乎听不见））` → `他说`（嵌套一起吞）
    - `他说（笑` → `他说`（未闭合且只剩很短，整段丢）
    - `他（这里少了个右括号但后面还有一整句话没写完` → 保留内容、只删括号符号
    - `你好）` → 孤立的右括号直接删掉
    """
    s = text or ""
    if not s:
        return ""

    out: List[str] = []
    depth = 0
    swallowed: List[str] = []  # 当前未闭合段里被吞掉的非括号字符
    for ch in s:
        if ch in BRACKET_PAIRS:
            if depth == 0:
                swallowed = []
            depth += 1
            continue
        if ch in _CLOSERS:
            if depth == 0:
                continue  # 孤立右括号
            depth -= 1
            if depth == 0:
                swallowed = []
            continue
        if depth == 0:
            out.append(ch)
        else:
            swallowed.append(ch)

    if depth > 0 and len("".join(swallowed).strip()) > unclosed_tail:
        # 未闭合但内容不短：说明是真内容，吐回去（括号符号已经丢了）
        out.extend(swallowed)
    return "".join(out)


# ----------------------------------------------------------------------
# 表情符号
# ----------------------------------------------------------------------

#: emoji 的码位分布。不收 U+2190–U+21FF（箭头）与 U+2100 区（℃ ™ 等），
#: 那些在正文里有语义，删了反而怪。
_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # 表情、象形、交通、补充符号（😊 👍 🎉 🚀 …）
    "\U0001F1E6-\U0001F1FF"  # 区域指示符（🇨🇳 🇯🇵）
    "\u2600-\u27BF"          # 杂项符号与装饰符号（☀ ❤ ✨ ✅ ✈ ⚠）
    "\u2B00-\u2BFF"          # ⭐ ⬛ ⭕ ⬆
    "\u3030\u303D\u3297\u3299"  # 〰 〽 ㊗ ㊙
    "\u20E3"                 # 组合键帽（1️⃣）
    "\uFE00-\uFE0F"          # 变体选择符（❤️ 里的 FE0F）
    "\u200D"                 # 零宽连接符（👨‍👩‍👧 中间的胶水）
    "\U000E0020-\U000E007F"  # 标签字符（旗帜序列）
    "]+"
)

def strip_emoji(text: str) -> str:
    """删掉表情符号与它们的连接符。"""
    return _EMOJI.sub("", text or "")


# ----------------------------------------------------------------------
# 收尾
# ----------------------------------------------------------------------

_CJK = "\u3400-\u4dbf\u4e00-\u9fff"

_DUP_PUNCT = re.compile(r"([，、；：。！？,.!?;:])\1+")
_PUNCT_AFTER_END = re.compile(r"([。！？!?])[，、；：,;:]+")
_PUNCT_BEFORE_END = re.compile(r"[，、；：,;:]+(?=[。！？!?])")
_LINE_LEAD_PUNCT = re.compile(r"(?m)^[ \t\u3000]*[，、；：,;:]+[ \t\u3000]*")
_LINE_TAIL_PUNCT = re.compile(r"(?m)[ \t\u3000]*[，、；,;]+[ \t\u3000]*(?=\n|$)")
_SPACE_RUN = re.compile(r"[ \t\u00a0\u3000]{2,}")
_SPACE_IN_CJK = re.compile(rf"(?<=[{_CJK}])[ \t\u00a0\u3000]+(?=[{_CJK}])")
_BLANK_LINES = re.compile(r"\n{3,}")


def tidy(text: str) -> str:
    """删完之后收拾残局：空标点、空行、汉字中间的空格。"""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = _DUP_PUNCT.sub(r"\1", s)
    s = _PUNCT_AFTER_END.sub(r"\1", s)
    s = _PUNCT_BEFORE_END.sub("", s)
    s = _LINE_LEAD_PUNCT.sub("", s)
    s = _LINE_TAIL_PUNCT.sub("", s)
    s = _SPACE_IN_CJK.sub("", s)
    s = _SPACE_RUN.sub(" ", s)
    s = _BLANK_LINES.sub("\n\n", s)
    lines = [ln.strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def sanitize(
    text: str,
    *,
    brackets: bool = True,
    emoji: bool = True,
    unclosed_tail: int = UNCLOSED_TAIL,
) -> str:
    """合成前的统一清洗。两步都可单独关掉。"""
    s = text or ""
    if brackets:
        s = strip_brackets(s, unclosed_tail=unclosed_tail)
    if emoji:
        s = strip_emoji(s)
    return tidy(s)


def clean_report(raw: str, cleaned: str) -> str:
    """给日志/回复用的一句话摘要。"""
    dropped = len(raw or "") - len(cleaned or "")
    if dropped <= 0:
        return "未删减"
    return f"去掉 {dropped} 个字符"


# ----------------------------------------------------------------------
# 切分
# ----------------------------------------------------------------------


def split_text(text: str, limit: int = MAX_TEXT, max_parts: int = 4) -> List[str]:
    """按句切分，保证每段不超过 limit 字。

    段数超过 max_parts 时抛错——一句话把机器人卡住几十秒，不如直接告诉用户分开发。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    parts: List[str] = []
    cur = ""
    for seg in _SENT_END.split(text):
        if not seg:
            continue
        if len(seg) > limit:  # 单句超长，硬切
            if cur:
                parts.append(cur)
                cur = ""
            for i in range(0, len(seg), limit):
                parts.append(seg[i : i + limit])
            continue
        if len(cur) + len(seg) > limit and cur:
            parts.append(cur)
            cur = seg
        else:
            cur += seg
    if cur:
        parts.append(cur)

    if len(parts) > max_parts:
        raise CosyVoiceError(
            f"文本太长（{len(text)} 字，要合成 {len(parts)} 段）。"
            f"一次最多 {max_parts} 段，请分几条发。"
        )
    return parts
