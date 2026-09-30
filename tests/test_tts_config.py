"""tts_config.py：MiniMax 音色映射与 provider 决策。"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import tts_config as tc  # noqa: E402


def test_resolve_minimax_voice_maps_friendly_names():
    assert tc.resolve_minimax_voice("冰糖") == "Chinese (Mandarin)_Gentle_Senior"
    assert tc.resolve_minimax_voice("苏打") == "male-qn-qingse"


def test_resolve_minimax_voice_passthrough_platform_ids():
    assert (
        tc.resolve_minimax_voice("Chinese (Mandarin)_Gentleman")
        == "Chinese (Mandarin)_Gentleman"
    )
    assert tc.resolve_minimax_voice("male-qn-qingse") == "male-qn-qingse"
    assert (
        tc.resolve_minimax_voice("Cantonese_ProfessionalHost（F)")
        == "Cantonese_ProfessionalHost（F)"
    )


def test_resolve_minimax_voice_unknown_chinese_falls_back():
    # 未登记的中文友好名不得当 voice_id 直通
    assert tc.resolve_minimax_voice("未知音色") == "female-tianmei"


def test_resolve_tts_provider_priority():
    assert tc.resolve_tts_provider() == "xiaomi"
    assert tc.resolve_tts_provider(storyboard_provider="minimax") == "minimax"
    assert (
        tc.resolve_tts_provider(storyboard_provider="minimax", cli_provider="xiaomi")
        == "xiaomi"
    )
