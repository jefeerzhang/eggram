"""
storyboard_gate.py — 分镜准备与静态闸门（唯一规则源）

集中最终配置（style/W/H/fps/motion）、布局选择（含变体回退）、页面准备、
规则顺序与诊断；make_video.py（渲染）与 validate_storyboard.py（独立校验）
消费同一行为，不留两套规则。

纯准备行为：只依赖标准库与 charts（SVG 字符串），不导入 playwright/ffmpeg/numpy；
缺少浏览器与音频运行依赖的环境也可完成静态分镜与页面校验。浏览器发现、TTS、
编码等运行环境初始化归各 CLI 自身。

配置初始化：load_env() 由各 CLI 入口调用——python-dotenv 可用时加载 ROOT/.env，
不覆盖已显式设置的环境变量；缺包或缺文件时静默跳过。
"""

import html
import json
import math
import os
import re

from charts import resolve_chart

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(ROOT, "templates")

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
# 变体适用槽位要求：在 kind 基础槽位之上，变体额外必须提供的槽位。
# 未知或缺失变体回退默认布局，故只校验实际存在的变体文件。
LAYOUT_VARIANT_SLOTS = {
    ("rule", "side"): ["__ZH__"],
    ("rule", "formula"): ["__FORMULA_MAIN__", "__PARTS__"],
    ("example", "side"): ["__WRONG_BODY__"],
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


def load_env():
    """集中配置初始化：python-dotenv 可用时加载 ROOT/.env。
    不覆盖已显式设置的环境变量（显式优先）；缺包或缺文件静默跳过。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(os.path.join(ROOT, ".env"))


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


def resolve_layout_file(kind, variant=None):
    """kind+variant → 实际使用的 layout 文件名。未知 kind 抛 ValueError；
    变体未知或文件缺失时回退默认布局（生成与检查共用此判定）。"""
    fn = LAYOUT_FILES.get(kind)
    if not fn:
        raise ValueError(f"未知 kind: {kind}（可选: {', '.join(LAYOUT_FILES)}）")
    if variant and kind in LAYOUT_VARIANTS:
        vfn = LAYOUT_VARIANTS[kind].get(variant)
        if vfn and os.path.isfile(os.path.join(TEMPLATE_DIR, vfn)):
            return vfn
    return fn


def load_layout(kind, variant=None):
    """加载 layout HTML。variant 非空时尝试加载变体，不存在则回退默认。"""
    with open(
        os.path.join(TEMPLATE_DIR, resolve_layout_file(kind, variant)),
        encoding="utf-8",
    ) as f:
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


# _escape 内部占位：NUL 包裹，先剥原文 NUL，故与教学正文不碰撞；
# 禁用下划线（后续 .replace("_") 会转义）；html.escape 不改动 \x00。
_ESC_BR = "\x00br\x00"
_ESC_SUBO, _ESC_SUBC = "\x00subo\x00", "\x00subc\x00"
_ESC_SUPO, _ESC_SUPC = "\x00supo\x00", "\x00supc\x00"


def _escape(text):
    """把教学字段当纯文本：& < > \" ' 按字面显示；下划线转为实体以中和 __...__ 槽位 token，
    避免内容被后续槽二次解释或被误判为残留占位符。
    换行处理：JSON 中的 \\n、真实换行、手写 <br> 均统一转为 HTML <br>。
    白名单标签：<br> / <sub> / <sup> 透传（公式上下标需求），其它 <...> 仍 escape。
    占位符用 NUL 包裹且先剥原文 NUL，避免 `@BR@` 这类字面串被误还原成标签。"""
    s = str(text).replace("\x00", "")
    # 1. 先把白名单标签提为占位符（避免被 escape 干掉）
    s = re.sub(r"<br\s*/?>", _ESC_BR, s, flags=re.IGNORECASE)
    s = re.sub(
        r"<sub>(.*?)</sub>",
        _ESC_SUBO + r"\1" + _ESC_SUBC,
        s,
        flags=re.IGNORECASE | re.DOTALL,
    )
    s = re.sub(
        r"<sup>(.*?)</sup>",
        _ESC_SUPO + r"\1" + _ESC_SUPC,
        s,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # 2. 统一换行：JSON 转义 \\n、真实换行、手写 <br> 均归一
    s = s.replace("\\n", "\n")
    s = s.replace("\n", _ESC_BR)
    # 3. escape 其它特殊字符 + 下划线
    s = html.escape(s, quote=True).replace("_", "&#95;")
    # 4. 还原白名单标签
    s = s.replace(_ESC_BR, "<br>")
    s = s.replace(_ESC_SUBO, "<sub>").replace(_ESC_SUBC, "</sub>")
    s = s.replace(_ESC_SUPO, "<sup>").replace(_ESC_SUPC, "</sup>")
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


# 公式页时间线：入场与主式两段的终点（占旁白时长比例），余下均分给 parts
_FORMULA_ENTER_END = 0.15
_FORMULA_MAIN_END = 0.40


def formula_motion_vars(parts, elapsed_seconds, duration_seconds):
    """公式页分步动效变量（秒语义，与 frame_motion_state 同一时钟）。

    duration 切成三段：入场 0–15% 卡抬起 → 主式 15–40% 分式线描画 →
    余下按 parts 数量均分，逐项点亮。elapsed 到 duration 即冻在末态
    （hold/尾垫期间画面不动）。无 id 的 part 被忽略；duration<=0 全冻初态。
    """
    ids = [pid for p in parts or [] if (pid := str(p.get("id") or "").strip())]
    duration = max(0.0, float(duration_seconds))
    if duration <= 0:
        return {"card_y": 8.0, "card_elev": 0.0, "frac_bar": 0.0, "active_part": ""}
    u = max(0.0, min(duration, float(elapsed_seconds))) / duration
    landed = {"card_y": 0.0, "card_elev": 1.0}
    if u < _FORMULA_ENTER_END:
        t = u / _FORMULA_ENTER_END
        return {
            "card_y": 8.0 * (1.0 - t),
            "card_elev": t,
            "frac_bar": 0.0,
            "active_part": "",
        }
    if u < _FORMULA_MAIN_END:
        frac = (u - _FORMULA_ENTER_END) / (_FORMULA_MAIN_END - _FORMULA_ENTER_END)
        return {**landed, "frac_bar": frac, "active_part": "__main__"}
    if not ids:
        return {**landed, "frac_bar": 1.0, "active_part": "__main__"}
    slot = (1.0 - _FORMULA_MAIN_END) / len(ids)
    idx = min(len(ids) - 1, int((u - _FORMULA_MAIN_END) / slot))
    return {**landed, "frac_bar": 1.0, "active_part": ids[idx]}


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


def build_formula_main_html(formula, kind):
    """主公式 HTML：优先 num+den 分式，否则 display 单行。"""
    num = (formula.get("num") or "").strip()
    den = (formula.get("den") or "").strip()
    if num and den:
        return (
            '<div class="formula-frac" data-formula-main="1">'
            f'<div class="formula-num">{highlight_body(num, kind)}</div>'
            '<div class="formula-bar" aria-hidden="true"></div>'
            f'<div class="formula-den">{highlight_body(den, kind)}</div>'
            "</div>"
        )
    display = formula.get("display") or ""
    return (
        f'<div class="formula" data-formula-main="1">'
        f"{highlight_body(display, kind)}</div>"
    )


def build_formula_parts_html(parts, *, legacy_zh="", badge=""):
    """分项 HTML；parts 为 None 时走旧双步（zh + badge）兼容。"""
    if parts is None:
        items = [
            {"id": "legacy1", "label": "1", "text": legacy_zh},
            {"id": "legacy2", "label": "2", "text": badge},
        ]
    else:
        items = parts
    chunks = ['<div class="breakdown">']
    for i, p in enumerate(items):
        pid = _escape(str(p.get("id") or f"p{i}"))
        label = _escape(str(p.get("label") or str(i + 1)))
        text = highlight_body(p.get("text") or "", "rule")
        chunks.append(
            f'<div class="step" data-part-id="{pid}">'
            f'<div class="step-num">{label}</div>'
            f'<div class="step-text part-text">{text}</div></div>'
        )
    chunks.append("</div>")
    return "".join(chunks)


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
    formula = sc.get("formula") if isinstance(sc.get("formula"), dict) else None
    use_formula = kind == "rule" and layout_variant == "formula"
    if use_formula and formula is not None:
        formula_main = build_formula_main_html(formula, kind)
        parts_html = build_formula_parts_html(formula.get("parts"))
    elif use_formula:
        formula_main = f'<div class="formula" data-formula-main="1">{body_html}</div>'
        parts_html = build_formula_parts_html(
            None, legacy_zh=str(zh), badge=KIND_BADGE.get(kind, "")
        )
    else:
        formula_main = ""
        parts_html = ""
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
        resolve_chart(chart_raw, style_token_map(style))
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
        "__FORMULA_MAIN__": formula_main,
        "__PARTS__": parts_html,
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


def _layout_needs(kind):
    """kind 的基础槽位要求（validate_layouts 与变体共用）。"""
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
    return need


def _check_layout_file(fn, raw, need, errors):
    """单文件布局契约：禁用 token、烘焙样式、内容槽与风格槽。"""
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
    for token in banned:
        if token in raw:
            errors.append(f"{fn}: 禁止画面进度条/帧计数（发现 {token}）")
    for m in re.finditer(r">\s*(#[0-9a-fA-F]{3,8}|\d{2,3})\s*<", raw):
        errors.append(f"{fn}: 文本节点疑似烘焙了样式值 {m.group(1)!r}")
    for m in _INLINE_BAKED_STYLE_RE.finditer(raw):
        errors.append(
            f"{fn}: HTML 属性 style 烘焙了视觉样式 {m.group(0)[:60]!r}——应走 style token"
        )
    for slot in need:
        if slot not in raw:
            errors.append(f"{fn}: 缺少内容槽 {slot}")
    for slot in ("__BG__", "__ACCENT__", "__INK__"):
        if slot not in raw:
            errors.append(f"{fn}: 缺少风格槽 {slot}（须由 style-*.json 注入）")


def validate_layouts():
    """模板契约：默认布局 + 已存在的排版变体（缺失变体回退默认，不报错）。"""
    errors = []
    for kind, fn in LAYOUT_FILES.items():
        raw = open(os.path.join(TEMPLATE_DIR, fn), encoding="utf-8").read()
        _check_layout_file(fn, raw, _layout_needs(kind), errors)
    for kind, variants in LAYOUT_VARIANTS.items():
        for variant, vfn in variants.items():
            path = os.path.join(TEMPLATE_DIR, vfn)
            if not os.path.isfile(path):
                continue
            raw = open(path, encoding="utf-8").read()
            need = _layout_needs(kind) + LAYOUT_VARIANT_SLOTS.get((kind, variant), [])
            if (kind, variant) == ("rule", "formula"):
                need = [s for s in need if s != "__BODY__"]
            _check_layout_file(vfn, raw, need, errors)
    return errors


def validate_formula_field(sc, prefix):
    """返回 (errors, warnings)。仅在 rule+formula 变体调用。"""
    errors, warnings = [], []
    formula = sc.get("formula")
    if not isinstance(formula, dict):
        errors.append(f"{prefix}: formula 须为 object")
        return errors, warnings
    num = formula.get("num")
    den = formula.get("den")
    display = (formula.get("display") or "").strip()
    has_frac = bool((num or "").strip() and (den or "").strip())
    if not has_frac and not display:
        errors.append(
            f"{prefix}: formula 须提供 num+den，或非空 display"
        )
    body = (sc.get("body") or "").strip()
    if body:
        warnings.append(
            f"{prefix}: 已提供 formula，body 将被忽略（以 formula 为准）"
        )
    parts = formula.get("parts")
    if parts is None:
        return errors, warnings
    if not isinstance(parts, list) or not (2 <= len(parts) <= 4):
        errors.append(f"{prefix}: formula.parts 须为长度 2–4 的数组")
        return errors, warnings
    seen = set()
    for j, p in enumerate(parts):
        pp = f"{prefix}.formula.parts[{j}]"
        if not isinstance(p, dict):
            errors.append(f"{pp}: 须为 object")
            continue
        for f in ("id", "label", "text"):
            if not str(p.get(f) or "").strip():
                errors.append(f"{pp}: {f} 不能为空")
        pid = str(p.get("id") or "").strip()
        if pid:
            if pid in seen:
                errors.append(f"{pp}: id={pid!r} 重复")
            seen.add(pid)
    return errors, warnings


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
        variant = sc.get("layout_variant")
        if sc.get("formula") is not None:
            if kind != "rule" or variant != "formula":
                warnings.append(
                    f"{prefix}: formula 仅用于 rule+layout_variant=formula"
                )
            else:
                fe, fw = validate_formula_field(sc, prefix)
                errors.extend(fe)
                warnings.extend(fw)
        required = ["header", "narrate"]
        formula_ok = (
            kind == "rule"
            and variant == "formula"
            and isinstance(sc.get("formula"), dict)
        )
        if not formula_ok:
            required = ["header", "body", "narrate"]
        for field in required:
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
        ".title",
        ".badge",
        ".sub",
        ".body",
        ".formula",
        ".formula-frac",
        ".formula-num",
        ".formula-den",
        ".step-text",
        ".part-text",
        ".example-text",
        ".hl",
        ".err",
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


def prepare_storyboard(tpl, style_name=None, motion_enabled=None):
    """分镜准备 + 完整静态闸门。两个 CLI 入口（渲染/独立校验）的唯一规则源。

    - 最终配置：style（显式参数 > 顶层 style）、W/H、fps、motion_enabled
      （显式参数 > 顶层 motion 开关；CLI 的 --no-motion 由调用方折算进显式参数）
    - 布局选择：kind+layout_variant 经 resolve_layout_file（未知/缺失变体回退默认），
      检查与实际生成选用同一布局
    - 规则顺序：validate_layouts → validate_storyboard → 每页 resolve_motion →
      render_html → validate_rendered_html（诊断带 scenes[i] 前缀）
    - 纯准备行为：不触浏览器/ffmpeg/TTS

    返回 dict：errors、warnings、style、style_name、W、H、fps（原始值，闸门通过后
    由渲染方转换）、scenes=[{i, sc, kind, variant, layout_file, motion, html}]。
    errors 非空时 scenes 条目字段可能残缺。
    """
    style_name = style_name or tpl.get("style", "teaching")
    style = load_style(style_name)
    W = int(tpl.get("width", 1280))
    H = int(tpl.get("height", 720))
    fps_raw = tpl.get("fps", 30)
    if motion_enabled is None:
        motion_enabled = tpl.get("motion", True) is not False
    scenes = tpl.get("scenes") or []

    errors, warnings = [], []
    errors.extend(validate_layouts())
    sb_errs, sb_warns = validate_storyboard(tpl)
    errors.extend(sb_errs)
    warnings.extend(sb_warns)
    prepared = []
    for i, sc in enumerate(scenes):
        entry = {
            "i": i,
            "sc": sc,
            "kind": None,
            "variant": sc.get("layout_variant"),
            "layout_file": None,
            "motion": None,
            "html": None,
        }
        prepared.append(entry)
        try:
            kind = resolve_kind(sc)
            motion = resolve_motion(sc, motion_enabled)
            html = render_html(sc, W, H, style, motion_enabled=motion_enabled)
            entry.update(
                kind=kind,
                layout_file=resolve_layout_file(kind, sc.get("layout_variant")),
                motion=motion,
                html=html,
            )
            errors.extend(validate_rendered_html(html, i))
        except Exception as e:
            errors.append(f"scenes[{i}] 试渲染失败: {e}")
    return {
        "errors": errors,
        "warnings": warnings,
        "style": style,
        "style_name": style_name,
        "W": W,
        "H": H,
        "fps": fps_raw,
        "scenes": prepared,
    }
