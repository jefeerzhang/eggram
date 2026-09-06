# -*- coding: utf-8 -*-
"""
make_video.py — 语法微课渲染器（Skill 阶段 2）

分镜 JSON → 校验 → 小米 TTS → style token 注入 layout → 教学动效截帧 → ffmpeg 合成 mp4

用法: python scripts/make_video.py examples/now_progressing.json [输出.mp4] [--style NAME] [--reuse-audio] [--no-motion]
"""
import os, sys, json, re, math, base64, subprocess, urllib.request
import numpy as np
from playwright.sync_api import sync_playwright
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TEMPLATE_DIR = os.path.join(ROOT, "templates")

MI_URL = os.environ.get("MIMO_API_URL", "https://token-plan-cn.xiaomimimo.com/v1/chat/completions")
MI_KEY = os.environ.get("MIMO_API_KEY", "")
MI_MODEL = "mimo-v2.5-tts"
SAMPLE_RATE = 24000

LAYOUT_FILES = {
    "title": "layout-title.html",
    "rule": "layout-rule.html",
    "example": "layout-example.html",
    "mistake": "layout-mistake.html",
    "practice": "layout-practice.html",
    "answer": "layout-answer.html",
    "summary": "layout-summary.html",
}
KIND_BADGE = {
    "title": "", "rule": "讲解", "example": "例句", "mistake": "易错",
    "practice": "练习", "answer": "揭晓", "summary": "总结",
}
ROLE_TO_KIND = {
    "learning_objective": "title",
    "concept_anchor": "rule",
    "worked_demo": "example",
    "common_mistake": "mistake",
    "understanding_check": "practice",
    "check_reveal": "answer",
    "recap": "summary",
}
KIND_TO_ROLE = {v: k for k, v in ROLE_TO_KIND.items()}

# 默认动效：提醒注意力，不做花哨转场
KIND_MOTION = {
    "title": "zoom_in",
    "rule": "focus",
    "example": "focus",
    "mistake": "pulse",
    "practice": "pulse",
    "answer": "zoom_in",
    "summary": "zoom_out",
}
MOTIONS = ("none", "focus", "pulse", "zoom_in", "zoom_out")

# 注入到每页：用 CSS 变量驱动，逐帧 evaluate 更新（避免每帧 set_content）
MOTION_CSS = """
<style id="eggram-motion">
  .stage{
    transform: scale(var(--m-scale, 1));
    transform-origin: 50% 42%;
    will-change: transform;
  }
  .hl, .err{
    display: inline-block;
    transform: scale(var(--m-hl, 1));
    transform-origin: center center;
    filter: drop-shadow(0 0 calc(var(--m-glow, 0) * 16px) currentColor);
    will-change: transform, filter;
  }
</style>
"""

PLACEHOLDER_RE = re.compile(r"__[A-Z0-9_]+__")
LEAK_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$|^\d{2,3}$")


