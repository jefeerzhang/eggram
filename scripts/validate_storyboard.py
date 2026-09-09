# -*- coding: utf-8 -*-
"""独立校验分镜 JSON + 布局契约（不跑 TTS/浏览器）。Skill 阶段 1 收尾或改模板后调用。

与渲染走同一份闸门规则（scripts/storyboard_gate.py 的 prepare_storyboard），
保证「独立校验通过 ⇔ make_video.py 闸门通过」。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from storyboard_gate import load_env, prepare_storyboard  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/validate_storyboard.py <分镜.json>")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        tpl = json.load(f)
    prep = prepare_storyboard(tpl)
    for w in prep["warnings"]:
        print(" WARN:", w)
    if prep["errors"]:
        print("VALIDATION FAILED:")
        for e in prep["errors"]:
            print(" -", e)
        sys.exit(2)
    print(
        f"OK {path}  scenes={len(prep['scenes'])}  style={prep['style_name']}"
    )


if __name__ == "__main__":
    load_env()
    main()
