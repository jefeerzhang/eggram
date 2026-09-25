"""worker_result.py 单元测试（#25）：协议行解析与六格勾选合成。

运行：python -m pytest tests/test_worker_result.py -q
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import worker_result as wr  # noqa: E402


def test_parse_check_lines_is_token_based_not_position_based():
    log = "\n".join(
        [
            "some prefix CHECK 3 PASS should not count",  # 行首非 CHECK → 忽略
            "CHECK 3 FAIL stale",  # 同项后行覆盖前行
            "CHECK 3 PASS mp4 1234B 1.00s",
            "CHECK 4 FAIL expected=1.00s got=3.00s drift=+200.0% (audio-src=run:x)",
            "  CHECK 5 SKIP 未要求 --expect-reuse-audio（显式跳过）",  # 前导空白也认
        ]
    )
    results = wr.parse_check_lines(log)
    assert set(results) == {3, 4, 5}
    assert results[3] == (wr.PASS, "mp4 1234B 1.00s")
    assert results[4][0] == wr.FAIL  # 括号/空格位置不影响解析
    assert "audio-src=run:x" in results[4][1]
    assert results[5][0] == wr.SKIP


def test_parse_ignores_non_protocol_lines():
    assert wr.parse_check_lines("verify FAIL [3]: boom\nVERIFY_OK [······]") == {}
    assert wr.parse_check_lines("CHECK 9 FAIL out of range") == {}


def test_marks_line_four_states_and_defaults():
    # 管道内：1/2 由父入口实测传入通过；3/4 过、5 显式跳过、6 失败
    m = wr.marks_line(
        (wr.PASS, wr.PASS),
        {3: (wr.PASS, ""), 4: (wr.PASS, ""), 5: (wr.SKIP, ""), 6: (wr.FAIL, "")},
    )
    assert m == "✓✓✓✓-✗"
    # 单独验收：1/2 无可靠证据 → 未执行；缺项默认 ·
    m = wr.marks_line(
        (wr.NOTRUN, wr.NOTRUN),
        {3: (wr.PASS, ""), 4: (wr.PASS, ""), 5: (wr.SKIP, ""), 6: (wr.PASS, "")},
    )
    assert m == "··✓✓-✓"
    # verify 崩溃无协议行：1/2 通过、3-6 未执行，绝不填通过或失败
    assert wr.marks_line((wr.PASS, wr.PASS), {}) == "✓✓····"


def test_check_line_format():
    assert wr.check_line(4, wr.FAIL, "boom boom") == "CHECK 4 FAIL boom boom"
    assert wr.check_line(6, wr.PASS) == "CHECK 6 PASS"
    assert wr.CHECK_ITEMS == set(range(1, wr.N_CHECKS + 1))
    assert wr.STAGE_EXITS == {"PREFLIGHT": 1, "PREVIEW": 2, "RENDER": 3, "VERIFY": 4}


def test_render_exit_routing_covers_every_make_video_code():
    """两个命名空间共用 1–4：每个 make_video 退出码都要有明确归因，不留靠分支顺序猜。"""
    codes = {
        wr.MV_EXIT_FAIL,
        wr.MV_EXIT_VALIDATION,
        wr.MV_EXIT_BROWSER,
        wr.MV_EXIT_PREVIEW_STALE,
    }
    assert codes == set(wr.MV_EXIT_STAGE_ROUTING), "有退出码没有归因"
    for rc, (stage, prefix) in wr.MV_EXIT_STAGE_ROUTING.items():
        assert stage in wr.STAGE_EXITS, f"{rc} 归到未知阶段 {stage}"
        assert "{rc}" in prefix, f"{rc} 的诊断前缀要能填退出码"
        assert prefix.format(rc=rc), rc


def test_render_exit_routing_stages_are_the_documented_ones():
    """#26 AC2 的具体口径：预览过期归 PREVIEW，闸门/浏览器归 PREFLIGHT，其余归 RENDER。"""
    assert wr.classify_render_exit(wr.MV_EXIT_PREVIEW_STALE)[0] == "PREVIEW"
    assert wr.classify_render_exit(wr.MV_EXIT_VALIDATION)[0] == "PREFLIGHT"
    assert wr.classify_render_exit(wr.MV_EXIT_BROWSER)[0] == "PREFLIGHT"
    assert wr.classify_render_exit(wr.MV_EXIT_FAIL)[0] == "RENDER"
    # 未列入映射表的非零码（渲染期未预期失败）兜底归 RENDER
    assert wr.classify_render_exit(99)[0] == "RENDER"
    assert "99" in wr.classify_render_exit(99)[1].format(rc=99)


def test_two_exit_namespaces_do_not_share_meaning_by_accident():
    """同名数字在两套命名空间里含义不同——这正是需要映射表的原因，钉住这个事实。"""
    # make_video 的 2 是「闸门校验失败」，worker 的 2 是「PREVIEW 阶段失败」
    assert wr.MV_EXIT_VALIDATION == wr.STAGE_EXITS["PREVIEW"] == 2
    assert wr.classify_render_exit(wr.MV_EXIT_VALIDATION)[0] == "PREFLIGHT"
    # make_video 的 3 是「浏览器缺失」，worker 的 3 是「RENDER 阶段失败」
    assert wr.MV_EXIT_BROWSER == wr.STAGE_EXITS["RENDER"] == 3
    assert wr.classify_render_exit(wr.MV_EXIT_BROWSER)[0] == "PREFLIGHT"
