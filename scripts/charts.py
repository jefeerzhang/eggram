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


def build_curve_svg(chart, colors):
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
    colors 为 style_token_map() 的产物（__ACCENT__ 等 token → 当前皮肤色值）；
    chart 里的 color 字段已由 resolve_chart 换成实际色值，故此处只兜默认。
    """
    accent = colors["__ACCENT__"]
    ink_sub = colors["__INK_SUB__"]
    surface = colors["__SURFACE__"]

    r = chart.get("range", {})
    xmin, xmax = r.get("xmin", 0), r.get("xmax", 5)
    ymin, ymax = r.get("ymin", 0), r.get("ymax", 100)

    axes = chart.get("axes", {})
    xlabel = axes.get("x", "")
    ylabel = axes.get("y", "")

    curve = chart.get("curve", {})
    curve_color = curve.get("color", accent)
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
            xlabel, ylabel, xmin, xmax, ymin, ymax, xticks, yticks, ink_sub
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
        hl_color = hl.get("color", accent)
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


# ── 解析入口 ──────────────────────────────────────────────────────────────────
def resolve_chart(chart, colors):
    """从分镜 chart 字段解析 SVG 字符串。

    colors 为 style_token_map() 的产物（token → 当前皮肤色值）。chart 里的
    `color` 字段既可写 __ACCENT__ / __WRONG__ / __CORRECT__ 等 token（换成皮肤
    色），也可写字面 hex（原样保留）。

    两种入参格式：
    1. 字符串 → 原样返回（手写 SVG 兼容）
    2. 对象 → preset 为 "curve" 时生成曲线图，否则返回空串
    """
    if isinstance(chart, str):
        return chart
    if not isinstance(chart, dict) or chart.get("preset") != "curve":
        return ""

    def walk(obj):
        if isinstance(obj, dict):
            return {
                k: (
                    colors.get(v, v)
                    if k == "color" and isinstance(v, str)
                    else walk(v)
                )
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [walk(i) for i in obj]
        return obj

    return build_curve_svg(walk(chart), colors)
