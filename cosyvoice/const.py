"""常量与错误类型。

这里只放不随运行环境变化的值；地址、超时等可调项都走配置。
"""

from __future__ import annotations

VERSION = "1.0.0"

#: ModelScope 上的 CosyVoice2 创空间页面（给人看的）
STUDIO_PAGE = "https://www.modelscope.cn/studios/iic/CosyVoice2-0.5B"

#: Gradio 应用地址。注意是 `.ms.show` 这个网关域名，不是 studiodetail 页
DEFAULT_BASE = "https://iic-cosyvoice2-0-5b.ms.show/"

#: ModelScope 的 acw 网关按 UA 拦人：非浏览器 UA 一律 403，
#: 连 /config 都取不到。gradio_client 报 "Could not fetch config" 就是这个原因。
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

#: 界面上「选择推理模式」的两个取值，必须逐字一致
MODE_INSTRUCT = "自然语言控制"
MODE_CLONE = "3s极速复刻"

#: 单次合成的字数上限。超过这个长度接口会明显变慢，且更容易被网关掐断
MAX_TEXT = 600

#: 参考音频长度区间（秒）。官方提示「不超过 30s」
MAX_REF_SEC = 30.0
MIN_REF_SEC = 0.8

#: 参考音频采样率要求「不低于 16kHz」，低于就补采样
TARGET_SR = 16000


class CosyVoiceError(RuntimeError):
    """接口层的可读错误。消息直接展示给用户，所以要说人话。"""


class QueueFull(CosyVoiceError):
    """创空间排队满了（503 / queue_full），等一会儿重试即可。"""
