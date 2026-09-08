"""worker_preview.py — render worker Step 2 预览闸门（GitHub issues #12/#18）

用法: py scripts/worker_preview.py examples/<slug>.json [output_path] [--preview-dir DIR]

跑 make_video.py --preview，再核对截图齐全 + 溢出报告干净。
全过 → stdout `PREVIEW_OK <n> frames`、exit 0；任一失败 → 诊断、exit 2（FAIL_AT_PREVIEW）。
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAKE_VIDEO = os.path.join(ROOT, "scripts", "make_video.py")


def fail(msg, out=""):
    print(f"preview FAIL: {msg}", file=sys.stderr)
    print("\n".join(out.strip().splitlines()[-50:]), file=sys.stderr)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(
        prog="worker_preview.py", description="render worker Step 2 预览闸门"
    )
    ap.add_argument("storyboard", help="分镜 JSON 路径")
    ap.add_argument("output", nargs="?", default=None, help="缺省 output/_preview_<slug>.mp4")
    ap.add_argument("--preview-dir", default=None, help="自定义预览截图目录")
    args = ap.parse_args()

    storyboard = args.storyboard
    slug = os.path.splitext(os.path.basename(storyboard))[0]
    output = args.output or f"output/_preview_{slug}.mp4"
    # 目录口径与 make_video run_preview 一致：相对路径挂 ROOT 下
    check_dir = args.preview_dir or os.path.join(ROOT, "_build", "preview", slug)
    if not os.path.isabs(check_dir):
        check_dir = os.path.join(ROOT, check_dir)

    # 1) make_video --preview：exit 1=溢出，2=占位符闸门（均归 FAIL_AT_PREVIEW）
    cmd = [sys.executable, MAKE_VIDEO, storyboard, output, "--preview"]
    if args.preview_dir:
        cmd += ["--preview-dir", args.preview_dir]
    r = subprocess.run(cmd, check=False, capture_output=True, text=True)
    combined = r.stdout + r.stderr
    if r.returncode != 0:
        fail(f"make_video --preview exit {r.returncode}", combined)

    # 2) 截图齐全：按分镜 scenes 数核对 s{i}.png（不 glob 计数）
    with open(storyboard, encoding="utf-8") as f:
        n_scenes = len(json.load(f)["scenes"])
    for i in range(n_scenes):
        png = os.path.join(check_dir, f"s{i}.png")
        if not os.path.isfile(png):
            fail(f"missing preview frame: {png}", combined)

    # 3) exit 0 仍复核 overflow.json（防 make_video 漂移造成假绿）
    report_path = os.path.join(check_dir, "overflow.json")
    if not os.path.isfile(report_path):
        fail(f"missing overflow report: {report_path}", combined)
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    bad = [e for e in report if e.get("findings") or e.get("placeholder_errs")]
    if bad:
        lines = "\n".join(
            f"scene {e['i']} ({e.get('kind')}): {j['msg']}"
            for e in bad
            for j in e["findings"]
        )
        fail(f"溢出报告非空: {len(bad)}/{len(report)} 页（{report_path}）", lines)

    print(f"PREVIEW_OK {n_scenes} frames")
    print(f"截图目录: {check_dir}")


if __name__ == "__main__":
    main()
