"""
make_video.py — 教学微课渲染器（Skill 阶段 2）

分镜 JSON → 校验 → 小米 TTS → style token 注入 layout → 教学动效截帧 → ffmpeg 合成 mp4

用法: python scripts/make_video.py examples/now_progressing.json [输出.mp4]
      [--style NAME] [--reuse-audio] [--no-motion] [--preview]
"""

import argparse
import base64
import hashlib
import html
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

import imageio_ffmpeg
import numpy as np
from charts import resolve_chart
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
TEMPLATE_DIR = os.path.join(ROOT, "templates")

# 音频缓存解码版本。错误解码路径生成的旧 raw 无此版本号，缓存不命中。
CACHE_VERSION = "2"

MI_URL = os.environ.get(
    "MIMO_API_URL", "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
)
MI_KEY = os.environ.get("MIMO_API_KEY", "")
MI_MODEL = "mimo-v2.5-tts"
SAMPLE_RATE = 24000

LAYOUT_FILES = {
    "title": "layout-title.html",
    "rule": "layout-rule.html",
    "diagram": "layout-diagram.html",
    "example": "layout-example.html",
    "mistake": "layout-mistake.html",
    "practice": "layout-practice.html",
    "answer": "layout-answer.html",
    "summary": "layout-summary.html",
}
# 排版变体：kind → {variant_id → layout_file}
LAYOUT_VARIANTS = {
    "rule": {
        "side": "layout-rule-side.html",
        "formula": "layout-rule-formula.html",
    },
    "example": {
        "side": "layout-example-side.html",
    },
}
KIND_BADGE = {
    "title": "",
    "rule": "讲解",
    "diagram": "图解",
    "example": "例句",
    "mistake": "易错",
    "practice": "练习",
    "answer": "揭晓",
    "summary": "总结",
}
ROLE_TO_KIND = {
    "learning_objective": "title",
    "concept_anchor": "rule",
    "visual_anchor": "diagram",
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
    "diagram": "focus",
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
  .icon-inline{
    display: inline-flex;
    width: 1.15em;
    height: 1.15em;
    vertical-align: -0.2em;
    margin: 0 0.08em;
    color: inherit;
  }
  .icon-inline svg{width:100%;height:100%;display:block;stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
</style>
"""

# 教学场景图标（inline SVG，currentColor 继承 .hl/.err 色，跟着 pulse 一起动）
#  body 中使用 [name]**词** 语法；placeholder 会被 highlight_body 还原为 <span class="icon-inline">SVG</span>
_ICON_SVG_ATTR = 'viewBox="0 0 24 24"'
ICONS = {
    "brain": f'<svg {_ICON_SVG_ATTR}><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 3 3 3 0 0 0 1 2 3 3 0 0 0 3 3M9 4a3 3 0 0 1 3 3v10a1 1 0 0 1-1 1M9 4v13M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 3 3 3 0 0 1-1 2 3 3 0 0 1-3 3M15 4a3 3 0 0 0-3 3v10a1 1 0 0 0 1 1M15 4v13"/></svg>',
    "wrench": f'<svg {_ICON_SVG_ATTR}><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    "memory": f'<svg {_ICON_SVG_ATTR}><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 4v4M16 4v4M4 10h16M8 16h2M14 16h2"/></svg>',
    "cycle": f'<svg {_ICON_SVG_ATTR}><path d="M21 12a9 9 0 1 1-3.5-7.1"/><path d="M21 3v6h-6"/></svg>',
    "harness": f'<svg {_ICON_SVG_ATTR}><rect x="3" y="6" width="18" height="14" rx="3"/><path d="M8 6V4h8v2"/><circle cx="12" cy="13" r="2.5"/><path d="M12 16v2M9 10l-2-2M15 10l2-2"/></svg>',
    "bulb": f'<svg {_ICON_SVG_ATTR}><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.7.7 1 1.4 1 2.3h6c0-.9.3-1.6 1-2.3A7 7 0 0 0 12 2z"/></svg>',
    "cross": f'<svg {_ICON_SVG_ATTR}><circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/></svg>',
    "pencil": f'<svg {_ICON_SVG_ATTR}><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
    "check": f'<svg {_ICON_SVG_ATTR}><circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-6"/></svg>',
    "bookmark": f'<svg {_ICON_SVG_ATTR}><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>',
}
_ICON_TOKEN_RE = re.compile(r"\[(\w+)\]")

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


def resolve_voice(sc, tpl):
    """解析场景音色：scene.voice → voices[scene.voice] → tpl.voice → '茉莉'。
    支持对话模式：顶层 voices={"narrator":"苏打","student":"冰糖"}，
    每页 scene.voice 可写角色 ID（如 "narrator"）或直接写音色名（如 "苏打"）。"""
    voices_map = tpl.get("voices", {})
    default_voice = tpl.get("voice", "茉莉")
    sc_voice = sc.get("voice")
    if sc_voice:
        # 先查 voices 映射（角色 ID → 音色名）
        if sc_voice in voices_map:
            return voices_map[sc_voice]
        return sc_voice
    return default_voice


def load_style(style_name="teaching"):
    path = os.path.join(TEMPLATE_DIR, f"style-{style_name}.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"风格文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _palette_hex(palette, key, default=""):
    """从 palette 提取 hex 值，兼容字符串与对象格式。"""
    val = palette.get(key, default)
    if isinstance(val, dict):
        return val.get("hex", default)
    return val if isinstance(val, str) else default


def style_token_map(style):
    p, t, e = style["palette"], style["typography"], style.get("exercise", {})

    def h(k, d=""):
        return _palette_hex(p, k, d)

    return {
        "__BG__": h("bg"),
        "__BG2__": h("bg_grad2"),
        "__SURFACE__": h("surface"),
        "__SURFACE_BORDER__": h("surface_border"),
        "__INK__": h("ink"),
        "__INK_SUB__": h("ink_sub"),
        "__ACCENT__": h("accent"),
        "__CORRECT__": h("correct"),
        "__WRONG__": h("wrong"),
        "__WARNING__": h("warning", h("accent")),
        "__INFO__": h("info", h("accent")),
        "__HIGHLIGHT__": h("highlight", h("accent")),
        "__MUTED__": h("muted", h("ink_sub")),
        "__PRACTICE_FILL__": h("practice_fill", "rgba(0,0,0,0.25)"),
        "__FONT__": t["family"],
        "__TITLE_SIZE__": str(t["title_size"]),
        "__BODY_SIZE__": str(t["body_size"]),
        "__SUB_SIZE__": str(t["sub_size"]),
        "__BADGE_SIZE__": str(t["badge_size"]),
        "__EX_BORDER_STYLE__": e.get("border_style", "dashed"),
        "__EX_BORDER_WIDTH__": e.get("border_width", "3px"),
        "__EX_BORDER_COLOR__": e.get("border_color", h("accent")),
    }


def inject_style(html, style):
    for k, v in style_token_map(style).items():
        html = html.replace(k, str(v))
    return html


def load_layout(kind, variant=None):
    """加载 layout HTML。variant 非空时尝试加载变体，不存在则回退默认。"""
    fn = LAYOUT_FILES.get(kind)
    if not fn:
        raise ValueError(f"未知 kind: {kind}（可选: {', '.join(LAYOUT_FILES)}）")
    # 尝试加载变体
    if variant and kind in LAYOUT_VARIANTS:
        vfn = LAYOUT_VARIANTS[kind].get(variant)
        if vfn:
            vpath = os.path.join(TEMPLATE_DIR, vfn)
            if os.path.isfile(vpath):
                with open(vpath, encoding="utf-8") as f:
                    return f.read()
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
    """解析 motion 字段。返回 list[{type, delay}] 格式。
    向后兼容：字符串 "focus" → [{"type": "focus", "delay": 0}]"""
    if not motion_enabled:
        return [{"type": "none", "delay": 0}]
    m = sc.get("motion")
    if m is None or m == "":
        default = KIND_MOTION.get(resolve_kind(sc), "none")
        return [{"type": default, "delay": 0}]
    # 字符串格式（向后兼容）
    if isinstance(m, str):
        if m not in MOTIONS:
            raise ValueError(f"未知 motion={m!r}（可选: {', '.join(MOTIONS)}）")
        return [{"type": m, "delay": 0}]
    # 数组格式（动效序列化）
    if isinstance(m, list):
        effects = []
        for item in m:
            if isinstance(item, str):
                if item not in MOTIONS:
                    raise ValueError(
                        f"未知 motion={item!r}（可选: {', '.join(MOTIONS)}）"
                    )
                effects.append({"type": item, "delay": 0})
            elif isinstance(item, dict):
                t = item.get("type", "none")
                if t not in MOTIONS:
                    raise ValueError(
                        f"未知 motion type={t!r}（可选: {', '.join(MOTIONS)}）"
                    )
                effects.append({"type": t, "delay": float(item.get("delay", 0))})
            else:
                raise ValueError(f"motion 数组元素格式错误: {item!r}")
        return effects if effects else [{"type": "none", "delay": 0}]
    raise ValueError(f"motion 格式错误: {m!r}（应为字符串或数组）")


def _motion_display_name(effects):
    """用于日志显示的动效名称。"""
    if len(effects) == 1:
        return effects[0]["type"]
    return "+".join(e["type"] for e in effects)


def _escape(text):
    """把教学字段当纯文本：& < > \" ' 按字面显示；下划线转为实体以中和 __...__ 槽位 token，
    避免内容被后续槽二次解释或被误判为残留占位符。
    换行处理：JSON 中的 \\n、真实换行、手写 <br> 均统一转为 HTML <br>。"""
    s = str(text)
    # 1. 先统一换行：JSON 转义 \\n、真实换行、手写 <br> / <br/> / <br /> 均归一
    s = s.replace("\\n", "\n")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    # 2. 保护 <br>：先提取，再 escape，最后还原
    s = s.replace("\n", "@@BR@@")
    s = html.escape(s, quote=True).replace("_", "&#95;")
    s = s.replace("@@BR@@", "<br>")
    return s


def highlight_body(body, kind):
    hl_cls = "err" if kind in ("practice", "mistake") else "hl"
    # 1. [name] token 提取为占位符（避免被 _escape 转义）
    icon_map = {}
    counter = [0]

    def stash(m):
        name = m.group(1)
        if name not in ICONS:
            return m.group(0)
        key = f"@@ICON{counter[0]}@@"
        icon_map[key] = ICONS[name]
        counter[0] += 1
        return key

    body_with_ph = _ICON_TOKEN_RE.sub(stash, str(body))
    parts = body_with_ph.split("**")
    out = []
    for j, part in enumerate(parts):
        esc = _escape(part)
        # 2. 占位符原为 <span class="icon-inline">SVG</span>，嵌入 hl/err span 内部
        for k, svg in icon_map.items():
            esc = esc.replace(k, f'<span class="icon-inline">{svg}</span>')
        out.append(f'<span class="{hl_cls}">{esc}</span>' if j % 2 == 1 else esc)
    return "".join(out)


def ease_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def motion_vars(effects, elapsed_seconds, duration_seconds):
    """返回 (--m-scale, --m-hl, --m-glow)。elapsed/duration/delay 均以秒计。
    延迟后在剩余旁白时间内完成动效，旁白结束后（elapsed≥duration）冻结在末态；
    delay ≥ duration（延迟不早于旁白结束）不启动。多动效叠加：scale/hl/glow 各取最大值。"""
    duration_seconds = max(0.0, float(duration_seconds))
    elapsed_seconds = max(0.0, min(duration_seconds, float(elapsed_seconds)))
    max_scale, max_hl, max_glow = 1.0, 1.0, 0.0
    for eff in effects:
        etype = eff["type"]
        delay = eff.get("delay", 0)
        if delay > 0 and (elapsed_seconds < delay or delay >= duration_seconds):
            continue
        remaining = duration_seconds - delay
        et = (elapsed_seconds - delay) / remaining if remaining > 0 else 0.0
        s, h, g = _single_motion_vars(etype, et)
        max_scale = max(max_scale, s)
        max_hl = max(max_hl, h)
        max_glow = max(max_glow, g)
    return max_scale, max_hl, max_glow


def _single_motion_vars(motion, t):
    """单动效计算。"""
    if motion == "none":
        return 1.0, 1.0, 0.0
    if motion == "zoom_in":
        return 1.0 + 0.055 * ease_out_cubic(t), 1.0, 0.0
    if motion == "zoom_out":
        return 1.06 - 0.06 * ease_out_cubic(t), 1.0, 0.0
    if motion == "focus":
        s = 1.0 + 0.028 * ease_out_cubic(min(t * 1.6, 1.0))
        if t < 0.45:
            pulse = math.sin((t / 0.45) * math.pi)
        else:
            pulse = 0.22
        return s, 1.0 + 0.14 * pulse, 0.55 * pulse
    if motion == "pulse":
        pulse = 0.55 + 0.45 * math.sin(t * math.pi * 2.0)
        return 1.0 + 0.012 * pulse, 1.0 + 0.16 * pulse, 0.5 * pulse
    return 1.0, 1.0, 0.0


def frame_motion_state(effects, frame, fps, narr_frames):
    """第 frame 帧的动效状态（帧→秒的唯一解释入口）：elapsed = frame/fps，
    旁白终点 = narr_frames/fps；hold/尾垫帧冻结在末态（音画锁）。
    delay 按秒解释、与 fps 无关：同一秒数在不同 fps 下状态一致（允许一帧量化）。"""
    duration = narr_frames / float(fps)
    elapsed = min(frame / float(fps), duration)
    return motion_vars(effects, elapsed, duration)


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


def render_html(sc, W, H, style, motion_enabled=True):
    """教学页 HTML；动效由 CSS 变量在截帧时驱动。无进度条/帧号。"""
    kind = resolve_kind(sc)
    layout_variant = sc.get("layout_variant")
    html = inject_style(load_layout(kind, layout_variant), style)
    if "</head>" in html:
        html = html.replace("</head>", MOTION_CSS + "</head>", 1)
    else:
        html = MOTION_CSS + html
    body_html = highlight_body(sc.get("body", ""), kind)
    zh = sc.get("zh", sc.get("sub", ""))
    # __THINK__：仅 practice layout 有。缺省沿用文案；显式空字符串隐藏提示与间距。
    think_html = None
    if "__THINK__" in html:
        think = sc.get("think")
        if think is None:
            think_html = "先想一想，别急着看答案"
        elif str(think) == "":
            html = html.replace('<div class="think">__THINK__</div>', "", 1)
        else:
            think_html = _escape(str(think))
    chart_raw = sc.get("chart", "")
    chart_html = (
        resolve_chart(chart_raw, style)
        if isinstance(chart_raw, dict)
        else str(chart_raw)
    )
    slots = {
        "__W__": str(W),
        "__H__": str(H),
        "__HEADER__": _escape(sc.get("header", "")),
        "__BADGE__": KIND_BADGE.get(kind, ""),
        "__SUB__": _escape(sc.get("sub", "")),
        "__ZH__": _escape(zh),
        "__BODY__": body_html,
        "__WRONG_BODY__": highlight_body(sc.get("wrong_body", ""), "mistake"),
        "__CHART__": chart_html,
        "__CHART_MOTION__": (
            "chart-animated"
            if kind == "diagram"
            and any(e["type"] != "none" for e in resolve_motion(sc, motion_enabled))
            else "chart-static"
        ),
    }
    if think_html is not None:
        slots["__THINK__"] = think_html
    # 单次替换：re.sub 不重扫替换值，避免内容里的 __...__ 被后续槽二次解释
    return PLACEHOLDER_RE.sub(lambda m: slots.get(m.group(0), m.group(0)), html)


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
        if kind in ("rule", "diagram", "example", "mistake", "practice", "answer"):
            need += ["__SUB__", "__BADGE__"]
        if kind == "diagram":
            need.append("__CHART__")
        if kind == "summary":
            need = ["__BODY__", "__SUB__"]
        if kind == "example":
            need.append("__ZH__")
        if kind == "mistake":
            need.append("__ZH__")
        if kind == "practice":
            need.append("__THINK__")
        for slot in need:
            if slot not in raw:
                errors.append(f"{fn}: 缺少内容槽 {slot}")
        for slot in ("__BG__", "__ACCENT__", "__INK__"):
            if slot not in raw:
                errors.append(f"{fn}: 缺少风格槽 {slot}（须由 style-*.json 注入）")
    return errors


# 教学弧相位（docs/teaching-method.md）：title → rule+ → (diagram) → example+ → (mistake) → practice → answer → summary
_ARC_PHASE = {
    "title": 0,
    "rule": 1,
    "diagram": 1,  # 图解归属于概念锚点阶段
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
    voices_map = tpl.get("voices", {})
    for role_id, vname in voices_map.items():
        if vname not in VOICE_WHITELIST:
            warnings.append(
                f"voices.{role_id}={vname!r} 不在小米 TTS 白名单 {VOICE_WHITELIST}（API 可能拒绝；非阻塞）"
            )
    fps = tpl.get("fps", 30)
    if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0:
        errors.append(f"fps 须为正整数（当前 {fps!r}）；缺省 30")
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
        if kind == "example" and sc.get("layout_variant") == "side":
            wrong_body = sc.get("wrong_body")
            if not isinstance(wrong_body, str) or not wrong_body.strip():
                errors.append(
                    f"{prefix}: example side 须提供非空字符串 wrong_body（错误示例）"
                )
            elif LEAK_RE.match(wrong_body.strip()):
                errors.append(f"{prefix}: wrong_body={wrong_body!r} 像样式泄漏")
        # 检查每页 voice 字段（支持角色 ID 或直接音色名）
        sc_voice = sc.get("voice")
        if sc_voice and sc_voice not in voices_map and sc_voice not in VOICE_WHITELIST:
            warnings.append(
                f"{prefix}: voice={sc_voice!r} 不在 voices 映射或 TTS 白名单"
            )
        if "motion" in sc:
            mv = sc["motion"]
            if isinstance(mv, str):
                if mv not in MOTIONS:
                    errors.append(
                        f"{prefix}: motion={mv!r} 非法（{', '.join(MOTIONS)}）"
                    )
            elif isinstance(mv, list):
                for idx, item in enumerate(mv):
                    mt = (
                        item
                        if isinstance(item, str)
                        else item.get("type", "")
                        if isinstance(item, dict)
                        else ""
                    )
                    if mt not in MOTIONS:
                        errors.append(
                            f"{prefix}: motion[{idx}] type={mt!r} 非法（{', '.join(MOTIONS)}）"
                        )
            else:
                errors.append(f"{prefix}: motion 格式错误（应为字符串或数组）")
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
    """占位符检查与未解释转义字符复核。溢出探测走 preview_overflow()，需 page 实测。"""
    errs = []
    left = PLACEHOLDER_RE.findall(html)
    if left:
        errs.append(f"scenes[{scene_index}] 渲染后仍残留占位符: {sorted(set(left))}")
    # 检查是否存在未解释的字面 \\n / \t 等生硬转义字符暴露在正文中
    if "\\n" in html or "\\t" in html:
        errs.append(f"scenes[{scene_index}] 渲染后仍残留字面转义字符 (如 \\n 或 \\t)")
    # 检查 <br> 是否被错误转义为 &lt;br&gt;（原样显示在画面上）
    if "&lt;br&gt;" in html or "&lt;br /&gt;" in html:
        errs.append(
            f"scenes[{scene_index}] 渲染后 <br> 被错误转义为 &lt;br&gt;（应为 HTML 换行）"
        )
    return errs


# 关键内容槽选择器（与 templates/layout-*.html 同步）。仅用于 preview 溢出探测。
# 按 kind 分组——layout 里 header 实际叫 .title/.big/.sum；mistake/practice/answer 的
# 正文叫 .q（不是 .body）；中文槽按 layout 不同叫 .zh/.why/.think/.explain。
_OVERFLOW_SELECTORS_BY_KIND = {
    "title": [".big", ".sub"],
    "rule": [
        ".title", ".badge", ".sub", ".body", ".formula", ".step-text",
        ".example-text", ".hl", ".err",
    ],
    "diagram": [".title", ".badge", ".sub", ".chart-container", ".body", ".hl", ".err"],
    "example": [".title", ".badge", ".sub", ".en", ".col-text", ".zh", ".hl", ".err"],
    "mistake": [".title", ".badge", ".sub", ".q", ".why", ".hl", ".err"],
    "practice": [".title", ".badge", ".sub", ".q", ".think", ".err"],
    "answer": [".title", ".badge", ".sub", ".mark", ".en", ".explain", ".hl", ".err"],
    "summary": [".sum", ".next", ".hl"],
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
                if (r.right > W + 0.5 || r.bottom > H + 0.5 || r.left < -0.5 || r.top < -0.5) {
                    out.push([sel, el.tagName, r.left, r.top, r.right, r.bottom, (el.textContent || '').slice(0, 40)]);
                }
            }
        }
        return out;
    }"""
    out = []
    for sel, tag, left, top, right, bottom, txt in page.evaluate(js, [W, H, selectors]):
        out.append(
            (
                sel,
                f"{tag} {sel} 溢出视口 left={left:.0f} top={top:.0f} right={right:.0f} bottom={bottom:.0f}（viewport {W}x{H}），内容='{txt}'",
            )
        )
    return out


def _motion_probe_states(effects):
    """预览闸门探测的动效可达状态：[(elapsed_seconds, duration_seconds), ...]。
    none 只测静态；其余动效在其自身可达窗口（delay 后 1 秒内完成）按 0..1 网格采样。
    不依赖真实旁白时长——TTS 前的预览也能覆盖延迟动效的放大末态。"""
    if isinstance(effects, str):  # 兼容旧调用
        effects = [{"type": effects, "delay": 0}]
    states = [(0.0, 1.0)]
    for eff in effects:
        if eff.get("type", "none") == "none":
            continue
        delay = max(0.0, float(eff.get("delay", 0)))
        states.extend((delay + i / 20.0, delay + 1.0) for i in range(21))
    return states


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

    style_name = args.style or tpl.get("style", "teaching")
    style = load_style(style_name)
    W = int(tpl.get("width", 1280))
    H = int(tpl.get("height", 720))
    fps_raw = tpl.get("fps", 30)
    scenes = tpl["scenes"]
    motion_enabled = (not args.no_motion) and (tpl.get("motion", True) is not False)

    print("0/4 校验布局与分镜...")
    layout_errs = validate_layouts()
    sb_errs, sb_warns = validate_storyboard(tpl)
    errors = layout_errs + sb_errs
    warnings = sb_warns
    for i, sc in enumerate(scenes):
        try:
            resolve_motion(sc, motion_enabled)
            html = render_html(sc, W, H, style, motion_enabled=motion_enabled)
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
    # fps 已在闸门校验为正整数；此处才转换，避免非法值在闸门前抛无上下文异常
    FPS = int(fps_raw)
    print(
        f"   style={style_name} ({style.get('style_id')}), motion={'on' if motion_enabled else 'off'}, scenes={len(scenes)} OK"
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
