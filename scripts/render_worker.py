"""render_worker.py — 渲染 worker 单一入口（GitHub issue #10）

用法: py scripts/render_worker.py examples/<slug>.json [output.mp4]
      (--reuse-audio | --no-reuse-audio) [--style NAME] [--no-motion] [--browser PATH]

5 步固定流水线：preflight → preview → render → verify → 回传。
退出码：0=OK 1=PREFLIGHT 2=PREVIEW 3=RENDER 4=VERIFY（含用法错误=1）。
stdout 末段为固定四字段回传：status / artifact / verify / diagnostic；
OK 路径另加一行 `steps:`（#19：各步执行痕迹，字段只增不改，失败路径行为不变）。
并行换皮（#18）：preview 目录按解析后的 style 隔离为 `_build/preview/<slug>__<style>/`，同 slug 多 worker 不再互踩。
"""

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Parser(argparse.ArgumentParser):
    """用法错误归 exit 1；argparse 默认的 exit 2 与 FAIL_AT_PREVIEW 契约冲突。"""

    def error(self, message):
        print(f"worker 用法错误: {message}", file=sys.stderr)
        sys.exit(1)


def run_script(argv):
    r = subprocess.run(
        [sys.executable] + argv, check=False, capture_output=True, text=True, cwd=ROOT
    )
    return r.returncode, r.stdout + r.stderr


def tail(text, n):
    return "\n".join(text.strip().splitlines()[-n:])


def pick(log, key):
    for line in log.splitlines():
        if key in line:
            return line.strip()
    return "?"


def emit(status, artifact=None, verify=None, diagnostic=None, steps=None):
    print(f"status: {status}")
    print(f"artifact: {artifact or '(none)'}")
    print(f"verify: {verify or '(none)'}")
    if steps:  # #19：仅 OK 路径输出，既有解析方不受影响
        print(f"steps: {steps}")
    if diagnostic:
        print(f"diagnostic:\n{diagnostic}")


def main():
    ap = Parser(
        prog="render_worker.py", description="渲染 worker：5 步流水线，不可绕过"
    )
    ap.add_argument("storyboard", help="分镜 JSON 路径")
    ap.add_argument("output", nargs="?", default=None, help="缺省 output/<slug>.mp4")
    g = ap.add_mutually_exclusive_group()
    g.add_argument(
        "--reuse-audio", action="store_true", help="复用音频缓存（默认应显式传）"
    )
    g.add_argument(
        "--no-reuse-audio", action="store_true", help="逃生口：全量重 TTS（打 warn）"
    )
    ap.add_argument("--style", default=None)
    ap.add_argument("--no-motion", action="store_true")
    ap.add_argument("--browser", default=None)
    args = ap.parse_args()

    if not args.reuse_audio and not args.no_reuse_audio:
        emit(
            "FAIL_AT_PREFLIGHT",
            diagnostic="必须显式选择 --reuse-audio 或 "
            "--no-reuse-audio（保护 MIMO_API_KEY 配额，不允许隐式默认）",
        )
        sys.exit(1)
    if args.no_reuse_audio:
        print(
            "WARN: --no-reuse-audio 逃生口已启用，全部旁白将重跑 TTS", file=sys.stderr
        )

    sb = args.storyboard
    slug = os.path.splitext(os.path.basename(sb))[0]
    out = args.output or f"output/{slug}.mp4"

    # Step 1 preflight（含浏览器时点检查；exit 3 语义已在其中处理）
    rc, log1 = run_script(
        ["scripts/worker_preflight.py", sb]
        + (["--browser", args.browser] if args.browser else [])
    )
    if rc != 0:
        emit("FAIL_AT_PREFLIGHT", diagnostic=tail(log1, 50))
        sys.exit(1)

    # Step 2 preview：独立跑只为错误分类（全渲内部本有预览闸门）。
    # preview 内容随 style 变（字体/间距→溢出结果不同），故按 style 隔离目录；
    # 音频缓存与 style 无关，共享 _build/<slug>/ 安全（同内容 + 原子写，见 #18）
    with open(
        sb if os.path.isabs(sb) else os.path.join(ROOT, sb), encoding="utf-8"
    ) as f:
        style_key = args.style or json.load(f).get("style") or "teaching"
    style_key = re.sub(r"[^\w.-]", "_", str(style_key))
    prev_dir = os.path.join("_build", "preview", f"{slug}__{style_key}")
    rc, log2 = run_script(["scripts/worker_preview.py", sb, "--preview-dir", prev_dir])
    if rc != 0:
        emit("FAIL_AT_PREVIEW", diagnostic=f"[worker exit {rc}]\n{tail(log2, 50)}")
        sys.exit(2)

    # Step 3 render：只调 CLI，不改其行为
    cmd = ["scripts/make_video.py", sb, out, "--preview-dir", prev_dir]
    if args.reuse_audio:
        cmd.append("--reuse-audio")
    if args.style:
        cmd += ["--style", args.style]
    if args.no_motion:
        cmd.append("--no-motion")
    if args.browser:
        cmd += ["--browser", args.browser]
    rc, log3 = run_script(cmd)
    if rc == 3:  # 映射表：make_video exit 3（浏览器缺失）任何阶段归 PREFLIGHT
        emit(
            "FAIL_AT_PREFLIGHT",
            diagnostic=f"render 中 make_video exit 3（浏览器缺失）\n{tail(log3, 100)}",
        )
        sys.exit(1)
    if rc != 0:
        art = out if os.path.isfile(os.path.join(ROOT, out)) else None
        emit(
            "FAIL_AT_RENDER",
            artifact=art,
            diagnostic=f"make_video.py exit {rc}\n{tail(log3, 100)}",
        )
        sys.exit(3)

    # Step 4 verify
    cmd = ["scripts/worker_verify.py", sb, out]
    if args.reuse_audio:
        cmd.append("--expect-reuse-audio")
    rc, log4 = run_script(cmd)
    if rc != 0:
        marks = ["✓"] * 6
        item = 0
        for line in log4.splitlines():
            if line.startswith("verify FAIL ["):
                item = int(line[13])
                if 1 <= item <= len(marks):
                    marks[item - 1] = "✗"
        if not item:  # worker_verify 崩溃等未预期失败，标后三项存疑
            marks[2:] = ["✗"] * (len(marks) - 2)
        emit(
            "FAIL_AT_VERIFY",
            verify="[" + "".join(marks) + "]",
            diagnostic=tail(log4, 50),
        )
        sys.exit(4)

    # Step 5 回传（steps 行给出各步执行痕迹，防"OK 但没真跑"质疑）
    steps = " | ".join(
        [
            pick(log1, "PREFLIGHT_OK"),
            pick(log2, "PREVIEW_OK"),
            pick(log3, "DONE"),
            pick(log4, "VERIFY_OK"),
        ]
    )
    emit("OK", artifact=out, verify="[✓✓✓✓✓✓]", steps=steps)


if __name__ == "__main__":
    main()
