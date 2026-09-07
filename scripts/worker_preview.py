"""worker_preview.py — render worker Step 2 预览闸门（GitHub issue #12）

用法: py scripts/worker_preview.py examples/<slug>.json [output_path]

跑 make_video.py --preview，再核对截图齐全 + 溢出报告干净。
全过 → stdout `PREVIEW_OK <n> frames`、exit 0；任一失败 → 诊断、exit 2（FAIL_AT_PREVIEW）。
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAKE_VIDEO = os.path.join(ROOT, "scripts", "make_video.py")


def fail(msg, out=""):
    print(f"preview FAIL: {msg}", file=sys.stderr)
    tail = out.strip().splitlines()[-50:]
    if tail:
        print("\n".join(tail), file=sys.stderr)
    sys.exit(2)


def main():
    if len(sys.argv) < 2:
        fail("缺少参数: <storyboard.json> [output_path]")
    storyboard = sys.argv[1]
    slug = os.path.splitext(os.path.basename(storyboard))[0]
    output = sys.argv[2] if len(sys.argv) > 2 else f"output/_preview_{slug}.mp4"

    # 1) make_video --preview：exit 1=溢出，2=占位符闸门失败（均归 FAIL_AT_PREVIEW）
    r = subprocess.run(
        [sys.executable, MAKE_VIDEO, storyboard, output, "--preview"],
        check=False,
        capture_output=True,
        text=True,
    )
    combined = r.stdout + r.stderr
    if r.returncode != 0:
        fail(f"make_video --preview exit {r.returncode}", combined)

    # 2) 截图齐全：s{i}.png 逐段核对（段数以分镜 JSON 为准，不 glob 计数）
    with open(storyboard, encoding="utf-8") as f:
        n_scenes = len(json.load(f)["scenes"])
    preview_dir = os.path.join(ROOT, "_build", "preview", slug)
    for i in range(n_scenes):
        png = os.path.join(preview_dir, f"s{i}.png")
        if not os.path.isfile(png):
            fail(f"missing preview frame: {png}", combined)

    # 3) 溢出报告干净：exit 0 时仍复核 overflow.json（防 make_video 行为漂移的假绿）
    report_path = os.path.join(preview_dir, "overflow.json")
    if not os.path.isfile(report_path):
        fail(f"missing overflow report: {report_path}", combined)
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    bad = [e for e in report if e.get("findings") or e.get("placeholder_errs")]
    if bad:
        lines = [
            f"scene {e['i']} ({e.get('kind')}): {item['msg']}"
            for e in bad
            for item in e.get("findings", [])
        ]
        fail(
            f"溢出报告非空: {len(bad)}/{len(report)} 页有发现问题（{report_path}）",
            "\n".join(lines),
        )

    print(f"PREVIEW_OK {n_scenes} frames")
    print(f"截图目录: {preview_dir}")


if __name__ == "__main__":
    main()
