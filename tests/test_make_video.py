# -*- coding: utf-8 -*-
"""make_video.py 的 8 张 P2 缺陷票回归测试。

纯函数部分不依赖浏览器/TTS；浏览器相关用 playwright（找不到浏览器时跳过）。
运行：python -m pytest tests/test_make_video.py -q
"""
import json
import os
import struct
import sys
import tempfile
import wave

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import make_video as mv  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "now_progressing.json")


def load_sample():
    with open(SAMPLE, encoding="utf-8") as f:
        return json.load(f)


def wav_bytes(pcm, rate=24000, channels=1, sampwidth=2, extra_list=False):
    """构造 WAV 字节；extra_list 时在 data 前插入一个 LIST chunk，验证容器字节不被当声音。"""
    data = np.asarray(pcm, dtype=np.int16).tobytes()
    byte_rate = rate * channels * sampwidth
    block_align = channels * sampwidth
    bits = sampwidth * 8
    fmt = struct.pack(
        "<4sIHHIIHH", b"fmt ", 16, 1, channels, rate, byte_rate, block_align, bits
    )
    extra = b"LIST" + struct.pack("<I", 4) + b"INFO" if extra_list else b""
    data_chunk = b"data" + struct.pack("<I", len(data)) + data
    body = fmt + extra + data_chunk
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


# ---- 01 教学文本转义 ----


def test_highlight_body_escapes_and_keeps_highlight():
    out = mv.highlight_body("区间：**0<x<1**", "rule")
    assert "区间：" in out
    assert '<span class="hl">0&lt;x&lt;1</span>' in out
    # 不生成真实 HTML 元素
    assert "<span>" not in out.replace('<span class="hl">', "")


def test_highlight_body_does_not_create_input_element():
    body = "HTML 标签：**<span>** 与 <input>"
    out = mv.highlight_body(body, "rule")
    assert "<input>" not in out
    assert "&lt;input&gt;" in out
    assert "&lt;span&gt;" in out


def test_render_html_escapes_header_sub_zh():
    sc = {
        "kind": "example",
        "header": "a<b",
        "sub": "x & y",
        "body": "**B**",
        "narrate": "n",
        "zh": "1 > 0",
    }
    html = mv.render_html(sc, 1280, 720, mv.load_style("teaching"))
    assert "a&lt;b" in html
    assert "x &amp; y" in html
    assert "1 &gt; 0" in html
    # 不生成真实 HTML 元素（只允许渲染器自己的 span）
    body = html.split("</head>")[1].split("</body>")[0]
    assert "<b>" not in body
    assert "<input>" not in body


def test_render_html_escape_practice_think_field():
    style = mv.load_style("teaching")
    base = {"kind": "practice", "header": "h", "sub": "s", "body": "**?**", "narrate": "n"}
    # 缺省沿用文案
    assert "先想一想，别急着看答案" in mv.render_html(base, 1280, 720, style)
    # 自定义文本（含特殊字符按字面显示）
    sc = dict(base, think="a < b & c")
    html = mv.render_html(sc, 1280, 720, style)
    assert "a &lt; b &amp; c" in html
    assert "先想一想" not in html
    # 空字符串隐藏提示与间距
    sc2 = dict(base, think="")
    html2 = mv.render_html(sc2, 1280, 720, style)
    assert '<div class="think">' not in html2
    assert "先想一想" not in html2


def test_render_html_no_double_substitution():
    # 内容里含 __SUB__ 等槽位 token：不应被后续槽二次解释，也不被误判为残留占位符
    sc = {"kind": "rule", "header": "__SUB__", "sub": "real", "body": "**B**", "narrate": "n"}
    html = mv.render_html(sc, 1280, 720, mv.load_style("teaching"))
    assert "&#95;&#95;SUB&#95;&#95;" in html  # header 里的 __SUB__ 被中和，按字面显示
    assert html.count("real") == 1  # sub 槽注入一次，header 里的 __SUB__ 不会被替换成 real
    assert not mv.validate_rendered_html(html, 0)  # 不产生残留占位符错误


# ---- 02 WAV 解码 ----


def test_decode_wav_zero_samples():
    pcm = np.zeros(24000, dtype=np.int16)
    data = wav_bytes(pcm)
    out, rate, ch, sw = mv.decode_wav(data)
    assert rate == 24000 and ch == 1 and sw == 2
    assert len(out) == 24000
    assert not np.any(out)


