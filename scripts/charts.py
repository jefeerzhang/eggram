"""
charts.py — 出版级 SVG 矢量图解生成器

设计规范吸收自 diagram-design（cathrynlavery/diagram-design）：
- Clean paper 背景，无多余装饰
- 字体阶梯：标题 17px / 刻度 11px / 标注 13px
- 路径描画动效（path draw）+ 逐序浮现（staggered reveal）+ 脉冲强调（glow pulse）
- 先画线后画节点（z-order 规范）
- 标签永不压线，与曲线保持 6px 间隙
- 所有坐标点通过 viewBox + pad 比例换算，自动适配任意尺寸

用法：在 make_video.py 中 from charts import resolve_chart
"""

import math

# ── viewBox 常量 ──────────────────────────────────────────────────────────────
_VW, _VH = 500, 320
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 60, 30, 30, 40
_PX = _VW - _PAD_L - _PAD_R  # 绘图区宽 410
_PY = _VH - _PAD_T - _PAD_B  # 绘图区高 250


def _xpx(x, xmin, xmax):
    if xmax == xmin:
        return _PAD_L + _PX / 2
    return _PAD_L + (x - xmin) / (xmax - xmin) * _PX


def _ypx(y, ymin, ymax):
    if ymax == ymin:
        return _PAD_T + _PY / 2
    return _PAD_T + (1.0 - (y - ymin) / (ymax - ymin)) * _PY


def _fmt_num(v):
    if v == int(v):
        return str(int(v))
    return f"{v:.1f}"


def _svg_text(
    x, y, text, size=13, color="#cccccc", anchor="middle", weight="400", mono=False
):
    font = "font-family='SF Mono','Consolas','Courier New',monospace" if mono else ""
    return (
        f"<text x='{x}' y='{y}' fill='{color}' font-size='{size}' "
        f"font-weight='{weight}' text-anchor='{anchor}' {font}>{text}</text>"
    )


# ── 坐标轴绘制 ─────────────────────────────────────────────────────────────────
def _draw_axes(
    xlabel,
    ylabel,
    xmin,
    xmax,
    ymin,
    ymax,
    xticks=None,
    yticks=None,
    accent="#ffb020",
    ink_sub="#9aa3b2",
):
    parts = []
    # 坐标轴线
    parts.append(
        f"<line x1='{_PAD_L}' y1='{_PAD_T + _PY}' x2='{_PAD_L + _PX}' y2='{_PAD_T + _PY}' "
        f"stroke='{ink_sub}' stroke-width='1.5' stroke-linecap='round' opacity='0.5'/>"
    )
    parts.append(
        f"<line x1='{_PAD_L}' y1='{_PAD_T + _PY}' x2='{_PAD_L}' y2='{_PAD_T}' "
        f"stroke='{ink_sub}' stroke-width='1.5' stroke-linecap='round' opacity='0.5'/>"
    )
    # X 刻度
    if xticks is None:
        step = max(1, round((xmax - xmin) / 5))
        xticks = list(range(int(xmin), int(xmax) + 1, step))
    for xt in xticks:
        xp = _xpx(xt, xmin, xmax)
        parts.append(
            f"<line x1='{xp}' y1='{_PAD_T + _PY}' x2='{xp}' y2='{_PAD_T + _PY + 4}' "
            f"stroke='{ink_sub}' stroke-width='1' opacity='0.5'/>"
        )
        parts.append(
            _svg_text(
                xp, _PAD_T + _PY + 18, _fmt_num(xt), size=11, color=ink_sub, mono=True
            )
        )
    # Y 刻度
    if yticks is None:
        step = max(1, round((ymax - ymin) / 5))
        yticks = list(range(int(ymin), int(ymax) + 1, step))
    for yt in yticks:
        yp = _ypx(yt, ymin, ymax)
        parts.append(
            f"<line x1='{_PAD_L - 4}' y1='{yp}' x2='{_PAD_L}' y2='{yp}' "
            f"stroke='{ink_sub}' stroke-width='1' opacity='0.5'/>"
        )
        parts.append(
            _svg_text(
                _PAD_L - 10,
                yp + 4,
                _fmt_num(yt),
                size=11,
                color=ink_sub,
                anchor="end",
                mono=True,
            )
        )
    # 轴标签
    parts.append(
        _svg_text(
            _PAD_L + _PX / 2, _VH - 4, xlabel, size=13, color=ink_sub, weight="600"
        )
    )
    # Y 轴标签竖排
    parts.append(
        f"<text x='12' y='{_PAD_T + _PY / 2}' fill='{ink_sub}' font-size='13' "
        f"font-weight='600' text-anchor='middle' "
        f"transform='rotate(-90,12,{_PAD_T + _PY / 2})'>{ylabel}</text>"
    )
    return "\n".join(parts)


