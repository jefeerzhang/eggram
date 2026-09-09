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
