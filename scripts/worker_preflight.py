"""worker_preflight.py — render worker Step 1 前置闸门（GitHub issue #11）

用法: py scripts/worker_preflight.py examples/<slug>.json [--browser PATH]
      [--tts-provider xiaomi|minimax]

四项检查全过 → stdout 打印 PREFLIGHT_OK、exit 0；任一失败 → stderr 文案、exit 1。
失败分类（FAIL_AT_PREFLIGHT）由 worker wrapper（issue 01）负责，本脚本只短路径失败。
入口处先 load_env()：TTS key 检查只看 os.environ，必须在它之前把 ROOT/.env 读进来。
第 3 项按本次 provider 查对应 key（provider = CLI > 分镜顶层 tts_provider > minimax）：
MiniMax 课要的是 MINIMAX_API_KEY，拿 MIMO_API_KEY 顶替只会误报或漏检。
"""

import argparse
import json
import os
import subprocess
import sys

import toolchain as tc  # 纯 stdlib：只找浏览器，不拉媒体管线
from storyboard_gate import load_env
from tts_config import (
    is_provider,
    minimax_config,
    qwen_config,
    resolve_tts_provider,
)

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
        "--browser", default=None, help="浏览器可执行文件路径（透传 toolchain.browser_path）"
    )
    ap.add_argument(
        "--tts-provider",
        default=None,
        help="TTS 引擎：xiaomi|minimax（优先于分镜顶层 tts_provider；决定第 3 项查哪个 key）",
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

    # 3. TTS key：只查环境变量，不试连 API（避免误判）。查哪个 key 由本次 provider
    #    决定，与 make_video 同源（CLI > 分镜顶层 tts_provider > minimax）：
    #    MiniMax 课缺 MINIMAX_API_KEY 时要在这一步说清，而不是拿 MIMO_API_KEY 顶替。
    try:
        with open(args.storyboard, encoding="utf-8") as f:
            tpl = json.load(f)
    except (OSError, ValueError):
        fail(f"分镜 JSON 无法读取: {args.storyboard}")
    provider = resolve_tts_provider(
        storyboard_provider=tpl.get("tts_provider"),
        cli_provider=args.tts_provider,
    )
    if not is_provider(provider):
        fail(f"unknown tts_provider: {provider!r}（应为 xiaomi、minimax 或 qwen）")
    if provider == "minimax":
        key_env, key = "MINIMAX_API_KEY", minimax_config()["key"]
    elif provider == "qwen":
        key_env, key = "DASHSCOPE_API_KEY", qwen_config()["key"]
    else:
        key_env, key = "MIMO_API_KEY", os.environ.get("MIMO_API_KEY")
    if not key:
        fail(f"no TTS key: provider={provider} 需要 {key_env}（环境变量或 ROOT/.env）")

    # 4. 浏览器可发现（时点检查：假设 preflight→render 期间路径不变；
    #    真失效时 make_video exit 3 仍按映射表归 FAIL_AT_PREFLIGHT）
    try:
        browser = tc.browser_path(args.browser)
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
    load_env()
    main()
