"""
make_video.py — 教学微课渲染器（Skill 阶段 2）

分镜 JSON → 校验 → 小米 TTS → style token 注入 layout → 教学动效截帧 → ffmpeg 合成 mp4

用法: python scripts/make_video.py examples/now_progressing.json [输出.mp4]
      [--style NAME] [--reuse-audio] [--no-motion] [--preview]
"""

import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import urllib.request

import imageio_ffmpeg
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TEMPLATE_DIR = os.path.join(ROOT, "templates")

MI_URL = os.environ.get(
    "MIMO_API_URL", "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
)
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
    "title": "",
    "rule": "讲解",
    "example": "例句",
    "mistake": "易错",
    "practice": "练习",
    "answer": "揭晓",
    "summary": "总结",
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
# 仅拦样式 hex token；不拦纯数字——教学文本里「100 米」「5 个动作」常见，误伤面太大。
LEAK_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
# 禁止 layout 在 HTML 节点属性里烘焙视觉样式（font-size/color/background/border）。
# 这些应走 style token；纯布局间距（margin/padding）允许内联。
_INLINE_BAKED_STYLE_RE = re.compile(
    r'style\s*=\s*"[^"]*(?:font-size\s*:|color\s*:|background[^:]*:|border[^:]*:)[^"]*"',
    re.IGNORECASE,
)

# 小米 TTS 音色白名单。闸门软提示（非阻塞）；实际拒绝在 TTS 阶段。
VOICE_WHITELIST = (
    "mimo_default",
    "冰糖",
    "茉莉",
    "苏打",
    "白桦",
    "Mia",
    "Chloe",
    "Milo",
    "Dean",
)


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
    return (
        html.replace("__W__", str(W))
        .replace("__H__", str(H))
        .replace("__HEADER__", sc.get("header", ""))
        .replace("__BADGE__", KIND_BADGE.get(kind, ""))
        .replace("__SUB__", sc.get("sub", ""))
        .replace("__ZH__", zh)
        .replace("__BODY__", body_html)
    )


def validate_layouts():
    errors = []
    banned = (
        "__PCT__",
        "__IDX__",
        "__TOTAL__",
        'class="progress"',
        "class='progress'",
        'class="pnum"',
        "class='pnum'",
        'class="track"',
        "class='track'",
    )
    for kind, fn in LAYOUT_FILES.items():
        raw = open(os.path.join(TEMPLATE_DIR, fn), encoding="utf-8").read()
        for token in banned:
            if token in raw:
                errors.append(f"{fn}: 禁止画面进度条/帧计数（发现 {token}）")
        for m in re.finditer(r">\s*(#[0-9a-fA-F]{3,8}|\d{2,3})\s*<", raw):
            errors.append(f"{fn}: 文本节点疑似烘焙了样式值 {m.group(1)!r}")
        for m in _INLINE_BAKED_STYLE_RE.finditer(raw):
            errors.append(
                f"{fn}: HTML 属性 style 烘焙了视觉样式 {m.group(0)[:60]!r}——应走 style token"
            )
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


# 教学弧相位（docs/teaching-method.md）：title → rule+ → example+ → (mistake) → practice → answer → summary
_ARC_PHASE = {
    "title": 0,
    "rule": 1,
    "example": 2,
    "mistake": 3,
    "practice": 4,
    "answer": 5,
    "summary": 6,
}


