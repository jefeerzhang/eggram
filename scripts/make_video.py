"""
make_video.py — 教学微课渲染器（Skill 阶段 2）

分镜 JSON → 静态闸门（storyboard_gate）→ 预览 → 小米 TTS → 教学动效截帧 → ffmpeg 合成 mp4

用法: python scripts/make_video.py examples/now_progressing.json [输出.mp4]
      [--style NAME] [--reuse-audio] [--no-motion] [--preview]

闸门规则、布局选择与页面准备集中在 storyboard_gate.py（唯一规则源）；
本模块持有运行环境与媒体管线：浏览器发现、TTS、音频加工、编码、预览探测执行。
"""

import argparse
import base64
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from storyboard_gate import (  # noqa: F401  兼容 re-export：测试与 worker 消费 mv.*
    KIND_BADGE,
    KIND_MOTION,
    KIND_TO_ROLE,
    LAYOUT_FILES,
    LAYOUT_VARIANTS,
    MOTIONS,
    ROLE_TO_KIND,
    TEMPLATE_DIR,
    _motion_display_name,
    _motion_probe_states,
    apply_motion_css_vars,
    frame_motion_state,
    highlight_body,
    load_env,
    load_layout,
    load_style,
    motion_vars,
    prepare_storyboard,
    preview_overflow,
    render_html,
    resolve_kind,
    resolve_layout_file,
    resolve_motion,
    resolve_voice,
    validate_layouts,
    validate_rendered_html,
    validate_storyboard,
)

# 集中配置初始化：可选加载 ROOT/.env（显式环境变量优先），先于 MI 配置读取
load_env()

import imageio_ffmpeg  # noqa: E402
import numpy as np  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# 音频缓存解码版本。错误解码路径生成的旧 raw 无此版本号，缓存不命中。
CACHE_VERSION = "2"

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


FADE_SEC = 0.012  # 仅抑咔哒；淡化落在段首/段尾静音区，不吞字
TAIL_PAD_SEC = 0.45  # 每段旁白后再垫一点静音，避免片尾/接缝被播放器吃掉
SPEECH_FLOOR = 180.0  # |sample| 低于此视为静音（int16 幅度）


