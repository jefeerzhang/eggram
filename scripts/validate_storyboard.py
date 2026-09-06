# -*- coding: utf-8 -*-
"""独立校验分镜 JSON + 布局契约（不跑 TTS）。Skill 阶段 1 收尾或改模板后调用。"""
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from make_video import (  # noqa: E402
    load_style, render_html, validate_layouts, validate_storyboard, validate_rendered_html,
)

def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/validate_storyboard.py <分镜.json>")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        tpl = json.load(f)
    style = load_style(tpl.get("style", "teaching"))
    W, H = int(tpl.get("width", 1280)), int(tpl.get("height", 720))
    errors = validate_layouts() + validate_storyboard(tpl)
    for i, sc in enumerate(tpl.get("scenes") or []):
        try:
            html = render_html(sc, W, H, style)
            errors.extend(validate_rendered_html(html, i))
        except Exception as e:
            errors.append(f"scenes[{i}] 试渲染失败: {e}")
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(" -", e)
        sys.exit(2)
    print(f"OK {path}  scenes={len(tpl['scenes'])}  style={tpl.get('style', 'teaching')}")

if __name__ == "__main__":
    main()