# ── 曲线图解 ─────────────────────────────────────────────────────────────────
def _compute_default_points(fn, xmin, xmax, n=40):
    """从函数推导点序列，fn: normalized t∈[0,1] → y"""
    pts = []
    for i in range(n + 1):
        t = i / n
        x = xmin + t * (xmax - xmin)
        y = fn(t)
        pts.append({"x": x, "y": y})
    return pts


def build_curve_svg(chart, style):
    """
    chart = {
        "axes": {"x": "消费量 Q", "y": "边际效用 MU"},
        "range": {"xmin": 0, "xmax": 5, "ymin": 0, "ymax": 100},
        "curve": {"color": "__ACCENT__", "width": 5,
                  "points": [{"x":1,"y":100},...],   # 显式点
                  "fn": "t^0.3", "fn_scale": 100},   # 或自动推导
        "highlights": [{"x":1,"y":100,"label":"Q=1","color":"__ACCENT__"},
                       {"x":4,"y":0,"label":"MU→0","color":"__WRONG__"}],
        "xticks": [0,1,2,3,4,5],
        "yticks": [0,25,50,75,100]
    }
    """
    s = style
    accent = s.get("accent", "#ffb020")
    correct = s.get("correct", "#2ecc71")
    wrong = s.get("wrong", "#e74c3c")
    ink_sub = s.get("ink_sub", "#9aa3b2")
    surface = s.get("surface", "rgba(255,255,255,0.06)")

    r = chart.get("range", {})
    xmin, xmax = r.get("xmin", 0), r.get("xmax", 5)
    ymin, ymax = r.get("ymin", 0), r.get("ymax", 100)

    axes = chart.get("axes", {})
    xlabel = axes.get("x", "")
    ylabel = axes.get("y", "")

    curve = chart.get("curve", {})
    curve_color = (
        accent if curve.get("color") == "__ACCENT__" else curve.get("color", accent)
    )
    curve_width = curve.get("width", 5)

    # 计算曲线点
    raw_pts = curve.get("points")
    if not raw_pts:
        scale = curve.get("fn_scale", 100)
        fn_expr = curve.get("fn", "t^0.3")

        def default_fn(t):
            if fn_expr == "t^0.3":
                return scale * (t**0.3)
            elif fn_expr == "1 - t":
                return scale * (1.0 - t)
            elif fn_expr == "sin":
                return scale * math.sin(t * math.pi)
            elif fn_expr == "log":
                import math as _m

                return scale * min(1.0, _m.log1p(t * 4) / _m.log1p(4))
            return scale * (1.0 - t)

        raw_pts = _compute_default_points(default_fn, xmin, xmax, n=50)

    xticks = chart.get("xticks")
    yticks = chart.get("yticks")

    # ── 构建 SVG ──
    parts = [
        f"<svg viewBox='0 0 {_VW} {_VH}' class='chart-svg' xmlns='http://www.w3.org/2000/svg'>",
    ]

    # 坐标轴
    parts.append(
        _draw_axes(
            xlabel, ylabel, xmin, xmax, ymin, ymax, xticks, yticks, accent, ink_sub
        )
    )

    # 曲线路径 — 先画线（z-order：线在节点之下）
    p0 = raw_pts[0]
    d_parts = [f"M {_xpx(p0['x'], xmin, xmax)} {_ypx(p0['y'], ymin, ymax)}"]
    for p in raw_pts[1:]:
        d_parts.append(f"L {_xpx(p['x'], xmin, xmax)} {_ypx(p['y'], ymin, ymax)}")
    d = " ".join(d_parts)

    # 主路径（静态，始终可见作为底图）
    parts.append(
        f"<path d='{d}' fill='none' stroke='{curve_color}' stroke-width='{curve_width}' "
        f"stroke-linecap='round' stroke-linejoin='round' opacity='0.25'/>"
    )
    # 动画路径（描画效果）
    parts.append(
        f"<path d='{d}' fill='none' stroke='{curve_color}' stroke-width='{curve_width}' "
        f"stroke-linecap='round' stroke-linejoin='round' "
        f"class='draw-path' pathLength='1'/>"
    )

    # 关键高亮点 — 后画节点（z-order：节点在线之上）
    highlights = chart.get("highlights", [])
    for idx, hl in enumerate(highlights):
        hx = _xpx(hl["x"], xmin, xmax)
        hy = _ypx(hl["y"], ymin, ymax)
        hl_color = (
            accent
            if hl.get("color") == "__ACCENT__"
            else (
                wrong
                if hl.get("color") == "__WRONG__"
                else (
                    correct
                    if hl.get("color") == "__CORRECT__"
                    else hl.get("color", accent)
                )
            )
        )
        label = hl.get("label", "")
        delay = 1.2 + idx * 0.4

        # 脉冲圆圈
        parts.append(
            f"<circle cx='{hx}' cy='{hy}' r='7' fill='{hl_color}' "
            f"class='glow-point' style='animation-delay:{delay:.1f}s'/>"
        )
        # 标签（始终在点的上方，保持 14px 间隙，不压线）
        ly = hy - 14
        # 如果靠近顶部就放到下方
        if ly < 20:
            ly = hy + 22
        # 如果靠右，标签左对齐；靠中则居中
        anchor = "start" if hx > _PAD_L + _PX * 0.7 else "middle"
        lx = hx + 10 if anchor == "start" else hx
        parts.append(
            f"<rect x='{lx - 4}' y='{ly - 11}' width='{len(label) * 7.5 + 8}' height='16' "
            f"rx='3' fill='{surface}' class='stagger-item' "
            f"style='animation-delay:{delay:.1f}s'/>"
        )
        parts.append(
            _svg_text(
                lx, ly, label, size=12, color=hl_color, anchor=anchor, weight="600"
            ).replace(
                "<text",
                f"<text class='stagger-item' style='animation-delay:{delay:.1f}s'",
            )
        )

    parts.append("</svg>")
    return "\n".join(parts)


