# TTS 模型调研（2025–2026）：eggram 微课旁白选型

> 调研日期：**2026-10-06**（文中"截至"均指该日）。来源以官方 GitHub / Hugging Face 模型卡 / 官方文档 / 官方新闻为准，第三方基准（Artificial Analysis、Vapi 等）单独标注。每条关键数据后附来源 URL。

## 0. 总览对比表

### 0.1 云端 API 组

| 模型 | 发布/现状 | 中文质量 | 克隆 | 价格 | License/商用 | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI gpt-4o-mini-tts | 2025-03 发布，当前在售 | 中（跟随 Whisper 语言，音色为英语优化） | ❌ | ~$0.60/1M tok 入 + $12/1M tok 出（约 $15/M 字符等效） | 商用 API | [OpenAI docs](https://developers.openai.com/api/docs/guides/text-to-speech)、[定价二手](https://costgoat.com/pricing/openai-tts) |
| OpenAI tts-1 / tts-1-hd | 2022 起，仍在售 | 中 | ❌ | $15 / $30 每 M 字符 | 商用 API | 同上 |
| ElevenLabs v3（GA 2026-03-14） | alpha 2025-06，GA 2026-03 | 高（70+ 语言，Audio Tags 情绪控制） | ✅（IVC；PVC 未优化） | ~$100/M 字符；延迟 ~758ms | 商用 API | [官方 docs](https://elevenlabs.io/docs/capabilities/text-to-speech)、[Vapi 实测](https://humannessindex.vapi.ai/models/elevenlabs-eleven-v3) |
| MiniMax Speech 2.8（02 家族已 Legacy） | 2.8 发布 2026-01-23，当前默认 | 高（中文母语级，332 官方音色） | ✅（10s 快速克隆） | HD $100/M、Turbo $60/M 字符；60 RPM | 商用 API（无开源权重） | [官方 news](https://www.minimaxi.com/news/minimax-speech-28)、[定价](https://platform.minimax.io/docs/guides/pricing-paygo) |
| 小米 MiMo（mimo-v2 / v2.5-tts） | 2025 年起，开放平台限时免费 | 高（中文原生，预置音色含"冰糖/苏打"等） | ✅（≤10MB 参考音频） | 限时免费 | 商用 API（免费期） | [mimo.mi.com 官方文档](https://mimo.mi.com/docs/news/v2-tts-release) |

### 0.2 开源/本地组

| 模型 | 发布/维护（截至 2026-10） | 中文质量（客观指标） | 克隆 | 速度/硬件 | License | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| **Qwen3-TTS**（0.6B/1.7B） | 2026-01-22，活跃 | test-zh WER **0.77**（1.7B-Base） | ✅ 3s | pip 即装；vLLM-Omni day-0；官方称 e2e 低至 97ms | **Apache-2.0（代码+权重）** | [GitHub](https://github.com/QwenLM/Qwen3-TTS) |
| **CosyVoice 2 / 3**（0.5B） | CV2 2024-12；CV3 2025-12；活跃（23.8k stars） | test-zh CER 1.45（CV2）→ **0.81**（CV3-RL）；18+ 中文方言 | ✅ zero-shot | 流式 150ms；TensorRT-LLM 4x 加速 | **Apache-2.0** | [GitHub](https://github.com/FunAudioLLM/CosyVoice) |
| **IndexTTS 2 / 2.5**（B站） | 2：2025-09-08；2.5：2026-08-10；活跃（24.3k stars） | zh CER **1.03** / SIM 76.5；情感+精确时长控制 | ✅ | 2.5 更快，支持 vLLM 生产部署 | bilibili 模型许可——**商用需单独授权** | [GitHub](https://github.com/index-tts/index-tts) |
| **GLM-TTS**（智谱） | 2025-12-11 开源，活跃 | zh CER **0.89**（RL 版）/ SIM 76.4 | ✅ 3–10s | 流式；官方未给 VRAM/RTF | **Apache-2.0** | [GitHub](https://github.com/zai-org/GLM-TTS) |
| **Breeze TTS 2**（3B） | 2026-08-25 | AA 开源榜 Elo **1206（开源第 1）** | ✅ | TTFA <40ms，RTF 0.32，~7.7GiB VRAM | **权重仅限研究/非商用** ❌ | [HF 模型卡](https://huggingface.co/BreezeBlue/Breeze-TTS-2) |
| **Fish Speech / OpenAudio S1、S2 Pro**（4B） | S2 Pro 2026；活跃（32.9k stars） | zh WER **0.54%**（自称最优）；EmergentTTS-Eval 胜率 81.88% | ✅ 10–30s | H200 上 RTF 0.195、TTFA ~100ms | **Fish Audio Research License——非商用** ❌（商用走 API $15/M） | [GitHub](https://github.com/fishaudio/fish-speech) |
| **F5-TTS** | v1 2025-03-12；维护放缓（最后新闻 2025-03） | zh CER 1.53（GLM-TTS 对比表） | ✅ 参考音频 | L20 上 RTF 0.039（TRT-LLM） | 代码 MIT，**权重 CC-BY-NC 非商用** ❌ | [GitHub](https://github.com/SWivid/F5-TTS) |
| **Kokoro 82M** | 2025-01-27，维护一般 | 中文可用但韵律弱于中文原生模型；AA 开源榜 Elo 1063 | ❌ | 82M 参数，CPU 可跑 | **Apache-2.0** | [GitHub](https://github.com/hexgrad/kokoro) |
| **Spark-TTS 0.5B** | 2025-03，活跃度一般 | 中英双语，无公开中文客观分 | ✅ zero-shot | L20 上 RTF 0.07–0.14 | **Apache-2.0** | [GitHub](https://github.com/SparkAudio/Spark-TTS) |
| **Step-Audio-TTS-3B** | 2025-02-17；**仓库已停止维护**（横幅指向 Step-Audio2/EditX） | zh CER 1.17 | ✅ | 最低 8GB VRAM | 代码 Apache-2.0，权重另附许可 | [GitHub](https://github.com/stepfun-ai/Step-Audio) |
| **Chatterbox**（Resemble AI） | 2025-05-28，Multilingual V3 2025-09；活跃（26.7k stars） | 23+ 语言含中文（有 zh 单语包）；AA 开源榜 Elo 1023 | ✅ ~10s | Nano 110M 可 CPU（8 核 3x 实时） | MIT，但**自带音频水印** | [GitHub](https://github.com/resemble-ai/chatterbox) |
| **MiMo-Audio-7B**（小米） | 2025 年，提交少（9 commits） | instruct-TTS 自称开源 SOTA（无量化公开指标） | ✅ | 7B，需 CUDA≥12.0 | 代码 Apache-2.0，权重条款未明示 | [GitHub](https://github.com/XiaomiMiMo/MiMo-Audio) |
| **Voxtral TTS**（Mistral） | 2026-03-23 | **不支持中文**（9 语言无 zh）→ 出局 | ✅ 3s | 70ms 模型延迟 | CC BY-NC 4.0 非商用 | [官方 news](https://mistral.ai/news/voxtral-tts) |
| **DiTTo-TTS**（KRAFTON/NVIDIA） | ICLR 2025 论文 | — | — | — | **无官方预训练权重** → 出局 | [OpenReview](https://openreview.net/forum?id=hQvX9MBowC)、[项目页](https://ditto-tts.github.io) |

### 0.3 第三方榜单快照（Artificial Analysis Speech Arena，2026-09 快照，二手）

- 全体榜前列：Cartesia Sonic 3.6（1277）、Google Gemini 3.8 Flash TTS（1268）、阿里 Qwen-Audio-3.0-TTS-Plus（1259）、Inworld Realtime TTS-2（1244）；ElevenLabs v3 Conversational 1197；MiniMax Speech 2.6 HD 1130。来源：[artificialanalysis.ai](https://artificialanalysis.ai/text-to-speech/leaderboard/provider-voice)
- 开源权重榜：Breeze TTS 2（1206）> Fish S2 Pro（1117）> Step Audio EditX（1092）> Voxtral（1079）> Kokoro（1063）> Chatterbox（1023）。来源：[open-weights board](https://artificialanalysis.ai/text-to-speech/leaderboard/provider-voice/open-weights)
- 注意：榜首两名开源模型（Breeze TTS 2、Fish S2 Pro）**权重均限非商用**，榜单名次不能直接当商用选型依据。

---

## 1. 云端 API 组

### 1.1 OpenAI gpt-4o-mini-tts / tts-1

- **现状**：gpt-4o-mini-tts 是 OpenAI 当前推荐的 TTS（支持 `instructions` 控制语调/情绪/耳语，13 个内置音色，流式输出）；tts-1/tts-1-hd 仍在售。来源：[官方 TTS 指南](https://developers.openai.com/api/docs/guides/text-to-speech)（抓取于 2026-10-06）
- **中文**：语言覆盖"大致跟随 Whisper"，含中文，但官方明示音色为英语优化。
- **价格**：gpt-4o-mini-tts 按 token 计价（$0.60/1M 输入 + $12/1M 音频输出，约 $0.015/分钟）；tts-1 $15/M 字符、tts-1-hd $30/M 字符。来源：[成本聚合](https://costgoat.com/pricing/openai-tts)（二手，2026-08）
- **无语音克隆**；单请求 4096 字符（gpt-4o-mini-tts 为 2000 token）。
- **结论**：工程稳但中文不突出，性价比一般，eggram 场景无特殊理由选它。

### 1.2 ElevenLabs v3（及 v2）

- **现状**：v3 alpha 2025-06 发布、**2026-03-14 GA**；Audio Tags（`[whispers]`/`[sighs]` 等行内情绪指令）、70+ 语言（v2 为 29）、复杂文本错误降 68%；不支持实时（~758ms），实时场景官方推 Flash v2.5（~75ms）。来源：[官方 docs](https://elevenlabs.io/docs/capabilities/text-to-speech)（2026-10-06 抓取）、[Vapi 实测](https://humannessindex.vapi.ai/models/elevenlabs-eleven-v3)（2026-10-02 榜单快照）
- **价格**：~$100/M 字符（v3）；v2 Multilingual 被官方定位为"长文本最稳"，很多人仍用它做中性旁白。
- **结论**：表达力最强档，适合"演播"，但对几十句短中文旁白属于杀鸡用牛刀，且价格最高、中文不是它的差异化优势。

### 1.3 MiniMax Speech 2.8（项目已接入）

- **现状**：Speech 02（2025-04-02）已列 Legacy；**Speech 2.8（2026-01-23）为当前默认**，API schema 与 02 完全兼容（换 model 字段即可），原生语气词、10s 克隆。来源：[Speech 2.8 官方新闻](https://www.minimaxi.com/news/minimax-speech-28)
- **中文**：332 个官方音色、24+ 语言，中文母语级；HD $100/M、Turbo $60/M 字符，60 RPM。来源：[定价](https://platform.minimax.io/docs/guides/pricing-paygo)、[音色表](https://platform.minimax.io/docs/faq/system-voice-id)
- **AA 榜**：Speech 2.6 HD Elo 1130（2026-09 快照）。
- **结论**：项目已有完整 provider 与音色映射（`tts_config.py`），零迁移成本；一课 5 分钟旁白约 3000 字，HD 约 ¥2.2/课。详见仓库内 `docs/research/minimax-speech-02.md`。

### 1.4 小米 MiMo（项目默认 provider）

- **现状**：MiMo 语音开放平台提供 `mimo-v2-tts` / `mimo-v2.5-tts`，OpenAI 兼容 `POST /v1/chat/completions`，**限时免费**；预置音色"冰糖/茉莉/苏打/白桦"（中）与"Mia/Chloe/Milo/Dean"（英）——即项目分镜里正在用的友好名本源；支持风格 tag（`[开心]`、`[东北话]`、`[吸气]` 等）。来源：[mimo.mi.com 官方文档](https://mimo.mi.com/docs/news/v2-tts-release)、[第三方接入实录](https://github.com/NousResearch/hermes-agent/issues/46257)（二手）
- **开源侧**：MiMo-Audio-7B（Base/Instruct + 1.2B Tokenizer）已开源，代码 Apache-2.0，训练超 1 亿小时；但它是通用音频 LLM（理解+生成+续写），TTS 只是子能力，7B 部署重、无公开 TTS 量化指标。来源：[GitHub](https://github.com/XiaomiMiMo/MiMo-Audio)（2026-10-06 抓取，仅 9 commits）
- **结论**：免费 + 中文好，作为云端备选保留；但"限时免费"意味着随时可能转收费，不宜作为唯一依赖。

---

## 2. 开源/本地组

### 2.1 Qwen3-TTS（阿里）★ 重点

- **发布**：2026-01-22 开源 0.6B / 1.7B（Qwen3-TTS-Tokenizer-12Hz），离散多码本 LM + 轻量非 DiT 解码器 + 双轨流式架构；10 语言含中日英。来源：[GitHub](https://github.com/QwenLM/Qwen3-TTS)（2026-10-06 抓取）
- **客观指标**：Seed-TTS eval test-zh WER **0.77**（1.7B-Base；对比 MiniMax 0.83、IndexTTS2 1.03、CosyVoice2 1.38）；训练约 5M 小时（KRAFTON Raon 报告对比表）。来源：[GitHub 评测表](https://github.com/QwenLM/Qwen3-TTS)、[Raon-OpenTTS](https://github.com/krafton-ai/Raon-OpenTTS)
- **克隆**：3 秒极速克隆；`qwen-tts` pip 一条命令安装，权重自动下载，自带 Gradio demo；vLLM-Omni day-0 支持（注意其 vLLM 路径仅 Linux/离线）。
- **License**：**Apache-2.0（代码与权重）**——商用无负担。
- **缺点**：Windows 下 vLLM 不可用（transformers 路径可用）；仓库较新，Windows 实战经验少。

### 2.2 CosyVoice 2 / 3（阿里 FunAudioLLM）★ 重点

- **发布**：CosyVoice 2（0.5B，2024-12）；**CosyVoice 3（Fun-CosyVoice3-0.5B-2512，2025-12，含 Base/RL 两版）**。维护活跃（23.8k stars、552 commits）。来源：[GitHub](https://github.com/FunAudioLLM/CosyVoice)（2026-10-06 抓取）
- **客观指标**：test-zh CER 1.45（CV2）→ 1.21（CV3-Base）→ **0.81（CV3-RL）**；SIM 75.8→77.4；英文/难例同步领先。9 国语言 + **18+ 中文方言**（粤/闽/川/东北……）。
- **速度/部署**：双向流式，**延迟低至 150ms**；TensorRT-LLM 4x 加速；vLLM ≥0.9.0 支持；`pip install -r requirements.txt`，无编译（文本前端默认 wetext）。
- **License**：**Apache-2.0**。
- **缺点**：官方环境面向 Linux（conda + sox），Windows 需 WSL2；RL 版权重资源开销更大。

### 2.3 IndexTTS 1.5 / 2 / 2.5（B站）

- **发布**：1.0（2025-03）、1.5（2025-05）、**2.0（2025-09-08，首个精确时长控制的 AR 模型，情感多模态控制）**、**2.5（2026-08-10：中/英/日/西/阿 5 语言，推理更快，vLLM 生产部署，拼音/音素级发音控制）**。24.3k stars。来源：[GitHub](https://github.com/index-tts/index-tts)（2026-10-06 抓取）
- **客观指标**：zh CER 1.03 / SIM 76.5（GLM-TTS 官方对比表，2025-12）。
- **License**：**bilibili 模型使用协议——默认非商用，商用需联系 indexspeech@bilibili.com**。这是最大限制。
- **结论**：质量与可控性一流（时长控制对"音画锁"甚至有用），但商用授权是硬门槛。

### 2.4 GLM-TTS（智谱）

- **发布**：2025-12-11 开源（技术报告 arXiv:2512.14291，2025-12-17）。两阶段（LLM 出 token + Flow 出 mel + vocoder），GRPO 多奖励 RL。来源：[GitHub](https://github.com/zai-org/GLM-TTS)（2026-10-06 抓取）
- **客观指标**：seed-tts-eval zh CER 1.03（Base）→ **0.89（RL）**/ SIM 76.4，RL 版 CER 压过 IndexTTS2；主打中文 + 中英混读，3–10s 克隆，支持流式。
- **License**：**Apache-2.0**。
- **缺点**：无官方 VRAM/RTF 数据；生态与文档成熟度不如 Qwen3-TTS/CosyVoice。

### 2.5 其他开源候选（简评）

| 模型 | 一句话结论 | 关键来源 |
| --- | --- | --- |
| Breeze TTS 2（3B，2026-08-25） | AA 开源榜第 1（Elo 1206）、TTFA<40ms，但**权重限非商用** | [HF](https://huggingface.co/BreezeBlue/Breeze-TTS-2) |
| Fish Speech / OpenAudio S1、S2 Pro | zh WER 0.54% 开源最优档，但 **Research License 非商用**；商用走 Fish API（$15/M） | [GitHub](https://github.com/fishaudio/fish-speech) |
| F5-TTS | 曾是一代主力；**权重 CC-BY-NC 非商用**，v1 后维护放缓，被 CV2/CV3 超越 | [GitHub](https://github.com/SWivid/F5-TTS) |
| Kokoro 82M | Apache-2.0、pip 即装、CPU 可跑、极轻；**中文韵律弱、无克隆**——适合英文/快速原型 | [GitHub](https://github.com/hexgrad/kokoro) |
| Spark-TTS 0.5B | Apache-2.0、中英 zero-shot，但社区热度/迭代已降温 | [GitHub](https://github.com/SparkAudio/Spark-TTS) |
| Step-Audio-TTS-3B | 2025-02 发布、**仓库已停止维护**；继任者 Step Audio EditX（2026-02/03 开源权重）在 AA 榜 1092 | [GitHub](https://github.com/stepfun-ai/Step-Audio) |
| Chatterbox（MIT） | 23+ 语言含中文、CPU 友好，但**所有输出带 Resemble 水印**，不适合出品 | [GitHub](https://github.com/resemble-ai/chatterbox) |
| Voxtral TTS | 不支持中文 + CC BY-NC，出局 | [官方](https://mistral.ai/news/voxtral-tts) |
| DiTTo-TTS | ICLR 2025 论文，**官方从未发布预训练权重**，出局；精神续作 KRAFTON Raon-OpenTTS（2026-05，权重+数据全开放但英文为主） | [OpenReview](https://openreview.net/forum?id=hQvX9MBowC) |
| VibeVoice（微软） | 2025-08-26 发布 10 天后被微软撤回权重（MIT 社区镜像仍在），有合规风险，不建议 | [pinggy 综述](https://pinggy.io/blog/best_open_source_self_hosted_text_to_speech_models)（二手） |

---

## 3. 场景分析：微课旁白要什么

eggram 的实际负载（`docs/audio.md`、`scripts/tts_config.py`）：

| 需求 | 推导 |
| --- | --- |
| 每页一句短中文口语句（narrate，约 10–40 字） | 不需要长文一致性，单句质量 > 篇章一致性 |
| 男/女旁白各 1–2 个固定音色，全课统一 | 需要"预置音色稳定"或"一次克隆、永久复用"；不需要实时流式 |
| 一课几十句、2–3 分钟成片 | 离线批量合成即可；RTF < 1 就够用，速度不敏感 |
| 已有缓存指纹 `sha256(voice\|narrate)` | 换引擎=全量重 TTS 一次，之后复用；本地引擎零边际成本 |
| 开发机为 Windows 11 | vLLM/SGLang 仅 Linux → 要么 transformers 直跑，要么 WSL2 |
| 项目诉求：省 API key、零成本、离线可跑 | **License 必须允许商用**（eggram 仓库公开、产物对外发布） |

由此排除：非商用 License 的全部开源模型（F5-TTS、Fish、Breeze TTS 2、IndexTTS 默认协议、Voxtral、Step 权重）、无中文的（Voxtral、Raon）、无官方权重的（DiTTo）、输出带水印的（Chatterbox）、已停维护的（Step-Audio-TTS、OpenVoice/XTTS 等老一代）。

---

## 4. 给 eggram 的选型建议（Top 3，不并列）

### 🥇 1. Qwen3-TTS-12Hz-1.7B（本地主力）

**理由**：2026 年最新一代开源旗舰里中文客观指标最强（test-zh WER 0.77，压过 MiniMax 的 0.83）；Apache-2.0 代码+权重，商用零法律负担；`pip install qwen-tts` 一条命令、权重自动下载、自带 Gradio 与 transformers 推理路径，写 provider 插件成本最低；3s 克隆 + CustomVoice 预置音色，男/女旁白音色可以固定下来全课复用；阿里持续迭代（vLLM-Omni day-0）。对"几十句短中文、求稳求清晰"的场景，它的强项（低 WER=不念错字）正中需求。

### 🥈 2. CosyVoice 3（Fun-CosyVoice3-0.5B-2512，本地备选/轻量化）

**理由**：同为 Apache-2.0；0.5B 比 Qwen3-TTS-1.7B 更轻、RTF 更高，150ms 流式、TensorRT-LLM 4x 加速，方言支持最广（教学课里若出现方言例句是唯一选择）；生态最成熟（23.8k stars、文档/部署案例最多）。排第二只因发布时间早一个月、客观指标略逊（0.81 vs 0.77）且 Windows 同样依赖 WSL2。**若机器显存 ≤8GB 或想要最稳的部署经验，它与第一名互换。**

### 🥉 3. MiniMax Speech 2.8（云端保底，保留现有 provider）

**理由**：已完整接入（含音色映射与缓存指纹），零改造成本；332 个官方中文音色、中文母语级、商业 SLA 稳定；按量计费下一课约 ¥1.3–2.2。本地 GPU 不可用（或不想维护）时直接切 `--tts-provider minimax` 并确认 `MINIMAX_MODEL=speech-2.8-hd` 即可。同时建议把现有 `xiaomi`（MiMo 限时免费）留作第二云端备选，但不要把"限时免费"当长期依赖。

**明确不推荐**：F5-TTS / Fish Speech / Breeze TTS 2（License 非商用）、IndexTTS2.5（质量高但要单独商用授权，除非愿意走授权流程，否则其"精确时长控制"的诱惑不值得法律风险）、Kokoro（中文不够稳）、ElevenLabs/OpenAI（贵且中文无优势）。

### 追加（2026-10-06）：用户明确"只用付费 API、不要本地模型"后的云端结论

需求反转：不要本地部署，接受按量付费。此时排序变为：

1. **🥇 Qwen-Audio-3.0-TTS-Plus（阿里 DashScope API，2026-07-23 发布）** —— Artificial Analysis 语音竞技场 2026-07 起榜首（Elo 1237，2026-09 快照 1259，压过 Cartesia Sonic 3.6 / Gemini Flash TTS / MiniMax 2.8 HD / ElevenLabs v3）；$20–27.6/M 字符，约为 ElevenLabs / MiniMax HD（均 $100/M）的 1/4–1/3.6；中文为阿里母语场景。来源：[OpenRouter 模型页](https://openrouter.ai/qwen/qwen-audio-3.0-tts-plus)、[aireiter 竞技场解读（2026-07-20）](https://aireiter.com/blog/qwen-audio-3-tts)、[artificialanalysis.ai](https://artificialanalysis.ai/text-to-speech/leaderboard/provider-voice)。注意：音色数量远少于 MiniMax（OpenRouter 仅 2 个；DashScope 侧以官方为准）。
2. **🥈 MiniMax Speech 2.8 HD** —— 已接入零改造；332 中文音色可选性最好。切换零成本。
3. **🥉 Cartesia Sonic 3.6 明确不推荐用于中文**：竞技场总分虽多次登顶（Elo 1282 @2026-09-08），但官方 changelog 明示 3.6 "改进所有语言**除中文外**（Chinese targeted for future updates）"；且为订阅点数制（≈$37–50/M），无按量付费。来源：[Cartesia changelog 2026](https://docs.cartesia.ai/changelog/2026)。
4. MiMo（xiaomi，限时免费）继续作免费备选，不作长期依赖。

成本量级：一课旁白约数百字符，按 $27.6/M 计**单课音频成本 < ¥0.2**，成本不构成选型约束，按质量选即可。

**国内阿里云（aliyun.com / 百炼）落地信息（2026-10-06 核实）**：模型 ID `qwen-audio-3.0-tts-plus`，北京地域 **¥1.4/万字符**（新开通 90 天内赠 1 万字符免费额度），RPM 180。系统音色含「龙安风悦（longanfengyue，自然亲切女）」等，另有 500+ 基础音色（`qwen-audio-3.0-tts-plus-{后缀}`）；支持情感/富语言标签（如 `[excited]`）与方言指令，支持声音复刻（创建免费）。注意：**Qwen-Audio-TTS 非实时语音合成仅北京地域可用**，需选北京地域的 API Key。来源：[模型信息页](https://help.aliyun.com/zh/model-studio/qwen-audio-3-0-tts-plus)、[音色列表](https://docs.bailian.console.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list)、[非实时语音合成指南](https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide)、[模型价格总表](https://help.aliyun.com/zh/model-studio/model-pricing)。另：迷你版 `qwen-audio-3.0-tts-flash` ¥1/万字符，可作降级备选。

### 落地路径（已完成 · 2026-10-06 走的是云端 API 版，非本地权重）

用户选择"只用付费 API、不要本地部署"，故落地的是 **DashScope 百炼的 `qwen-audio-3.0-tts-plus`**，
不是上面开源榜里的 Qwen3-TTS-1.7B 权重。实际改动：

1. `tts_config.py`：新增 `PROVIDERS` 常量（单一事实源）、`QWEN_VOICE_MAP`、`resolve_qwen_voice`、`qwen_config`；`is_provider` 改为从 `PROVIDERS` 派生。
2. `make_video.py`：新增 `qwen_tts()`（POST → 取回 `output.audio.url` → 再 GET 音频字节），`synthesize` 增加 `qwen` 分支。
3. 端点与请求体（**冒烟核实**）：`POST https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer`，
   body `{"model": "...", "input": {"text", "voice", "format": "wav", "sample_rate": 24000}}`。
   **注意与 Qwen-TTS 的端点不同**（后者是 `.../aigc/multimodal-generation/generation`），不可混用。
4. 音色：plus 仅 2 个系统音色 `longanlingxin`(女) / `longanlufeng`(男)，友好名并束到这两条；更多音色走百炼声音复刻（创建免费）。
5. 两处 argparse（`make_video.py` / `render_worker.py`）的 `--tts-provider choices` 改从 `PROVIDERS` 派生，杜绝"闸门放行、CLI 先拒"的漂移。
6. 缓存指纹含 `provider|voice|narrate`，未改缓存逻辑；实测换 provider 后 `--reuse-audio` 10/10 命中。

**坑（已核实）**：接口返回的 WAV 头 `nframes` 是占位值（0x3FFFFFCD），**不得用 `getnframes()` 估时长**，
一律以实际读到的 PCM 为准（`decode_wav` 本来就是这么做的）。返回音频为单声道/24000Hz/16bit，无需 ffmpeg 转码。
5. 回归：`py -m pytest tests/test_tts_config.py tests/test_audio_cache.py` 加一个 qwen provider 的单测。

---

## 附：关键来源清单

一手（官方）

- Qwen3-TTS：https://github.com/QwenLM/Qwen3-TTS
- CosyVoice：https://github.com/FunAudioLLM/CosyVoice
- IndexTTS：https://github.com/index-tts/index-tts
- GLM-TTS：https://github.com/zai-org/GLM-TTS ｜ https://huggingface.co/zai-org/GLM-TTS
- F5-TTS：https://github.com/SWivid/F5-TTS
- Kokoro：https://github.com/hexgrad/kokoro
- Spark-TTS：https://github.com/SparkAudio/Spark-TTS
- Fish Speech：https://github.com/fishaudio/fish-speech
- Step-Audio：https://github.com/stepfun-ai/Step-Audio
- Chatterbox：https://github.com/resemble-ai/chatterbox
- MiMo-Audio：https://github.com/XiaomiMiMo/MiMo-Audio ｜ MiMo TTS 文档：https://mimo.mi.com/docs/news/v2-tts-release
- OpenAI TTS：https://developers.openai.com/api/docs/guides/text-to-speech
- ElevenLabs：https://elevenlabs.io/docs/capabilities/text-to-speech
- MiniMax：https://www.minimaxi.com/news/minimax-speech-28 ｜ https://platform.minimax.io/docs/guides/pricing-paygo
- Voxtral TTS：https://mistral.ai/news/voxtral-tts
- Breeze TTS 2：https://huggingface.co/BreezeBlue/Breeze-TTS-2
- DiTTo-TTS：https://openreview.net/forum?id=hQvX9MBowC ｜ https://ditto-tts.github.io
- KRAFTON Raon-OpenTTS：https://github.com/krafton-ai/Raon-OpenTTS

二手（榜单/实测，已标注）

- Artificial Analysis Speech Arena：https://artificialanalysis.ai/text-to-speech/leaderboard/provider-voice 及 /open-weights（2026-09 快照）
- Vapi Humanness Index（ElevenLabs v3 延迟/发布日）：https://humannessindex.vapi.ai/models/elevenlabs-eleven-v3（2026-10-02 快照）
- OpenAI TTS 价格聚合：https://costgoat.com/pricing/openai-tts（2026-08）
- pinggy 2026 开源 TTS 综述：https://pinggy.io/blog/best_open_source_self_hosted_text_to_speech_models
