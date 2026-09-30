# -*- coding: utf-8 -*-
"""tts_config.py — TTS 引擎配置与音色映射(纯 stdlib)

只承载配置常量,不依赖任何媒体/网络库。make_video / storyboard_gate / 任何
后续 provider 都从这里读 mapping 与默认参数。

为什么不放 env:
- MiniMax 的 voice_id 含空格、全角括号(如 "Cantonese_ProfessionalHost（F)"、
  "Santa_Claus " 末尾空格),通过 env 传递易踩 shell/JSON 转义坑;
- 用户的现有音色名(冰糖/苏打)是教学语义,不暴露给 API 层;
- 集中在一处便于补加新音色或换 provider。

新增音色:在 MINIMAX_VOICE_MAP 加一行(用户友好名 → MiniMax voice_id)。
完整 voice_id 见 https://platform.minimax.cn/docs/faq/system-voice-id
"""

import os


def _load_dotenv_once():
    """惰性补读 ROOT/.env,显式 env 优先。

    make_video.py 入口会调 storyboard_gate.load_env(),但 standalone 调用
    (如 .scratch/minimax_smoke.py)不会。本函数让 minimax_config() /
    resolve_tts_provider() 自给自足:模块被 import 时不读,只在
    minimax_config() 首次被调用时读一次。
    """
    if getattr(_load_dotenv_once, "_done", False):
        return
    _load_dotenv_once._done = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    if os.path.isfile(env_path):
        load_dotenv(env_path)


MINIMAX_VOICE_MAP = {
    # 用户友好名(分镜里继续用这个)         # MiniMax voice_id(平台原文)
    "冰糖": "Chinese (Mandarin)_Gentle_Senior",  # 温柔学姐
    "苏打": "male-qn-qingse",                     # 青涩青年音色
    "白桦": "Chinese (Mandarin)_Gentleman",       # 温润男声
    "茉莉": "female-tianmei",                     # 甜美女性音色
    "小新": "chunzhen_xuedi",                     # 纯真学弟(新增 · 活泼学生)
}


def _looks_like_minimax_voice_id(value):
    """判断字符串是否像 MiniMax 平台 voice_id（高级直通），而非中文友好名。

    平台 voice_id 总含 ASCII 字母，并常带 `_` / `-` / 空格 / 半角或全角括号
   （如 ``Chinese (Mandarin)_Gentle_Senior``、``Cantonese_ProfessionalHost（F)``）。
    纯中文友好名（如「冰糖」）不含 ASCII 字母，不应直通。
    """
    s = str(value).strip()
    if not s:
        return False
    has_ascii_letter = any("A" <= c <= "Z" or "a" <= c <= "z" for c in s)
    if not has_ascii_letter:
        return False
    allowed = set(" _-()（）")
    return all(
        ("A" <= c <= "Z")
        or ("a" <= c <= "z")
        or c.isdigit()
        or c in allowed
        for c in s
    )


def resolve_minimax_voice(friendly_name):
    """把分镜里的中文友好名映射成 MiniMax voice_id。

    映射表未命中时：若像平台 voice_id 原值则直通；否则回退默认音色。
    """
    if friendly_name in MINIMAX_VOICE_MAP:
        return MINIMAX_VOICE_MAP[friendly_name]
    if _looks_like_minimax_voice_id(friendly_name):
        return str(friendly_name).strip()
    # 兜底:甜美女性音色,中文教学最稳的默认值
    return "female-tianmei"


def minimax_config():
    """读 MiniMax 相关 env,带默认值。返回 dict。"""
    _load_dotenv_once()
    return {
        "url": os.environ.get(
            "MINIMAX_API_URL", "https://api.minimax.cn/v1/t2a_v2"
        ),
        "key": os.environ.get("MINIMAX_API_KEY", ""),
        "model": os.environ.get("MINIMAX_MODEL", "speech-2.8-hd"),
    }


def resolve_tts_provider(storyboard_provider=None, cli_provider=None):
    """决定本次渲染走哪家 TTS。

    优先级:CLI 参数 > 分镜顶层 tts_provider > 默认 xiaomi(向后兼容)。
    """
    if cli_provider:
        return cli_provider
    if storyboard_provider:
        return storyboard_provider
    return "xiaomi"


def is_provider(name):
    return name in ("xiaomi", "minimax")