def test_decode_wav_ignores_extra_chunk():
    pcm = np.arange(1000, dtype=np.int16)
    data = wav_bytes(pcm, extra_list=True)
    out, rate, ch, sw = mv.decode_wav(data)
    assert len(out) == 1000
    assert np.array_equal(out, pcm)


def test_decode_wav_reports_actual_params():
    stereo = wav_bytes(np.zeros(100, dtype=np.int16), channels=2)
    _, rate, ch, sw = mv.decode_wav(stereo)
    assert ch == 2 and sw == 2
    lowrate = wav_bytes(np.zeros(100, dtype=np.int16), rate=16000)
    _, rate2, ch2, sw2 = mv.decode_wav(lowrate)
    assert rate2 == 16000


def test_decode_wav_rejects_non_16bit():
    pcm8 = np.zeros(100, dtype=np.int8)
    data = wav_bytes(pcm8, sampwidth=1)
    with pytest.raises(RuntimeError):
        mv.decode_wav(data)


def test_prepare_scene_audio_keeps_silence():
    # 24k mono 零样本 WAV → decode → prepare 后仍静音
    raw = np.zeros(24000, dtype=np.int16)
    pcm, n_frames, dur, narr = mv.prepare_scene_audio(raw, 0.0, 30)
    assert not np.any(pcm)
    assert narr == 30


# ---- 03 预览溢出（浏览器探针）----


def test_motion_probe_ts_none_is_static():
    assert mv._motion_probe_ts("none") == [0.0]
    assert len(mv._motion_probe_ts("pulse")) == 21


# ---- 04 hold 冻结 ----


def test_frame_progress_freezes_after_narration():
    assert mv._frame_progress(0, 30) == 0.0
    assert mv._frame_progress(29, 30) == 1.0
    assert mv._frame_progress(30, 30) == 1.0  # hold
    assert mv._frame_progress(50, 30) == 1.0
    assert mv._frame_progress(0, 1) == 0.0  # 零旁白不除零
    assert mv._frame_progress(1, 1) == 1.0


def test_prepare_scene_audio_reports_narration_frames():
    raw = np.zeros(24000, dtype=np.int16)  # 1s @ 24k
    pcm, n_frames, dur, narr = mv.prepare_scene_audio(raw, 3.0, 30)
    assert narr == 30
    assert n_frames > narr  # hold + 尾垫使总帧数更多
    assert not np.any(pcm)


# ---- 05 fps 校验 ----


@pytest.mark.parametrize("bad", [0, -1, True, 29.5, "30", "abc", 30.0])
def test_validate_storyboard_rejects_invalid_fps(bad):
    tpl = load_sample()
    tpl["fps"] = bad
    errors, _ = mv.validate_storyboard(tpl)
    assert any("fps" in e for e in errors)


def test_validate_storyboard_accepts_default_and_valid_fps():
    tpl = load_sample()
    errors, _ = mv.validate_storyboard(tpl)
    assert not any("fps" in e for e in errors)
    tpl["fps"] = 60
    errors, _ = mv.validate_storyboard(tpl)
    assert not any("fps" in e for e in errors)


def test_make_video_invalid_fps_does_not_call_tts(monkeypatch):
    tpl = load_sample()
    tpl["fps"] = 0
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False)
        path = f.name
    try:
        monkeypatch.setattr(sys, "argv", ["make_video.py", path])
        calls = []
        monkeypatch.setattr(mv, "mi_tts", lambda text, voice: calls.append(text) or b"")
        with pytest.raises(SystemExit) as e:
            mv.main()
        assert e.value.code == 2
        assert calls == []  # 非法 fps 在 TTS 前被闸门拒绝
    finally:
        os.remove(path)


# ---- 06 浏览器发现 ----


def test_find_browser_explicit_path():
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        path = f.name
    try:
        assert mv.find_browser(path) == path
    finally:
        os.remove(path)


def test_find_browser_explicit_missing_raises():
    with pytest.raises(FileNotFoundError):
        mv.find_browser(r"C:\definitely\missing\chrome.exe")


