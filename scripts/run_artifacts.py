# -*- coding: utf-8 -*-
"""run_artifacts.py — 单次渲染产物归属（issue #22，A8/A13）与输出目标占用（#23）

一次渲染 = 一个 run：由 (分镜文件字节, style, motion 开关) 确定性推导 run_key，
落到 `_build/runs/<slug>__<style>__<key>/`。该目录拥有本次运行的：

- preview/   本次预览截图 + overflow.json
- audio/     本次加工音轨（prepare_scene_audio 产物，随 hold/fps 变化）
- manifest.json  本次产物清单（verify 据此用「本次实际音轨集合」验收）

可共享的原始旁白 raw 不在这里——仍按旁白+音色指纹放 `_build/<slug>/`
（换皮复用、style 不参与指纹）。纯 stdlib，不依赖 make_video。

输出目标占用（#23）：worker 省略 output 时按 (分镜, 最终皮肤) 自动命名；
`acquire_target` 用 `<output>.lock`（O_EXCL + 心跳保活）保护同一目标不被
两个活动运行同时写，进程死亡后锁过期可接管。不删除历史成片。
"""

import hashlib
import json
import os
import re
import sys
import threading
import time
import uuid

MANIFEST_SCHEMA = 1

# 预览有效性印记（#26）：记录「本次预览对哪些输入有效」，供成片阶段决定复用
PREVIEW_STAMP_SCHEMA = 1

# 占用锁：心跳保活间隔与失效判定阈值（进程死后 ≤ 阈值秒可被接管）
LOCK_STALE_SECONDS = 60
LOCK_HEARTBEAT_SECONDS = 5


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


def preview_stamp_path(preview_dir):
    return os.path.join(preview_dir, "stamp.json")


def read_preview_stamp(preview_dir):
    """返回预览印记 dict；缺失或损坏返回 None。"""
    p = preview_stamp_path(preview_dir)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_preview_stamp(preview_dir, stamp):
    data = json.dumps(stamp, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_write_bytes(preview_stamp_path(preview_dir), data)


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


def default_output_name(slug, style_name):
    """worker 省略 output 时的自动成片名（#23）：绑定分镜主名 + 最终皮肤。

    皮肤名无需规范化时用 `output/<slug>__<style>.mp4`；被规范化改写过时
    追加皮肤名短指纹——不同皮肤（如 "a b" 与 "a_b"）不会映射到同一输出。
    """
    key = style_key_of(style_name)
    name = f"{slug}__{key}"
    if key != str(style_name):
        fp = hashlib.sha256(str(style_name).encode("utf-8")).hexdigest()[:8]
        name += f"-{fp}"
    return f"output/{name}.mp4"


class TargetOccupied(Exception):
    """目标正被活动运行占用（锁新鲜）。info 为锁文件内容（可能为空 dict）。"""

    def __init__(self, lock_path, info):
        self.lock_path = lock_path
        self.info = info or {}
        owner = self.info.get("pid", "?")
        started = self.info.get("started", "?")
        what = self.info.get("output", lock_path)
        super().__init__(
            f"{what} 正被活动运行占用（pid={owner} started={started}；锁 {lock_path}）。"
            f"等前一运行结束再试，或换一个显式 output。"
        )


def _read_lock(lock_path):
    try:
        with open(lock_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class _TargetLock:
    def __init__(self, lock_path, token):
        self.lock_path = lock_path
        self.token = token
        self._stop = threading.Event()
        self._beat = threading.Thread(target=self._heartbeat, daemon=True)
        self._beat.start()

    def _heartbeat(self):
        while not self._stop.wait(LOCK_HEARTBEAT_SECONDS):
            try:
                os.utime(self.lock_path, None)
            except OSError:
                return

    def release(self):
        self._stop.set()
        self._beat.join()
        try:
            info = _read_lock(self.lock_path)
            if info and info.get("token") == self.token:
                os.remove(self.lock_path)
        except OSError:
            pass


def acquire_target(output, storyboard="", style_name=""):
    """占用输出目标：O_EXCL 创建 `<output>.lock`（含 pid/token/started）。

    锁由心跳保活（mtime 每几秒刷新）；已存在的锁超过 LOCK_STALE_SECONDS
    无心跳视为失效并接管（打印接管说明），否则抛 TargetOccupied。
    """
    lock = f"{output}.lock"
    os.makedirs(os.path.dirname(os.path.abspath(lock)), exist_ok=True)
    for _ in range(2):
        token = uuid.uuid4().hex
        info = {
            "token": token,
            "pid": os.getpid(),
            "output": str(output),
            "storyboard": str(storyboard),
            "style": str(style_name),
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = time.time() - os.path.getmtime(lock)
            if age <= LOCK_STALE_SECONDS:
                raise TargetOccupied(lock, _read_lock(lock)) from None
            print(
                f"WARN: 目标占用锁已失效（{lock}，距最后心跳 {age:.0f}s），接管继续",
                file=sys.stderr,
            )
            try:
                os.remove(lock)
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False)
        return _TargetLock(lock, token)
    raise TargetOccupied(lock, _read_lock(lock))
