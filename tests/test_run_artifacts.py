"""run_artifacts.py 单元测试 + worker_verify 音轨定位验收（issue #22）。

不依赖浏览器/TTS；mp4 用本地 ffmpeg 合成最小样本。
不用 pytest tmp_path fixture（Windows 老 lock 会 PermissionError），
统一 tempfile.mkdtemp 自管理。
运行：python -m pytest tests/test_run_artifacts.py -q
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import wave

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import run_artifacts as ra  # noqa: E402


def _mkdtemp(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    return d


def _write_sb(path, narrate="N", hold=0.0):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"title": "T", "voice": "mimo_default", "fps": 2,
             "scenes": [{"kind": "rule", "header": "H", "sub": "S",
                         "body": "**B**", "narrate": narrate, "hold": hold}]},
            f, ensure_ascii=False,
        )
    return path


def test_run_key_stable_and_discriminating():
    d = _mkdtemp("ra_key_")
    try:
        sb = _write_sb(os.path.join(d, "lesson.json"))
        k1 = ra.run_key(sb, "teaching", True)
        assert k1 == ra.run_key(sb, "teaching", True)  # 同文件同配置 → 稳定
        assert k1 != ra.run_key(sb, "classroom", True)  # style 参与
        assert k1 != ra.run_key(sb, "teaching", False)  # motion 开关参与
        # 分镜字节变化（不同来源/不同 hold/fps）→ key 变
        with open(sb, "r+", encoding="utf-8") as f:
            tpl = json.load(f)
            tpl["scenes"][0]["hold"] = 2.0
            f.seek(0)
            json.dump(tpl, f, ensure_ascii=False)
            f.truncate()
        assert k1 != ra.run_key(sb, "teaching", True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_run_dir_layout_and_style_sanitized():
    d = _mkdtemp("ra_dir_")
    try:
        sb = _write_sb(os.path.join(d, "lesson.json"))
        key = ra.run_key(sb, "my style/1", True)
        rdir = ra.run_dir(ROOT, "lesson", "my style/1", key)
        assert os.sep + "_build" + os.sep + "runs" + os.sep in rdir
        assert "my_style_1" in rdir and "lesson__" in rdir and key in rdir
        assert "preview" in ra.preview_dir(rdir)
        assert "audio" in ra.audio_dir(rdir)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_manifest_roundtrip():
    d = _mkdtemp("ra_manifest_")
    try:
        rdir = os.path.join(d, "run")
        os.makedirs(rdir, exist_ok=True)  # 契约：调用方保证 run 目录存在
        ra.write_manifest(rdir, {"schema": ra.MANIFEST_SCHEMA, "scenes": [{"i": 0}]})
        m = ra.read_manifest(rdir)
        assert m["schema"] == ra.MANIFEST_SCHEMA
        shutil.rmtree(rdir, ignore_errors=True)
        assert ra.read_manifest(rdir) is None  # 缺失 → None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_manifest_concurrent_writes_never_torn():
    """并行同配置写同一 manifest：读方永远拿到完整 JSON（原子写）。"""
    d = _mkdtemp("ra_torn_")
    try:
        rdir = os.path.join(d, "run")
        os.makedirs(rdir, exist_ok=True)
        errors = []

        def writer(n):
            try:
                for k in range(10):
                    ra.write_manifest(rdir, {"schema": 1, "writer": n, "k": k,
                                             "payload": "x" * 4096})
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        m = ra.read_manifest(rdir)
        assert m is not None and m["payload"] == "x" * 4096
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---- worker_verify 音轨定位（真实 mp4/wav，不跑 TTS/浏览器）----
# 与 test_render_worker 同口径：拷贝 scripts 到临时项目，_build 全部落在项目内。


@pytest.fixture(scope="session")
def ffmpeg():
    from make_video import FFMPEG

    return FFMPEG


@pytest.fixture
def project():
    d = tempfile.mkdtemp(prefix="ra_proj_")
    try:
        shutil.copytree(
            os.path.join(ROOT, "scripts"), os.path.join(d, "proj", "scripts"),
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        yield os.path.join(d, "proj")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _make_wav(path, seconds, rate=24000):
    n = int(rate * seconds)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.zeros(n, dtype=np.int16).tobytes())
    return path


def _make_mp4(ffmpeg, path, seconds):
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=black:s=64x64:d={seconds:.3f}", "-c:v", "libx264", str(path)],
        check=True, timeout=30,
    )
    return path


def _write_manifest_for(proj_root, sb_path, wav, seconds):
    """以项目为 ROOT 写一份与渲染器同构的 manifest（schema/字段一致）。"""
    rdir = os.path.join(
        str(proj_root), "_build", "runs",
        f"lesson__teaching__{ra.run_key(str(sb_path), 'teaching', True)}",
    )
    os.makedirs(rdir, exist_ok=True)
    ra.write_manifest(
        rdir,
        {
            "schema": ra.MANIFEST_SCHEMA,
            "run_key": ra.run_key(str(sb_path), "teaching", True),
            "slug": "lesson",
            "style_name": "teaching",
            "motion_enabled": True,
            "fps": 2,
            "expected_duration": seconds,
            "scenes": [{"i": 0, "voice": "mimo_default", "narrate": "N",
                        "fp": "0" * 8, "raw": str(wav), "wav": os.path.abspath(wav),
                        "duration": seconds, "frames": 4, "narr_frames": 4,
                        "hold": 0.0}],
        },
    )
    return rdir


def _run_verify(project, sb, mp4, *extra):
    return subprocess.run(
        [sys.executable, os.path.join(str(project), "scripts", "worker_verify.py"),
         str(sb), str(mp4), *extra],
        capture_output=True, text=True, encoding="utf-8",
        env=dict(os.environ, PYTHONUTF8="1"), timeout=60,
    )


def test_verify_uses_run_manifest_audio(project, ffmpeg):
    """manifest 存在 → 用本次实际音轨集合独立测量；±5% 内 OK。"""
    d = _mkdtemp("ra_verify_ok_")
    try:
        sb = _write_sb(os.path.join(d, "lesson.json"))
        wav = _make_wav(os.path.join(d, "s0.wav"), 1.0)
        _write_manifest_for(project, sb, wav, 1.0)
        mp4 = _make_mp4(ffmpeg, os.path.join(d, "a.mp4"), 1.0)
        r = _run_verify(project, sb, mp4)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "VERIFY_OK" in r.stdout and "run:" in r.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_verify_out_of_tolerance_fails_with_direction(project, ffmpeg):
    """mp4 时长与本次音轨集合差 >5% → 失败且标明偏长/偏短。"""
    d = _mkdtemp("ra_verify_tol_")
    try:
        sb = _write_sb(os.path.join(d, "lesson.json"))
        wav = _make_wav(os.path.join(d, "s0.wav"), 1.0)
        _write_manifest_for(project, sb, wav, 1.0)
        mp4 = _make_mp4(ffmpeg, os.path.join(d, "a.mp4"), 3.0)  # 明显偏长
        r = _run_verify(project, sb, mp4)
        assert r.returncode == 4, r.stdout + r.stderr
        assert "AUDIO_LOCK_FAIL" in r.stderr and "偏长" in r.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_verify_missing_audio_fails_without_guessing(project, ffmpeg):
    """无 manifest 且无旧版共享音轨 → 失败并给出定位指引，不猜目录。"""
    d = _mkdtemp("ra_verify_missing_")
    try:
        sb = _write_sb(os.path.join(d, "lesson.json"))
        mp4 = _make_mp4(ffmpeg, os.path.join(d, "a.mp4"), 1.0)
        r = _run_verify(project, sb, mp4)
        assert r.returncode == 4, r.stdout + r.stderr
        assert "missing scene audio" in r.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_verify_wrong_style_flag_does_not_match_run(project, ffmpeg):
    """渲染 style 与验收 flag 不一致 → run 定位不到 → 失败（不静默换数据源）。"""
    d = _mkdtemp("ra_verify_style_")
    try:
        sb = _write_sb(os.path.join(d, "lesson.json"))
        wav = _make_wav(os.path.join(d, "s0.wav"), 1.0)
        _write_manifest_for(project, sb, wav, 1.0)
        mp4 = _make_mp4(ffmpeg, os.path.join(d, "a.mp4"), 1.0)
        r = _run_verify(project, sb, mp4, "--style", "classroom")  # 渲染是 teaching
        assert r.returncode == 4, r.stdout + r.stderr
        assert "missing scene audio" in r.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---- #23 自动命名与目标占用 ----


def test_default_output_name_binds_skin_without_collision():
    # 无需规范化的皮肤：干净命名
    assert ra.default_output_name("lesson", "teaching") == "output/lesson__teaching.mp4"
    # 规范化会重合的两个皮肤（"a b" 与 "a_b"）→ 不同输出
    a = ra.default_output_name("lesson", "a b")
    b = ra.default_output_name("lesson", "a_b")
    assert a != b
    assert "a_b" in a and "a_b" in b
    # 同名皮肤 → 同名输出（确定性）
    assert ra.default_output_name("lesson", "a b") == a