def load_style(style_name="teaching"):
    path = os.path.join(TEMPLATE_DIR, f"style-{style_name}.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"风格文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def style_token_map(style):
    p, t, e = style["palette"], style["typography"], style.get("exercise", {})
    return {
        "__BG__": p["bg"],
        "__BG2__": p["bg_grad2"],
        "__SURFACE__": p["surface"],
        "__SURFACE_BORDER__": p["surface_border"],
        "__INK__": p["ink"],
        "__INK_SUB__": p["ink_sub"],
        "__ACCENT__": p["accent"],
        "__CORRECT__": p["correct"],
        "__WRONG__": p["wrong"],
        "__PRACTICE_FILL__": p.get("practice_fill", "rgba(0,0,0,0.25)"),
        "__FONT__": t["family"],
        "__TITLE_SIZE__": str(t["title_size"]),
        "__BODY_SIZE__": str(t["body_size"]),
        "__SUB_SIZE__": str(t["sub_size"]),
        "__BADGE_SIZE__": str(t["badge_size"]),
        "__EX_BORDER_STYLE__": e.get("border_style", "dashed"),
        "__EX_BORDER_WIDTH__": e.get("border_width", "3px"),
        "__EX_BORDER_COLOR__": e.get("border_color", p["accent"]),
    }


def inject_style(html, style):
    for k, v in style_token_map(style).items():
        html = html.replace(k, str(v))
    return html


def load_layout(kind):
    fn = LAYOUT_FILES.get(kind)
    if not fn:
        raise ValueError(f"未知 kind: {kind}（可选: {', '.join(LAYOUT_FILES)}）")
    path = os.path.join(TEMPLATE_DIR, fn)
    with open(path, encoding="utf-8") as f:
        return f.read()


def resolve_kind(sc):
    kind = sc.get("kind")
    role = sc.get("role")
    if kind:
        return kind
    if role and role in ROLE_TO_KIND:
        return ROLE_TO_KIND[role]
    raise ValueError("scene 缺少 kind（或可映射的 role）")


def resolve_motion(sc, motion_enabled=True):
    if not motion_enabled:
        return "none"
    m = sc.get("motion")
    if m is None or m == "":
        return KIND_MOTION.get(resolve_kind(sc), "none")
    if m not in MOTIONS:
        raise ValueError(f"未知 motion={m!r}（可选: {', '.join(MOTIONS)}）")
    return m


def highlight_body(body, kind):
    hl_cls = "err" if kind in ("practice", "mistake") else "hl"
    parts = body.split("**")
    out = []
    for j, part in enumerate(parts):
        out.append(f'<span class="{hl_cls}">{part}</span>' if j % 2 == 1 else part)
    return "".join(out)


def ease_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def motion_vars(motion, t):
    """返回 (--m-scale, --m-hl, --m-glow)。t∈[0,1] 为段内进度。"""
    t = max(0.0, min(1.0, float(t)))
    if motion == "none":
        return 1.0, 1.0, 0.0
    if motion == "zoom_in":
        return 1.0 + 0.055 * ease_out_cubic(t), 1.0, 0.0
    if motion == "zoom_out":
        return 1.06 - 0.06 * ease_out_cubic(t), 1.0, 0.0
    if motion == "focus":
        # 整页轻推近 + 高亮词一次聚焦后保持微强调
        s = 1.0 + 0.028 * ease_out_cubic(min(t * 1.6, 1.0))
        if t < 0.45:
            pulse = math.sin((t / 0.45) * math.pi)
        else:
            pulse = 0.22
        return s, 1.0 + 0.14 * pulse, 0.55 * pulse
    if motion == "pulse":
        # 易错/练习：高亮词两下轻跳，提醒「看这里」
        pulse = 0.55 + 0.45 * math.sin(t * math.pi * 2.0)
        return 1.0 + 0.012 * pulse, 1.0 + 0.16 * pulse, 0.5 * pulse
    return 1.0, 1.0, 0.0


def apply_motion_css_vars(page, scale, hl, glow):
    page.evaluate(
        """([s, h, g]) => {
          const b = document.body;
          b.style.setProperty('--m-scale', String(s));
          b.style.setProperty('--m-hl', String(h));
          b.style.setProperty('--m-glow', String(g));
        }""",
        [round(scale, 4), round(hl, 4), round(glow, 4)],
    )


def render_html(sc, W, H, style):
    """教学页 HTML；动效由 CSS 变量在截帧时驱动。无进度条/帧号。"""
    kind = resolve_kind(sc)
    html = inject_style(load_layout(kind), style)
    if "</head>" in html:
        html = html.replace("</head>", MOTION_CSS + "</head>", 1)
    else:
        html = MOTION_CSS + html
    body_html = highlight_body(sc.get("body", ""), kind)
    zh = sc.get("zh", sc.get("sub", ""))
    return (html
        .replace("__W__", str(W)).replace("__H__", str(H))
        .replace("__HEADER__", sc.get("header", ""))
        .replace("__BADGE__", KIND_BADGE.get(kind, ""))
        .replace("__SUB__", sc.get("sub", ""))
        .replace("__ZH__", zh)
        .replace("__BODY__", body_html))


def validate_layouts():
    errors = []
    banned = ("__PCT__", "__IDX__", "__TOTAL__", "class=\"progress\"", "class='progress'",
              "class=\"pnum\"", "class='pnum'", "class=\"track\"", "class='track'")
    for kind, fn in LAYOUT_FILES.items():
        raw = open(os.path.join(TEMPLATE_DIR, fn), encoding="utf-8").read()
        for token in banned:
            if token in raw:
                errors.append(f"{fn}: 禁止画面进度条/帧计数（发现 {token}）")
        for m in re.finditer(r">\s*(#[0-9a-fA-F]{3,8}|\d{2,3})\s*<", raw):
            errors.append(f"{fn}: 文本节点疑似烘焙了样式值 {m.group(1)!r}")
        need = ["__HEADER__"] if kind == "title" else ["__HEADER__", "__BODY__"]
        if kind in ("rule", "example", "mistake", "practice", "answer"):
            need += ["__SUB__", "__BADGE__"]
        if kind == "summary":
            need = ["__BODY__", "__SUB__"]
        if kind == "example":
            need.append("__ZH__")
        if kind == "mistake":
            need.append("__ZH__")
        for slot in need:
            if slot not in raw:
                errors.append(f"{fn}: 缺少内容槽 {slot}")
        for slot in ("__BG__", "__ACCENT__", "__INK__"):
            if slot not in raw:
                errors.append(f"{fn}: 缺少风格槽 {slot}（须由 style-*.json 注入）")
    return errors


def validate_storyboard(tpl):
    errors = []
    scenes = tpl.get("scenes") or []
    if not scenes:
        errors.append("scenes 为空")
    kinds_seen = []
    for i, sc in enumerate(scenes):
        prefix = f"scenes[{i}]"
        try:
            kind = resolve_kind(sc)
        except ValueError as e:
            errors.append(f"{prefix}: {e}")
            continue
        if kind not in LAYOUT_FILES:
            errors.append(f"{prefix}: 未知 kind={kind!r}")
            continue
        kinds_seen.append(kind)
        role = sc.get("role") or KIND_TO_ROLE.get(kind, "")
        for field in ("header", "body", "narrate"):
            val = (sc.get(field) or "").strip()
            if not val:
                errors.append(f"{prefix}: {field} 不能为空")
            elif LEAK_RE.match(val):
                errors.append(f"{prefix}: {field}={val!r} 像样式泄漏（色值/字号），不是教学内容")
        sub = (sc.get("sub") or "").strip()
        if sub and LEAK_RE.match(sub):
            errors.append(f"{prefix}: sub={sub!r} 像样式泄漏")
        if "motion" in sc and sc["motion"] not in MOTIONS:
            errors.append(f"{prefix}: motion={sc['motion']!r} 非法（{', '.join(MOTIONS)}）")
        if kind == "mistake":
            if "**" not in sc.get("body", ""):
                errors.append(f"{prefix}: mistake（common_mistake）的 body 须用 ** 标出错误点")
            if not (sc.get("zh") or sc.get("sub")):
                errors.append(f"{prefix}: mistake 须有 sub/zh 说明「为什么容易错」")
        if kind == "practice":
            if "**" not in sc.get("body", ""):
                errors.append(f"{prefix}: practice（understanding_check）的 body 须用 ** 标出待判断点")
            if float(sc.get("hold", 0) or 0) < 2.5:
                errors.append(f"{prefix}: practice 建议 hold>=3.0（留思考时间）")
        if kind == "answer":
            if "**" not in sc.get("body", ""):
                errors.append(f"{prefix}: answer（check_reveal）的 body 须用 ** 标出正确语法点")
        if role and role in ROLE_TO_KIND and ROLE_TO_KIND[role] != kind:
            errors.append(f"{prefix}: role={role} 与 kind={kind} 不一致")
    required = ["title", "rule", "example", "practice", "answer", "summary"]
    for k in required:
        if k not in kinds_seen:
            errors.append(f"缺少必要 kind={k}（教学弧不完整；见 docs/teaching-method.md）")
    return errors


def validate_rendered_html(html, scene_index):
    left = PLACEHOLDER_RE.findall(html)
    if left:
        return [f"scenes[{scene_index}] 渲染后仍残留占位符: {sorted(set(left))}"]
    return []


def mi_tts(text, voice):
    if not MI_KEY:
        raise RuntimeError("未设置环境变量 MIMO_API_KEY（小米 TTS）")
    payload = {
        "model": MI_MODEL,
        "messages": [{"role": "user", "content": ""}, {"role": "assistant", "content": text}],
        "audio": {"format": "wav", "voice": voice},
        "stream": False,
    }
    req = urllib.request.Request(MI_URL, data=json.dumps(payload).encode(), method="POST")
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
    import wave
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm, rate


def write_wav_pcm(path, pcm, rate=SAMPLE_RATE):
    import wave
    pcm = np.asarray(pcm, dtype=np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


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

    返回 (pcm_int16, n_frames, duration_sec)。
    """
    speech = np.asarray(raw_pcm, dtype=np.float32).copy()
    hold = max(0.0, float(hold))
    speech = _fade_edges_in_silence(speech, fade_sec)
    pad_n = int(round((hold + max(0.0, float(tail_pad))) * SAMPLE_RATE))
    if pad_n > 0:
        speech = np.concatenate([speech, np.zeros(pad_n, dtype=np.float32)])
    # ceil 帧数，保证画面覆盖全部样本；禁止裁切旁白
    dur = len(speech) / float(SAMPLE_RATE)
    n_frames = max(1, int(math.ceil(dur * fps - 1e-9)))
    target = int(math.ceil(n_frames * SAMPLE_RATE / float(fps) - 1e-9))
    if target < len(speech):
        n_frames = max(n_frames + 1, int(math.ceil(len(speech) * fps / float(SAMPLE_RATE) - 1e-9)))
        target = int(math.ceil(n_frames * SAMPLE_RATE / float(fps) - 1e-9))
    if target > len(speech):
        speech = np.concatenate([speech, np.zeros(target - len(speech), dtype=np.float32)])
    pcm = np.clip(np.rint(speech), -32768, 32767).astype(np.int16)
    return pcm, n_frames, n_frames / float(fps)


def main():
    args = [a for a in sys.argv[1:] if a]
    if not args or args[0] in ("-h", "--help"):
        print("用法: python scripts/make_video.py <分镜.json> [输出.mp4] [--style NAME] [--reuse-audio] [--no-motion]")
        print("  --reuse-audio  复用 _build/s*_raw.wav（仍 prepare / 音画锁）")
        print("  --no-motion    关闭 focus/pulse/zoom")
        print("详见 SKILL.md / docs/audio.md / docs/motion.md")
        sys.exit(0 if args else 1)

    reuse_audio = "--reuse-audio" in args
    no_motion = "--no-motion" in args
    args = [a for a in args if a not in ("--reuse-audio", "--no-motion")]
    style_override = None
    if "--style" in args:
        i = args.index("--style")
        if i + 1 >= len(args):
            print("ERROR: --style 需要名称（teaching|classroom|explainer）")
            sys.exit(1)
        style_override = args[i + 1]
        args = args[:i] + args[i + 2:]

    tpl_path = args[0]
    with open(tpl_path, encoding="utf-8") as f:
        tpl = json.load(f)
    out = args[1] if len(args) > 1 else os.path.join(
        ROOT, "output", os.path.splitext(os.path.basename(tpl_path))[0] + ".mp4"
    )
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    style_name = style_override or tpl.get("style", "teaching")
    style = load_style(style_name)
    W = int(tpl.get("width", 1280))
    H = int(tpl.get("height", 720))
    FPS = int(tpl.get("fps", 30))
    voice = tpl.get("voice", "茉莉")
    scenes = tpl["scenes"]
    motion_enabled = (not no_motion) and (tpl.get("motion", True) is not False)

    print("0/3 校验布局与分镜...")
    errors = validate_layouts() + validate_storyboard(tpl)
    for i, sc in enumerate(scenes):
        try:
            resolve_motion(sc, motion_enabled)
            html = render_html(sc, W, H, style)
            errors.extend(validate_rendered_html(html, i))
        except Exception as e:
            errors.append(f"scenes[{i}] 试渲染失败: {e}")
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(" -", e)
        sys.exit(2)
    print(f"   style={style_name} ({style.get('style_id')}), motion={'on' if motion_enabled else 'off'}, scenes={len(scenes)} OK")

    print("1/3 生成配音..." + (" (reuse-audio)" if reuse_audio else ""))
    wavs, durs, frame_counts = [], [], []
    for i, sc in enumerate(scenes):
        raw_path = os.path.join(ROOT, "_build", f"s{i}_raw.wav")
        wav = os.path.join(ROOT, "_build", f"s{i}.wav")
        os.makedirs(os.path.dirname(wav), exist_ok=True)
        hold = float(sc.get("hold", 0.0))
        if reuse_audio and os.path.isfile(raw_path):
            raw_pcm, rate = read_wav_pcm(raw_path)
            if rate != SAMPLE_RATE:
                raise RuntimeError(f"{raw_path} 采样率 {rate} != {SAMPLE_RATE}")
            src = "reuse"
        elif reuse_audio and os.path.isfile(wav):
            # 兼容旧缓存：若无 raw，把现有 wav 当旁白（可能已含错误处理，仍再跑 prepare）
            raw_pcm, rate = read_wav_pcm(wav)
            if rate != SAMPLE_RATE:
                raise RuntimeError(f"{wav} 采样率 {rate} != {SAMPLE_RATE}")
            write_wav_pcm(raw_path, raw_pcm, rate)
            src = "reuse-legacy"
        else:
            raw_pcm = np.frombuffer(mi_tts(sc["narrate"], voice), dtype=np.int16)
            write_wav_pcm(raw_path, raw_pcm, SAMPLE_RATE)
            src = "tts"
        pcm, n_frames, dur = prepare_scene_audio(raw_pcm, hold, FPS)
        write_wav_pcm(wav, pcm, SAMPLE_RATE)
        wavs.append(wav)
        durs.append(dur)
        frame_counts.append(n_frames)
        print(f"   scene {i} [{resolve_kind(sc)}/{resolve_motion(sc, motion_enabled)}]: {dur:.2f}s ({n_frames}f, hold={hold:.1f}, {src})")
    print(f"   总时长 = {sum(durs):.2f}s  /  {sum(frame_counts)} frames @ {FPS}fps")

    print("2/3 渲染 HTML 画面并合成...")
    n = len(wavs)
    # 音轨已在 prepare_scene_audio 完成淡化+hold 填充；此处只 aresample + concat，不再二次 afade
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-nostats",
           "-framerate", str(FPS), "-f", "image2pipe", "-vcodec", "png", "-i", "-"]
    for w in wavs:
        cmd += ["-i", w]
    fparts = [f"[{i+1}:a]aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=mono[a{i}]" for i in range(n)]
    chain = "".join(f"[a{i}]" for i in range(n))
    fparts.append(f"{chain}concat=n={n}:v=0:a=1[outa]")
    cmd += ["-filter_complex", ";".join(fparts), "-map", "0:v", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", str(SAMPLE_RATE), "-ac", "1",
            "-movflags", "+faststart", out]
    # 不用 -shortest：音画已按帧锁定同长

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    gi = 0
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, headless=True)
        page = b.new_page(viewport={"width": W, "height": H})
        for i, sc in enumerate(scenes):
            html = render_html(sc, W, H, style)
            left = validate_rendered_html(html, i)
            if left:
                proc.kill()
                print("VALIDATION FAILED mid-render:", left)
                sys.exit(2)
            page.set_content(html)
            motion = resolve_motion(sc, motion_enabled)
            n_frames = frame_counts[i]
            if motion == "none" or n_frames == 1:
                apply_motion_css_vars(page, *motion_vars(motion, 0.0))
                shot = page.screenshot(type="png")
                for _ in range(n_frames):
                    proc.stdin.write(shot)
                    gi += 1
            else:
                for k in range(n_frames):
                    t = k / max(n_frames - 1, 1)
                    apply_motion_css_vars(page, *motion_vars(motion, t))
                    proc.stdin.write(page.screenshot(type="png"))
                    gi += 1
        b.close()
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", errors="replace")
    rc = proc.wait()
    print(f"   {gi} 帧 pipe 完成, rc={rc}")
    if rc != 0:
        print("FFMPEG ERR:", err[-2000:])
        sys.exit(1)
    print(f"DONE -> {out}  ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
