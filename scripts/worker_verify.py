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
本次运行的 manifest，用 manifest 列出的「本次实际音轨集合」独立测量。manifest
不存在 → 检查 4 直接失败（视为未渲染/未完成），不回退到共享 raw 目录猜文件名：
那会量到上一版或别的皮肤的音轨，比报错更糟。也不猜最近目录、不扫同名残留文件。
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
from storyboard_gate import resolve_motion_enabled  # noqa: E402
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


def resolve_audio_sources(storyboard, style_name, motion_enabled):
    """返回 (本次实际音轨列表, 来源说明, manifest)。

    manifest 由 make_video 执行时写出，是本次运行音轨的唯一权威清单；缺失即
    视为未渲染或渲染未完成，返回空清单由调用方判失败。不回退到共享 raw 目录
    猜文件名——那会量到上一版或别的皮肤的音轨。
    """
    rdir = ra.locate_run(ROOT, storyboard, style_name, motion_enabled)
    manifest = ra.read_manifest(rdir)
    if not manifest or manifest.get("schema") != ra.MANIFEST_SCHEMA:
        return [], f"no-manifest:{rdir}", None
    return (
        [sc["wav"] for sc in manifest.get("scenes", [])],
        f"run:{rdir}",
        manifest,
    )


def _cache_facts(manifest):
    """本次生成/复用事实（make_video 执行时记录进 manifest）；旧产物无此字段。"""
    if not manifest or "tts_generated" not in manifest:
        return ""
    return (
        f"(本次生成 {manifest.get('tts_generated', '?')} / "
        f"复用 {manifest.get('tts_reused', '?')}, mode={manifest.get('reuse_mode', '?')})"
    )


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
    motion_enabled = resolve_motion_enabled(tpl, args.no_motion)
    style_name = args.style or tpl.get("style", "teaching")
    wavs, src, manifest = resolve_audio_sources(
        args.storyboard, style_name, motion_enabled
    )
    if not wavs:
        fail(
            4,
            f"本次运行没有 manifest，拿不到实际音轨清单\n"
            f"  定位到的 run 目录: {src}\n"
            f"  若渲染时用了 --style/--no-motion，验收须传相同参数以定位同一次运行；"
            f" 或先完成渲染",
        )
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
        _record(5, wr.PASS, ("reuse-confirmed " + _cache_facts(manifest)).rstrip())
    else:
        skip = "未要求 --expect-reuse-audio（显式跳过） " + _cache_facts(manifest)
        _record(5, wr.SKIP, skip.rstrip())

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
