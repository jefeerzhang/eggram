"""Worker CLI integration tests with a local stand-in for the external TTS API."""

import base64
import io
import json
import os
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
