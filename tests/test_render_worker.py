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
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from toolchain import browser_path, ffmpeg_path  # noqa: E402
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


@pytest.fixture
def minimax_tts_url():
    """MiniMax /v1/t2a_v2 形状的本地 stand-in：`data.audio` 是 mp3 的 hex。

    与小米 adapter 不同，MiniMax 回 mp3（make_video 自己过 ffmpeg 转 wav），
    所以这里用 ffmpeg 现造一段 0.2s 静音 mp3；同时计数收到的 POST。
    """
    import imageio_ffmpeg

    mp3 = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.2",
            "-c:a", "libmp3lame", "-f", "mp3", "pipe:1",
        ],
        capture_output=True,
    ).stdout
    assert mp3, "ffmpeg 未能生成 mp3 测试负载"
    payload = json.dumps(
        {"base_resp": {"status_code": 0}, "data": {"audio": mp3.hex()}}
    ).encode()
    counter = {"post": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            counter["post"] += 1
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
            yield f"http://127.0.0.1:{server.server_port}/v1/t2a_v2", counter
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize("override", ["style", "no-motion", "browser"])
def test_worker_accepts_preview_configuration_overrides(tts_url, override):
    browser = browser_path()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_worker_") as tmp:
        project = Path(tmp)
        shutil.copytree(ROOT / "scripts", project / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "templates", project / "templates")
        tpl = {
            "title": "Worker", "voice": "mimo_default", "fps": 2,
            "tts_provider": "xiaomi",  # 钉住小米，配 tts_url 的 stand-in
            "scenes": [
                {"kind": kind, "header": "H", "body": "**B**", "narrate": "N"}
                for kind in ("title", "rule", "example", "practice", "answer", "summary")
            ],
        }
        tpl["scenes"][3]["hold"] = 5
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
            "tts_provider": "xiaomi",  # 钉住小米，配 tts_url 的 stand-in
            "scenes": [
                {"kind": kind, "header": "H", "body": "**B**", "narrate": "N", "motion": "none"}
                for kind in ("title", "rule", "example", "practice", "answer", "summary")
            ],
        }
        tpl["scenes"][1].update(motion=[{"type": "zoom_in", "delay": 2}], hold=2)
        tpl["scenes"][3]["hold"] = 5
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
                [ffmpeg_path(), "-loglevel", "error", "-ss", str(second), "-i", str(output),
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


def _write_source_storyboard(project, sub, narrate, hold=0.0, provider="xiaomi"):
    """完整教学弧（闸门要求 6 个必要 kind）；变量 hold 放 scene 0（title）。

    provider 显式钉住本次课的 TTS 引擎，缺省 xiaomi 以匹配 tts_url fixture 的
    小米形状 stand-in（全局默认是 minimax，不写就打到真 MiniMax 去）；传 None
    则不写顶层字段，专供验证「默认 provider」路径的用例。
    """
    d = project / "cases" / sub
    d.mkdir(parents=True, exist_ok=True)
    tpl = {
        "title": "T", "voice": "mimo_default", "fps": 2,
        "scenes": [
            {"kind": kind, "header": "H", "body": "**B**", "narrate": narrate}
            for kind in ("title", "rule", "example", "practice", "answer", "summary")
        ],
    }
    if provider is not None:
        tpl["tts_provider"] = provider
    tpl["scenes"][0]["hold"] = hold
    tpl["scenes"][3]["hold"] = 5.0  # practice 闸门要求 hold >= 5.0
    (d / "lesson.json").write_text(json.dumps(tpl), encoding="utf-8")


def _run_worker(project, env, sb, out, *extra):
    return subprocess.run(
        [sys.executable, "scripts/render_worker.py", sb, out, *extra],
        cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=240,
    )


@pytest.mark.parametrize("tts_url", [0.3], indirect=True)
def test_parallel_same_slug_different_sources_own_their_artifacts(tts_url):
    """不同来源但主名相同的分镜并行：预览与加工音轨互不覆盖（显式 MP4 目标）。"""
    browser = browser_path()
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
    browser = browser_path()
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
    browser = browser_path()
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


def test_preflight_reads_tts_key_from_dotenv():
    """ROOT/.env 的 MIMO_API_KEY 必须在 key 检查前进入 environ，
    否则干净 shell 里 worker 必然 FAIL_AT_PREFLIGHT。"""
    pytest.importorskip("dotenv")  # 缺包时 load_env 静默 no-op，本用例前提不成立
    with tempfile.TemporaryDirectory(prefix="mv_env_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Env key narration.", 0.0)
        (project / ".env").write_text("MIMO_API_KEY=from-dotenv\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "MIMO_API_KEY"}
        env["PYTHONUTF8"] = "1"
        r = subprocess.run(
            [sys.executable, "scripts/worker_preflight.py", "cases/a/lesson.json"],
            cwd=project, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=120,
        )
        assert "no TTS key" not in r.stderr, r.stderr


def _preflight(project, env):
    return subprocess.run(
        [sys.executable, "scripts/worker_preflight.py", "cases/a/lesson.json"],
        cwd=project, env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=120,
    )


def test_preflight_tts_key_follows_provider():
    """第 3 项按本次 provider 查 key：MiniMax 课要 MINIMAX_API_KEY。

    回归：曾无条件只查 MIMO_API_KEY → 只配了 MINIMAX_API_KEY 的 MiniMax 课
    被拒之门外，而 MIMO_API_KEY 在、MiniMax key 缺时又放行到渲染才炸。
    """
    with tempfile.TemporaryDirectory(prefix="mv_pre_key_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Provider key narration.", 0.0)
        sb = project / "cases/a/lesson.json"
        tpl = json.loads(sb.read_text(encoding="utf-8"))
        tpl["tts_provider"] = "minimax"
        sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")

        base = {
            k: v for k, v in os.environ.items()
            if k not in ("MIMO_API_KEY", "MINIMAX_API_KEY")
        }
        base["PYTHONUTF8"] = "1"

        # MiniMax 课 + 只有小米 key → 必须点名 MINIMAX_API_KEY，不拿 MIMO 顶替
        r = _preflight(project, dict(base, MIMO_API_KEY="local-test"))
        assert r.returncode == 1, r.stdout + r.stderr
        assert "MINIMAX_API_KEY" in r.stderr, r.stderr

        # 反向：只有 MiniMax key → 不再报「缺 TTS key」（浏览器缺失是另一项）
        r = _preflight(project, dict(base, MINIMAX_API_KEY="local-test"))
        assert "no TTS key" not in r.stderr, r.stderr
        assert "MIMO_API_KEY" not in r.stderr, r.stderr

        # 分镜未声明 provider（默认 minimax）→ 查 MINIMAX_API_KEY 并点名它
        tpl.pop("tts_provider")
        sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        r = _preflight(project, base)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "MINIMAX_API_KEY" in r.stderr, r.stderr

        # CLI 覆盖优先于分镜字段：分镜写 xiaomi、CLI 传 minimax → 查 MiniMax key
        tpl["tts_provider"] = "xiaomi"
        sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, "scripts/worker_preflight.py", "cases/a/lesson.json",
             "--tts-provider", "minimax"],
            cwd=project, env=dict(base, MIMO_API_KEY="local-test"), capture_output=True,
            text=True, encoding="utf-8", timeout=120,
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert "MINIMAX_API_KEY" in r.stderr, r.stderr


def test_worker_preview_failure_runs_zero_tts_requests():
    browser = browser_path()
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
    browser = browser_path()
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


def test_minimax_storyboard_renders_and_reuses_with_provider_aware_check5(
    minimax_tts_url,
):
    """MiniMax 课的 provider 要贯穿三处：preflight 查 MINIMAX_API_KEY、render 写
    minimax 指纹缓存、verify 检查 5 用同一 provider 核对（audio_cache v3 指纹含 provider）。

    回归：verify 曾漏传 provider（静默退化成 xiaomi）→ MiniMax 课第一次渲染就
    必然 FAIL_AT_VERIFY「cache miss」，`--reuse-audio` 在这条链上完全不可用。
    """
    browser = browser_path()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    url, counter = minimax_tts_url
    with tempfile.TemporaryDirectory(prefix="mv_minimax_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "MiniMax narration.", 0.0)
        sb = project / "cases/a/lesson.json"
        tpl = json.loads(sb.read_text(encoding="utf-8"))
        tpl["tts_provider"] = "minimax"
        sb.write_text(json.dumps(tpl, ensure_ascii=False), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "MIMO_API_KEY"}
        env.update(MINIMAX_API_KEY="local-test", MINIMAX_API_URL=url, PYTHONUTF8="1")

        r1 = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4", "--reuse-audio")
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "status: OK" in r1.stdout, r1.stdout
        assert "generated=6 reused=0" in r1.stdout, r1.stdout
        assert counter["post"] == 6, counter  # 6 幕各合成一次

        # worker 的 OK 路径只回传摘要行，检查 5 的 provider 明细只在 standalone verify 里可见
        v = subprocess.run(
            [
                sys.executable,
                "scripts/worker_verify.py",
                "cases/a/lesson.json",
                "out/x.mp4",
                "--expect-reuse-audio",
            ],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert v.returncode == 0, v.stdout + v.stderr
        assert "CHECK 5 PASS" in v.stdout, v.stdout
        assert "reuse-confirmed provider=minimax" in v.stdout, v.stdout

        # 第二次同分镜同 provider：全命中，零 TTS 请求，检查 5 仍须绿
        r2 = _run_worker(project, env, "cases/a/lesson.json", "out/x.mp4", "--reuse-audio")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "status: OK" in r2.stdout, r2.stdout
        assert "generated=0 reused=6" in r2.stdout, r2.stdout
        assert counter["post"] == 6, counter


def test_worker_tts_provider_cli_reaches_all_three_stages(minimax_tts_url):
    """分镜不写 provider：默认走 minimax，CLI `--tts-provider` 三处透传各自被钉住。

    render_worker 把 provider 分别转发给 preflight（查 key）、make_video（合成/写缓存）、
    verify（检查 5 核对缓存）。三个分支此前都没有测试，删掉任意一个都能静默通过：
      · preflight 漏传 → 按默认 minimax 查 key，CLI 传的 xiaomi 无人认领
      · make_video 漏传 → 同上，缓存写进 minimax 指纹路径
      · verify 漏传 → 拿 minimax 指纹查 xiaomi 缓存 → 假 cache miss → FAIL_AT_VERIFY
    反向控制：CLI 显式传 xiaomi 时，env 里没有 MIMO_API_KEY，必须提前失败。
    """
    browser = browser_path()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    url, counter = minimax_tts_url
    with tempfile.TemporaryDirectory(prefix="mv_provider_cli_") as tmp:
        project = _copy_project(tmp)
        # provider=None：分镜不写顶层字段，走全局默认 minimax
        _write_source_storyboard(project, "a", "CLI provider narration.", 0.0, provider=None)
        sb = "cases/a/lesson.json"
        env = {k: v for k, v in os.environ.items() if k != "MIMO_API_KEY"}
        env.update(MINIMAX_API_KEY="local-test", MINIMAX_API_URL=url, PYTHONUTF8="1")

        def verify(*extra):
            return subprocess.run(
                [sys.executable, "scripts/worker_verify.py", sb, "out/x.mp4", *extra],
                cwd=project, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=120,
            )

        # 反向控制（1）：CLI 显式传 xiaomi → preflight 查 MIMO_API_KEY → 提前失败
        r0 = _run_worker(project, env, sb, "out/x.mp4",
                         "--reuse-audio", "--tts-provider", "xiaomi")
        assert r0.returncode == 1, r0.stdout + r0.stderr
        assert "status: FAIL_AT_PREFLIGHT" in r0.stdout, r0.stdout
        assert "MIMO_API_KEY" in r0.stdout, r0.stdout
        assert counter["post"] == 0, counter  # preflight 失败不花配额

        # 不传 provider → 默认 minimax，六页全部生成
        r1 = _run_worker(project, env, sb, "out/x.mp4", "--reuse-audio")
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "status: OK" in r1.stdout, r1.stdout
        assert "generated=6 reused=0" in r1.stdout, r1.stdout
        assert counter["post"] == 6, counter

        # 反向控制（2）：缓存是 minimax 指纹，verify 传 xiaomi → 检查 5 必须红
        v0 = verify("--expect-reuse-audio", "--tts-provider", "xiaomi")
        assert v0.returncode != 0, v0.stdout + v0.stderr
        assert "CHECK 5 FAIL" in v0.stdout, v0.stdout
        assert "cache miss scene 0" in v0.stdout, v0.stdout

        v1 = verify("--expect-reuse-audio")
        assert v1.returncode == 0, v1.stdout + v1.stderr
        assert "CHECK 5 PASS" in v1.stdout, v1.stdout
        assert "reuse-confirmed provider=minimax" in v1.stdout, v1.stdout

        # 第二次同 provider：全命中、零新增请求
        r2 = _run_worker(project, env, sb, "out/x.mp4", "--reuse-audio")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "status: OK" in r2.stdout, r2.stdout
        assert "generated=0 reused=6" in r2.stdout, r2.stdout
        assert counter["post"] == 6, counter


def test_worker_verify_failure_marks_failed_and_unexecuted(tts_url):
    """预览拦不到的分镜级残留（rule 页 wrong_body 不进渲染 HTML）→ 检查 6 红。"""
    browser = browser_path()
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
    browser = browser_path()
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
    browser = browser_path()
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


# ---- 预览去重：Step 2 用 --preview 预验，Step 3 用 --skip-preview 复用同 run 目录 ----


def _png_mtimes(preview_dir):
    return {p.name: p.stat().st_mtime_ns for p in Path(preview_dir).glob("s*.png")}


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_skip_preview_reuses_this_run_preview(tts_url):
    """--skip-preview 复用同 run_key 目录里刚验过的截图：不重写产物、仍出成片；
    不传该开关则自行重截。--preview 与 --skip-preview 互斥。"""
    browser = browser_path()
    if not browser:
        pytest.skip("no Chrome/Edge available")
    with tempfile.TemporaryDirectory(prefix="mv_skip_") as tmp:
        project = _copy_project(tmp)
        _write_source_storyboard(project, "a", "Skip preview.", 0.0)
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

        r = run_make("--preview")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PREVIEW_OK" in r.stdout
        before = _png_mtimes(pvdir)

        r = run_make("out/full.mp4", "--skip-preview", "--reuse-audio")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "跳过（复用已有预览）" in r.stdout
        assert _png_mtimes(pvdir) == before  # 复用：截图未被重写
        assert (project / "out/full.mp4").stat().st_size > 1000

        r = run_make("out/direct.mp4", "--reuse-audio")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "跳过（复用已有预览）" not in r.stdout
        assert _png_mtimes(pvdir) != before  # 默认自行重截

        # 两个开关互斥，同时传是用法错误
        r = run_make("out/both.mp4", "--preview", "--skip-preview")
        assert r.returncode != 0


def test_worker_maps_preview_reuse_rejection_to_preview_stage(monkeypatch, capsys):
    """Step 3 复用被拒（make_video exit 4）必须归 PREVIEW 阶段。

    报成 FAIL_AT_RENDER 会把人引去查编码，实际该重跑预览（#26 AC2）。
    """
    import render_worker as rw

    sb = str(ROOT / "examples" / "what_is_harness.json")

    def fake_run(argv):
        if argv[0].endswith("worker_preflight.py"):
            return 0, "PREFLIGHT_OK"
        if "--preview" in argv:  # Step 2 通过；Step 3 传的是 --skip-preview
            return 0, "PREVIEW_OK"
        return 4, "PREVIEW FAILED:\n - 未找到已通过的预览报告"

    monkeypatch.setattr(rw, "run_script", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["render_worker.py", sb, "out/x.mp4", "--reuse-audio"]
    )
    with pytest.raises(SystemExit) as exc:
        rw.main()
    assert exc.value.code == rw.wr.STAGE_EXITS["PREVIEW"] == 2
    out = capsys.readouterr().out
    assert "FAIL_AT_PREVIEW" in out
    assert "FAIL_AT_RENDER" not in out


# ---- #23 并行换皮自动独立成片（自动命名防重合）----


def _artifact_of(stdout):
    return next(
        line.split(": ", 1)[1] for line in stdout.splitlines() if line.startswith("artifact: ")
    )


@pytest.mark.parametrize("tts_url", [0.2], indirect=True)
def test_worker_three_skins_parallel_auto_outputs(tts_url):
    """同一分镜三种皮肤省略 output 真并行：三个不同可播成片，验收互不污染。"""
    browser = browser_path()
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
    browser = browser_path()
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