def validate_storyboard(tpl):
    """返回 (errors, warnings)。errors 非空 → 闸门失败；warnings 仅打印。"""
    errors, warnings = [], []
    voice = tpl.get("voice")
    if voice is not None and voice not in VOICE_WHITELIST:
        warnings.append(
            f"voice={voice!r} 不在小米 TTS 白名单 {VOICE_WHITELIST}（API 可能拒绝；非阻塞）"
        )
    scenes = tpl.get("scenes") or []
    if not scenes:
        errors.append("scenes 为空")
        return errors, warnings
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
                errors.append(
                    f"{prefix}: {field}={val!r} 像样式泄漏（色值/字号），不是教学内容"
                )
        sub = (sc.get("sub") or "").strip()
        if sub and LEAK_RE.match(sub):
            errors.append(f"{prefix}: sub={sub!r} 像样式泄漏")
        if "motion" in sc and sc["motion"] not in MOTIONS:
            errors.append(
                f"{prefix}: motion={sc['motion']!r} 非法（{', '.join(MOTIONS)}）"
            )
        if kind == "mistake":
            if "**" not in sc.get("body", ""):
                errors.append(
                    f"{prefix}: mistake（common_mistake）的 body 须用 ** 标出错误点"
                )
            if not (sc.get("zh") or sc.get("sub")):
                errors.append(f"{prefix}: mistake 须有 sub/zh 说明「为什么容易错」")
        if kind == "practice":
            if "**" not in sc.get("body", ""):
                errors.append(
                    f"{prefix}: practice（understanding_check）的 body 须用 ** 标出待判断点"
                )
            hold_v = float(sc.get("hold", 0) or 0)
            if hold_v < 3.0:
                errors.append(
                    f"{prefix}: practice hold={hold_v} 须 >= 3.0（docs/teaching-method.md）"
                )
        if kind == "answer":
            if "**" not in sc.get("body", ""):
                errors.append(
                    f"{prefix}: answer（check_reveal）的 body 须用 ** 标出正确知识点"
                )
        if role and role in ROLE_TO_KIND and ROLE_TO_KIND[role] != kind:
            errors.append(f"{prefix}: role={role} 与 kind={kind} 不一致")

    required = ["title", "rule", "example", "practice", "answer", "summary"]
    for k in required:
        if k not in kinds_seen:
            errors.append(
                f"缺少必要 kind={k}（教学弧不完整；见 docs/teaching-method.md）"
            )

    if kinds_seen and kinds_seen[0] != "title":
        errors.append(f"教学弧须以 title 开头（现在是 {kinds_seen[0]}）")
    if kinds_seen and kinds_seen[-1] != "summary":
        errors.append(f"教学弧须以 summary 结尾（现在是 {kinds_seen[-1]}）")
    if kinds_seen.count("title") > 1:
        errors.append("title 只能出现一次")
    if kinds_seen.count("summary") > 1:
        errors.append("summary 只能出现一次")
    if kinds_seen.count("practice") != 1 and "practice" in kinds_seen:
        errors.append("practice 须恰好一次（其后紧跟 answer）")
    if kinds_seen.count("answer") != 1 and "answer" in kinds_seen:
        errors.append("answer 须恰好一次（紧跟 practice）")

    last_phase, last_kind = -1, None
    for i, k in enumerate(kinds_seen):
        phase = _ARC_PHASE.get(k)
        if phase is None:
            continue
        if phase < last_phase:
            errors.append(
                f"scenes[{i}] 教学弧错位: kind={k} 出现在 {last_kind} 之后"
                f"（须 title→rule+→example+→(mistake)→practice→answer→summary）"
            )
        last_phase, last_kind = phase, k

    for j in range(len(kinds_seen) - 1):
        if kinds_seen[j] == "practice" and kinds_seen[j + 1] != "answer":
            errors.append(
                f"scenes[{j}] practice 后必须紧跟 answer（现在是 {kinds_seen[j + 1]}）"
            )

    if "practice" in kinds_seen:
        pi = kinds_seen.index("practice")
        if "mistake" not in kinds_seen[:pi]:
            warnings.append(
                f"scenes[{pi}] practice 前无 mistake（docs/teaching-method.md 推荐）"
            )
    return errors, warnings


def validate_rendered_html(html, scene_index):
    """占位符检查。溢出探测走 preview_overflow()，需 page 实测。"""
    errs = []
    left = PLACEHOLDER_RE.findall(html)
    if left:
        errs.append(f"scenes[{scene_index}] 渲染后仍残留占位符: {sorted(set(left))}")
    return errs


# 关键内容槽选择器（与 templates/layout-*.html 同步）。仅用于 preview 溢出探测。
# 按 kind 分组——layout 里 header 实际叫 .title/.big/.sum；mistake/practice/answer 的
# 正文叫 .q（不是 .body）；中文槽按 layout 不同叫 .zh/.why/.think/.explain。
_OVERFLOW_SELECTORS_BY_KIND = {
    "title": [".big", ".sub"],
    "rule": [".title", ".badge", ".sub", ".body"],
    "example": [".title", ".badge", ".sub", ".en", ".zh"],
    "mistake": [".title", ".badge", ".sub", ".q", ".why"],
    "practice": [".title", ".badge", ".sub", ".q", ".think"],
    "answer": [".title", ".badge", ".sub", ".mark", ".en", ".explain"],
    "summary": [".sum", ".next"],
}
# 兼容旧调用：未传 kind 时取所有选择器的并集。
_OVERFLOW_SELECTORS = sorted(
    {s for sels in _OVERFLOW_SELECTORS_BY_KIND.values() for s in sels}
)


