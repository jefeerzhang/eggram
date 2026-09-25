# -*- coding: utf-8 -*-
"""run_artifacts.py — 单次渲染产物归属（issue #22，A8/A13）与输出目标命名（#23）

一次渲染 = 一个 run：由 (分镜文件字节, style, motion 开关, templates/ 内容) 确定性
推导 run_key，落到 `_build/runs/<slug>__<style>__<key>/`。该目录拥有本次运行的：

- preview/   本次预览截图 + overflow.json
- audio/     本次加工音轨（prepare_scene_audio 产物，随 hold/fps 变化）
- manifest.json  本次产物清单（verify 据此用「本次实际音轨集合」验收）

可共享的原始旁白 raw 不在这里——仍按旁白+音色指纹放 `_build/<slug>/`
（换皮复用、style 不参与指纹）。纯 stdlib，不依赖 make_video。

输出目标命名（#23）：worker 省略 output 时按 (分镜, 最终皮肤) 自动命名，
同分镜多皮肤并行各得一个成片。不删除历史成片。
"""

import hashlib
import json
import os
import re
import time
import uuid

MANIFEST_SCHEMA = 1

# 仓库根：templates/ 与 _build/ 都挂在它下面。默认由本文件位置推出，
# 使 run_key 在「真实仓库」与「测试里复制出来的 project」下都解析到自己的模板。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIRNAME = "templates"


def style_key_of(style_name):
    """目录名用的 style 标识（与 render_worker 历史口径一致）。"""
    return re.sub(r"[^\w.-]", "_", str(style_name))


def render_inputs_digest(h, root=None):
    """把 templates/ 的内容并入 run 标识（layout-*.html 与 style-*.json 都在其中）。

    画面同时取决于分镜字节和模板/皮肤文件，而后者不在分镜里。只按分镜定 key 时，
    改模板或换皮文件内容后 run_key 不变，`--skip-preview` 会复用按旧模板验过的
    预览——正是 #26 AC3 要拦的「过期成功结果」。故一并入 key。

    整目录入 key 是保守做法：多算一个本次没用到的模板只会让 run 多失效一次，
    不会漏失效；反过来漏失效才是本函数要防的。
    """
    tdir = os.path.join(root or _ROOT, TEMPLATE_DIRNAME)
    if not os.path.isdir(tdir):
        h.update(b"\0templates-missing")
        return
    for name in sorted(os.listdir(tdir)):
        path = os.path.join(tdir, name)
        if not os.path.isfile(path):
            continue
        h.update(b"\0T" + name.encode("utf-8") + b"\0")
        with open(path, "rb") as f:
            h.update(f.read())


def storyboard_fingerprint(storyboard_path):
    """分镜字节的短指纹。

    与 run_key 用途不同：run_key 是「这一次运行的目录归属」，本指纹是「这份预览报告
    属于哪份分镜」——写进 overflow.json，复用准入据此挡住显式 --preview-dir 指向
    别人报告的绕过（#26 AC3）。
    """
    h = hashlib.sha256()
    with open(storyboard_path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:10]


def run_key(storyboard_path, style_name, motion_enabled, root=None):
    """确定性 run 标识：同文件+同配置+同模板 → 同 key（verify 可精确重定位）；
    来源不同、style 不同、motion 开关不同、模板/皮肤内容不同 → 不同 key
    （并行互不覆盖；改模板后也不复用旧预览）。"""
    h = hashlib.sha256()
    with open(storyboard_path, "rb") as f:
        h.update(f.read())
    h.update(b"\0" + str(style_name).encode("utf-8"))
    h.update(b"\0" + (b"motion-on" if motion_enabled else b"motion-off"))
    render_inputs_digest(h, root)
    return h.hexdigest()[:10]


def run_dir(root, slug, style_name, key):
    return os.path.join(root, "_build", "runs", f"{slug}__{style_key_of(style_name)}__{key}")


def locate_run(root, storyboard_path, style_name, motion_enabled):
    """由 (分镜字节, style, motion 开关, root 下的模板内容) 直接得到本次 run 目录。

    run_key 与 run_dir 在三个入口里总是成对使用，收成一个调用，免得各拼一遍。
    root 同时决定 _build 位置与模板目录，故一并传给 run_key，两边不会各解析一次。
    """
    slug = os.path.splitext(os.path.basename(storyboard_path))[0]
    return run_dir(
        root,
        slug,
        style_name,
        run_key(storyboard_path, style_name, motion_enabled, root),
    )


def preview_dir(rdir):
    return os.path.join(rdir, "preview")


# 预览报告文件名：写入方（make_video.run_preview）与复用准入只有这一个来源。
PREVIEW_REPORT_NAME = "overflow.json"


def preview_report_path(preview_dir):
    return os.path.join(preview_dir, PREVIEW_REPORT_NAME)


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


# --- manifest 契约：字段名与构造点只在这里出现 ---------------------------------
# 写入方（make_video）、两个读者（render_worker / worker_verify）与测试夹具都走
# 这里。夹具曾与生产者悄悄漂移（夹具写 run_key/slug，生产者从不写），因为字段名
# 在四处各写了一遍；有了构造点，夹具只能造出合法形状。


def make_manifest(
    *,
    style_name,
    motion_enabled,
    fps,
    W,
    H,
    storyboard,
    mp4,
    expected_duration,
    scenes,
    tts_generated=0,
    tts_reused=0,
    reuse_mode="reuse",
):
    """本次运行的产物清单。字段即接口；缺项在这里补齐默认，不散在各调用点。"""
    return {
        "schema": MANIFEST_SCHEMA,
        "style_name": style_name,
        "motion_enabled": motion_enabled,
        "fps": fps,
        "W": W,
        "H": H,
        "storyboard": storyboard,
        "mp4": mp4,
        "expected_duration": expected_duration,
        "tts_generated": tts_generated,
        "tts_reused": tts_reused,
        "reuse_mode": reuse_mode,
        "scenes": scenes,
    }


def is_current_manifest(manifest):
    """schema 相符才算本次可用的 manifest；旧版本产物视为不可用。"""
    return bool(manifest) and manifest.get("schema") == MANIFEST_SCHEMA


def tts_facts(manifest):
    """本次 TTS 生成/复用事实 → (generated, reused, mode)；无此字段返回 None。

    「哪些字段算事实」只在这里判断，两个读者不再各写一遍。
    """
    if not is_current_manifest(manifest) or "tts_generated" not in manifest:
        return None
    return (
        manifest.get("tts_generated", 0),
        manifest.get("tts_reused", 0),
        manifest.get("reuse_mode", ""),
    )


def scene_wavs(manifest):
    """本次实际加工音轨清单——manifest 是唯一权威来源，缺 manifest 即空。"""
    if not is_current_manifest(manifest):
        return []
    return [sc["wav"] for sc in manifest.get("scenes", [])]


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
