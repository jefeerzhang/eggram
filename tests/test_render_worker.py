"""Worker CLI integration tests with a local stand-in for the external TTS API."""

import base64
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from make_video import FFMPEG, find_browser  # noqa: E402
import run_artifacts as ra  # noqa: E402


@pytest.fixture
def tts_url(request):
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * int(24000 * getattr(request, "param", 0.2)))
    payload = json.dumps({"choices": [{"message": {"audio": {
        "data": base64.b64encode(audio.getvalue()).decode("ascii"),
    }}}]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/tts"
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize("override", ["style", "no-motion", "browser"])
def test_worker_accepts_preview_configuration_overrides(tts_url, override):
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_worker_") as tmp:
        project = Path(tmp)
        shutil.copytree(ROOT / "scripts", project / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "templates", project / "templates")
        tpl = {
            "title": "Worker", "voice": "mimo_default", "fps": 2,
            "scenes": [
                {"kind": kind, "header": "H", "body": "**B**", "narrate": "N"}
                for kind in ("title", "rule", "example", "practice", "answer", "summary")
            ],
        }
        tpl["scenes"][3]["hold"] = 3
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        flags = []
        if override == "style":
            style = json.loads((project / "templates/style-classroom.json").read_text(encoding="utf-8"))
            style["typography"]["body_size"] = 1000
            (project / "templates/style-oversized.json").write_text(json.dumps(style), encoding="utf-8")
            tpl["style"] = "oversized"
            flags = ["--style", "classroom"]
        elif override == "no-motion":
            layout = project / "templates/layout-rule.html"
            layout.write_text(layout.read_text(encoding="utf-8").replace(
                "</style>", ".title{position:absolute;top:0}</style>"
            ), encoding="utf-8")
            tpl["scenes"][1]["motion"] = "zoom_out"
            flags = ["--no-motion"]
        else:
            env["BROWSER_PATH"] = sys.executable
            flags = ["--browser", browser]
        storyboard = project / "lesson.json"
        storyboard.write_text(json.dumps(tpl), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "scripts/render_worker.py", str(storyboard), "--reuse-audio", *flags],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "status: OK" in result.stdout
        # #23 自动命名：省略 output 时绑定最终皮肤（不再固定 output/lesson.mp4）
        artifact = next(
            line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("artifact: ")
        )
        assert "lesson__" in artifact and artifact.endswith(".mp4"), artifact
        assert (project / artifact).stat().st_size > 0


@pytest.mark.parametrize("tts_url", [6], indirect=True)
def test_rendered_delayed_zoom_uses_video_seconds_and_freezes_during_hold(tts_url):
    with tempfile.TemporaryDirectory(prefix="mv_delayed_video_") as tmp:
        project = Path(tmp)
        shutil.copytree(ROOT / "scripts", project / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "templates", project / "templates")
        layout = project / "templates/layout-rule.html"
        layout.write_text(layout.read_text(encoding="utf-8").replace(
            "</style>", ".body{width:200px;height:100px;background:__CORRECT__}</style>"
        ), encoding="utf-8")
        tpl = {
            "title": "Timing", "voice": "mimo_default", "fps": 2,
            "width": 1280, "height": 720,  # 帧像素断言按 720p 写死
            "blocks": False,  # 本用例测静态布局的动效时序（rule 页不被 block 换肤）
            "scenes": [
                {"kind": kind, "header": "H", "body": "**B**", "narrate": "N", "motion": "none"}
                for kind in ("title", "rule", "example", "practice", "answer", "summary")
            ],
        }
        tpl["scenes"][1].update(motion=[{"type": "zoom_in", "delay": 2}], hold=2)
        tpl["scenes"][3]["hold"] = 3
        storyboard = project / "lesson.json"
        storyboard.write_text(json.dumps(tpl), encoding="utf-8")
        output = project / "lesson.mp4"
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        result = subprocess.run(
            [sys.executable, "scripts/make_video.py", str(storyboard), str(output)],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        widths = []
        # The title lasts 6.5s; inspect rule elapsed times 1s, 4s, 5.5s and hold 7s.
        for second in (7.5, 10.5, 12, 13.5):
            frame = subprocess.run(
                [FFMPEG, "-loglevel", "error", "-ss", str(second), "-i", str(output),
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, check=True, timeout=15,
            ).stdout
            pixels = np.frombuffer(frame, dtype=np.uint8).reshape(720, 1280, 3)
            mask = (pixels[:, :, 0] < 100) & (pixels[:, :, 1] > 150) & (pixels[:, :, 2] < 150)
            xs = np.where(mask)[1]
            assert xs.size > 0
            widths.append(int(xs.max() - xs.min() + 1))
        assert 199 <= widths[0] <= 201, widths
        assert widths[1] >= widths[0] + 6, widths
        assert widths[2] >= widths[1], widths
        assert abs(widths[3] - widths[2]) <= 1, widths


# ---- #22 并行产物归属：run 目录隔离 + raw 共享（真实 TTS adapter / 浏览器 / ffmpeg）----


def _copy_project(tmp):
    project = Path(tmp)
    shutil.copytree(ROOT / "scripts", project / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "templates", project / "templates")
    return project


def _write_source_storyboard(project, sub, narrate, hold=0.0):
    """完整教学弧（闸门要求 6 个必要 kind）；变量 hold 放 scene 0（title）。
    钉 720p 且关 block：这批用例测与视觉无关的归属/失败分类，保持静态布局
    的确定性（block 行为由 #27 专属用例覆盖）。"""
    d = project / "cases" / sub
    d.mkdir(parents=True, exist_ok=True)
    tpl = {
        "title": "T", "voice": "mimo_default", "fps": 2,
        "width": 1280, "height": 720,
        "blocks": False,
        "scenes": [
            {"kind": kind, "header": "H", "body": "**B**", "narrate": narrate}
            for kind in ("title", "rule", "example", "practice", "answer", "summary")
        ],
    }
    tpl["scenes"][0]["hold"] = hold
    tpl["scenes"][3]["hold"] = 3.0  # practice 闸门要求 hold >= 3.0
    (d / "lesson.json").write_text(json.dumps(tpl), encoding="utf-8")


def _run_worker(project, env, sb, out, *extra):
    return subprocess.run(
        [sys.executable, "scripts/render_worker.py", sb, out, *extra],
        cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=240,
    )


@pytest.mark.parametrize("tts_url", [0.3], indirect=True)
def test_parallel_same_slug_different_sources_own_their_artifacts(tts_url):
    """不同来源但主名相同的分镜并行：预览与加工音轨互不覆盖（显式 MP4 目标）。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_par_src_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Alpha narration.", 0.0)
        _write_source_storyboard(project, "b", "Beta narration.", 2.0)
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(
                lambda sub: _run_worker(project, env, f"cases/{sub}/lesson.json", f"out/{sub}.mp4", "--reuse-audio"),
                ("a", "b"),
            ))
        for sub, r in zip(("a", "b"), results):
            assert r.returncode == 0, f"[{sub}] " + r.stdout + r.stderr
            assert "status: OK" in r.stdout, r.stdout
        runs = sorted(p.name for p in (project / "_build" / "runs").iterdir())
        assert len(runs) == 2, runs  # 两个来源各自 run 目录
        for name in runs:
            rdir = project / "_build" / "runs" / name
            assert (rdir / "manifest.json").is_file()
            assert (rdir / "audio").is_dir() and list((rdir / "audio").iterdir())
            assert (rdir / "preview").is_dir() and (rdir / "preview" / "s0.png").is_file()
        # 各自验收：verify 重算 run_key，用本次音轨集合独立核对
        for sub in ("a", "b"):
            r = subprocess.run(
                [sys.executable, "scripts/worker_verify.py", f"cases/{sub}/lesson.json", f"out/{sub}.mp4"],
                cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            assert r.returncode == 0, r.stdout + r.stderr
            assert "run:" in r.stdout


@pytest.mark.parametrize("tts_url", [0.3], indirect=True)
def test_parallel_same_narration_different_hold_use_own_processed_audio(tts_url):
    """相同旁白与音色、hold 不同并行：各用各的加工音轨且分别满足音画锁。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_par_hold_") as tmp:
        project = _copy_project(tmp)
        for sub, hold in (("a", 0.0), ("b", 2.0)):
            _write_source_storyboard(project, sub, "Same narration.", hold)
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(
                lambda sub: _run_worker(project, env, f"cases/{sub}/lesson.json", f"out/{sub}.mp4", "--reuse-audio"),
                ("a", "b"),
            ))
        for sub, r in zip(("a", "b"), results):
            assert r.returncode == 0, f"[{sub}] " + r.stdout + r.stderr
            assert "status: OK" in r.stdout, r.stdout

        def wav_seconds(path):
            with wave.open(str(path), "rb") as w:
                return w.getnframes() / w.getframerate()

        audios = sorted((project / "_build" / "runs").glob("*/audio/s0_*.wav"))
        assert len(audios) == 2, audios
        d0, d1 = (wav_seconds(p) for p in audios)
        assert abs(d1 - d0) >= 1.5, (d0, d1)  # hold 差 2s → 各自加工音轨显著不同
        # raw 仍共享：同旁白同音色只有一份 raw（换课/并行不复制）
        raws = list((project / "_build" / "lesson").glob("s0_*_raw.wav"))
        assert len(raws) == 1, raws
        for sub in ("a", "b"):
            r = subprocess.run(
                [sys.executable, "scripts/worker_verify.py", f"cases/{sub}/lesson.json", f"out/{sub}.mp4"],
                cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("tts_url", [0.3], indirect=True)
def test_skin_rerender_reuses_raw_not_processed_audio(tts_url):
    """换皮复用 raw（cache 全命中），加工音轨归各自 run、不冒充共享 raw。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_skin_raw_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Skin narration.", 0.0)
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        r1 = _run_worker(project, env, "cases/a/lesson.json", "out/teaching.mp4", "--reuse-audio")
        assert r1.returncode == 0, r1.stdout + r1.stderr
        r2 = _run_worker(project, env, "cases/a/lesson.json", "out/classroom.mp4",
                         "--reuse-audio", "--style", "classroom")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        # 第二次换皮：raw 全命中（verify 检查 5），两个 run 目录按 style 分开
        r = subprocess.run(
            [sys.executable, "scripts/worker_verify.py", "cases/a/lesson.json",
             "out/classroom.mp4", "--style", "classroom", "--expect-reuse-audio"],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "reuse-confirmed" in r.stdout
        runs = sorted(p.name for p in (project / "_build" / "runs").iterdir())
        assert len(runs) == 2 and any("classroom" in n for n in runs) and any("teaching" in n for n in runs), runs


# ---- #25 失败分类与六项验收回传：各阶段失败路径（CLI + 可替换依赖）----


@contextmanager
def local_tts(status=200):
    """本地 TTS stand-in，计数收到的 POST；status!=200 时一律回该状态码。"""
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 24000)
    payload = json.dumps({"choices": [{"message": {"audio": {
        "data": base64.b64encode(audio.getvalue()).decode("ascii"),
    }}}]}).encode()
    counter = {"post": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            counter["post"] += 1
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload) if status == 200 else 0))
            self.end_headers()
            if status == 200:
                self.wfile.write(payload)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/tts", counter
        finally:
            server.shutdown()
            thread.join()


def test_worker_usage_error_is_preflight_failure():
    with tempfile.TemporaryDirectory(prefix="mv_fail_use_") as tmp:
        project = _copy_project(tmp)
        r = _run_worker(project, dict(os.environ, PYTHONUTF8="1"), "x.json", "out/x.mp4")
    assert r.returncode == 1
    assert "status: FAIL_AT_PREFLIGHT" in r.stdout
    assert "必须显式选择 --reuse-audio" in r.stdout


def test_worker_missing_storyboard_fails_at_preflight_with_four_fields():
    with tempfile.TemporaryDirectory(prefix="mv_fail_pre_") as tmp:
        project = _copy_project(tmp)
        env = dict(os.environ, MIMO_API_KEY="local-test", PYTHONUTF8="1")
        r = _run_worker(project, env, "cases/none/lesson.json", "out/x.mp4", "--reuse-audio")
    assert r.returncode == 1
    assert "status: FAIL_AT_PREFLIGHT" in r.stdout
    for field in ("artifact: (none)", "verify: (none)", "diagnostic:"):
        assert field in r.stdout
    assert "分镜 JSON 不存在" in r.stdout


def test_worker_missing_browser_maps_to_preflight():
    with tempfile.TemporaryDirectory(prefix="mv_fail_br_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Browser missing.", 0.0)
        env = dict(os.environ, MIMO_API_KEY="local-test", PYTHONUTF8="1",
                   MIMO_API_URL="http://127.0.0.1:9/tts")
        r = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4",
                        "--reuse-audio", "--browser", "Z:/no/browser.exe")
    assert r.returncode == 1
    assert "status: FAIL_AT_PREFLIGHT" in r.stdout
    assert "指定浏览器不存在" in r.stdout


def test_worker_preview_failure_runs_zero_tts_requests():
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_fail_pv_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Overflow narration.", 0.0)
        sb = project / "cases/a/lesson.json"
        tpl = json.loads(sb.read_text(encoding="utf-8"))
        tpl["scenes"][1]["body"] = "<br>".join(["A = B + C"] * 24)  # rule 正文溢出
        sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        with local_tts() as (url, counter):
            env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=url, PYTHONUTF8="1")
            r = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4", "--reuse-audio")
        assert r.returncode == 2
        assert "status: FAIL_AT_PREVIEW" in r.stdout
        assert "verify: (none)" in r.stdout
        assert "cache: (none)" in r.stdout  # 渲染未完成，无本次事实
        assert counter["post"] == 0  # 预览失败零 TTS 请求


def test_worker_tts_failure_reports_render_stage():
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_fail_rd_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Render fail.", 0.0)
        with local_tts(status=500) as (url, counter):
            env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=url, PYTHONUTF8="1")
            r = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4", "--reuse-audio")
        assert counter["post"] > 0  # 确实走到了 render 的 TTS
        assert r.returncode == 3
        assert "status: FAIL_AT_RENDER" in r.stdout
        assert "make_video.py exit" in r.stdout


def test_worker_verify_failure_marks_failed_and_unexecuted(tts_url):
    """预览拦不到的分镜级残留（rule 页 wrong_body 不进渲染 HTML）→ 检查 6 红。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_fail_vf_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Verify check6.", 0.0)
        sb = project / "cases/a/lesson.json"
        tpl = json.loads(sb.read_text(encoding="utf-8"))
        tpl["scenes"][1]["wrong_body"] = "line1\\nline2"
        sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        r = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4", "--no-reuse-audio")
        assert r.returncode == 4, r.stdout + r.stderr
        assert "status: FAIL_AT_VERIFY" in r.stdout
        assert "verify: [✓✓✓✓-✗]" in r.stdout  # 5 显式跳过、6 失败，未执行不填通过
        assert "CHECK 6 FAIL" in r.stdout
        assert "verify FAIL [6]" in r.stdout


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_worker_success_and_standalone_verify_marks_are_honest(tts_url):
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_ok_marks_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Marks narration.", 0.0)
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        r = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4", "--reuse-audio")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verify: [✓✓✓✓✓✓]" in r.stdout  # 全部实测通过才可全勾
        steps = next(line for line in r.stdout.splitlines() if line.startswith("steps:"))
        for token in ("PREFLIGHT_OK", "PREVIEW_OK", "DONE", "VERIFY_OK"):
            assert token in steps
        # 单独验收：1/2 没跑过 → 如实记 ·，5 未要求 → 显式跳过 -
        v1 = subprocess.run(
            [sys.executable, "scripts/worker_verify.py", "cases/a/lesson.json", "out/x.mp4"],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        assert v1.returncode == 0, v1.stdout + v1.stderr
        assert "VERIFY_OK [··✓✓-✓]" in v1.stdout
        assert "CHECK 1 PASS" not in v1.stdout  # 不声称未执行的前置检查
        v2 = subprocess.run(
            [sys.executable, "scripts/worker_verify.py", "cases/a/lesson.json", "out/x.mp4",
             "--style", "teaching", "--expect-reuse-audio"],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        assert v2.returncode == 0, v2.stdout + v2.stderr
        assert "VERIFY_OK [··✓✓✓✓]" in v2.stdout
        assert "reuse-confirmed" in v2.stdout


# ---- #24 回传真实复用与 TTS 生成情况：事实取自本次 run manifest ----


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_worker_reports_cache_facts_across_runs(tts_url):
    """冷缓存全生成、热缓存零 TTS、单段旁白改动只重配一段、--no-reuse-audio
    全量重跑 mode=regenerate 且检查 5 显式跳过不假通过。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_cache_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Cache facts.", 0.0)
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        with local_tts() as (url, counter):
            env["MIMO_API_URL"] = url
            r1 = _run_worker(project, env, "cases/a/lesson.json", "out/a.mp4", "--reuse-audio")
            assert r1.returncode == 0, r1.stdout + r1.stderr
            assert "cache: generated=6 reused=0 mode=reuse" in r1.stdout, r1.stdout
            assert counter["post"] == 6, counter
            r2 = _run_worker(project, env, "cases/a/lesson.json", "out/a2.mp4", "--reuse-audio")
            assert r2.returncode == 0, r2.stdout + r2.stderr
            assert "cache: generated=0 reused=6 mode=reuse" in r2.stdout, r2.stdout
            assert counter["post"] == 6, counter  # 热缓存零 TTS 请求
            sb = project / "cases/a/lesson.json"
            tpl = json.loads(sb.read_text(encoding="utf-8"))
            tpl["scenes"][2]["narrate"] = "Changed narration only."
            sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
            r3 = _run_worker(project, env, "cases/a/lesson.json", "out/a3.mp4", "--reuse-audio")
            assert r3.returncode == 0, r3.stdout + r3.stderr
            assert "cache: generated=1 reused=5 mode=reuse" in r3.stdout, r3.stdout
            assert counter["post"] == 7, counter  # 只重配改动的一段
            r4 = _run_worker(project, env, "cases/a/lesson.json", "out/a4.mp4", "--no-reuse-audio")
            assert r4.returncode == 0, r4.stdout + r4.stderr
            assert "cache: generated=6 reused=0 mode=regenerate" in r4.stdout, r4.stdout
            assert "verify: [✓✓✓✓-✓]" in r4.stdout  # 5 显式跳过，不填通过
            assert counter["post"] == 13, counter


# ---- #26 完整 worker 只预览一次：token 归属 + 输入指纹，过期/他 run 不沿用 ----


def _png_mtimes(preview_dir):
    return {p.name: p.stat().st_mtime_ns for p in Path(preview_dir).glob("s*.png")}


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_make_video_preview_reuse_bound_to_token_and_inputs(tts_url):
    """复用仅对「同 token + 同输入」生效：直接渲染/换 token/改分镜、style、
    layout 一律重新预验，绝不以旧成功结果渲染新输入。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_once_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Preview once.", 0.0)
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        sb = project / "cases/a/lesson.json"
        rkey = ra.run_key(str(sb), "teaching", True)
        pvdir = project / "_build" / "runs" / f"lesson__teaching__{rkey}" / "preview"

        def run_make(*extra):
            return subprocess.run(
                [sys.executable, "scripts/make_video.py", "cases/a/lesson.json", *extra],
                cwd=project, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=240,
            )

        orig_sb = sb.read_bytes()
        orig_layout = (project / "templates/layout-rule.html").read_text(encoding="utf-8")
        style = json.loads((project / "templates/style-teaching.json").read_text(encoding="utf-8"))
        orig_style = json.dumps(style, ensure_ascii=False)

        # 1) 独立预览（token T1）→ 印记落位
        r = run_make("--preview", "--preview-token", "T1")
        assert r.returncode == 0, r.stdout + r.stderr
        stamp = json.loads((pvdir / "stamp.json").read_text(encoding="utf-8"))
        assert stamp["token"] == "T1" and len(stamp["digest"]) == 64
        m1 = _png_mtimes(pvdir)
        # 2) 同 token 成片 → 复用（截图不再重写），成片正常
        r = run_make("out/full.mp4", "--preview-token", "T1", "--reuse-audio")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PREVIEW REUSED" in r.stdout
        assert _png_mtimes(pvdir) == m1  # 实际预览产物未被重写
        assert (project / "out/full.mp4").stat().st_size > 1000
        # 3) 直接渲染（无 token）→ 仍自行预览
        r = run_make("out/direct.mp4", "--reuse-audio")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PREVIEW REUSED" not in r.stdout
        assert _png_mtimes(pvdir) != m1  # 截图确实重跑了
        # 4) 换 token → 他 run 的预览不沿用
        r = run_make("out/other.mp4", "--preview-token", "T2", "--reuse-audio")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PREVIEW REUSED" not in r.stdout
        # 5) 预览后改 layout → 指纹变，重新预验
        (project / "templates/layout-rule.html").write_text(
            orig_layout.replace("</style>", ".x{color:red}</style>"), encoding="utf-8"
        )
        r = run_make("--preview", "--preview-token", "T1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PREVIEW REUSED" not in r.stdout
        (project / "templates/layout-rule.html").write_text(orig_layout, encoding="utf-8")
        # 6) 改 style → 指纹变，重新预验
        style["palette"]["bg"] = "#010203"
        (project / "templates/style-teaching.json").write_text(
            json.dumps(style, ensure_ascii=False), encoding="utf-8"
        )
        r = run_make("--preview", "--preview-token", "T1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PREVIEW REUSED" not in r.stdout
        (project / "templates/style-teaching.json").write_text(orig_style, encoding="utf-8")
        # 7) 改分镜 → 指纹变，重新预验（不得沿用旧成功结果）
        tpl = json.loads(sb.read_text(encoding="utf-8"))
        tpl["scenes"][1]["body"] = "**Changed**"
        sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        r = run_make("--preview", "--preview-token", "T1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PREVIEW REUSED" not in r.stdout
        # 8) 输入复原：首次预览重建印记（case 7 已覆盖旧印记），再次预览即复用
        sb.write_bytes(orig_sb)
        r = run_make("--preview", "--preview-token", "T1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PREVIEW REUSED" not in r.stdout
        r = run_make("--preview", "--preview-token", "T1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PREVIEW REUSED" in r.stdout


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_full_worker_previews_once_with_reuse_trace(tts_url):
    """完整 worker 全程只截一次图：steps 行带 PREVIEW_REUSED 执行痕迹，
    run 目录留有本次 run 的 stamp + 全套截图；输入变化后新一轮自验自用。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_wonce_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Worker previews once.", 0.0)
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        with local_tts() as (url, counter):
            env["MIMO_API_URL"] = url
            r1 = _run_worker(project, env, "cases/a/lesson.json", "out/w1.mp4", "--reuse-audio")
            assert r1.returncode == 0, r1.stdout + r1.stderr
            steps1 = next(x for x in r1.stdout.splitlines() if x.startswith("steps:"))
            assert "PREVIEW_OK" in steps1 and "PREVIEW_REUSED" in steps1
            assert counter["post"] == 6, counter
        rkey = ra.run_key(str(project / "cases/a/lesson.json"), "teaching", True)
        pvdir = project / "_build" / "runs" / f"lesson__teaching__{rkey}" / "preview"
        stamp = json.loads((pvdir / "stamp.json").read_text(encoding="utf-8"))
        assert len(stamp["digest"]) == 64 and stamp["token"]  # 本次 run 的归属印记
        assert (pvdir / "s5.png").is_file()
        # 预览后改分镜：新一轮在改动后的内容上重验（raw 未变 → 零 TTS）
        sb = project / "cases/a/lesson.json"
        tpl = json.loads(sb.read_text(encoding="utf-8"))
        tpl["scenes"][1]["body"] = "**Edited after preview**"
        sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        with local_tts() as (url, counter):
            env["MIMO_API_URL"] = url
            r2 = _run_worker(project, env, "cases/a/lesson.json", "out/w2.mp4", "--reuse-audio")
            assert r2.returncode == 0, r2.stdout + r2.stderr
            steps2 = next(x for x in r2.stdout.splitlines() if x.startswith("steps:"))
            assert "PREVIEW_REUSED" in steps2  # 本轮自己的预览→成片仍只截一次图
            assert counter["post"] == 0, counter  # 旁白未变：重验不消耗 TTS
        runs = sorted(p.name for p in (project / "_build" / "runs").iterdir())
        assert len(runs) == 2, runs  # 改动后新 run 目录，旧 run 产物未被挪用


# ---- #23 并行换皮自动独立成片 + 目标占用保护 ----


def _artifact_of(stdout):
    return next(
        line.split(": ", 1)[1] for line in stdout.splitlines() if line.startswith("artifact: ")
    )


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_worker_three_skins_parallel_auto_outputs(tts_url):
    """同一分镜三种皮肤省略 output 真并行：三个不同可播成片，验收互不污染。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_par3_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Three skins narration.", 0.0)
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        jobs = [
            (["cases/a/lesson.json", "--reuse-audio"], "lesson__teaching"),
            (["cases/a/lesson.json", "--reuse-audio", "--style", "classroom"], "lesson__classroom"),
            (["cases/a/lesson.json", "--reuse-audio", "--style", "explainer"], "lesson__explainer"),
        ]
        with ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(
                lambda j: _run_worker(project, env, *j[0]), jobs
            ))
        artifacts = []
        for (flags, want), r in zip(jobs, results):
            assert r.returncode == 0, r.stdout + r.stderr
            art = _artifact_of(r.stdout)
            assert want in art and art.endswith(".mp4"), art  # 自动命名绑定皮肤
            mp4 = project / art
            assert mp4.is_file() and mp4.stat().st_size > 0, art
            artifacts.append(art)
        assert len(set(artifacts)) == 3, artifacts  # 三皮肤三个不同输出
        # 各自验收互不污染：verify 按各自 run（style 参与定位）独立通过
        for art, style_flag in zip(artifacts, ([], ["--style", "classroom"], ["--style", "explainer"])):
            v = subprocess.run(
                [sys.executable, "scripts/worker_verify.py", "cases/a/lesson.json", art, *style_flag],
                cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            assert v.returncode == 0, v.stdout + v.stderr


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_worker_auto_naming_no_sanitize_collision(tts_url):
    """皮肤名规范化会重合（"a b" 与 "a_b"）→ 自动输出必须仍不同。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_name_col_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Name collision.", 0.0)
        base = (project / "templates/style-classroom.json").read_text(encoding="utf-8")
        (project / "templates/style-a b.json").write_text(base, encoding="utf-8")
        (project / "templates/style-a_b.json").write_text(base, encoding="utf-8")
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(
                lambda s: _run_worker(project, env, "cases/a/lesson.json",
                                      "--reuse-audio", "--style", s),
                ("a b", "a_b"),
            ))
        arts = []
        for s, r in zip(("a b", "a_b"), results):
            assert r.returncode == 0, f"[{s}] " + r.stdout + r.stderr
            arts.append(_artifact_of(r.stdout))
        assert arts[0] != arts[1], arts  # 不同皮肤不映射到同一输出
        assert (project / arts[0]).is_file() and (project / arts[1]).is_file()


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_worker_target_occupied_refuses_before_tts(tts_url):
    """活动运行占用显式目标 → 后启动者 PREFLIGHT 拒绝、零 TTS、历史成片不动；
    释放后可顺序重渲。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_occ_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Occupied target.", 0.0)
        outdir = project / "out"
        outdir.mkdir(exist_ok=True)
        (outdir / "x.mp4").write_bytes(b"old artifact")  # 历史成片
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        with local_tts() as (url, counter):
            env["MIMO_API_URL"] = url
            lock = ra.acquire_target(str(outdir / "x.mp4"), style_name="teaching")
            try:
                r = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4", "--reuse-audio")
                assert r.returncode == 1
                assert "status: FAIL_AT_PREFLIGHT" in r.stdout
                assert "正被活动运行占用" in r.stdout
                assert counter["post"] == 0  # 被拒运行未开始配音
                assert (outdir / "x.mp4").read_bytes() == b"old artifact"
            finally:
                lock.release()
            assert not (outdir / "x.mp4.lock").exists()  # 释放后可重用目标
            r2 = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4", "--reuse-audio")
            assert r2.returncode == 0, r2.stdout + r2.stderr
            assert (outdir / "x.mp4").stat().st_size > 1000  # 顺序重渲得真成片


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_worker_stale_lock_recovered(tts_url):
    """进程死亡留下的过期锁（心跳停止、mtime 过旧）被接管，运行正常完成。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_stale_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Stale lock.", 0.0)
        outdir = project / "out"
        outdir.mkdir(exist_ok=True)
        lockfile = outdir / "x.mp4.lock"
        lockfile.write_text(
            json.dumps({"token": "deadbeef", "pid": 999999, "output": "out/x.mp4"}),
            encoding="utf-8",
        )
        old = time.time() - ra.LOCK_STALE_SECONDS * 5
        os.utime(lockfile, (old, old))
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        r = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4", "--reuse-audio")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "已失效" in r.stderr  # 接管有可验证的说明
        assert not lockfile.exists()  # 正常结束释放的是本次自己的锁
        assert (outdir / "x.mp4").stat().st_size > 1000


# ---- #27 动画 block 整页换肤（hyperframes Path A）----


def _cdn_reachable():
    import urllib.request

    try:
        urllib.request.urlopen(
            "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js", timeout=5
        )
        return True
    except OSError:
        return False


def test_block_lookup_and_switch():
    from make_video import block_for_kind, blocks_enabled

    assert block_for_kind("title")[0] == "beat-freeze-cut.html"
    assert block_for_kind("rule")[0] == "cinematic-zoom.html"
    assert block_for_kind("mistake")[0] == "bar-chart-race.html"
    for kind in ("example", "practice", "answer", "summary", "diagram", None):
        assert block_for_kind(kind) is None
    assert blocks_enabled({}) is True  # 默认开启
    assert blocks_enabled({"blocks": True}) is True
    assert blocks_enabled({"blocks": False}) is False  # 分镜级关闭


def test_block_smoke_timelines_initialize():
    """blocks/_smoke.py：3 个 block 的 GSAP timeline 在 headless 下初始化成功。"""
    if not find_browser():
        pytest.skip("no Chrome/Edge available")
    if not _cdn_reachable():
        pytest.skip("blocks CDN (jsdelivr) unreachable")
    r = subprocess.run(
        [sys.executable, "templates/blocks/_smoke.py"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("[PASS]") == 3, r.stdout


def _write_block_storyboard(project, sub):
    """默认 1080p（不写 width/height），title/rule/mistake 会被 block 换肤。"""
    d = project / "cases" / sub
    d.mkdir(parents=True, exist_ok=True)
    tpl = {
        "title": "现在进行时", "voice": "mimo_default", "fps": 2,
        "scenes": [
            {"kind": "title", "header": "现在进行时", "sub": "be + V-ing",
             "body": "**现在进行时**", "narrate": "N"},
            {"kind": "rule", "header": "核心规则", "sub": "结构",
             "body": "be (am/is/are) + **V-ing**", "narrate": "N"},
            {"kind": "example", "header": "例句", "sub": "S",
             "body": "I am **running**", "narrate": "N"},
            {"kind": "mistake", "header": "常见错误", "sub": "占比",
             "body": "He go **to school**", "zh": "Z", "narrate": "N"},
            {"kind": "practice", "header": "练习", "sub": "S",
             "body": "She **is** run", "think": "T", "narrate": "N", "hold": 3},
            {"kind": "answer", "header": "答案", "sub": "S",
             "body": "She **is running**", "narrate": "N"},
            {"kind": "summary", "header": "S", "sub": "next",
             "body": "**be + V-ing**", "narrate": "N"},
        ],
    }
    (d / "lesson.json").write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_blocks_render_pages_and_1080p(tts_url):
    """block 页整页换肤并进成片：preview/成片日志、manifest 记录、1080p 分辨率。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    if not _cdn_reachable():
        pytest.skip("blocks CDN (jsdelivr) unreachable")
    with tempfile.TemporaryDirectory(prefix="mv_blk_") as tmp:
        project = _copy_project(tmp)
        _write_block_storyboard(project, "a")
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        r = subprocess.run(
            [sys.executable, "scripts/make_video.py", "cases/a/lesson.json", "out/blk.mp4"],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[title/block:beat-freeze-cut]" in r.stdout
        assert "[rule/block:cinematic-zoom]" in r.stdout
        assert "[mistake/block:bar-chart-race]" in r.stdout
        runs = project / "_build" / "runs"
        manifest = json.loads(
            (runs / sorted(p.name for p in runs.iterdir())[0] / "manifest.json").read_text(encoding="utf-8")
        )
        assert (manifest["W"], manifest["H"]) == (1920, 1080)
        blocks = [s["block"] for s in manifest["scenes"]]
        assert blocks == [
            "beat-freeze-cut", "cinematic-zoom", None,
            "bar-chart-race", None, None, None,
        ]
        assert (project / "out/blk.mp4").stat().st_size > 1000
        # 六项验收对 block 成片照常工作（读 manifest 真实音轨）
        v = subprocess.run(
            [sys.executable, "scripts/worker_verify.py", "cases/a/lesson.json", "out/blk.mp4",
             "--expect-reuse-audio"],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        assert v.returncode == 0, v.stdout + v.stderr


def test_blocks_disabled_renders_static():
    """顶层 "blocks": false → 整支走静态布局，无 block 换肤。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_blkoff_") as tmp:
        project = _copy_project(tmp)
        _write_block_storyboard(project, "a")
        sb = project / "cases/a/lesson.json"
        tpl = json.loads(sb.read_text(encoding="utf-8"))
        tpl["blocks"] = False
        sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, MIMO_API_KEY="local-test", PYTHONUTF8="1")
        r = subprocess.run(
            [sys.executable, "scripts/make_video.py", "cases/a/lesson.json", "--preview"],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "block:" not in r.stdout
        assert "PREVIEW OK" in r.stdout


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_block_init_failure_falls_back_to_static(tts_url):
    """block 初始化失败（GSAP 加载不到）→ 该页回退静态布局，整支视频照常出片。"""
    browser = find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_blkfb_") as tmp:
        project = _copy_project(tmp)
        _write_block_storyboard(project, "a")
        bf = project / "templates/blocks/beat-freeze-cut.html"
        bf.write_text(
            bf.read_text(encoding="utf-8").replace(
                '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>',
                "",
            ),
            encoding="utf-8",
        )
        env = dict(os.environ, MIMO_API_KEY="local-test", MIMO_API_URL=tts_url, PYTHONUTF8="1")
        r = subprocess.run(
            [sys.executable, "scripts/make_video.py", "cases/a/lesson.json", "out/blk.mp4"],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "初始化失败" in r.stderr  # 回退有可验证的 warning
        runs = project / "_build" / "runs"
        manifest = json.loads(
            (runs / sorted(p.name for p in runs.iterdir())[0] / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["scenes"][0]["block"] is None  # title 回退静态
        assert manifest["scenes"][1]["block"] == "cinematic-zoom"  # 其他 block 不受影响
        assert (project / "out/blk.mp4").stat().st_size > 1000