def preview_overflow(page, W, H, kind=None):
    """在已 set_content 的 page 上测关键槽是否溢出视口。返回 list[(selector, msg)]。

    kind 提供时按 _OVERFLOW_SELECTORS_BY_KIND 取（精确匹配当前 layout 实际类名）；
    未提供时取所有选择器并集（兼容旧调用）。
    """
    if kind is not None and kind in _OVERFLOW_SELECTORS_BY_KIND:
        selectors = _OVERFLOW_SELECTORS_BY_KIND[kind]
    else:
        selectors = _OVERFLOW_SELECTORS
    js = """([W, H, sels]) => {
        const out = [];
        for (const sel of sels) {
            for (const el of document.querySelectorAll(sel)) {
                if (!el || !el.textContent || !el.textContent.trim()) continue;
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                if (r.right > W + 0.5 || r.bottom > H + 0.5 || r.left < -0.5) {
                    out.push([sel, el.tagName, r.left, r.top, r.right, r.bottom, (el.textContent || '').slice(0, 40)]);
                }
            }
        }
        return out;
    }"""
    out = []
    for sel, tag, l, t, r, b, txt in page.evaluate(js, [W, H, selectors]):
        out.append(
            (
                sel,
                f"{tag} {sel} 溢出视口 left={l:.0f} top={t:.0f} right={r:.0f} bottom={b:.0f}（viewport {W}x{H}），内容='{txt}'",
            )
        )
    return out


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
        n_frames = max(
            n_frames + 1, int(math.ceil(len(speech) * fps / float(SAMPLE_RATE) - 1e-9))
        )
        target = int(math.ceil(n_frames * SAMPLE_RATE / float(fps) - 1e-9))
    if target > len(speech):
        speech = np.concatenate(
            [speech, np.zeros(target - len(speech), dtype=np.float32)]
        )
    pcm = np.clip(np.rint(speech), -32768, 32767).astype(np.int16)
    return pcm, n_frames, n_frames / float(fps)


