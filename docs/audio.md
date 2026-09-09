# 音画锁（audio）

*音画锁*：每段音轨时长 = 该段画面帧时长（含 `hold` 与尾垫静音）。

## 缓存（防串课）

路径：`_build/<lesson_slug>/s{i}_{fp}_raw.wav`  
`lesson_slug` = 分镜 JSON 主名；`fp` = `sha256(voice|narrate)[:8]`。

- 旁白或音色变 → 指纹变 → 不复用旧文件
- 换皮（`--style`）不进指纹，不重 TTS
- `--reuse-audio` 仅在 raw + `.meta.json` 与旁白/音色一致时命中；无 meta 的旧共享缓存一律 miss
- meta 写有 `ver = CACHE_VERSION`（`scripts/make_video.py` 中常量，初始 `"2"`）；与当前值不一致则失效，解码逻辑改了旧缓存自动 miss

## 对话模式（多音色）

分镜支持 `voices` 映射 + 每页 `voice` 覆盖，实现男女生对话式教学：

- 顶层 `voices`：`{"narrator": "苏打", "student": "冰糖"}`
- 每页 `voice`：角色 ID（如 `"narrator"`）或直接音色名（如 `"苏打"`）
- 缓存指纹含实际音色名（非角色 ID），换角色映射自动重 TTS
- 同一课的不同页可用不同音色，ffmpeg `concat` 自然拼接

## 管线（`prepare_scene_audio`）

1. TTS → `…_raw.wav`（纯旁白）+ `.meta.json`
2. **静音区边缘淡化**（~12ms 抑咔哒；不从满幅 0 淡入有声区，避免吞句首）
3. 追加 `hold` + `TAIL_PAD`（~0.45s）零样本
4. **ceil 锁帧、只垫不裁**（禁止为凑帧切掉旁白尾）
5. 写出 `…_{fp}.wav` → ffmpeg `aformat` + `concat`

`--reuse-audio` 复用 raw，每次仍跑 prepare。成片后核对实测时长 ≈ Σ(旁白+hold+尾垫)。

## 产物归属（run 目录，#22）

一次渲染 = 一个 run：`run_key = sha256(分镜文件字节 + style + motion 开关)[:10]`，
目录 `_build/runs/<slug>__<style>__<run_key>/`（`scripts/run_artifacts.py`）：

- `preview/`：本次预览截图 + `overflow.json`
- `audio/`：本次**加工音轨** `s{i}_{fp}.wav`（随 hold/fps 变化，不属于共享缓存）
- `manifest.json`：本次产物清单（音轨集合、时长、fps、mp4 路径，及本次 TTS
  执行事实 `tts_generated`/`tts_reused`/`reuse_mode`）

分工：**raw 可共享**（`_build/<slug>/`，旁白+音色指纹，换皮复用），**加工音轨归
本次 run**——同 slug 不同来源、同旁白不同 hold/fps 的并行运行各写各的 run 目录，
互不覆盖；同配置并行另用 `<rdir>.lock` 拒绝交错写，原子写保证读方只见完整文件。

验收（`worker_verify.py`）按相同口径重算 run_key 精确重定位 run、用 manifest 的
本次实际音轨集合独立测量（±5% 双向容差）；manifest 缺失时回退旧版共享音轨
`_build/<slug>/s{i}_{fp}.wav`（兼容迁移前产物）。正常/失败退出都不清理任何
run 目录或历史产物。

## 缓存使用事实（#24）

「本次生成了几段、复用了几段」以 make_video 执行时记录为准（audio 循环里的
实际 `tts`/`reuse` 决定），写进 run manifest 并汇总到顶层
`tts_generated` / `tts_reused` / `reuse_mode`（`reuse` | `regenerate`）：

- worker 回传新增 `cache:` 字段（如 `cache: generated=1 reused=5 mode=reuse`），
  渲染完成前为 `(none)`
- verify 检查 5 的明细附带同一事实——**通过检查 5 ≠ 本次零 TTS**：命中判定按
  指纹逐段核对，旁白改动的那段会如实记为重新生成
- 不做事后数文件：缓存目录里旧指纹文件残留不影响统计

## Done when

- 句首句尾听得见完整字；练习提问不被淡入吃掉
- `hold`（practice **须** ≥3.0s）画面停、音轨静音
- 片尾总结听完整；成片时长 ≈ Σ(旁白+hold+尾垫)
- 段间接缝干净；换课 / 改旁白不会误复用别课音频

## 改渲染器时保持

- 淡化落在静音头/尾，有声区最多轻微侵入
- `hold` 与尾垫进音轨；用 ceil 帧对齐，不靠 `-shortest`、不裁旁白
- 缓存按课目录 + 旁白/音色指纹；缺 meta 不命中
