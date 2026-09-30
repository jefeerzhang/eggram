# -*- coding: utf-8 -*-
"""audio_cache.py — 原始旁白缓存的命名与命中契约（纯 stdlib）

渲染器写缓存、验收核对缓存，两边必须对「哪个文件、算不算命中」用同一套规则。
契约单独成模块，是因为它决定了验收是否真的独立：verify 若为了核对缓存而导入
媒体管线，渲染器命名逻辑里的 bug 会让 verify 与它一致地错，独立验收就失去意义。
本模块只依赖 stdlib 与 run_artifacts（原子写入），不含 TTS、ffmpeg 或 numpy。
"""

import hashlib
import json
import os

import run_artifacts as ra

# 音频缓存解码版本。错误解码路径生成的旧 raw 无此版本号，缓存不命中。
# v3：缓存指纹加 provider 维度，小米/MiniMax 两套 TTS 互不污染。
CACHE_VERSION = "3"


def fingerprint(narrate, voice, provider="xiaomi"):
    """8 字符内容指纹。provider/voice/narrate 任一变化 → 路径变化 → 缓存失效。"""
    return hashlib.sha256(f"{provider}|{voice}|{narrate}".encode()).hexdigest()[:8]


def paths(cache_dir, i, narrate, voice, provider="xiaomi"):
    """本次旁白的 (raw 下载件, 加工件) 路径。"""
    fp = fingerprint(narrate, voice, provider)
    return (
        os.path.join(cache_dir, f"s{i}_{fp}_raw.wav"),
        os.path.join(cache_dir, f"s{i}_{fp}.wav"),
    )


def meta_path(raw_path):
    """raw 的 sidecar 元数据路径（版本/音色/旁白/指纹）。"""
    return raw_path + ".meta.json"


def write_meta(raw_path, voice, narrate, rate, provider="xiaomi"):
    meta = {
        "ver": CACHE_VERSION,
        "provider": provider,
        "voice": voice,
        "narrate": narrate,
        "rate": rate,
        "fp": fingerprint(narrate, voice, provider),
    }
    ra.atomic_write_bytes(
        meta_path(raw_path),
        json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def is_hit(raw_path, voice, narrate, provider="xiaomi"):
    """raw 存在 + sidecar meta 与旁白/音色/provider 一致且为当前解码版本才命中。

    两侧都查：只有 meta 而 raw 缺失（手工清理、写到一半）时若算命中，
    渲染器随后会拿着不存在的路径去解码，报的却是解码错误。
    """
    if not os.path.isfile(raw_path):
        return False
    p = meta_path(raw_path)
    if not os.path.isfile(p):
        return False
    try:
        with open(p, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return False
    return (
        meta.get("ver") == CACHE_VERSION
        and meta.get("provider", "xiaomi") == provider
        and meta.get("voice") == voice
        and meta.get("narrate") == narrate
        and meta.get("fp") == fingerprint(narrate, voice, provider)
    )
