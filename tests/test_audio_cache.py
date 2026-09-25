"""audio_cache.py 单元测试：原始旁白缓存的命名与命中契约。

契约单独成模块的理由是验收独立性——渲染器与 verify 共用同一条判据。
这里不需要 TTS、浏览器或 ffmpeg。
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import audio_cache as ac  # noqa: E402


def test_fingerprint_tracks_voice_and_narrate():
    assert ac.fingerprint("旁白", "苏打") == ac.fingerprint("旁白", "苏打")
    assert ac.fingerprint("旁白", "苏打") != ac.fingerprint("旁白2", "苏打")
    assert ac.fingerprint("旁白", "苏打") != ac.fingerprint("旁白", "冰糖")
    assert len(ac.fingerprint("旁白", "苏打")) == 8


def test_paths_are_distinct_and_carry_the_fingerprint():
    raw, wav = ac.paths("d", 3, "旁白", "苏打")
    assert raw.endswith("_raw.wav") and wav.endswith(".wav")
    assert raw != wav
    assert ac.fingerprint("旁白", "苏打") in raw
    assert raw.startswith(os.path.join("d", "s3_"))


def test_meta_roundtrip_fields():
    with tempfile.TemporaryDirectory() as d:
        raw, _ = ac.paths(d, 0, "旁白", "苏打")
        ac.write_meta(raw, "苏打", "旁白", 24000)
        meta = json.load(open(ac.meta_path(raw), encoding="utf-8"))
        assert meta["ver"] == ac.CACHE_VERSION
        assert meta["voice"] == "苏打" and meta["narrate"] == "旁白"
        assert meta["rate"] == 24000
        assert meta["fp"] == ac.fingerprint("旁白", "苏打")


def test_hit_requires_both_raw_and_meta():
    with tempfile.TemporaryDirectory() as d:
        raw, _ = ac.paths(d, 0, "旁白", "苏打")
        assert ac.is_hit(raw, "苏打", "旁白") is False  # 两者都缺
        with open(raw, "wb") as f:
            f.write(b"\0\0")
        assert ac.is_hit(raw, "苏打", "旁白") is False  # 有 raw 无 meta
        ac.write_meta(raw, "苏打", "旁白", 24000)
        assert ac.is_hit(raw, "苏打", "旁白") is True


def test_hit_rejects_mismatched_voice_or_narrate():
    with tempfile.TemporaryDirectory() as d:
        raw, _ = ac.paths(d, 0, "旁白", "苏打")
        with open(raw, "wb") as f:
            f.write(b"\0\0")
        ac.write_meta(raw, "苏打", "旁白", 24000)
        assert ac.is_hit(raw, "冰糖", "旁白") is False
        assert ac.is_hit(raw, "苏打", "换了旁白") is False


def test_hit_rejects_other_decode_version():
    with tempfile.TemporaryDirectory() as d:
        raw, _ = ac.paths(d, 0, "旁白", "苏打")
        with open(raw, "wb") as f:
            f.write(b"\0\0")
        ac.write_meta(raw, "苏打", "旁白", 24000)
        p = ac.meta_path(raw)
        meta = json.load(open(p, encoding="utf-8"))
        meta["ver"] = "old"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        assert ac.is_hit(raw, "苏打", "旁白") is False


def test_hit_survives_corrupt_meta():
    with tempfile.TemporaryDirectory() as d:
        raw, _ = ac.paths(d, 0, "旁白", "苏打")
        with open(raw, "wb") as f:
            f.write(b"\0\0")
        with open(ac.meta_path(raw), "w", encoding="utf-8") as f:
            f.write("{ 不是 json")
        assert ac.is_hit(raw, "苏打", "旁白") is False