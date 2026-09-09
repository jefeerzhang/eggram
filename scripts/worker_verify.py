"""worker_verify.py — render worker Step 4 六项自动验收（GitHub issues #14/#22/#25）

用法: py scripts/worker_verify.py examples/<slug>.json output/<slug>.mp4
      [--style NAME] [--no-motion] [--expect-reuse-audio]

六项定义见 scripts/worker_result.py（单一事实源）。本脚本只评估自己实测的
3=mp4 存在且时长>0；4=音画锁 ±5%（成片音轨口径）；5=cache 命中（可选）；
6=残留字面转义字符拦截。检查 1/2（闸门绿、预览无溢出）是父入口 Step 1/2 的
职责——单独执行本脚本时没有其可靠运行证据，勾选串如实记 `·`（未执行），
不声称通过；完整六格由 render_worker 用 Step 1/2 实际结果合成。
每项终态输出协议行 `CHECK <n> PASS|FAIL|SKIP|NOTRUN`（空白分词，#25）；
全过 → stdout `VERIFY_OK [<六格>]`、exit 0；任一失败 → exit 4 + FAIL_AT_VERIFY 文案。

音轨定位（#22）：按 (分镜文件字节, style, motion 开关) 重算 run_key 精确定位
本次运行的 manifest，用 manifest 列出的「本次实际音轨集合」独立测量；manifest
不存在时回退旧版共享音轨 `_build/<slug>/s{i}_{fp}.wav`（兼容迁移前产物）。
不猜最近目录、不扫同名残留文件。
"""

import argparse
import json
import os
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import run_artifacts as ra  # noqa: E402
import worker_result as wr  # noqa: E402
from make_video import (  # noqa: E402
    _audio_paths,
    _cache_hit,
    _ffprobe_duration,
    resolve_voice,
)

# 各检查项终态：{item: (state, detail)}；只记本脚本实测结果，不替前置检查背书
_results = {}


def _record(item, state, detail=""):
    _results[item] = (state, detail)
    print(wr.check_line(item, state, detail))


def fail(item, msg):
    _record(item, wr.FAIL, msg.splitlines()[0] if msg else "")
    print(f"verify FAIL [{item}]: {msg}", file=sys.stderr)
    sys.exit(wr.STAGE_EXITS["VERIFY"])


