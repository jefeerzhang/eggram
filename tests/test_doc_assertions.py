"""文档与实现的一致性断言：同一规则只写一遍，写歪了就红。

项目已有同族断言（test_gate_hold_floor_message_matches_docs：代码里的门槛文案必须与
文档字面一致）。这里把同一条纪律补到 run_key 组成与「manifest 缺失」规则上——这两处
此前各漂移过一次：run_key 公式漏了 templates/ 内容，而文档仍承诺一个已被删除、
且被测试明令禁止的回退。
"""

import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import run_artifacts as ra  # noqa: E402


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_audio_doc_run_key_formula_covers_every_real_input():
    """文档写出的 run_key 组成必须覆盖实现真正吃的每一项输入。

    实现侧逐项验证「改这一项 → key 变」，文档侧逐项验证「这一项被写出来」，
    两侧用同一份清单，漏一项即失败。
    """
    with tempfile.TemporaryDirectory(prefix="doc_rk_") as d:
        root = os.path.join(d, "repo")
        tdir = os.path.join(root, "templates")
        os.makedirs(tdir)
        tpl_file = os.path.join(tdir, "layout-rule.html")
        with open(tpl_file, "w", encoding="utf-8") as f:
            f.write("<div>__BODY__</div>")
        sb = os.path.join(d, "lesson.json")
        with open(sb, "w", encoding="utf-8") as f:
            json.dump({"scenes": []}, f)

        # 1 分镜字节
        k0 = ra.run_key(sb, "teaching", True, root)
        with open(sb, "w", encoding="utf-8") as f:
            json.dump({"scenes": [{"kind": "rule"}]}, f)
        k1 = ra.run_key(sb, "teaching", True, root)
        assert k1 != k0, "分镜字节未参与 run_key"
        # 2 style
        assert ra.run_key(sb, "classroom", True, root) != k1, "style 未参与 run_key"
        # 3 motion 开关
        assert ra.run_key(sb, "teaching", False, root) != k1, "motion 开关未参与 run_key"
        # 4 templates/ 内容
        with open(tpl_file, "w", encoding="utf-8") as f:
            f.write('<div class="x">__BODY__</div>')
        assert ra.run_key(sb, "teaching", True, root) != k1, "模板内容未参与 run_key"

    line = next(
        ln for ln in _read("docs/audio.md").splitlines() if "run_key = sha256" in ln
    )
    for token in ("分镜文件字节", "style", "motion", "templates/"):
        assert token in line, f"docs/audio.md 的 run_key 公式漏了 {token}：{line}"


def test_audio_doc_and_verifier_agree_there_is_no_manifest_fallback():
    """manifest 缺失只有一个口径：检查 4 失败，不猜文件名。

    文档一度承诺「回退旧版共享音轨」，而 worker_verify 与
    test_verify_without_manifest_fails_without_guessing 都禁止回退。
    """
    doc = _read("docs/audio.md")
    assert "manifest 缺失即检查 4 失败" in doc, "文档没写清 manifest 缺失时的行为"
    assert not re.search(r"manifest\s*缺失时回退", doc), "文档仍在承诺已删除的回退"

    verifier = _read("scripts/worker_verify.py")
    assert "不回退到共享 raw 目录" in verifier, "verify 的口径变了，文档需同步"


def test_audio_doc_agrees_on_where_artifacts_live():
    """产物归属：raw 共享、加工音轨与预览归本次 run。"""
    doc = _read("docs/audio.md")
    for token in ("_build/runs/", "raw 可共享", "加工音轨归"):
        assert token in doc, f"docs/audio.md 的产物归属描述漏了 {token}"


def test_skip_preview_contract_is_documented_where_it_is_used():
    """--skip-preview 的准入条件写在 SKILL.md 与 json-schema.md，不只活在 --help 里。"""
    for rel in ("SKILL.md", "docs/json-schema.md"):
        text = _read(rel)
        assert "overflow.json" in text, f"{rel} 未说明 --skip-preview 读什么"
        assert "指纹" in text, f"{rel} 未说明报告须属于本次分镜"