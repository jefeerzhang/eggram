"""
make_video.py — 教学微课渲染器（Skill 阶段 2）

分镜 JSON → 静态闸门（storyboard_gate）→ 预览 → TTS（xiaomi / minimax）→ 教学动效截帧 → ffmpeg 合成 mp4

用法: python scripts/make_video.py examples/now_progressing.json [输出.mp4]
      [--style NAME] [--reuse-audio] [--no-motion] [--preview | --skip-preview]
      [--tts-provider xiaomi|minimax]

闸门规则、布局选择与页面准备集中在 storyboard_gate.py（唯一规则源）；
本模块持有运行环境与媒体管线：浏览器发现、TTS、音频加工、编码、预览探测执行。
预览去重：worker 先用 --preview 单独预验，再以 --skip-preview 渲成片，一次运行
只截一次图。跳过前必须读到同一目录里通过的 overflow.json（页数/顺序/kind/分镜
指纹/模板指纹一致，且无溢出、无占位符错误）；缺失或未通过则停，不配音（exit 4）。
「什么算通过」由 storyboard_gate.preview_report_errors 单一定义，本模块与复用准入
共用同一条判据。预览目录由 run_key（分镜字节 + style + motion 开关 +
templates/ 内容）决定。
"""

import argparse
import base64
import io
import json
import math
import os
import subprocess
import sys
import urllib.request

import audio_cache as ac  # noqa: E402  原始旁白缓存契约（纯 stdlib，与 verify 共用）
import run_artifacts as ra  # noqa: E402  单次渲染产物归属（run_key/manifest）
import toolchain as tc  # noqa: E402  本机工具定位（纯 stdlib，惰性解析 ffmpeg）
import worker_result as wr  # noqa: E402  子进程退出码契约（与 worker 共用）
# 只导入本模块真正要用的闸门名字。这里曾经整块再导出 24 个名字供测试消费 mv.*——
# 同一个实现于是有两个 interface，还掩盖了哪条规则归哪个模块。
from storyboard_gate import (
    _motion_display_name,
    _motion_probe_states,
    apply_motion_css_vars,
    frame_motion_state,
    formula_motion_vars,
    formula_parts_for_motion,
    load_env,
    motion_vars,
    parse_seconds,
    prepare_storyboard,
    preview_overflow,
    preview_report_entry,
    preview_report_errors,
    render_html,
    resolve_kind,
    resolve_motion,
    resolve_motion_enabled,
    resolve_voice,
    validate_rendered_html,
)

# 集中配置初始化：可选加载 ROOT/.env（显式环境变量优先），先于 MI 配置读取
load_env()

import numpy as np  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MI_URL = os.environ.get(
    "MIMO_API_URL", "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
)
MI_KEY = os.environ.get("MIMO_API_KEY", "")
MI_MODEL = "mimo-v2.5-tts"
SAMPLE_RATE = 24000


def mi_tts(text, voice):
    if not MI_KEY:
        raise RuntimeError("未设置环境变量 MIMO_API_KEY（小米 TTS）")
    payload = {
        "model": MI_MODEL,
        "messages": [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": text},
        ],
        "audio": {"format": "wav", "voice": voice},
        "stream": False,
    }
    req = urllib.request.Request(
        MI_URL, data=json.dumps(payload).encode(), method="POST"
    )
    req.add_header("Authorization", "Bearer " + MI_KEY)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        js = json.loads(r.read().decode("utf-8"))
    return base64.b64decode(js["choices"][0]["message"]["audio"]["data"])


def _mp3_bytes_to_wav_bytes(mp3_bytes, target_rate=SAMPLE_RATE):
    """MiniMax 返回 mp3 hex,经此函数转成 wav bytes(单声道 16-bit,目标采样率)。"""
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "mp3", "-i", "pipe:0",
            "-ar", str(target_rate), "-ac", "1", "-acodec", "pcm_s16le",
            "-f", "wav", "pipe:1",
        ],
        input=mp3_bytes, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "MiniMax mp3→wav 转码失败: " + proc.stderr.decode("utf-8", errors="ignore")
        )
    return proc.stdout


