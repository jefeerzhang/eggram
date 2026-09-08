# micro-course

> 项目名从 `eggram` 迁移到 `micro-course`；仓库目录沿用 `eggram/` 以保留 git 历史与远程地址。

教学微课仓库（从英语语法起步，已扩展到任意适合讲练穿插的知识点）。Agent 入口：根目录 [`SKILL.md`](SKILL.md)（*micro-video*）。

## 核心流程三阶段

```text
主题输入 → [阶段 0: 脚本大纲与用户确认(硬阻断)] → [阶段 1: 写分镜与过闸门] → [阶段 2: 渲视频与验收]
```

## Context pointers

| Leading | 何时打开 |
| --- | --- |
| *脚本硬阻断* / 用户确认 | [`SKILL.md`](SKILL.md) 阶段 0 |
| *分镜* / 教学微课流程 | [`SKILL.md`](SKILL.md) |
| *page-role* / 教学弧 | [`docs/teaching-method.md`](docs/teaching-method.md) |
| 分镜字段 / `**` 高亮 | [`docs/json-schema.md`](docs/json-schema.md) |
| *换皮* | [`docs/styles.md`](docs/styles.md) |
| motion | [`docs/motion.md`](docs/motion.md) |
| *音画锁* / hold 卡顿 | [`docs/audio.md`](docs/audio.md) |
| GitHub issues | [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md) |
| domain / ADR | [`docs/agents/domain.md`](docs/agents/domain.md) |

命令与 flag：以 `SKILL.md` 阶段 2 与 `py scripts/make_video.py --help` 为准（Windows 用 `py` 启动器；macOS/Linux 用 `python3`，详见 SKILL.md 环境说明）。

## Agent skills

### Issue tracker

GitHub Issues via `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context. See `docs/agents/domain.md`.
