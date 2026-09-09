"""render_worker.py — 渲染 worker 单一入口（GitHub issue #10，#25 统一失败分类）

用法: py scripts/render_worker.py examples/<slug>.json [output.mp4]
      (--reuse-audio | --no-reuse-audio) [--style NAME] [--no-motion] [--browser PATH]

5 步固定流水线：preflight → preview → render → verify → 回传；前序失败即短路，
后续阶段不执行。退出码映射见 scripts/worker_result.py（0=OK 1=PREFLIGHT
2=PREVIEW 3=RENDER 4=VERIFY，含用法错误=1）。
stdout 末段为固定回传：status / artifact / verify / cache / diagnostic；
OK 路径另加一行 `steps:`（#19：各步执行痕迹）。`cache:`（#24）报告本次 TTS
生成/复用事实（generated/reused/mode，取自本次 run 的 manifest），渲染完成前
为 `(none)`——通过验收不等于零 TTS，事实以执行记录为准。
verify 勾选串六格图例：✓ 通过、✗ 失败、- 显式跳过、· 因前序失败/未执行；
由 worker_verify 的 `CHECK <n> <STATE>` 协议行（空白分词）与本 worker 自己实测的
Step 1/2 结果合成（#25），不解析日志字符位置，未检查项绝不填通过。
产物归属（#22）：preview 与加工音轨按 run 目录隔离（run_key = 分镜字节 +
style + motion 开关，见 scripts/run_artifacts.py），同 slug 多 worker 并行互踩
不再可能；raw 旁白仍共享 `_build/<slug>/`（换皮复用）。verify 传相同的
--style/--no-motion 以精确重定位本次运行。
输出目标（#23）：省略 output 时自动命名 `output/<slug>__<最终皮肤>.mp4`
（皮肤名被规范化改写时追加短指纹防重合），同分镜多皮肤并行各得一个成片；
显式 output 永远优先。活动运行竞争同一目标时，后启动者在 TTS/MP4 写入前
被拒（FAIL_AT_PREFLIGHT + 占用诊断）；目标锁 `<output>.lock` 心跳保活，
成功/失败/崩溃都释放，进程死亡后锁过期可接管，历史成片不删除。
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import run_artifacts as ra  # noqa: E402
import worker_result as wr  # noqa: E402


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


def emit(status, artifact=None, verify=None, diagnostic=None, steps=None, cache=None):
    print(f"status: {status}")
    print(f"artifact: {artifact or '(none)'}")
    print(f"verify: {verify or '(none)'}")
    print(f"cache: {cache or '(none)'}")  # #24：本次 TTS 生成/复用事实，渲染完成前无
    if steps:  # #19：仅 OK 路径输出，既有解析方不受影响
        print(f"steps: {steps}")
    if diagnostic:
        print(f"diagnostic:\n{diagnostic}")


def main():
    ap = Parser(
        prog="render_worker.py", description="渲染 worker：5 步流水线，不可绕过"
    )
    ap.add_argument("storyboard", help="分镜 JSON 路径")
    ap.add_argument(
        "output", nargs="?", default=None,
        help="缺省 output/<slug>__<皮肤>.mp4（#23 自动命名，绑定分镜+最终皮肤）",
    )
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
        sys.exit(wr.STAGE_EXITS["PREFLIGHT"])
    if args.no_reuse_audio:
        print(
            "WARN: --no-reuse-audio 逃生口已启用，全部旁白将重跑 TTS", file=sys.stderr
        )

    sb = args.storyboard
    slug = os.path.splitext(os.path.basename(sb))[0]
    # 自动命名（#23）：绑定最终皮肤（--style > 分镜顶层 style > teaching），
    # 三皮肤并行省略 output 也各得一个成片；显式 output 永远优先
    style_name = args.style
    if not style_name:
        try:
            with open(sb, encoding="utf-8") as f:
                style_name = json.load(f).get("style", "teaching")
        except (OSError, ValueError):
            style_name = "teaching"  # 缺/坏分镜由 preflight 报错，此处仅兜底命名
    out = args.output or ra.default_output_name(slug, style_name)

    # 目标占用（#23）：TTS / MP4 写入前拒绝后启动者；成功、失败、崩溃都释放
    try:
        lock = ra.acquire_target(out, storyboard=sb, style_name=style_name)
    except ra.TargetOccupied as e:
        emit("FAIL_AT_PREFLIGHT", diagnostic=str(e))
        sys.exit(wr.STAGE_EXITS["PREFLIGHT"])

    try:
        _pipeline(args, sb, out, style_name)
    finally:
        lock.release()


def _cache_facts(sb, style_name, no_motion):
    """本次 TTS 生成/复用事实（#24）：读本次 run 的 manifest（make_video 执行时
    记录），不做事后数文件；旧产物/渲染未完成 → None。"""
    try:
        with open(sb, encoding="utf-8") as f:
            motion_enabled = (not no_motion) and (json.load(f).get("motion", True) is not False)
    except (OSError, ValueError):
        return None
    slug = os.path.splitext(os.path.basename(sb))[0]
    rkey = ra.run_key(sb, style_name, motion_enabled)
    manifest = ra.read_manifest(ra.run_dir(ROOT, slug, style_name, rkey))
    if not manifest or manifest.get("schema") != ra.MANIFEST_SCHEMA:
        return None
    if "tts_generated" not in manifest:
        return None
    return (
        f"generated={manifest.get('tts_generated', '?')} "
        f"reused={manifest.get('tts_reused', '?')} "
        f"mode={manifest.get('reuse_mode', '?')}"
    )


def _pipeline(args, sb, out, style_name):
    # Step 1 preflight（含浏览器时点检查；exit 3 语义已在其中处理）
    rc, log1 = run_script(
        ["scripts/worker_preflight.py", sb]
        + (["--browser", args.browser] if args.browser else [])
    )
    if rc != 0:
        emit("FAIL_AT_PREFLIGHT", diagnostic=tail(log1, 50))
        sys.exit(wr.STAGE_EXITS["PREFLIGHT"])

    # Step 2 preview：独立跑只为错误分类（全渲内部本有预览闸门）。
    # 预览/音轨目录由 run_key 决定（#22）：分镜字节+style+motion 开关不同即隔离，
    # 无需 worker 再自算 --preview-dir；raw 旁白缓存与 style 无关，共享安全（#18）
    render_options = []
    if args.style:
        render_options += ["--style", args.style]
    if args.no_motion:
        render_options.append("--no-motion")
    if args.browser:
        render_options += ["--browser", args.browser]
    rc, log2 = run_script(["scripts/worker_preview.py", sb] + render_options)
    if rc != 0:
        emit("FAIL_AT_PREVIEW", diagnostic=f"[worker exit {rc}]\n{tail(log2, 50)}")
        sys.exit(wr.STAGE_EXITS["PREVIEW"])

    # Step 3 render：只调 CLI，不改其行为
    cmd = ["scripts/make_video.py", sb, out] + render_options
    if args.reuse_audio:
        cmd.append("--reuse-audio")
    rc, log3 = run_script(cmd)
    if rc == 3:  # 映射表：make_video exit 3（浏览器缺失）任何阶段归 PREFLIGHT
        emit(
            "FAIL_AT_PREFLIGHT",
            diagnostic=f"render 中 make_video exit 3（浏览器缺失）\n{tail(log3, 100)}",
        )
        sys.exit(wr.STAGE_EXITS["PREFLIGHT"])
    if rc != 0:
        art = out if os.path.isfile(os.path.join(ROOT, out)) else None
        emit(
            "FAIL_AT_RENDER",
            artifact=art,
            diagnostic=f"make_video.py exit {rc}\n{tail(log3, 100)}",
        )
        sys.exit(wr.STAGE_EXITS["RENDER"])

    # Step 4 verify：传与渲染相同的 --style/--no-motion，精确重定位本次 run（#22）。
    # 勾选串由 CHECK 协议行合成（#25）：1/2 用本 worker 实测的 Step 1/2 结果，
    # 3-6 用 verify 报告的终态；verify 崩溃时 3-6 如实记未执行，不填通过或失败
    cmd = ["scripts/worker_verify.py", sb, out]
    if args.style:
        cmd.append("--style")
        cmd.append(args.style)
    if args.no_motion:
        cmd.append("--no-motion")
    if args.reuse_audio:
        cmd.append("--expect-reuse-audio")
    rc, log4 = run_script(cmd)
    marks = wr.marks_line((wr.PASS, wr.PASS), wr.parse_check_lines(log4))
    # #24：渲染完成后才有本次 run 的 manifest，事实只在成功路径后读取
    cache = _cache_facts(sb, style_name, args.no_motion)
    if rc != 0:
        emit(
            "FAIL_AT_VERIFY",
            verify=f"[{marks}]",
            diagnostic=tail(log4, 50),
            cache=cache,
        )
        sys.exit(wr.STAGE_EXITS["VERIFY"])

    # Step 5 回传（steps 行给出各步执行痕迹，防"OK 但没真跑"质疑）
    steps = " | ".join(
        [
            pick(log1, "PREFLIGHT_OK"),
            pick(log2, "PREVIEW_OK"),
            pick(log3, "DONE"),
            pick(log4, "VERIFY_OK"),
        ]
    )
    emit("OK", artifact=out, verify=f"[{marks}]", steps=steps, cache=cache)


if __name__ == "__main__":
    main()
