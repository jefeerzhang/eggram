# -*- coding: utf-8 -*-
"""toolchain.py — 本机外部工具定位（纯 stdlib）

浏览器与 ffmpeg 在哪里。单独成模块的理由是依赖重量：make_video 导入
playwright/numpy 并在导入期解析 ffmpeg，而 preflight 只想找一个浏览器、
verify 只想量一个时长——它们不该为此拉起整条媒体管线。

导入本模块不碰任何重依赖；`ffmpeg_path()` 在首次调用时才惰性导入
imageio_ffmpeg。于是「找浏览器」这一步可以在没有 Chromium 之外任何东西的
环境里跑完。
"""

import os
import re
import shutil
import subprocess

_FFMPEG = None


def _candidate_browser_paths():
    """按优先级列出候选浏览器可执行路径（含显式 BROWSER_PATH/CHROME_PATH）。"""
    cands = []
    env = os.environ.get("BROWSER_PATH") or os.environ.get("CHROME_PATH")
    if env:
        cands.append(env)
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    cands += [
        os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    if local:
        cands += [
            os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local, "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
    for name in ("chrome", "google-chrome", "msedge", "chromium", "chromium-browser"):
        w = shutil.which(name)
        if w:
            cands.append(w)
    return [c for c in cands if c]


def browser_path(explicit=None):
    """解析浏览器路径：显式参数 > BROWSER_PATH/CHROME_PATH > 常见安装/PATH。

    返回可用路径，或 None（候选都不存在时）。preview 与成片共用同一结果。
    """
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        raise FileNotFoundError(f"指定浏览器不存在: {explicit}")
    for p in _candidate_browser_paths():
        if os.path.isfile(p):
            return p
    return None


def ffmpeg_path():
    """本机 ffmpeg 可执行文件路径（imageio_ffmpeg 自带，惰性解析并缓存）。

    惰性导入是刻意的：本模块要能在没装 imageio_ffmpeg 的环境里被导入，
    代价是首次调用才付。
    """
    global _FFMPEG
    if _FFMPEG is None:
        import imageio_ffmpeg

        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    return _FFMPEG


def media_duration(path):
    """通过 ffmpeg -i 解析 stderr 的 Duration 字段，返回秒；失败返回 None。"""
    try:
        r = subprocess.run(
            [ffmpeg_path(), "-i", path], capture_output=True, timeout=15
        )
        s = r.stderr.decode(errors="replace")
        m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}\.\d+)", s)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return None