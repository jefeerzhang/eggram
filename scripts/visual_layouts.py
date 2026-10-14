"""Structured visual content for three layout variants; no media dependencies."""
# Each variant belongs to a teaching role, not a new arc phase.
VISUAL_KINDS = {"structure": "rule", "steps": "example", "compare": "mistake"}
_FIELDS = {
    "structure": ("label", "text"),
    "steps": ("label", "text", "result"),
    "compare": ("wrong", "right", "reason"),
}
_LIMITS = {"label": 24, "text": 100, "result": 100, "wrong": 80, "right": 80, "reason": 100}


def validate_visual(sc, kind, prefix):
    """Validate before HTML generation; reject visual data on unrelated layouts."""
    variant = sc.get("layout_variant")
    active = isinstance(variant, str) and VISUAL_KINDS.get(variant) == kind
    if not active:
        return [f"{prefix}: visual 仅用于 rule/structure、example/steps、mistake/compare"] if "visual" in sc else []
    visual = sc.get("visual")
    if not isinstance(visual, dict):
        return [f"{prefix}: {variant} 须提供 visual 对象"]
    errors = []
    if variant == "structure":
        label = visual.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 40:
            errors.append(f"{prefix}: visual.label 须为 1–40 字符的非空字符串")
    allowed = {"items", "label"} if variant == "structure" else {"items"}
    if set(visual) - allowed:
        errors.append(f"{prefix}: visual 未知字段 {sorted(set(visual) - allowed)}")
    items = visual.get("items")
    low, high = (1, 3) if variant == "compare" else (2, 4)
    if not isinstance(items, list) or not low <= len(items) <= high:
        return errors + [f"{prefix}: visual.items 须为 {low}–{high} 项的数组"]
    for i, item in enumerate(items):
        path = f"{prefix}.visual.items[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: 须为对象")
            continue
        if set(item) - set(_FIELDS[variant]):
            errors.append(f"{path}: 未知字段 {sorted(set(item) - set(_FIELDS[variant]))}")
        if variant == "compare" and isinstance(item.get("wrong"), str) and "**" not in item["wrong"]:
            errors.append(f"{path}.wrong: 须用 ** 标出错误点")
        for field in _FIELDS[variant]:
            value = item.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > _LIMITS[field]:
                errors.append(f"{path}.{field}: 须为 1–{_LIMITS[field]} 字符的非空字符串")
    return errors


def build_visual_html(visual, variant, text, highlight):
    """Only the gate calls this after validation. Never interpolate raw content."""
    chunks = [f'<div class="visual visual-{variant}">']
    items = visual["items"]
    if variant == "structure":
        chunks.append(f'<div class="visual-root">{text(visual["label"])}</div><div class="visual-branches">')
    elif variant == "steps":
        chunks.append('<div class="visual-flow">')
    for i, item in enumerate(items):
        chunks.append(f'<div class="visual-item" data-visual-index="{i}">')
        if variant == "compare":
            chunks.append(
                f'<div class="visual-wrong">× {highlight(item["wrong"], "mistake")}</div>'
                '<div class="visual-arrow" aria-hidden="true">→</div>'
                f'<div class="visual-reveal"><div class="visual-right">{highlight(item["right"], "answer")}</div>'
                f'<div class="visual-reason">{text(item["reason"])}</div></div>'
            )
        else:
            if variant == "steps":
                chunks.append(f'<div class="visual-action"><span class="visual-number">{i + 1}</span>{text(item["label"])}</div>')
            else:
                chunks.append(f'<div class="visual-label">{text(item["label"])}</div>')
            chunks.append(f'<div class="visual-text">{highlight(item["text"], VISUAL_KINDS[variant])}</div>')
            if variant == "steps":
                chunks.append(f'<div class="visual-result">{highlight(item["result"], "answer")}</div>')
        chunks.append('</div>')
    if variant != "compare":
        chunks.append('</div>')
    chunks.append('</div>')
    return ''.join(chunks)


def visual_reveal_levels(count, elapsed, duration):
    """Equal narration-time windows, cumulative reveal; hold freezes the end state.

    shortcut: timing is proportional, not word-aligned; use explicit cue timings
    only when the audio pipeline exposes validated narration markers.
    """
    if count <= 0:
        return []
    if duration <= 0:
        return [1.0] * count
    progress = min(1.0, max(0.0, elapsed / duration))
    # Finish each reveal in the first half of its window, including the last one.
    return [min(1.0, max(0.0, (progress * count - i) * 2)) for i in range(count)]


def apply_visual_state(page, sc, elapsed=None, duration=None):
    """None = complete static/preview state. Recompute every frame, seek-safe."""
    visual = sc.get("visual")
    count = len(visual["items"]) if isinstance(visual, dict) and isinstance(visual.get("items"), list) else 0
    levels = [1.0] * count if elapsed is None else visual_reveal_levels(count, elapsed, duration)
    page.evaluate('''levels => {
        document.querySelectorAll('[data-visual-index]').forEach((el, i) => {
            el.style.setProperty('--v-on', String(levels[i] ?? 1));
        });
    }''', levels)