def main():
    args = [a for a in sys.argv[1:] if a]
    if not args or args[0] in ("-h", "--help"):
        print(
            "用法: python scripts/make_video.py <分镜.json> [输出.mp4] "
            "[--style NAME] [--reuse-audio] [--no-motion] [--preview]"
        )
        print(
            "  --reuse-audio  复用 _build/<lesson>/s*_<fp>_raw.wav（旁白+音色指纹命中才复用）"
        )
        print("  --no-motion    关闭 focus/pulse/zoom")
        print("  --preview      只截图+溢出探测，不调 TTS/ffmpeg")
        print("详见 SKILL.md / docs/audio.md / docs/motion.md")
        sys.exit(0 if args else 1)

    reuse_audio = "--reuse-audio" in args
    no_motion = "--no-motion" in args
    preview_flag = "--preview" in args
    args = [a for a in args if a not in ("--reuse-audio", "--no-motion", "--preview")]
    style_override = None
    if "--style" in args:
        i = args.index("--style")
        if i + 1 >= len(args):
            print("ERROR: --style 需要名称（teaching|classroom|explainer）")
            sys.exit(1)
        style_override = args[i + 1]
        args = args[:i] + args[i + 2 :]

    tpl_path = args[0]
    with open(tpl_path, encoding="utf-8") as f:
        tpl = json.load(f)
    out = (
        args[1]
        if len(args) > 1
        else os.path.join(
            ROOT, "output", os.path.splitext(os.path.basename(tpl_path))[0] + ".mp4"
        )
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

    print("0/4 校验布局与分镜...")
    layout_errs = validate_layouts()
    sb_errs, sb_warns = validate_storyboard(tpl)
    errors = layout_errs + sb_errs
    warnings = sb_warns
    for i, sc in enumerate(scenes):
        try:
            resolve_motion(sc, motion_enabled)
            html = render_html(sc, W, H, style)
            errors.extend(validate_rendered_html(html, i))
        except Exception as e:
            errors.append(f"scenes[{i}] 试渲染失败: {e}")
    for w in warnings:
        print(" WARN:", w)
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(" -", e)
        sys.exit(2)
    print(
        f"   style={style_name} ({style.get('style_id')}), motion={'on' if motion_enabled else 'off'}, scenes={len(scenes)} OK"
    )

    # 预览闸门：缩略图 + 溢出；--preview 到此结束
    print("1/4 预览截图与溢出...")
    preview_rc = run_preview(tpl_path, scenes, style, W, H, motion_enabled)
    if preview_flag:
        sys.exit(preview_rc)
    if preview_rc != 0:
        print("预览未通过，已跳过配音/成片。修分镜或模板后重试；或单独跑 --preview。")
        sys.exit(preview_rc)

    print("2/4 生成配音..." + (" (reuse-audio)" if reuse_audio else ""))
    wavs, durs, frame_counts = [], [], []
    lesson_key = os.path.splitext(os.path.basename(tpl_path))[0]
    cache_dir = os.path.join(ROOT, "_build", lesson_key)
    os.makedirs(cache_dir, exist_ok=True)
    for i, sc in enumerate(scenes):
        raw_path, wav_path = _audio_paths(cache_dir, i, sc["narrate"], voice)
        hold = float(sc.get("hold", 0.0))
        if reuse_audio and _cache_hit(raw_path, voice, sc["narrate"]):
            raw_pcm, rate = read_wav_pcm(raw_path)
            if rate != SAMPLE_RATE:
                raise RuntimeError(f"{raw_path} 采样率 {rate} != {SAMPLE_RATE}")
            src = "reuse"
        else:
            if reuse_audio:
                print(f"   cache miss scene {i}（旁白/音色变更或无缓存），重 TTS")
            raw_pcm = np.frombuffer(mi_tts(sc["narrate"], voice), dtype=np.int16)
            write_wav_pcm(raw_path, raw_pcm, SAMPLE_RATE)
            _write_cache_meta(raw_path, voice, sc["narrate"], SAMPLE_RATE)
            src = "tts"
        pcm, n_frames, dur = prepare_scene_audio(raw_pcm, hold, FPS)
        write_wav_pcm(wav_path, pcm, SAMPLE_RATE)
        wavs.append(wav_path)
        durs.append(dur)
        frame_counts.append(n_frames)
        print(
            f"   scene {i} [{resolve_kind(sc)}/{resolve_motion(sc, motion_enabled)}]: "
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
    return hashlib.sha1(f"{voice}|{narrate}".encode()).hexdigest()[:8]


def _audio_paths(cache_dir, i, narrate, voice):
    fp = _audio_fingerprint(narrate, voice)
    raw = os.path.join(cache_dir, f"s{i}_{fp}_raw.wav")
    wav = os.path.join(cache_dir, f"s{i}_{fp}.wav")
    return raw, wav


def _write_cache_meta(raw_path, voice, narrate, rate):
    meta = {
        "voice": voice,
        "narrate": narrate,
        "rate": rate,
        "fp": _audio_fingerprint(narrate, voice),
    }
    with open(raw_path + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _cache_hit(raw_path, voice, narrate):
    """raw 存在 + sidecar meta 与旁白/音色一致才命中。缺 meta → 失效（防旧共享缓存串课）。"""
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
        meta.get("voice") == voice
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


def run_preview(tpl_path, scenes, style, W, H, motion_enabled):
    """截图 + 溢出探测。返回 0=OK，1=溢出，2=占位符闸门失败。不调 TTS/ffmpeg。"""
    lesson_key = os.path.splitext(os.path.basename(tpl_path))[0]
    out_dir = os.path.join(ROOT, "_build", "preview", lesson_key)
    os.makedirs(out_dir, exist_ok=True)
    print(f"   → {out_dir}")
    report = []
    gate_errs = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, headless=True)
        page = b.new_page(viewport={"width": W, "height": H})
        for i, sc in enumerate(scenes):
            html = render_html(sc, W, H, style)
            ph_errs = validate_rendered_html(html, i)
            if ph_errs:
                gate_errs.extend(ph_errs)
            page.set_content(html)
            # 静态预览：动效取 t=0，避免截到中间态
            apply_motion_css_vars(
                page, *motion_vars(resolve_motion(sc, motion_enabled), 0.0)
            )
            png = os.path.join(out_dir, f"s{i}.png")
            page.screenshot(path=png, type="png", full_page=False)
            findings = preview_overflow(page, W, H, kind=resolve_kind(sc))
            report.append(
                {
                    "i": i,
                    "kind": resolve_kind(sc),
                    "motion": resolve_motion(sc, motion_enabled),
                    "png": png,
                    "findings": [{"sel": sel, "msg": msg} for sel, msg in findings],
                    "placeholder_errs": ph_errs,
                }
            )
            tag = "OK" if not ph_errs and not findings else "FAIL"
            print(
                f"   scene {i} [{resolve_kind(sc)}/{resolve_motion(sc, motion_enabled)}]: {tag}  → {png}"
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