# ── 四象限图解 ────────────────────────────────────────────────────────────────
def build_quadrant_svg(chart, style):
    """
    chart = {
        "axes": {"x": "低频率", "x2": "高频率", "y": "低影响", "y2": "高影响"},
        "labels": [
            {"label": "A", "desc": "低频高影响", "qx": 0.25, "qy": 0.75, "color": "__WRONG__"},
            ...
        ]
    }
    """
    s = style
    accent = s.get("accent", "#ffb020")
    correct = s.get("correct", "#2ecc71")
    wrong = s.get("wrong", "#e74c3c")
    ink_sub = s.get("ink_sub", "#9aa3b2")
    surface = s.get("surface", "rgba(255,255,255,0.06)")

    axes = chart.get("axes", {})
    labels = chart.get("labels", [])

    cx, cy = _PAD_L + _PX / 2, _PAD_T + _PY / 2

    parts = [
        f"<svg viewBox='0 0 {_VW} {_VH}' class='chart-svg' xmlns='http://www.w3.org/2000/svg'>"
    ]

    # 十字轴
    parts.append(
        f"<line x1='{_PAD_L}' y1='{cy}' x2='{_PAD_L + _PX}' y2='{cy}' "
        f"stroke='{ink_sub}' stroke-width='1' opacity='0.4' stroke-dasharray='4,3'/>"
    )
    parts.append(
        f"<line x1='{cx}' y1='{_PAD_T}' x2='{cx}' y2='{_PAD_T + _PY}' "
        f"stroke='{ink_sub}' stroke-width='1' opacity='0.4' stroke-dasharray='4,3'/>"
    )

    # 轴标签
    for anchor_x, anchor_y, label in [
        (_PAD_L + 8, _PAD_T + _PY - 8, axes.get("x", "")),
        (_PAD_L + _PX - 8, _PAD_T + _PY - 8, axes.get("x2", "")),
        (_PAD_L + 8, _PAD_T + 14, axes.get("y2", "")),
        (_PAD_L + _PX - 8, _PAD_T + 14, axes.get("y", "")),
    ]:
        a = "start" if anchor_x < cx else "end"
        parts.append(
            _svg_text(
                anchor_x,
                anchor_y,
                label,
                size=11,
                color=ink_sub,
                anchor=a,
                weight="500",
            )
        )

    # 标签节点
    for idx, item in enumerate(labels):
        qx = item.get("qx", 0.5)
        qy = item.get("qy", 0.5)
        lx = _PAD_L + qx * _PX
        ly = _PAD_T + (1.0 - qy) * _PY
        c = (
            accent
            if item.get("color") == "__ACCENT__"
            else (
                wrong
                if item.get("color") == "__WRONG__"
                else (
                    correct
                    if item.get("color") == "__CORRECT__"
                    else item.get("color", accent)
                )
            )
        )
        delay = 0.6 + idx * 0.3
        parts.append(
            f"<circle cx='{lx}' cy='{ly}' r='22' fill='none' stroke='{c}' stroke-width='2' "
            f"opacity='0.6' class='stagger-item' style='animation-delay:{delay:.1f}s'/>"
        )
        parts.append(
            f"<circle cx='{lx}' cy='{ly}' r='6' fill='{c}' "
            f"class='glow-point' style='animation-delay:{delay:.1f}s'/>"
        )
        lbl = item.get("label", "")
        desc = item.get("desc", "")
        parts.append(
            _svg_text(lx, ly + 4, lbl, size=15, color=c, weight="800").replace(
                "<text",
                f"<text class='stagger-item' style='animation-delay:{delay:.1f}s'",
            )
        )
        if desc:
            parts.append(
                _svg_text(lx, ly + 22, desc, size=10, color=ink_sub).replace(
                    "<text",
                    f"<text class='stagger-item' style='animation-delay:{delay + 0.2:.1f}s'",
                )
            )

    parts.append("</svg>")
    return "\n".join(parts)


