# 音画锁（audio）

*音画锁*：每段音轨时长 = 该段画面帧时长（含 `hold` 与尾垫静音）。

## 管线（`prepare_scene_audio`）

1. TTS → `_build/s{i}_raw.wav`（纯旁白）
2. **静音区边缘淡化**（~12ms 抑咔哒；不从满幅 0 淡入有声区，避免吞句首）
3. 追加 `hold` + `TAIL_PAD`（~0.45s）零样本
4. **ceil 锁帧、只垫不裁**（禁止为凑帧切掉旁白尾）
5. 写出 `_build/s{i}.wav` → ffmpeg `aformat` + `concat`

`--reuse-audio` 复用 raw，每次仍跑 prepare。

## Done when

- 句首句尾听得见完整字；练习提问不被淡入吃掉
- `hold`（practice 建议 ≥3.0s）画面停、音轨静音
- 片尾总结听完整；成片时长 ≈ Σ(旁白+hold+尾垫)
- 段间接缝干净

## 改渲染器时保持

- 淡化落在静音头/尾，有声区最多轻微侵入
- `hold` 与尾垫进音轨；用 ceil 帧对齐，不靠 `-shortest`、不裁旁白
