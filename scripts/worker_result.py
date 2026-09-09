"""worker_result.py — worker 阶段结果与六项验收的单一事实源（#25）

集中六项验收条目、单项状态（通过/失败/显式跳过/因前序失败未执行）与
阶段→退出码映射；render_worker（父入口）与 worker_verify（验收脚本）共用。
脚本间协议行 `CHECK <n> <STATE> <detail...>` 按空白分词解析，不依赖字符位置。
内部模块：仅被 worker 脚本使用，不构成对外公开接口。
"""

N_CHECKS = 6
CHECK_NAMES = {
    1: "闸门绿",
    2: "预览无溢出",
    3: "mp4存在且时长>0",
    4: "音画锁±5%",
    5: "cache命中(可选)",
    6: "无残留转义",
}

# 单项状态四态：可区分 通过/失败/显式跳过/因前序失败未执行；缺失一律 NOTRUN，
# 绝不默认填通过。
PASS, FAIL, SKIP, NOTRUN = "PASS", "FAIL", "SKIP", "NOTRUN"
MARKS = {PASS: "✓", FAIL: "✗", SKIP: "-", NOTRUN: "·"}

# 阶段 → worker 退出码（0=OK）。
STAGE_EXITS = {"PREFLIGHT": 1, "PREVIEW": 2, "RENDER": 3, "VERIFY": 4}


def check_line(item, state, detail=""):
    return f"CHECK {item} {state} {detail}".rstrip()


def parse_check_lines(log):
    """从合并日志提取各检查项最终状态 {item: (state, detail)}。

    只认空白分词后形如 `CHECK <n> <STATE>` 的行；同项以后出现的行为准，
    诊断内容里的位置、括号、空格均不影响解析。
    """
    results = {}
    for line in log.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "CHECK" and parts[1].isdigit():
            item, state = int(parts[1]), parts[2]
            if item in CHECK_NAMES and state in MARKS:
                results[item] = (state, " ".join(parts[3:]))
    return results


def marks_line(stage12, check_results):
    """合成六格勾选串。stage12 = 检查 1/2 的状态，由父入口用自己实测的
    阶段结果传入（单独跑验收时传 NOTRUN，不得声称未执行的前置检查）。"""
    states = dict(zip((1, 2), stage12))
    states.update({i: s for i, (s, _) in check_results.items() if i in CHECK_NAMES})
    return "".join(MARKS[states.get(i, NOTRUN)] for i in range(1, N_CHECKS + 1))