def test_find_browser_prefers_available_candidate(monkeypatch):
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    monkeypatch.setenv("BROWSER_PATH", r"C:\missing\chrome.exe")
    monkeypatch.setattr(mv.shutil, "which", lambda name: None)

    def fake_isfile(p):
        return p == edge

    monkeypatch.setattr(mv.os.path, "isfile", fake_isfile)
    assert mv.find_browser() == edge


def test_candidate_paths_includes_env_override(monkeypatch):
    monkeypatch.setenv("BROWSER_PATH", r"C:\custom\browser.exe")
    assert r"C:\custom\browser.exe" in mv._candidate_browser_paths()


# ---- 07 CLI 参数解析 ----


def test_build_parser_valid():
    args = mv.build_parser().parse_args(["x.json", "out.mp4", "--style", "teaching", "--preview"])
    assert args.storyboard == "x.json"
    assert args.output == "out.mp4"
    assert args.style == "teaching"
    assert args.preview is True


def test_build_parser_rejects_unknown_option():
    with pytest.raises(SystemExit):
        mv.build_parser().parse_args(["x.json", "--preveiw"])


def test_build_parser_rejects_missing_style_value():
    with pytest.raises(SystemExit):
        mv.build_parser().parse_args(["x.json", "--style"])


def test_build_parser_rejects_extra_positional():
    with pytest.raises(SystemExit):
        mv.build_parser().parse_args(["x.json", "a.mp4", "b.mp4"])


def test_build_parser_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        mv.build_parser().parse_args(["--help"])
    assert e.value.code == 0


# ---- 08 think 槽与布局校验 ----


def test_validate_layouts_requires_think_slot():
    errs = mv.validate_layouts()
    assert not any("__THINK__" in e for e in errs)


def test_sample_passes_think_and_escape():
    tpl = load_sample()
    errors, warns = mv.validate_storyboard(tpl)
    assert not errors


# ---- 浏览器实测：文本保真 + 溢出探测（找不到浏览器则跳过）----


@pytest.fixture(scope="session")
def browser():
    path = mv.find_browser()
    if not path:
        pytest.skip("no Chrome/Edge available")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=path, headless=True)
        yield b
        b.close()


def test_browser_text_fidelity(browser):
    sc = {"kind": "rule", "header": "区间", "sub": "", "body": "区间：**0<x<1**", "narrate": "n"}
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(mv.render_html(sc, 1280, 720, mv.load_style("teaching")))
    assert page.locator(".body").inner_text().strip() == "区间：0<x<1"
    page.close()


def test_browser_no_input_element_from_content(browser):
    sc = {"kind": "rule", "header": "h", "sub": "", "body": "HTML 标签：**<span>** 与 <input>", "narrate": "n"}
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(mv.render_html(sc, 1280, 720, mv.load_style("teaching")))
    assert page.locator("input").count() == 0
    assert page.locator("span.hl").count() == 1
    page.close()


def test_browser_overflow_detects_hl_scale(browser):
    # 复现 issue 03 的核心：.hl 独立变换（放大）时即使容器 .body 布局不变也会被测量到
    sc = {
        "kind": "rule",
        "header": "h",
        "sub": "",
        "body": "**" + "知识点" * 22 + "**",
        "narrate": "n",
    }
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(mv.render_html(sc, 1280, 720, mv.load_style("teaching")))
    # 放大高亮词（模拟动效对 .hl 的独立缩放），.stage/.body 布局不变
    mv.apply_motion_css_vars(page, 1.0, 3.0, 0.0)
    findings = mv.preview_overflow(page, 1280, 720, kind="rule")
    sels = [sel for sel, _ in findings]
    assert ".hl" in sels
    assert ".body" not in sels  # 容器未溢出，只有被放大的高亮词被报告
    page.close()


def test_browser_overflow_reports_top_bound(browser):
    # 四侧边界：顶部裁切也要被报告
    sc = {"kind": "rule", "header": "h", "sub": "s", "body": "**B**", "narrate": "n"}
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(mv.render_html(sc, 1280, 720, mv.load_style("teaching")))
    page.evaluate("() => { const t = document.querySelector('.title'); t.style.position = 'absolute'; t.style.top = '-100px'; }")
    findings = mv.preview_overflow(page, 1280, 720, kind="rule")
    assert any(sel == ".title" for sel, _ in findings)
    page.close()
