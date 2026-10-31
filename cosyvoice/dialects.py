"""11 种方言的指令表。

CosyVoice2 的「自然语言控制」模式靠一句 instruct 文本切方言，官方输入框里的
示例就是「用四川话说这句话。」——所以这里每种方言给出的主指令都照这个句式，
保证和模型训练时的分布一致；备选指令只在用户要「更土一点」时用。

音色不在这里管：instruct 只决定「怎么说」，参考音频才决定「谁在说」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Dialect:
    name: str  #: 规范名，也是 /语音 方言 的取值
    region: str  #: 地区说明，写进帮助与提示
    aliases: Tuple[str, ...]  #: 别名，用来匹配用户输入
    instructs: Tuple[str, ...]  #: 交给模型的指令，第一条为主用
    sample: str  #: 该方言的示例台词，供 /语音 示例 使用
    note: str = ""  #: 一句口语提示


#: /语音 方言 关 时使用。关掉方言 = 不再给 instruct，直接复刻参考音色
OFF_WORDS = {"关", "关闭", "无", "标准", "普通话", "标准话", "关闭方言"}

DIALECTS: Tuple[Dialect, ...] = (
    Dialect(
        name="广东",
        region="粤语（广州话）",
        aliases=("广东", "广东话", "粤语", "白话", "广州话", "广府话", "香港话"),
        instructs=("用粤语说这句话。", "用广东话说这句话。"),
        sample="今晚去边度食饭啊？我请客。",
        note="粤语和普通话差异最大，参考音频说得越标准，切换越稳",
    ),
    Dialect(
        name="闽南",
        region="闽南语（泉州—厦门腔）",
        aliases=("闽南", "闽南话", "闽南语", "台语", "福建话", "厦门话", "泉州话", "台湾话"),
        instructs=("用闽南话说这句话。", "用闽南语说这句话。"),
        sample="今仔日天气真好，咱来去海边行行。",
        note="文白异读多，长句容易被拉回普通话，短句效果更好",
    ),
    Dialect(
        name="四川",
        region="西南官话（成渝片）",
        aliases=("四川", "四川话", "川话", "川普", "成都话", "重庆话", "川渝", "西南官话"),
        instructs=("用四川话说这句话。", "用四川方言说这句话。"),
        sample="你今天咋个了嘛，脸色不大对头哦。",
        note="重庆话、成都话都归到这里；要区分口音可在指令里补「重庆口音」",
    ),
    Dialect(
        name="东北",
        region="东北官话",
        aliases=("东北", "东北话", "东北腔", "东北方言", "辽宁话", "吉林话", "黑龙江话"),
        instructs=("用东北话说这句话。", "用东北方言说这句话。"),
        sample="哎呀妈呀，这天儿贼冷，赶紧进屋暖和暖和。",
        note="语调起伏大，情绪类台词辨识度最高",
    ),
    Dialect(
        name="陕西",
        region="中原官话（关中片）",
        aliases=("陕西", "陕西话", "陕西方言", "西安话", "关中话", "秦腔"),
        instructs=("用陕西话说这句话。", "用陕西方言说这句话。"),
        sample="你吃咧么？没吃咱一搭儿去吃泡馍。",
        note="西安话为准；陕北话是晋语，不在这个范围内",
    ),
    Dialect(
        name="山西",
        region="晋语（并州片）",
        aliases=("山西", "山西话", "山西方言", "太原话", "晋语", "晋中话"),
        instructs=("用山西话说这句话。", "用山西方言说这句话。"),
        sample="你咋介个样子咧，赶紧回家吃饭哇。",
        note="入声保留，句中停顿比普通话多，慢速台词更像",
    ),
    Dialect(
        name="上海",
        region="吴语（太湖片上海小片）",
        aliases=("上海", "上海话", "上海方言", "沪语", "吴语", "苏州话"),
        instructs=("用上海话说这句话。", "用上海方言说这句话。"),
        sample="侬今朝夜到有空伐？一道去吃夜饭。",
        note="浊音多，参考音频若是女声，切上海话相对更稳",
    ),
    Dialect(
        name="天津",
        region="冀鲁官话（天津小片）",
        aliases=("天津", "天津话", "天津方言", "天津腔"),
        instructs=("用天津话说这句话。", "用天津方言说这句话。"),
        sample="姐姐，您介是干嘛去呀？捎我一段呗。",
        note="相声腔和日常腔差别不小，可在指令里补「别太夸张」",
    ),
    Dialect(
        name="山东",
        region="冀鲁官话 / 胶辽官话",
        aliases=("山东", "山东话", "山东方言", "济南话", "青岛话", "鲁语"),
        instructs=("用山东话说这句话。", "用山东方言说这句话。"),
        sample="你咋才来咧？俺都等你半天了。",
        note="济南腔与青岛腔差异明显，默认按济南腔走",
    ),
    Dialect(
        name="宁夏",
        region="兰银官话（银吴片）",
        aliases=("宁夏", "宁夏话", "宁夏方言", "银川话", "兰银官话"),
        instructs=("用宁夏话说这句话。", "用宁夏方言说这句话。"),
        sample="你吃了吗？咱一块儿走撒。",
        note="和甘肃话同属兰银官话，两者的差别比和普通话小得多",
    ),
    Dialect(
        name="甘肃",
        region="兰银官话（金城片）",
        aliases=("甘肃", "甘肃话", "甘肃方言", "兰州话", "陇语"),
        instructs=("用甘肃话说这句话。", "用甘肃方言说这句话。"),
        sample="你咋咧？脸咋这么红着哩。",
        note="兰州腔为准；河西走廊一带口音更接近普通话",
    ),
)

BY_NAME = {d.name: d for d in DIALECTS}


def resolve(word: str) -> Optional[Dialect]:
    """把用户输入（含别名）解析成方言；`关` 之类返回 None 表示关闭方言。

    无法识别时抛 KeyError，由调用方给出可用列表。
    """
    raw = (word or "").strip()
    if not raw:
        raise KeyError(raw)
    if raw in OFF_WORDS:
        return None
    if raw in BY_NAME:
        return BY_NAME[raw]
    for d in DIALECTS:
        if raw in d.aliases:
            return d
    # 再退一步：去掉「方言 / 话 / 语」后缀再匹配，处理「四川方言」「广东语」这类输入
    for suffix in ("方言", "话", "语"):
        if raw.endswith(suffix):
            stem = raw[: -len(suffix)].strip()
            if stem in BY_NAME:
                return BY_NAME[stem]
            for d in DIALECTS:
                if stem in d.aliases:
                    return d
    raise KeyError(raw)


def build_instruct(dialect: Optional[Dialect], extra: str = "") -> str:
    """拼出最终 instruct 文本。

    - 只有方言：`用四川话说这句话。`
    - 方言 + 修饰：`用四川话说这句话，语气冷一点。`
    - 只有修饰：直接用修饰本身（用户写的就是完整指令）
    - 都没有：空串，等同于纯音色复刻
    """
    extra = (extra or "").strip().rstrip("。.！!")
    if dialect is None:
        return extra + "。" if extra else ""
    base = dialect.instructs[0].rstrip("。")
    if extra:
        return f"{base}，{extra}。"
    return base + "。"


def table_lines(current: Optional[str] = None) -> str:
    """`/语音 方言` 的列表文本。列宽按实际内容算，东亚字符按 2 计。"""
    w_name = max(_w(d.name) for d in DIALECTS)
    w_region = max(_w(d.region) for d in DIALECTS)
    out = []
    for d in DIALECTS:
        mark = "▶" if current == d.name else "·"
        out.append(
            f"{mark} {_ljust(d.name, w_name)}  {_ljust(d.region, w_region)}  {d.note}"
        )
    return "\n".join(out)


def _w(s: str) -> int:
    """显示宽度：CJK 与全角符号算 2。"""
    n = 0
    for ch in s:
        n += 2 if ("\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f"
                   or "\uff00" <= ch <= "\uffef") else 1
    return n


def _ljust(s: str, width: int) -> str:
    return s + " " * max(0, width - _w(s))
