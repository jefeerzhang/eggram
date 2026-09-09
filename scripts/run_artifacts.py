# -*- coding: utf-8 -*-
"""run_artifacts.py — 单次渲染产物归属（issue #22，A8/A13）

一次渲染 = 一个 run：由 (分镜文件字节, style, motion 开关) 确定性推导 run_key，
落到 `_build/runs/<slug>__<style>__<key>/`。该目录拥有本次运行的：

- preview/   本次预览截图 + overflow.json
- audio/     本次加工音轨（prepare_scene_audio 产物，随 hold/fps 变化）
- manifest.json  本次产物清单（verify 据此用「本次实际音轨集合」验收）

可共享的原始旁白 raw 不在这里——仍按旁白+音色指纹放 `_build/<slug>/`
（换皮复用、style 不参与指纹）。纯 stdlib，不依赖 make_video。
"""

import hashlib
import json
import os
import re
import time
import uuid

MANIFEST_SCHEMA = 1


def style_key_of(style_name):
    """目录名用的 style 标识（与 render_worker 历史口径一致）。"""
    return re.sub(r"[^\w.-]", "_", str(style_name))


def run_key(storyboard_path, style_name, motion_enabled):
    """确定性 run 标识：同文件+同配置 → 同 key（verify 可精确重定位）；
    来源不同、style 不同、motion 开关不同 → 不同 key（并行互不覆盖）。"""
    h = hashlib.sha256()
    with open(storyboard_path, "rb") as f:
        h.update(f.read())
    h.update(b"\0" + str(style_name).encode("utf-8"))
    h.update(b"\0" + (b"motion-on" if motion_enabled else b"motion-off"))
    return h.hexdigest()[:10]


def run_dir(root, slug, style_name, key):
    return os.path.join(root, "_build", "runs", f"{slug}__{style_key_of(style_name)}__{key}")


def preview_dir(rdir):
    return os.path.join(rdir, "preview")


def audio_dir(rdir):
    return os.path.join(rdir, "audio")


def scene_wav(rdir, i, fp):
    return os.path.join(audio_dir(rdir), f"s{i}_{fp}.wav")


def manifest_path(rdir):
    return os.path.join(rdir, "manifest.json")


def atomic_write_bytes(path, data):
    """临时文件 + os.replace 原子落位；Windows 目标被短暂持句柄时退避重试。

    tmp 名含 uuid：同进程多线程并行写同一路径时互不踩（make_video 渲染线程
    与并行 worker 同理）。
    """
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.2 * (attempt + 1))
        raise RuntimeError(f"原子替换失败（目标被长期占用）: {path}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def write_manifest(rdir, manifest):
    data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_write_bytes(manifest_path(rdir), data)


def read_manifest(rdir):
    """返回 manifest dict；不存在或损坏返回 None（调用方决定回退/失败）。"""
    p = manifest_path(rdir)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
