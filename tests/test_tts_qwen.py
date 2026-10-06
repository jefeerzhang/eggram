"""Qwen-Audio-TTS(DashScope 百炼) provider 契约。

不依赖网络：urlopen 被替换成最小替身，只验证"发出去的请求"与"拿回来的字节"。
真实音频格式（单声道 / 24000Hz / 16bit）已由一次冒烟核实，见
docs/notes/tts-model-survey-2026.md。
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import make_video as mv  # noqa: E402
import tts_config as tc  # noqa: E402


# ---- tts_config：provider 与音色解析 ----


def test_is_provider_accepts_qwen():
    assert tc.is_provider("qwen")
    assert tc.is_provider("xiaomi")
    assert tc.is_provider("minimax")
    assert not tc.is_provider("nope")


def test_resolve_qwen_voice_maps_friendly_names():
    # 分镜里同一批教学友好名，在 Qwen 下解析到 Qwen 的系统音色
    assert tc.resolve_qwen_voice("冰糖") == "longanlingxin"
    assert tc.resolve_qwen_voice("苏打") == "longanlufeng"


def test_resolve_qwen_voice_passthrough_platform_ids():
    assert tc.resolve_qwen_voice("longanlingxin") == "longanlingxin"
    assert tc.resolve_qwen_voice("longanhuan_v3.6") == "longanhuan_v3.6"
    assert (
        tc.resolve_qwen_voice("qwen-audio-3.0-tts-plus-male_01")
        == "qwen-audio-3.0-tts-plus-male_01"
    )


def test_resolve_qwen_voice_unknown_chinese_falls_back():
    # 未登记的中文友好名不得当 voice_id 直通
    assert tc.resolve_qwen_voice("未知音色") == tc.QWEN_DEFAULT_VOICE


def test_qwen_config_reads_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.delenv("QWEN_TTS_MODEL", raising=False)
    cfg = tc.qwen_config()
    assert cfg["key"] == "sk-test"
    assert cfg["model"] == "qwen-audio-3.0-tts-plus"
    assert cfg["url"].endswith("/api/v1/services/audio/tts/SpeechSynthesizer")


# ---- make_video：请求构造与分派 ----


class _FakeResp:
    """urlopen 的最小替身：只用到上下文管理与 read()。"""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


def test_qwen_tts_posts_to_speech_synthesizer_and_downloads_audio(monkeypatch):
    wav = b"RIFF\x00\x00\x00\x00WAVEfake"
    seen = {}

    def fake_urlopen(req, timeout=60):
        if isinstance(req, str):  # 第二步：GET 音频 URL
            seen["download"] = req
            return _FakeResp(wav)
        seen["post_url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(
            json.dumps(
                {
                    "output": {
                        "audio": {"url": "https://oss.example/a.wav", "data": ""}
                    },
                    "request_id": "rid-1",
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(mv.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")

    assert mv.qwen_tts("现在完成时的用法", "冰糖") == wav

    assert seen["post_url"] == (
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
    )
    assert seen["auth"] == "Bearer sk-test"
    assert seen["download"] == "https://oss.example/a.wav"
    body = seen["body"]
    assert body["model"] == "qwen-audio-3.0-tts-plus"
    assert body["input"]["text"] == "现在完成时的用法"
    assert body["input"]["voice"] == "longanlingxin"
    assert body["input"]["format"] == "wav"
    assert body["input"]["sample_rate"] == mv.SAMPLE_RATE


def test_qwen_tts_requires_api_key(monkeypatch):
    """缺 Key 应立刻报错，而不是发一次注定失败的请求。"""
    monkeypatch.setattr(tc, "_load_dotenv_once", lambda: None)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(
        mv.urllib.request, "urlopen", lambda *a, **k: pytest.fail("不应发起网络请求")
    )
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        mv.qwen_tts("句子", "冰糖")


def test_synthesize_dispatches_qwen(monkeypatch):
    calls = []

    def fake(text, voice):
        calls.append((text, voice))
        return b"WAV"

    monkeypatch.setattr(mv, "qwen_tts", fake)
    assert mv.synthesize("句子", "冰糖", "qwen") == b"WAV"
    assert calls == [("句子", "冰糖")]


# ---- provider 集合的单一事实源 ----


def test_providers_constant_covers_is_provider():
    assert set(tc.PROVIDERS) == {"xiaomi", "minimax", "qwen"}
    for name in tc.PROVIDERS:
        assert tc.is_provider(name)


def test_cli_tts_provider_choices_track_providers_constant():
    """两处 argparse 的 --tts-provider 可选值须与 PROVIDERS 同源。

    回归点：曾各自硬编码 ("xiaomi","minimax")，于是新增 provider 时
    is_provider 与闸门放行、CLI 却先拒，可用集自相矛盾。
    """
    import subprocess

    want = "{" + ",".join(tc.PROVIDERS) + "}"
    for script in ("scripts/make_video.py", "scripts/render_worker.py"):
        out = subprocess.run(
            [sys.executable, os.path.join(ROOT, script), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert want in out.stdout, (script, want, out.stdout, out.stderr)