# ── 时间轴图解 ────────────────────────────────────────────────────────────────
def build_timeline_svg(chart, style):
    """
    chart = {
        "events": [
            {"year": "2020", "label": "事件A", "color": "__ACCENT__"},
            ...
        ]
    }
    """
    s = style
    accent = s.get("accent", "#ffb020")
    correct = s.get("correct", "#2ecc71")
    wrong = s.get("wrong", "#e74c3c")
    ink_sub = s.get("ink_sub", "#9aa3b2")

    events = chart.get("events", [])
    if not events:
        return "<svg viewBox='0 0 500 320' class='chart-svg'></svg>"

    n = len(events)
    usable_w = _VW - 80
    spacing = usable_w / max(n - 1, 1) if n > 1 else 0
    start_x = 40
    line_y = _VH / 2

    parts = [
        f"<svg viewBox='0 0 {_VW} {_VH}' class='chart-svg' xmlns='http://www.w3.org/2000/svg'>"
    ]

    # 主时间轴线
    parts.append(
        f"<line x1='{start_x}' y1='{line_y}' x2='{start_x + usable_w}' y2='{line_y}' "
        f"stroke='{ink_sub}' stroke-width='2' opacity='0.3' class='draw-path' pathLength='1'/>"
    )

    for idx, ev in enumerate(events):
        ex = start_x + idx * spacing
        c = (
            accent
            if ev.get("color") == "__ACCENT__"
            else (
                wrong
                if ev.get("color") == "__WRONG__"
                else (
                    correct
                    if ev.get("color") == "__CORRECT__"
                    else ev.get("color", accent)
                )
            )
        )
        delay = 0.8 + idx * 0.35
        above = idx % 2 == 0
        dy = line_y - 38 if above else line_y + 38

        parts.append(
            f"<circle cx='{ex}' cy='{line_y}' r='5' fill='{c}' "
            f"class='glow-point' style='animation-delay:{delay:.1f}s'/>"
        )
        parts.append(
            f"<line x1='{ex}' y1='{line_y}' x2='{ex}' y2='{dy}' "
            f"stroke='{c}' stroke-width='1.5' opacity='0.5' "
            f"class='stagger-item' style='animation-delay:{delay:.1f}s'/>"
        )
        label = ev.get("label", "")
        year = ev.get("year", "")
        ty = dy - 8 if above else dy + 14
        parts.append(
            _svg_text(ex, ty, year, size=11, color=ink_sub, mono=True).replace(
                "<text",
                f"<text class='stagger-item' style='animation-delay:{delay:.1f}s'",
            )
        )
        parts.append(
            _svg_text(ex, ty + 15, label, size=12, color=c, weight="600").replace(
                "<text",
                f"<text class='stagger-item' style='animation-delay:{delay + 0.15:.1f}s'",
            )
        )

    parts.append("</svg>")
    return "\n".join(parts)


# ── 解析入口 ──────────────────────────────────────────────────────────────────
def resolve_chart(chart, style):
    """从分镜 chart 字段解析 SVG 字符串。
    支持两种格式：
    1. 字符串 → 原样返回（手写 SVG 兼容）
    2. 对象 → 根据 preset 字段分发到对应生成器
    """
    if isinstance(chart, str):
        return chart
    if not isinstance(chart, dict):
        return ""

    preset = chart.get("preset", "")
    builders = {
        "curve": build_curve_svg,
        "quadrant": build_quadrant_svg,
        "timeline": build_timeline_svg,
    }
    builder = builders.get(preset)
    if not builder:
        return ""

    # 解析颜色 token：__ACCENT__ / __WRONG__ / __CORRECT__ → 实际色值
    def resolve_color(val):
        token_map = {
            "__ACCENT__": style.get("accent", "#ffb020"),
            "__WRONG__": style.get("wrong", "#e74c3c"),
            "__CORRECT__": style.get("correct", "#2ecc71"),
            "__INK_SUB__": style.get("ink_sub", "#9aa3b2"),
        }
        return token_map.get(str(val), str(val))

    def walk(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k in ("color",) and isinstance(v, str):
                    out[k] = resolve_color(v)
                else:
                    out[k] = walk(v)
            return out
        if isinstance(obj, list):
            return [walk(i) for i in obj]
        return obj

    resolved = walk(chart)
    return builder(resolved, style)
