"""worker_preflight.py — render worker Step 1 前置闸门（GitHub issue #11）

用法: py scripts/worker_preflight.py examples/<slug>.json [--browser PATH]

四项检查全过 → stdout 打印 PREFLIGHT_OK、exit 0；任一失败 → stderr 文案、exit 1。
失败分类（FAIL_AT_PREFLIGHT）由 worker wrapper（issue 01）负责，本脚本只短路径失败。
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(ROOT, "scripts", "validate_storyboard.py")


def fail(msg):
    print(f"preflight FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(
        prog="worker_preflight.py", description="render worker Step 1 前置检查"
    )
    ap.add_argument("storyboard", help="分镜 JSON 路径")
    ap.add_argument(
        "--browser", default=None, help="浏览器可执行文件路径（透传 find_browser）"
    )
    args = ap.parse_args()

    # 1. 分镜 JSON 存在
    if not os.path.isfile(args.storyboard):
        fail(f"分镜 JSON 不存在: {args.storyboard}")

    # 2. 校验闸门 exit 0：只看退出码，末 50 行原样带回作诊断
    r = subprocess.run(
        [sys.executable, VALIDATOR, args.storyboard],
        check=False,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).strip().splitlines()[-50:]
        print(f"preflight FAIL: 校验闸门未通过 (exit {r.returncode})", file=sys.stderr)
        print("\n".join(tail), file=sys.stderr)
        sys.exit(1)

    # 3. TTS key：只查环境变量，不试连 API（避免误判）
    if not os.environ.get("MIMO_API_KEY"):
        fail("no TTS key: 未配置 MIMO_API_KEY 环境变量")

    # 4. 浏览器可发现（时点检查：假设 preflight→render 期间路径不变；
    #    真失效时 make_video exit 3 仍按映射表归 FAIL_AT_PREFLIGHT）
    try:
        from make_video import find_browser

        browser = find_browser(args.browser)
    except ImportError as e:
        print(f"preflight FAIL: 无法导入 make_video.find_browser: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"preflight FAIL: {e}", file=sys.stderr)
        print("  请检查 --browser 路径，或安装 Chrome/Edge 后重试。", file=sys.stderr)
        sys.exit(1)
    if not browser:
        fail(
            "no browser: 未找到可用浏览器（Chrome/Edge）。请安装 Chrome 或 Edge；"
            "或用环境变量 BROWSER_PATH（或 CHROME_PATH）指定浏览器可执行文件路径，"
            "或用 --browser <路径> 显式指定。"
        )

    print("PREFLIGHT_OK")


if __name__ == "__main__":
    main()