def wav_duration(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


def resolve_audio_sources(storyboard, tpl, style_name, motion_enabled):
    """返回 (音轨路径列表, 来源说明)。run manifest 优先，旧版共享音轨回退。"""
    slug = os.path.splitext(os.path.basename(storyboard))[0]
    rkey = ra.run_key(storyboard, style_name, motion_enabled)
    rdir = ra.run_dir(ROOT, slug, style_name, rkey)
    manifest = ra.read_manifest(rdir)
    if manifest and manifest.get("schema") == ra.MANIFEST_SCHEMA:
        wavs = [sc["wav"] for sc in manifest.get("scenes", [])]
        if wavs:
            return wavs, f"run:{rdir}"
    cache_dir = os.path.join(ROOT, "_build", slug)
    wavs = []
    for i, sc in enumerate(tpl["scenes"]):
        sc_voice = resolve_voice(sc, tpl)
        _, wav_path = _audio_paths(cache_dir, i, sc["narrate"], sc_voice)
        wavs.append(wav_path)
    return wavs, f"legacy:{cache_dir}"


def main():
    ap = argparse.ArgumentParser(
        prog="worker_verify.py", description="render worker Step 4 验收"
    )
    ap.add_argument("storyboard")
    ap.add_argument("mp4")
    ap.add_argument("--style", default=None, help="渲染时的 --style（用于定位 run）")
    ap.add_argument(
        "--no-motion",
        action="store_true",
        help="渲染时带了 --no-motion 则验收也须带上（用于定位 run）",
    )
    ap.add_argument(
        "--expect-reuse-audio", action="store_true", help="检查 5：音频 cache 全命中"
    )
    args = ap.parse_args()

    # 检查 3：mp4 存在且时长 > 0（_ffprobe_duration 走 imageio_ffmpeg，不依赖 ffprobe）
    if not os.path.isfile(args.mp4):
        fail(3, f"mp4 不存在: {args.mp4}")
    got = _ffprobe_duration(args.mp4) or 0.0
    if got <= 0:
        fail(3, f"mp4 时长无法解析或为 0: {args.mp4}")
    _record(3, wr.PASS, f"{os.path.getsize(args.mp4)}B {got:.2f}s")

    # 检查 4：音画锁。expected = Σ 本次实际加工音轨（独立 wave 测量），
    # ±5% 双向容差；诊断标明偏长/偏短
    with open(args.storyboard, encoding="utf-8") as f:
        tpl = json.load(f)
    motion_enabled = (not args.no_motion) and (tpl.get("motion", True) is not False)
    style_name = args.style or tpl.get("style", "teaching")
    wavs, src = resolve_audio_sources(args.storyboard, tpl, style_name, motion_enabled)
    expected = 0.0
    for w in wavs:
        if not os.path.isfile(w):
            fail(
                4,
                f"missing scene audio: {w}\n"
                f"  音轨来源: {src}\n"
                f"  若渲染时用了 --style/--no-motion，验收须传相同参数以定位同一次运行",
            )
        expected += wav_duration(w)
    drift = (got - expected) / expected
    if abs(drift) > 0.05:
        direction = "偏长(mux级?)" if drift > 0 else "偏短(音轨截断，真bug)"
        fail(
            4,
            f"AUDIO_LOCK_FAIL: expected={expected:.2f}s got={got:.2f}s "
            f"drift={drift:+.1%} {direction} (audio-src={src})",
        )
    _record(4, wr.PASS, f"drift={drift:+.1%} (exp {expected:.2f}s, {len(wavs)} tracks, {src})")

    # 检查 5：cache 命中按指纹核对（raw+meta 都算），不看目录文件数——
    # 旁白改过会残留旧指纹文件，计数口径误报；meta 不符时 render 会重 TTS（假阳性）
    if args.expect_reuse_audio:
        slug = os.path.splitext(os.path.basename(args.storyboard))[0]
        cache_dir = os.path.join(ROOT, "_build", slug)
        for i, sc in enumerate(tpl["scenes"]):
            sc_voice = resolve_voice(sc, tpl)
            raw_path, _ = _audio_paths(cache_dir, i, sc["narrate"], sc_voice)
            if not _cache_hit(raw_path, sc_voice, sc["narrate"]):
                fail(5, f"cache miss scene {i}: {raw_path}（旁白/音色与缓存不符）")
        _record(5, wr.PASS, "reuse-confirmed")
    else:
        _record(5, wr.SKIP, "未要求 --expect-reuse-audio（显式跳过）")

    # 检查 6：文本与视觉生硬未转义字符拦截（例如未渲染的字面 \\n / \\t）
    for i, sc in enumerate(tpl["scenes"]):
        for field in ("header", "sub", "body", "wrong_body", "zh", "think"):
            val = str(sc.get(field, ""))
            if "\\n" in val or "\\t" in val:
                fail(
                    6,
                    f"scene {i} 字段 '{field}' 残留字面未解析转义字符 (如 \\\\n 或 \\\\t)",
                )
    _record(6, wr.PASS)

    marks = wr.marks_line((wr.NOTRUN, wr.NOTRUN), _results)
    print(f"VERIFY_OK [{marks}]")
    print(
        f"3:mp4 {os.path.getsize(args.mp4)}B {got:.2f}s | "
        f"4:audio-lock drift={drift:+.1%} (exp {expected:.2f}s, {len(wavs)} tracks, {src}) | "
        f"5:{_results[5][1]}"
    )


if __name__ == "__main__":
    main()
