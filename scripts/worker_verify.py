"""worker_verify.py — render worker Step 4 五项自动验收（GitHub issue #14）

用法: py scripts/worker_verify.py examples/<slug>.json output/<slug>.mp4 [--expect-reuse-audio]

检查 1/2（闸门绿、预览无溢出）由 Step 1/2 确认，此处不重复但计入勾选。
本脚本跑：3=mp4 存在且时长>0；4=音画锁 ±5%（成片音轨口径）；5=cache 命中（可选）。
全过 → stdout `VERIFY_OK [✓✓✓✓✓]`、exit 0；任一失败 → exit 4 + FAIL_AT_VERIFY 文案。
"""

import argparse
import json
import os
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from make_video import (  # noqa: E402
    _audio_paths,
    _cache_hit,
    _ffprobe_duration,
    resolve_voice,
)


def fail(item, msg):
    print(f"verify FAIL [{item}]: {msg}", file=sys.stderr)
    sys.exit(4)


def wav_duration(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


def main():
    ap = argparse.ArgumentParser(
        prog="worker_verify.py", description="render worker Step 4 验收"
    )
    ap.add_argument("storyboard")
    ap.add_argument("mp4")
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

    # 检查 4：音画锁。expected = Σ 成片音轨（_build/<slug>/s{i}_{fp}.wav，
    # prepare_scene_audio 产物、ceil 垫帧已含），不用 raw+hold+TAIL_PAD 重建口径
    with open(args.storyboard, encoding="utf-8") as f:
        tpl = json.load(f)
    slug = os.path.splitext(os.path.basename(args.storyboard))[0]
    cache_dir = os.path.join(ROOT, "_build", slug)
    expected = 0.0
    for i, sc in enumerate(tpl["scenes"]):
        sc_voice = resolve_voice(sc, tpl)
        _, wav_path = _audio_paths(cache_dir, i, sc["narrate"], sc_voice)
        if not os.path.isfile(wav_path):
            fail(4, f"missing scene audio: {wav_path}")
        expected += wav_duration(wav_path)
    drift = (got - expected) / expected
    if abs(drift) > 0.05:
        direction = "偏长(mux级?)" if drift > 0 else "偏短(音轨截断，真bug)"
        fail(
            4,
            f"AUDIO_LOCK_FAIL: expected={expected:.2f}s got={got:.2f}s "
            f"drift={drift:+.1%} {direction}",
        )

    # 检查 5：cache 命中按指纹核对（raw+meta 都算），不看目录文件数——
    # 旁白改过会残留旧指纹文件，计数口径误报；meta 不符时 render 会重 TTS（假阳性）
    if args.expect_reuse_audio:
        for i, sc in enumerate(tpl["scenes"]):
            sc_voice = resolve_voice(sc, tpl)
            raw_path, _ = _audio_paths(cache_dir, i, sc["narrate"], sc_voice)
            if not _cache_hit(raw_path, sc_voice, sc["narrate"]):
                fail(5, f"cache miss scene {i}: {raw_path}（旁白/音色与缓存不符）")

    # 检查 6：文本与视觉生硬未转义字符拦截（例如未渲染的字面 \\n / \\t）
    for i, sc in enumerate(tpl["scenes"]):
        for field in ("header", "sub", "body", "zh", "think"):
            val = str(sc.get(field, ""))
            if "\\n" in val or "\\t" in val:
                fail(
                    6,
                    f"scene {i} 字段 '{field}' 残留字面未解析转义字符 (如 \\\\n 或 \\\\t)",
                )

    print("VERIFY_OK [✓✓✓✓✓]")
    print(
        f"3:mp4 {os.path.getsize(args.mp4)}B {got:.2f}s | "
        f"4:audio-lock drift={drift:+.1%} (exp {expected:.2f}s) | "
        f"5:{'reuse-confirmed' if args.expect_reuse_audio else 'skipped(no-reuse)'}"
    )


if __name__ == "__main__":
    main()