def pcm_to_wav(pcm_bytes, path):
    import wave

    arr = np.frombuffer(pcm_bytes, dtype=np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(arr.tobytes())


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
    import wave

    pcm = np.asarray(pcm, dtype=np.int16)
    # 先写临时文件再 os.replace 原子落位：并行 worker（同 slug 换皮批）对同一
    # 确定性内容的并发读写不再产生撕裂（读方要么旧文件要么新文件，都是完整的）。
    # Windows 反例（#18 复测坐实）：目标被其它进程 ffmpeg 持句柄时 replace 抛
    # WinError 5。同指纹路径的并发写内容完全确定 → 尺寸一致即视为已落位；
    # 否则短退避重试，仍失败才抛（真异常）。
    tmp = f"{path}.tmp{os.getpid()}"
    try:
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm.tobytes())
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                try:
                    if os.path.getsize(path) == os.path.getsize(tmp):
                        return  # 并发同内容写入，目标已完整，读方无损
                except OSError:
                    pass
                time.sleep(0.3)
        raise RuntimeError(f"wav 原子替换失败（目标被长期占用）: {path}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


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


def find_browser(explicit=None):
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
    p.add_argument(
        "--preview", action="store_true", help="只截图+溢出探测，不调 TTS/ffmpeg"
    )
    p.add_argument(
        "--browser",
        default=None,
        help="浏览器可执行文件路径（覆盖自动发现 Chrome/Edge）",
    )
    p.add_argument(
        "--preview-dir",
        default=None,
        help="预览截图/溢出报告目录（缺省 _build/preview/<slug>/；并行换皮按 style 隔开）",
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

    motion_enabled = (not args.no_motion) and (tpl.get("motion", True) is not False)

    print("0/4 校验布局与分镜...")
    prep = prepare_storyboard(tpl, style_name=args.style, motion_enabled=motion_enabled)
    for w in prep["warnings"]:
        print(" WARN:", w)
    if prep["errors"]:
        print("VALIDATION FAILED:")
        for e in prep["errors"]:
            print(" -", e)
        sys.exit(2)
    # fps 已在闸门校验为正整数；此处才转换，避免非法值在闸门前抛无上下文异常
    FPS = int(prep["fps"])
    style, W, H = prep["style"], prep["W"], prep["H"]
    scenes = tpl["scenes"]
    print(
        f"   style={prep['style_name']} ({style.get('style_id')}), motion={'on' if motion_enabled else 'off'}, scenes={len(scenes)} OK"
    )

    # 浏览器解析：preview 与成片共用同一结果；候选全缺时在 TTS 前给出可执行提示
    try:
        browser = find_browser(args.browser)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(3)
    if not browser:
        print(
            "ERROR: 未找到可用浏览器（Chrome/Edge）。请安装 Chrome 或 Edge；"
            "或用环境变量 BROWSER_PATH（或 CHROME_PATH）指定浏览器可执行文件路径，"
            "或用 --browser <路径> 显式指定。"
        )
        sys.exit(3)

    # 预览闸门：缩略图 + 溢出；--preview 到此结束
    print("1/4 预览截图与溢出...")
    preview_rc = run_preview(
        tpl_path, scenes, style, W, H, motion_enabled, browser, args.preview_dir
    )
    if args.preview:
        sys.exit(preview_rc)
    if preview_rc != 0:
        print("预览未通过，已跳过配音/成片。修分镜或模板后重试；或单独跑 --preview。")
        sys.exit(preview_rc)

    print("2/4 生成配音..." + (" (reuse-audio)" if args.reuse_audio else ""))
    wavs, durs, frame_counts, narr_frames_list = [], [], [], []
    lesson_key = os.path.splitext(os.path.basename(tpl_path))[0]
    cache_dir = os.path.join(ROOT, "_build", lesson_key)
    os.makedirs(cache_dir, exist_ok=True)
    for i, sc in enumerate(scenes):
        sc_voice = resolve_voice(sc, tpl)
        raw_path, wav_path = _audio_paths(cache_dir, i, sc["narrate"], sc_voice)
        hold = float(sc.get("hold", 0.0))
        if args.reuse_audio and _cache_hit(raw_path, sc_voice, sc["narrate"]):
            raw_pcm, rate = read_wav_pcm(raw_path)
            if rate != SAMPLE_RATE:
                raise RuntimeError(f"{raw_path} 采样率 {rate} != {SAMPLE_RATE}")
            src = "reuse"
        else:
            if args.reuse_audio:
                print(f"   cache miss scene {i}（旁白/音色变更或无缓存），重 TTS")
            wav_bytes = mi_tts(sc["narrate"], sc_voice)
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
            _write_cache_meta(raw_path, sc_voice, sc["narrate"], SAMPLE_RATE)
            src = "tts"
        pcm, n_frames, dur, narr_frames = prepare_scene_audio(raw_pcm, hold, FPS)
        write_wav_pcm(wav_path, pcm, SAMPLE_RATE)
        wavs.append(wav_path)
        durs.append(dur)
        frame_counts.append(n_frames)
        narr_frames_list.append(narr_frames)
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
        FFMPEG,
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
                sc, W, H, style, motion_enabled=motion_enabled and frame_counts[i] > 1
            )
            left = validate_rendered_html(html, i)
            if left:
                proc.kill()
                print("VALIDATION FAILED mid-render:", left)
                sys.exit(2)
            page.set_content(html)
            motion = resolve_motion(sc, motion_enabled)
            n_frames = frame_counts[i]
            is_static = all(e["type"] == "none" for e in motion) or n_frames == 1
            if is_static:
                apply_motion_css_vars(page, *motion_vars(motion, 0.0, 1.0))
                shot = page.screenshot(type="png")
                for _ in range(n_frames):
                    ff_stdin.write(shot)
                    gi += 1
            else:
                narr_frames = narr_frames_list[i]
                for k in range(n_frames):
                    # 秒语义：elapsed=k/fps，旁白终点=narr_frames/fps；hold/尾垫冻结末态
                    apply_motion_css_vars(
                        page, *frame_motion_state(motion, k, FPS, narr_frames)
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
        sys.exit(1)

    print("4/4 时长核对...")
    actual_dur = _ffprobe_duration(out)
    if actual_dur is not None and abs(actual_dur - expected_dur) > 0.15:
        print(
            f"   WARN: 时长偏差: 实测 {actual_dur:.2f}s vs Σ {expected_dur:.2f}s"
            f"（差 {actual_dur - expected_dur:+.2f}s）"
        )
    elif actual_dur is not None:
        print(f"   OK: {actual_dur:.2f}s ≈ {expected_dur:.2f}s")
    print(f"DONE -> {out}  ({os.path.getsize(out)} bytes)")


# ---- 音频缓存：按 lesson 目录隔离；旁白+音色指纹；style 不参与（换皮不重 TTS）----


def _audio_fingerprint(narrate, voice):
    """8 字符内容指纹。voice/narrate 任一变化 → 路径变化 → 缓存失效。"""
    return hashlib.sha256(f"{voice}|{narrate}".encode()).hexdigest()[:8]


def _audio_paths(cache_dir, i, narrate, voice):
    fp = _audio_fingerprint(narrate, voice)
    raw = os.path.join(cache_dir, f"s{i}_{fp}_raw.wav")
    wav = os.path.join(cache_dir, f"s{i}_{fp}.wav")
    return raw, wav


def _write_cache_meta(raw_path, voice, narrate, rate):
    meta = {
        "ver": CACHE_VERSION,
        "voice": voice,
        "narrate": narrate,
        "rate": rate,
        "fp": _audio_fingerprint(narrate, voice),
    }
    with open(raw_path + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _cache_hit(raw_path, voice, narrate):
    """raw 存在 + sidecar meta 与旁白/音色一致且为当前解码版本才命中。"""
    if not os.path.isfile(raw_path):
        return False
    meta_path = raw_path + ".meta.json"
    if not os.path.isfile(meta_path):
        return False
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return False
    return (
        meta.get("ver") == CACHE_VERSION
        and meta.get("voice") == voice
        and meta.get("narrate") == narrate
        and meta.get("fp") == _audio_fingerprint(narrate, voice)
    )


def _ffprobe_duration(path):
    """通过 ffmpeg -i 解析 stderr 的 Duration 字段，返回秒；失败返回 None。"""
    try:
        r = subprocess.run([FFMPEG, "-i", path], capture_output=True, timeout=15)
        s = r.stderr.decode(errors="replace")
        m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}\.\d+)", s)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return None


def run_preview(
    tpl_path, scenes, style, W, H, motion_enabled, browser, preview_dir=None
):
    """截图 + 溢出探测。返回 0=OK，1=溢出，2=占位符闸门失败。不调 TTS/ffmpeg。"""
    lesson_key = os.path.splitext(os.path.basename(tpl_path))[0]
    if preview_dir:
        out_dir = (
            preview_dir
            if os.path.isabs(preview_dir)
            else os.path.join(ROOT, preview_dir)
        )
    else:
        out_dir = os.path.join(ROOT, "_build", "preview", lesson_key)
    os.makedirs(out_dir, exist_ok=True)
    print(f"   → {out_dir}")
    report = []
    gate_errs = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=browser, headless=True)
        page = b.new_page(viewport={"width": W, "height": H})
        for i, sc in enumerate(scenes):
            html = render_html(sc, W, H, style, motion_enabled=motion_enabled)
            ph_errs = validate_rendered_html(html, i)
            if ph_errs:
                gate_errs.extend(ph_errs)
            page.set_content(html)
            kind = resolve_kind(sc)
            motion = resolve_motion(sc, motion_enabled)
            # 缩略图取 t=0（起点画面），避免截到中间态
            apply_motion_css_vars(page, *motion_vars(motion, 0.0, 1.0))
            png = os.path.join(out_dir, f"s{i}.png")
            page.screenshot(path=png, type="png", full_page=False)
            # 溢出探测覆盖动效可达状态：none 只测静态；其余按各动效自身窗口采样 0..1
            seen, findings = set(), []
            for elapsed, duration in _motion_probe_states(motion):
                apply_motion_css_vars(page, *motion_vars(motion, elapsed, duration))
                for sel, msg in preview_overflow(page, W, H, kind=kind):
                    m = re.search(r"内容='(.*)'$", msg)
                    key = (sel, m.group(1) if m else msg)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append((sel, msg))
            report.append(
                {
                    "i": i,
                    "kind": kind,
                    "motion": motion,
                    "png": png,
                    "findings": [{"sel": sel, "msg": msg} for sel, msg in findings],
                    "placeholder_errs": ph_errs,
                }
            )
            tag = "OK" if not ph_errs and not findings else "FAIL"
            print(
                f"   scene {i} [{kind}/{_motion_display_name(motion)}]: {tag}  → {png}"
            )
        b.close()
    report_path = os.path.join(out_dir, "overflow.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    if gate_errs:
        print("PREVIEW GATE FAILED:")
        for e in gate_errs:
            print(" -", e)
        return 2
    bad = [r for r in report if r["findings"]]
    if bad:
        print(f"PREVIEW FAILED: {len(bad)}/{len(report)} 页有溢出（{report_path}）")
        for r in bad:
            for item in r["findings"]:
                print(f" - scene {r['i']} ({r['kind']}) {item['sel']}: {item['msg']}")
        return 1
    print(f"   PREVIEW OK  {len(report)} 页")
    return 0


if __name__ == "__main__":
    main()
