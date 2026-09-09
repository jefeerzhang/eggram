"""Worker CLI integration tests with a local stand-in for the external TTS API."""

import base64
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
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
from make_video import FFMPEG, find_browser  # noqa: E402


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
        assert (project / "output/lesson.mp4").stat().st_size > 0


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
    """完整教学弧（闸门要求 6 个必要 kind）；变量 hold 放 scene 0（title）。"""
    d = project / "cases" / sub
    d.mkdir(parents=True, exist_ok=True)
    tpl = {
        "title": "T", "voice": "mimo_default", "fps": 2,
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
