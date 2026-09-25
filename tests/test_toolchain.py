"""toolchain.py 单元测试：外部工具定位（纯 stdlib，不依赖媒体管线）。

本模块独立出来的理由就是依赖重量，所以第一条测试守的就是这条纪律：
导入它不得把 playwright / numpy / imageio_ffmpeg 拉进来。
"""

import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import toolchain as tc  # noqa: E402

HEAVY = {"playwright", "numpy", "imageio_ffmpeg"}


def test_module_imports_no_heavy_deps():
    """纯 stdlib：preflight 只找一个浏览器，不该为此拉起整条媒体管线。"""
    code = (
        "import sys, toolchain;"
        f"heavy = {HEAVY!r} & set(sys.modules);"
        "assert not heavy, f'heavy imports leaked: {heavy}'"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.path.join(ROOT, "scripts"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONUTF8="1"),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


def test_ffmpeg_path_is_lazy():
    """ffmpeg 只在首次调用时解析——导入本模块不该触发它。"""
    code = (
        "import sys, toolchain;"
        "assert 'imageio_ffmpeg' not in sys.modules, '导入即解析了 ffmpeg';"
        "p = toolchain.ffmpeg_path();"
        "assert p and os.path.isfile(p);"
        "assert toolchain.ffmpeg_path() == p, '应缓存同一路径';"
    )
    r = subprocess.run(
        [sys.executable, "-c", "import os;" + code],
        cwd=os.path.join(ROOT, "scripts"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONUTF8="1"),
        timeout=120,
    )
    assert r.returncode == 0, r.stderr


def test_browser_explicit_path():
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        path = f.name
    try:
        assert tc.browser_path(path) == path
    finally:
        os.remove(path)


def test_browser_explicit_missing_raises():
    with pytest.raises(FileNotFoundError):
        tc.browser_path(r"C:\definitely\missing\chrome.exe")


def test_browser_prefers_available_candidate(monkeypatch):
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    monkeypatch.setenv("BROWSER_PATH", r"C:\missing\chrome.exe")
    monkeypatch.setattr(tc.shutil, "which", lambda name: None)

    def fake_isfile(p):
        return p == edge

    monkeypatch.setattr(tc.os.path, "isfile", fake_isfile)
    assert tc.browser_path() == edge


def test_candidate_paths_includes_env_override(monkeypatch):
    monkeypatch.setenv("BROWSER_PATH", r"C:\custom\browser.exe")
    assert r"C:\custom\browser.exe" in tc._candidate_browser_paths()


def test_media_duration_reads_a_real_file():
    """时长测量是唯一真正需要 ffmpeg 的能力，单独钉住。"""
    ff = tc.ffmpeg_path()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "a.mp4")
        subprocess.run(
            [ff, "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "color=black:s=64x64:d=1.5", "-c:v", "libx264", out],
            check=True, timeout=60,
        )
        assert tc.media_duration(out) == pytest.approx(1.5, abs=0.15)


def test_media_duration_returns_none_on_garbage():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"not a video")
        path = f.name
    try:
        assert tc.media_duration(path) is None
    finally:
        os.remove(path)