def minimax_tts(text, voice):
    """MiniMax 同步语音合成(/v1/t2a_v2)。

    返回值与 mi_tts 契约一致:单声道 16-bit wav bytes(24kHz),
    直接走既有 decode_wav → prepare_scene_audio 链路。
    """
    from tts_config import minimax_config, resolve_minimax_voice

    cfg = minimax_config()
    if not cfg["key"]:
        raise RuntimeError("未设置环境变量 MINIMAX_API_KEY（MiniMax TTS）")
    voice_id = resolve_minimax_voice(voice)
    payload = {
        "model": cfg["model"],
        "text": text,
        "stream": False,
        "voice_setting": {"voice_id": voice_id, "speed": 1, "vol": 1, "pitch": 0},
        "audio_setting": {
            "sample_rate": SAMPLE_RATE,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
        "output_format": "hex",
    }
    req = urllib.request.Request(
        cfg["url"], data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    req.add_header("Authorization", "Bearer " + cfg["key"])
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        js = json.loads(r.read().decode("utf-8"))
    if js.get("base_resp", {}).get("status_code") != 0:
        raise RuntimeError(f"MiniMax API 错误: {js.get('base_resp')}")
    mp3_bytes = bytes.fromhex(js["data"]["audio"])
    return _mp3_bytes_to_wav_bytes(mp3_bytes, target_rate=SAMPLE_RATE)


def synthesize(text, voice, provider):
    """统一 TTS 入口:按 provider 分派到 mi_tts / minimax_tts。"""
    if provider == "minimax":
        return minimax_tts(text, voice)
    return mi_tts(text, voice)


FADE_SEC = 0.012  # 仅抑咔哒；淡化落在段首/段尾静音区，不吞字
TAIL_PAD_SEC = 0.45  # 每段旁白后再垫一点静音，避免片尾/接缝被播放器吃掉
SPEECH_FLOOR = 180.0  # |sample| 低于此视为静音（int16 幅度）


def read_wav_pcm(path):
    with open(path, "rb") as f:
        data = f.read()
    pcm, rate, channels, sampwidth = decode_wav(data)
    assert channels == 1 and sampwidth == 2
    return pcm, rate


def decode_wav(data):
    """解析 WAV 容器，返回 (pcm_int16, rate, channels, sampwidth)。

    用标准 wave 模块读取：只取 data chunk 的实际 PCM，忽略 RIFF/fmt 等容器字节；
    额外合法 chunk（如 LIST/fact）也不会被当成声音。位深不支持时明确报错，不静默重解释。
    """
    import wave

    with wave.open(io.BytesIO(data), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        if sampwidth != 2:
            raise RuntimeError(f"WAV 位深 {sampwidth * 8}bit 不支持（仅 16bit）")
        frames = w.readframes(w.getnframes())
        pcm = np.frombuffer(frames, dtype=np.int16)
    return pcm, rate, channels, sampwidth


def write_wav_pcm(path, pcm, rate=SAMPLE_RATE):
    """单声道 16bit WAV 落位。

    原子替换与 Windows 上目标被短暂持句柄时的退避，统一由
    run_artifacts.atomic_write_bytes 负责（并行 worker 写同一确定性路径时，
    读方要么旧文件要么新文件，都是完整的）。
    """
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.asarray(pcm, dtype=np.int16).tobytes())
    ra.atomic_write_bytes(path, buf.getvalue())


def _speech_bounds(speech, floor=SPEECH_FLOOR):
    hit = np.where(np.abs(speech) >= floor)[0]
    if hit.size == 0:
        return 0, len(speech)
    return int(hit[0]), int(hit[-1]) + 1


def _fade_edges_in_silence(speech, fade_sec=FADE_SEC):
    """只在静音头/尾做淡化；有声区最多侵入 fade 的 1/4，避免截断句首句尾。"""
    n = len(speech)
    if n == 0:
        return speech
    fade_n = min(int(round(fade_sec * SAMPLE_RATE)), max(1, n // 8))
    start, end = _speech_bounds(speech)
    # 段首：从 0 淡到有声起点（无声则仅极短）
    head = start if start > 0 else min(fade_n, max(1, int(0.004 * SAMPLE_RATE)))
    head = min(head, fade_n if start == 0 else start + max(1, fade_n // 4))
    head = min(head, n)
    if head > 1:
        speech[:head] *= np.linspace(0.0, 1.0, head, dtype=np.float32)
    # 段尾：从有声终点淡到结束
    tail_room = n - end
    if tail_room > 0:
        tail = min(fade_n, tail_room + max(1, fade_n // 4))
    else:
        tail = min(fade_n, max(1, int(0.004 * SAMPLE_RATE)))
    tail = min(tail, n)
    if tail > 1:
        speech[-tail:] *= np.linspace(1.0, 0.0, tail, dtype=np.float32)
    return speech


def prepare_scene_audio(raw_pcm, hold, fps, fade_sec=FADE_SEC, tail_pad=TAIL_PAD_SEC):
    """旁白边缘静音淡化 + hold/尾垫静音；只垫不裁，按 ceil 锁帧（音画锁）。

    返回 (pcm_int16, n_frames, duration_sec, narration_frames)。
    narration_frames = 旁白对应帧数；hold 与尾垫期间动效应复用最后状态（音画锁）。
    """
    speech = np.asarray(raw_pcm, dtype=np.float32).copy()
    hold = max(0.0, float(hold))
    speech = _fade_edges_in_silence(speech, fade_sec)
    # 旁白时长（淡化不改长度）；其对应帧数驱动动效进度，hold/尾垫复用末态
    narration_frames = max(
        1, int(math.ceil(len(speech) / float(SAMPLE_RATE) * fps - 1e-9))
    )
    pad_n = int(round((hold + max(0.0, float(tail_pad))) * SAMPLE_RATE))
    if pad_n > 0:
        speech = np.concatenate([speech, np.zeros(pad_n, dtype=np.float32)])
    # ceil 帧数，保证画面覆盖全部样本；禁止裁切旁白
    dur = len(speech) / float(SAMPLE_RATE)
    n_frames = max(1, int(math.ceil(dur * fps - 1e-9)))
    target = int(math.ceil(n_frames * SAMPLE_RATE / float(fps) - 1e-9))
    if target < len(speech):
        n_frames = max(
            n_frames + 1, int(math.ceil(len(speech) * fps / float(SAMPLE_RATE) - 1e-9))
        )
        target = int(math.ceil(n_frames * SAMPLE_RATE / float(fps) - 1e-9))
    if target > len(speech):
        speech = np.concatenate(
            [speech, np.zeros(target - len(speech), dtype=np.float32)]
        )
    pcm = np.clip(np.rint(speech), -32768, 32767).astype(np.int16)
    return pcm, n_frames, n_frames / float(fps), narration_frames


def build_parser():
    p = argparse.ArgumentParser(
        prog="make_video.py",
        description="教学微课渲染器（Skill 阶段 2）：分镜 JSON → 校验 → TTS → 动效截帧 → ffmpeg 合成 mp4",
    )
    p.add_argument("storyboard", help="分镜 JSON 路径")
    p.add_argument(
        "output",
        nargs="?",
        default=None,
        help="输出 mp4 路径（缺省 output/<主名>.mp4）",
    )
    p.add_argument(
        "--style",
        default=None,
        help="换皮名（teaching/classroom/explainer，或自定义 style-<name>.json）",
    )
    p.add_argument(
        "--reuse-audio",
        action="store_true",
        help="复用 _build/<lesson>/s*_<fp>_raw.wav（旁白+音色指纹命中才复用）",
    )
    p.add_argument("--no-motion", action="store_true", help="关闭 focus/pulse/zoom")
    pv = p.add_mutually_exclusive_group()
    pv.add_argument(
        "--preview", action="store_true", help="只截图+溢出探测，不调 TTS/ffmpeg"
    )
    pv.add_argument(
        "--skip-preview",
        action="store_true",
        help="跳过重新截图：仅当本目录 overflow.json 属本次分镜且已通过（页数/顺序/kind 一致、无溢出/占位符错误）",
    )
    p.add_argument(
        "--browser",
        default=None,
        help="浏览器可执行文件路径（覆盖自动发现 Chrome/Edge）",
    )
    p.add_argument(
        "--preview-dir",
        default=None,
        help="预览截图/溢出报告目录（缺省 run 目录 preview/；显式指定可覆盖）",
    )
    p.add_argument(
        "--tts-provider",
        default=None,
        choices=("xiaomi", "minimax"),
        help="TTS 引擎：xiaomi（默认）/ minimax；分镜顶层 tts_provider 字段也会被读，CLI 优先",
    )
    return p


def main():
    args = build_parser().parse_args()
    tpl_path = args.storyboard
    with open(tpl_path, encoding="utf-8") as f:
        tpl = json.load(f)
    out = args.output or os.path.join(
        ROOT, "output", os.path.splitext(os.path.basename(tpl_path))[0] + ".mp4"
    )
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    motion_enabled = resolve_motion_enabled(tpl, args.no_motion)

    print("0/4 校验布局与分镜...")
    prep = prepare_storyboard(tpl, style_name=args.style, motion_enabled=motion_enabled)
    for w in prep["warnings"]:
        print(" WARN:", w)
    if prep["errors"]:
        print("VALIDATION FAILED:")
        for e in prep["errors"]:
            print(" -", e)
        sys.exit(wr.MV_EXIT_VALIDATION)
    # fps 已在闸门校验为正整数；此处才转换，避免非法值在闸门前抛无上下文异常
    cfg = prep["cfg"]
    FPS = int(cfg.fps)
    style, W, H = cfg.style, cfg.W, cfg.H
    scenes = tpl["scenes"]
    # TTS provider 决策:CLI > 分镜顶层 tts_provider > 默认 xiaomi
    from tts_config import resolve_tts_provider
    tts_provider = resolve_tts_provider(
        storyboard_provider=tpl.get("tts_provider"),
        cli_provider=getattr(args, "tts_provider", None),
    )
    if tts_provider not in ("xiaomi", "minimax"):
        raise RuntimeError(f"未知 tts_provider: {tts_provider!r}")
    print(f"   tts_provider={tts_provider}")
    # 单次运行产物归属（#22）：run 目录拥有本次 preview + 加工音轨 + manifest；
    # 可共享的 raw 旁白仍在 _build/<slug>/（旁白+音色指纹，style 不参与）
    slug = os.path.splitext(os.path.basename(tpl_path))[0]
    rdir = ra.locate_run(ROOT, tpl_path, cfg.style_name, motion_enabled)
    print(
        f"   style={cfg.style_name} ({style.get('style_id')}), motion={'on' if motion_enabled else 'off'}, scenes={len(scenes)} OK"
    )
    print(f"   run={rdir}")
    preview_out = args.preview_dir or ra.preview_dir(rdir)
    if not os.path.isabs(preview_out):
        preview_out = os.path.join(ROOT, preview_out)
    os.makedirs(preview_out, exist_ok=True)

    # 浏览器解析：preview 与成片共用同一结果；候选全缺时在 TTS 前给出可执行提示
    try:
        browser = tc.browser_path(args.browser)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(wr.MV_EXIT_BROWSER)
    if not browser:
        print(
            "ERROR: 未找到可用浏览器（Chrome/Edge）。请安装 Chrome 或 Edge；"
            "或用环境变量 BROWSER_PATH（或 CHROME_PATH）指定浏览器可执行文件路径，"
            "或用 --browser <路径> 显式指定。"
        )
        sys.exit(wr.MV_EXIT_BROWSER)

    # 预览闸门：缩略图 + 溢出；--preview 到此结束。
    # 去重：完整 worker 的 Step 2 已用 --preview 验过同 run_key 的产物，
    # 成片阶段传 --skip-preview 复用。缺报告、页数不符或仍有溢出则停，不配音。
    if args.skip_preview:
        preview_errs = preview_reuse_errors(
            preview_out,
            scenes,
            ra.storyboard_fingerprint(tpl_path),
            ra.templates_fingerprint(ROOT),
        )
        if preview_errs:
            print("PREVIEW FAILED:")
            for e in preview_errs:
                print(" -", e)
            print("预览未通过，已跳过配音/成片。先跑 --preview，或去掉 --skip-preview。")
            sys.exit(wr.MV_EXIT_PREVIEW_STALE)
        print(f"1/4 预览截图与溢出... 跳过（复用已有预览）→ {preview_out}")
    else:
        print("1/4 预览截图与溢出...")
        preview_rc = run_preview(tpl_path, cfg, scenes, browser, preview_out)
        if args.preview:
            sys.exit(preview_rc)
        if preview_rc != 0:
            print("预览未通过，已跳过配音/成片。修分镜或模板后重试；或单独跑 --preview。")
            sys.exit(preview_rc)

    print("2/4 生成配音..." + (" (reuse-audio)" if args.reuse_audio else ""))
    wavs, durs, frame_counts, narr_frames_list = [], [], [], []
    audio_out = ra.audio_dir(rdir)
    os.makedirs(audio_out, exist_ok=True)
    cache_dir = os.path.join(ROOT, "_build", slug)
    os.makedirs(cache_dir, exist_ok=True)
    scene_meta = []
    for i, sc in enumerate(scenes):
        sc_voice = resolve_voice(sc, tpl)
        raw_path, _ = ac.paths(cache_dir, i, sc["narrate"], sc_voice, tts_provider)
        fp = ac.fingerprint(sc["narrate"], sc_voice, tts_provider)
        wav_path = ra.scene_wav(rdir, i, fp)
        hold, hold_err = parse_seconds(sc.get("hold", 0.0))
        if hold_err:
            raise RuntimeError(f"scene {i} {hold_err}（闸门应已拒绝）")
        if args.reuse_audio and ac.is_hit(raw_path, sc_voice, sc["narrate"], tts_provider):
            raw_pcm, rate = read_wav_pcm(raw_path)
            if rate != SAMPLE_RATE:
                raise RuntimeError(f"{raw_path} 采样率 {rate} != {SAMPLE_RATE}")
            src = "reuse"
        else:
            if args.reuse_audio:
                print(f"   cache miss scene {i}（旁白/音色/provider 变更或无缓存），重 TTS")
            wav_bytes = synthesize(sc["narrate"], sc_voice, tts_provider)
            raw_pcm, rate, channels, sampwidth = decode_wav(wav_bytes)
            if rate != SAMPLE_RATE:
                raise RuntimeError(
                    f"scene {i} TTS 采样率 {rate} != {SAMPLE_RATE}（需 {SAMPLE_RATE}）"
                )
            if channels != 1:
                raise RuntimeError(
                    f"scene {i} TTS 声道 {channels} != 1（仅支持单声道）"
                )
            if sampwidth != 2:
                raise RuntimeError(
                    f"scene {i} TTS 位深 {sampwidth * 8}bit != 16bit（仅支持 16bit）"
                )
            write_wav_pcm(raw_path, raw_pcm, SAMPLE_RATE)
            ac.write_meta(raw_path, sc_voice, sc["narrate"], SAMPLE_RATE, tts_provider)
            src = "tts"
        pcm, n_frames, dur, narr_frames = prepare_scene_audio(raw_pcm, hold, FPS)
        write_wav_pcm(wav_path, pcm, SAMPLE_RATE)
        wavs.append(wav_path)
        durs.append(dur)
        frame_counts.append(n_frames)
        narr_frames_list.append(narr_frames)
        scene_meta.append(
            {
                "i": i,
                "voice": sc_voice,
                "narrate": sc["narrate"],
                "fp": fp,
                "raw": os.path.abspath(raw_path),
                "wav": os.path.abspath(wav_path),
                "duration": dur,
                "frames": n_frames,
                "narr_frames": narr_frames,
                "hold": hold,
                "cache": src,  # 本次实际执行事实：tts=新配音 / reuse=命中复用（#24）
            }
        )
        print(
            f"   scene {i} [{resolve_kind(sc)}/{_motion_display_name(resolve_motion(sc, motion_enabled))}]: "
            f"{dur:.2f}s ({n_frames}f, hold={hold:.1f}, {src})"
        )
    expected_dur = sum(durs)
    print(
        f"   Σ(旁白+hold+尾垫) = {expected_dur:.2f}s  /  {sum(frame_counts)} frames @ {FPS}fps"
    )

    print("3/4 渲染 HTML 画面并合成...")
    n = len(wavs)
    # 音轨已在 prepare_scene_audio 完成淡化+hold 填充；此处只 aresample + concat，不再二次 afade
    cmd = [
        tc.ffmpeg_path(),
        "-y",
        "-loglevel",
        "error",
        "-nostats",
        "-framerate",
        str(FPS),
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-i",
        "-",
    ]
    for w in wavs:
        cmd += ["-i", w]
    fparts = [
        f"[{i + 1}:a]aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=mono[a{i}]"
        for i in range(n)
    ]
    chain = "".join(f"[a{i}]" for i in range(n))
    fparts.append(f"{chain}concat=n={n}:v=0:a=1[outa]")
    cmd += [
        "-filter_complex",
        ";".join(fparts),
        "-map",
        "0:v",
        "-map",
        "[outa]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-movflags",
        "+faststart",
        out,
    ]
    # 不用 -shortest：音画已按帧锁定同长

    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    ff_stdin, ff_stderr = proc.stdin, proc.stderr
    if ff_stdin is None or ff_stderr is None:
        raise RuntimeError("ffmpeg pipe 未初始化")
    gi = 0
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=browser, headless=True)
        page = b.new_page(viewport={"width": W, "height": H})
        for i, sc in enumerate(scenes):
            html = render_html(
                sc, cfg._replace(motion_enabled=motion_enabled and frame_counts[i] > 1)
            )
            left = validate_rendered_html(html, i)
            if left:
                proc.kill()
                print("VALIDATION FAILED mid-render:", left)
                sys.exit(wr.MV_EXIT_VALIDATION)
            page.set_content(html)
            motion = resolve_motion(sc, motion_enabled)
            fparts = formula_parts_for_motion(sc)
            n_frames = frame_counts[i]
            is_static = all(e["type"] == "none" for e in motion) or n_frames == 1
            if is_static:
                # 整页一帧复用：公式动效取末态，不停在入场中途
                fvars = (
                    formula_motion_vars(fparts, 1.0, 1.0) if fparts is not None else None
                )
                apply_motion_css_vars(page, motion_vars(motion, 0.0, 1.0), fvars)
                shot = page.screenshot(type="png")
                for _ in range(n_frames):
                    ff_stdin.write(shot)
                    gi += 1
            else:
                narr_frames = narr_frames_list[i]
                narr_seconds = narr_frames / float(FPS)
                for k in range(n_frames):
                    # 秒语义：elapsed=k/fps，旁白终点=narr_frames/fps；hold/尾垫冻结末态
                    # 公式分步与整页动效共用这一天 clock，超时长由 formula_motion_vars 夹紧
                    fvars = (
                        formula_motion_vars(fparts, k / float(FPS), narr_seconds)
                        if fparts is not None
                        else None
                    )
                    apply_motion_css_vars(
                        page,
                        frame_motion_state(motion, k, FPS, narr_frames),
                        fvars,
                    )
                    ff_stdin.write(page.screenshot(type="png"))
                    gi += 1
        b.close()
    ff_stdin.close()
    err = ff_stderr.read().decode("utf-8", errors="replace")
    rc = proc.wait()
    print(f"   {gi} 帧 pipe 完成, rc={rc}")
    if rc != 0:
        print("FFMPEG ERR:", err[-2000:])
        sys.exit(wr.MV_EXIT_FAIL)

    print("4/4 时长核对...")
    actual_dur = tc.media_duration(out)
    if actual_dur is not None and abs(actual_dur - expected_dur) > 0.15:
        print(
            f"   WARN: 时长偏差: 实测 {actual_dur:.2f}s vs Σ {expected_dur:.2f}s"
            f"（差 {actual_dur - expected_dur:+.2f}s）"
        )
    elif actual_dur is not None:
        print(f"   OK: {actual_dur:.2f}s ≈ {expected_dur:.2f}s")
    # 本次运行产物清单（#22）：verify 用它拿「本次实际音轨集合」，精确重定位；
    # 缓存使用事实来自本次执行（循环内命中/未命中），不做事后文件计数（#24）
    tts_generated = sum(1 for m in scene_meta if m["cache"] == "tts")
    tts_reused = sum(1 for m in scene_meta if m["cache"] == "reuse")
    print(f"   TTS 本次生成 {tts_generated} / 复用 {tts_reused}")
    ra.write_manifest(
        rdir,
        ra.make_manifest(
            style_name=cfg.style_name,
            motion_enabled=motion_enabled,
            fps=FPS,
            W=W,
            H=H,
            storyboard=os.path.abspath(tpl_path),
            mp4=os.path.abspath(out),
            expected_duration=expected_dur,
            scenes=scene_meta,
            tts_generated=tts_generated,
            tts_reused=tts_reused,
            reuse_mode="reuse" if args.reuse_audio else "regenerate",
        ),
    )
    print(f"DONE -> {out}  ({os.path.getsize(out)} bytes)")


# ---- 音频缓存与工具定位：契约分别在 audio_cache / toolchain（纯 stdlib）----


def preview_reuse_errors(preview_dir, scenes, storyboard_fp, templates_fp=None):
    """--skip-preview 的准入检查。返回错误列表；空列表表示可以复用、不必重截。

    本函数只管「报告在不在、读不读得动」；「什么算通过、报告是否属于本次分镜/模板」
    由 storyboard_gate.preview_report_errors 这一条判据决定（唯一规则源）。
    """
    path = ra.preview_report_path(preview_dir)
    if not os.path.isfile(path):
        return [f"未找到已通过的预览报告: {path}"]
    try:
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return [f"预览报告无法读取: {path} ({e})"]
    gate_errs, overflow_errs, binding_errs = preview_report_errors(
        report, scenes, storyboard_fp, templates_fp
    )
    errs = [f"{e}（{path}）" for e in binding_errs]
    if gate_errs:
        errs.append(f"预览仍有占位符错误（{len(gate_errs)} 条）：{gate_errs[0]}")
    if overflow_errs:
        errs.append(f"预览仍有溢出/裁切（{len(overflow_errs)} 条）：{overflow_errs[0]}")
    return errs


def _finding_key(finding):
    """跨动效状态的去重键：同一槽同时「越界」与「被裁切」是两条不同诊断，不能互相
    吞掉，故 how 必须入键；坐标不入键（动效各状态坐标会变），否则同一条会重复上报。

    键全部取自 preview_overflow 的字段，不解析 msg——诊断文案是表现层，改文案
    不该改变去重行为。
    """
    return (finding["sel"], finding["how"], finding.get("txt", ""))


def run_preview(tpl_path, cfg, scenes, browser, preview_dir):
    """截图 + 溢出探测。返回 0=OK，1=溢出，2=占位符闸门失败。不调 TTS/ffmpeg。

    cfg 是 prepare_storyboard 产出的 RenderConfig（W/H/style/motion_enabled），
    与成片阶段共用同一个值——不再把它的字段当散参数重传一遍。
    preview_dir 由调用方给定（缺省为 run 目录的 preview/，#22 产物归属）。
    返回码由 preview_report_errors（与复用准入同一条判据）判定，不另写一套。
    """
    out_dir = (
        preview_dir if os.path.isabs(preview_dir) else os.path.join(ROOT, preview_dir)
    )
    os.makedirs(out_dir, exist_ok=True)
    print(f"   → {out_dir}")
    report = []
    storyboard_fp = ra.storyboard_fingerprint(tpl_path)
    templates_fp = ra.templates_fingerprint(ROOT)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=browser, headless=True)
        page = b.new_page(viewport={"width": cfg.W, "height": cfg.H})
        for i, sc in enumerate(scenes):
            html = render_html(sc, cfg)
            ph_errs = validate_rendered_html(html, i)
            page.set_content(html)
            kind = resolve_kind(sc)
            motion = resolve_motion(sc, cfg.motion_enabled)
            # 缩略图取 t=0（起点画面），避免截到中间态
            apply_motion_css_vars(page, motion_vars(motion, 0.0, 1.0))
            png = os.path.join(out_dir, f"s{i}.png")
            # 原子落位：并行同配置运行写同一路径时读方只见完整文件（#22）
            ra.atomic_write_bytes(png, page.screenshot(type="png", full_page=False))
            # 溢出探测覆盖动效可达状态：none 只测静态；其余按各动效自身窗口采样 0..1
            seen, findings = set(), []
            for elapsed, duration in _motion_probe_states(motion):
                apply_motion_css_vars(page, motion_vars(motion, elapsed, duration))
                for finding in preview_overflow(page, cfg.W, cfg.H, kind=kind):
                    key = _finding_key(finding)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(finding)
            report.append(
                preview_report_entry(
                    i,
                    kind,
                    motion,
                    png,
                    findings,
                    ph_errs,
                    storyboard_fp,
                    templates_fp,
                )
            )
            tag = "OK" if not ph_errs and not findings else "FAIL"
            print(
                f"   scene {i} [{kind}/{_motion_display_name(motion)}]: {tag}  → {png}"
            )
        b.close()
    report_path = ra.preview_report_path(out_dir)
    ra.atomic_write_bytes(
        report_path, json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    )
    gate_errs, overflow_errs, _ = preview_report_errors(report, scenes)
    if gate_errs:
        print("PREVIEW GATE FAILED:")
        for e in gate_errs:
            print(" -", e)
        return 2
    if overflow_errs:
        print(f"PREVIEW FAILED: {len(overflow_errs)} 条溢出/裁切（{report_path}）")
        for e in overflow_errs:
            print(" -", e)
        return 1
    print(f"   PREVIEW_OK {len(report)} 页")
    return 0


if __name__ == "__main__":
    main()
