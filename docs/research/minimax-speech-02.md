# Research: MiniMax Speech-02 TTS 接入方式

## Summary

MiniMax Speech 02（含 HD / Turbo 两个变体）通过 REST `POST /v1/t2a_v2`（同步）、`/v1/t2a_async_v2`（异步长文）、`wss://.../ws/v1/t2a_v2`（流式 WebSocket）三个端点暴露，海外域 `https://api.minimax.io`、国内域 `https://api.minimaxi.com`；认证为 `Authorization: Bearer <API_KEY>`。官方无独立 SDK，仅 REST + WebSocket。**任务给的目标 URL `…/news/minimax-speech-28` 实际是 2026-01-23 发布的 Speech 2.8，不是 Speech 02；两套 model ID 共享同一套 API schema 与音色体系**。`冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean` 这 8 个名字**未在 MiniMax 官方系统音色表中出现**，仅在某些第三方聚合平台（如 MiMo TTS、小渡 API）作为对外别名存在——不要把第三方别名当成 MiniMax 官方音色。

---

## ⚠️ 任务前置澄清（重要）

| 项 | 实际事实 | 来源 |
| --- | --- | --- |
| 任务给的 URL `…/news/minimax-speech-28` | 实际是 **Speech 2.8** 发布博客（2026-01-23），不是 Speech 02 | [minimax-speech-28](https://www.minimaxi.com/news/minimax-speech-28) |
| Speech 02 发布日 | 2025-04-02，MiniMax 当前**归类为 Legacy Model** | [minimax-speech-02 blog](https://www.minimax.io/news/minimax-speech-02) |
| Speech 02 / 2.8 关系 | 共用同一 T2A v2 接口与音色体系；只是 model 字段取 `speech-02-hd` 还是 `speech-2.8-hd` 的区别 | [Pricing PayGo](https://platform.minimax.io/docs/guides/pricing-paygo) |
| 用户询问的 8 个 voice 名 | **均不是 MiniMax 官方系统音色 ID**——属于第三方聚合平台的别名 | 见下方"可用音色"章节 |

下面把 **Speech 02 家族** 的接入写清楚，同时注明 2.8 的差异点。

---

## 1. API endpoint

| 用途 | Method | URL |
| --- | --- | --- |
| 同步合成（推荐，≤10k 字符/请求） | POST | `https://api.minimax.io/v1/t2a_v2`（海外）/ `https://api.minimaxi.com/v1/t2a_v2`（国内） |
| 异步长文合成（最长 1M 字符） | POST | `https://api.minimax.io/v1/t2a_async_v2` |
| 异步任务查询 | GET | `https://api.minimax.io/v1/query/t2a_async_query_v2?task_id={id}` |
| 流式合成 | WS | `wss://api.minimax.io/ws/v1/t2a_v2` |
| 查询系统音色列表 | POST | `https://api.minimax.io/v1/voice/voice_setting/voice_list` （旧版）/ 见 [Get Voice API](https://platform.minimaxi.com/docs/api-reference/voice-management-get) |

**Sources:**

- [T2A HTTP OpenAPI](https://platform.minimax.io/docs/api-reference/speech-t2a-http)（direct evidence: `servers.url = https://api.minimax.io`，`/v1/t2a_v2` POST endpoint）
- [T2A Async Guide](https://platform.minimax.io/docs/guides/speech-t2a-async)（direct evidence: URL、curl 示例）
- [T2A WebSocket](https://platform.minimax.io/docs/api-reference/speech-t2a-websocket)（direct evidence: `wss://api.minimax.io/ws/v1/t2a_v2`）
- [T2A Async 国内版](https://platform.minimaxi.com/docs/guides/speech-t2a-async)（direct evidence: 国内域 `api.minimax.cn`、`api.minimaxi.com`）

> **研究者备注**：海外官方域 `api.minimax.io` 与官方文档站 `platform.minimax.io` 同子域；国内常见别名为 `api.minimaxi.com` 与旧版 `api.minimax.cn`，两个都能用，但 endpoint 路径一致。

---

## 2. 认证方式

```http
Authorization: Bearer <MINIMAX_API_KEY>
Content-Type: application/json
```

- **header 字段**：`Authorization`，scheme 为 `bearer`，`bearerFormat: JWT`（OpenAPI 标注）。
- **key 命名**：官方环境变量名是 **`MINIMAX_API_KEY`**（见 [minimax_tts.py](https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/scripts/minimax_tts.py) 与所有官方示例）。项目里自定义的 `MIMO_API_KEY` 与 MiniMax 无关，是用户/团队的本地变量名，二者**不要混用**——必须自己把 `MIMO_API_KEY` 的值赋给官方期望的 `MINIMAX_API_KEY`（或者按官方脚本从 `os.getenv("MINIMAX_API_KEY")` 取）。
- 国内版**还需要 `GroupId` header**（见 [minimax-python-client](https://github.com/linzeyang/minimax-python-client) 说明），海外版不需要。

**Sources:** [T2A HTTP securitySchemes](https://platform.minimax.io/docs/api-reference/speech-t2a-http)（direct evidence: bearerAuth），[官方示例脚本](https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/scripts/minimax_tts.py)

---

## 3. 请求格式（核心字段）

`POST /v1/t2a_v2` body schema（精简版）：

```json
{
  "model": "speech-02-hd",              // 或 speech-02-turbo / speech-2.8-hd / speech-2.8-turbo
  "text": "要合成的文本",              // ≤10,000 字符（同步）
  "stream": false,                      // true 走 SSE/WS 流式
  "language_boost": "auto",             // auto | Chinese | English | Japanese | Cantonese 等
  "output_format": "hex",               // hex | url（仅非流式；url 24h 过期）
  "voice_setting": {
    "voice_id": "male-qn-qingse",
    "speed": 1.0,                       // [0.5, 2]
    "vol": 1.0,                          // (0, 10]
    "pitch": 0,                          // [-12, 12] 整数
    "emotion": "neutral",                // happy / sad / angry / fearful / disgusted / surprised / calm / fluent / whisper
    "english_normalization": false
  },
  "pronunciation_dict": { "tone": [] },
  "audio_setting": {
    "sample_rate": 32000,                // 8000 / 16000 / 22050 / 24000 / 32000 / 44100
    "bitrate": 128000,                   // 32000 / 64000 / 128000 / 256000（仅 mp3）
    "format": "mp3",                     // mp3 | pcm | flac | wav | opus（wav 仅非流式）
    "channel": 1                          // 1 或 2
  },
  "voice_modify": {
    "pitch": 0, "intensity": 0, "timbre": 0,
    "sound_effects": "spacious_echo"     // spacious_echo / auditorium_echo / lofi_telephone / robotic
  }
}
```

**Sources:** [T2A HTTP OpenAPI schema](https://platform.minimax.io/docs/api-reference/speech-t2a-http)（direct evidence: 完整字段约束）, [Async 异步示例](https://platform.minimaxi.com/docs/guides/speech-t2a-async)（direct evidence: curl 完整请求）

---

## 4. 响应格式

```json
{
  "data": { "audio": "<hex>", "status": 2 },
  "extra_info": {
    "audio_length": 11124,            // 毫秒
    "audio_sample_rate": 32000,
    "audio_size": 179926,             // 字节
    "bitrate": 128000,
    "word_count": 163,
    "usage_characters": 163,          // 计费字符数
    "audio_format": "mp3",
    "audio_channel": 1
  },
  "trace_id": "01b8bf9bb7433cc75c18eee6cfa8fe21",
  "base_resp": { "status_code": 0, "status_msg": "success" }
}
```

| 音频格式 | 采样率 | 声道 | 流式 |
| --- | --- | --- | --- |
| mp3 / pcm / flac / opus | 8k / 16k / 22.05k / 24k / 32k / 44.1k | 1（mono）/ 2（stereo） | ✅ |
| **wav** | 同上 | 同上 | ❌ 仅非流式 |

`output_format`：

- `hex`：返回 hex 编码音频（流式强制 hex）
- `url`：返回 24h 过期的下载链接（**仅非流式**）

**Sources:** [T2A HTTP OpenAPI response 示例](https://platform.minimax.io/docs/api-reference/speech-t2a-http)（direct evidence: 响应 schema、format 枚举）

---

## 5. 可用音色列表

### 5.1 重点结论（先回答用户的 8 个名字）

| 用户询问 | 是否 MiniMax 官方 | 说明 |
| --- | --- | --- |
| 冰糖 | ❌ | 未在 MiniMax 官方系统音色表出现；为某些第三方聚合平台别名 |
| 茉莉 | ❌ | 同上 |
| 苏打 | ❌ | 同上 |
| 白桦 | ❌ | 同上 |
| Mia | ❌ | 同上 |
| Chloe | ❌ | 同上 |
| Milo | ❌ | 同上 |
| Dean | ❌ | 同上 |

> **直接证据**：上述名字在 [platform.minimaxi.com/docs/faq/system-voice-id](https://platform.minimaxi.com/docs/faq/system-voice-id) 与 [platform.minimax.io/docs/faq/system-voice-id](https://platform.minimax.io/docs/faq/system-voice-id) 的完整 332 个官方音色 ID 列表中**均不出现**。它们出现在第三方平台 [MiMo TTS 文档](https://github.com/duolabmeng6/voice_hub/blob/main/docs/mimo-tts.md) 与 [小渡 API](https://api.dwo.cc/api/258) 等——这些平台对 MiniMax 音色做了二次封装/重命名。

### 5.2 MiniMax 官方中文（普通话）音色精选

官方国内域音色表前 30 条全部展示（按平台顺序）：

| voice_id | 音色名称 | voice_id | 音色名称 |
| --- | --- | --- | --- |
| `male-qn-qingse` | 青涩青年音色 | `bingjiao_didi` | 病娇弟弟 |
| `male-qn-jingying` | 精英青年音色 | `junlang_nanyou` | 俊朗男友 |
| `male-qn-badao` | 霸道青年音色 | `chunzhen_xuedi` | 纯真学弟 |
| `male-qn-daxuesheng` | 青年大学生音色 | `lengdan_xiongzhang` | 冷淡学长 |
| `female-shaonv` | 少女音色 | `badao_shaoye` | 霸道少爷 |
| `female-yujie` | 御姐音色 | `tianxin_xiaoling` | 甜心小玲 |
| `female-chengshu` | 成熟女性音色 | `qiaopi_mengmei` | 俏皮萌妹 |
| `female-tianmei` | 甜美女性音色 | `wumei_yujie` | 妩媚御姐 |
| `clever_boy` | 聪明男童 | `diadia_xuemei` | 嗲嗲学妹 |
| `cute_boy` | 可爱男童 | `danya_xuejie` | 淡雅学姐 |
| `lovely_girl` | 萌萌女童 | `Chinese (Mandarin)_Reliable_Executive` | 沉稳高管 |
| `cartoon_pig` | 卡通猪小琪 | `Chinese (Mandarin)_News_Anchor` | 新闻女声 |
| `Chinese (Mandarin)_Sweet_Lady` | 甜美女声 | `Chinese (Mandarin)_Lyrical_Voice` | 抒情男声 |
| `Chinese (Mandarin)_Warm_Bestie` | 温暖闺蜜 | `Chinese (Mandarin)_Pure-hearted_Boy` | 清澈邻家弟弟 |
| `Chinese (Mandarin)_Warm_Girl` | 温暖少女 | `Chinese (Mandarin)_Soft_Girl` | 柔和少女 |

另有 `-jingpin` / `-beta` 后缀的高清版（如 `female-shaonv-jingpin`），以及粤语、英语、日语、韩语、西班牙语、葡语、印尼语、德语、俄语、意大利语、阿拉伯语、土语、乌克兰语、荷兰语、越南语、泰语、波兰语、罗马尼亚语、希腊语、捷克语、芬兰语、印地语等共 **332 个** 系统音色。

**Sources:** [platform.minimaxi.com/docs/faq/system-voice-id](https://platform.minimaxi.com/docs/faq/system-voice-id)（direct evidence: 完整 327 条），[platform.minimax.io/docs/faq/system-voice-id](https://platform.minimax.io/docs/faq/system-voice-id)（direct evidence: 332 条海外版）

> **建议**：项目里要"甜美少女"就用 `female-shaonv` 或 `Chinese (Mandarin)_Sweet_Lady`；要"沉稳男"用 `male-qn-jingying` 或 `Chinese (Mandarin)_Reliable_Executive`。**不要用第三方别名**，因为一旦 MiniMax 升级 API、第三方聚合层失效，你会被卡住。

---

## 6. SDK

**官方没有发布独立 SDK**（Python / Node / Go / Java 均无）。官方仅提供：

- REST HTTP（同步）—— `POST /v1/t2a_v2`
- REST HTTP（异步长文）—— `POST /v1/t2a_async_v2`
- WebSocket（流式）—— `wss://api.minimax.io/ws/v1/t2a_v2`

**第三方（非官方）**：

| 项目 | 说明 | 来源 |
| --- | --- | --- |
| `MiniMax-AI/skills` 仓库 | 提供官方风格的 Python 示例脚本 `minimax_tts.py`（同步） + WebSocket 流式脚本 | [github.com/MiniMax-AI/skills](https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/scripts/minimax_tts.py) |
| `linzeyang/minimax-python-client` | 社区 Python SDK，封装 T2A / T2A Pro / Voice Cloning 等 | [github.com/linzeyang/minimax-python-client](https://github.com/linzeyang/minimax-python-client) |
| `novita.ai` / `fal.ai` / `replicate.com` / `WaveSpeedAI` | 通过聚合 API 访问 speech-02-hd；URL、字段名、价格均与 MiniMax 直连不同，**不可直接套用** | [fal.ai/.../minimax-speech-02-hd](https://fal.ai/models/fal-ai/minimax/speech-02-hd/api) 等 |

**Sources:** [官方文档导航](https://platform.minimax.io/docs/guides/models-intro)（direct evidence: 仅列出 REST / WebSocket / Async 三类，无 SDK 下载链接）

> **研究者建议**：项目里直接用 `requests`（同步）或 `websockets`（流式）调 REST API 就够，不要引入第三方 SDK 以免吃版本兼容坑。

---

## 7. 速率限制 / 计费

### 7.1 计费（按字符，按模型分档）

来自 [官方 PayGo 页](https://platform.minimax.io/docs/guides/pricing-paygo)：

| 模型 | 价格 | 备注 |
| --- | --- | --- |
| **speech-02-hd** | **$100 / 1M characters** | Legacy 模型 |
| **speech-02-turbo** | **$60 / 1M characters** | Legacy 模型 |
| speech-2.6-hd | $100 / 1M characters | Legacy 模型 |
| speech-2.6-turbo | $60 / 1M characters | Legacy 模型 |
| speech-2.8-hd | $100 / 1M characters | **当前默认 HD** |
| speech-2.8-turbo | $60 / 1M characters | **当前默认 Turbo** |
| Voice Design | $3 per voice | 首次用于合成时扣费 |
| Rapid Voice Cloning | $1.5 per voice | 首次用于合成时扣费 |
| Speech-to-Text | $0.38 / hour | ASR |

**Sources:** [platform.minimax.io/docs/guides/pricing-paygo](https://platform.minimax.io/docs/guides/pricing-paygo)（direct evidence: 完整定价表）

### 7.2 速率限制

来自 [官方 Rate Limits](https://platform.minimax.io/docs/guides/rate-limits)：

| 模型 | RPM（每分钟请求数） |
| --- | --- |
| **speech-02-hd** | 60 |
| **speech-02-turbo** | 60 |
| Voice Cloning | 60 |
| Voice Design | 20 |

TPM / 并发上限未在官方页明确公开（**未在官方页面找到**）。

**Sources:** [platform.minimax.io/docs/guides/rate-limits](https://platform.minimax.io/docs/guides/rate-limits)

### 7.3 输入上限

- 同步 T2A：≤ **10,000 字符** / 请求
- 异步 T2A：≤ **1,000,000 字符** / 请求

---

## 8. speech-02 vs speech-02-hd 区别

⚠️ 这里有个命名歧义——"speech-02" 实际上指 **Speech 02 家族**，包含两个变体：

| 变体 | model 字段 | 定位 | 价格 | 延迟（Vapi 实测中位数） |
| --- | --- | --- | --- | --- |
| **speech-02-hd** | `speech-02-hd` | 高保真：配音 / 有声书 / 品牌叙事 | $100 / 1M chars | ~357 ms 首包（Vapi 50 trial 基准） |
| **speech-02-turbo** | `speech-02-turbo` | 低延迟：AI agent / 语音聊天 / 交互 | $60 / 1M chars | ~315 ms 首包（同基准） |

- **语言支持**：两者均支持 24+ 语言，7 种情绪（happy / sad / angry / fearful / disgusted / surprised / calm / fluent / whisper；按官方文档枚举）。
- **音质**：HD 更高保真，turbo 更便宜更快——选择规则："HD 给音质，Turbo 给响应速度"。
- **官方文档分类**：两者都已**划入 Legacy Models**，新接入推荐用 `speech-2.8-hd` / `speech-2.8-turbo`（API schema 完全兼容，直接换 model 字段即可）。

**Sources:**

- [Pricing PayGo（Legacy 表）](https://platform.minimax.io/docs/guides/pricing-paygo)（direct evidence: $100/$60 价格）
- [T2A HTTP Models 表](https://platform.minimax.io/docs/api-reference/speech-t2a-http)（direct evidence: speech-02-hd / speech-02-turbo 仍列为合法 model）
- [Vapi Speech 2 HD 实测](https://humannessindex.vapi.ai/models/minimax-speech-02-hd)（direct evidence: 357 ms vs 315 ms）
- [speech-02-series 发布博客](https://www.minimax.io/news/speech-02-series)（direct evidence: HD = 配音/有声书，Turbo = 实时交互）

---

## 9. 最小可运行接入示例

### 9.1 curl（同步，speech-02-turbo）

```bash
export MINIMAX_API_KEY="<your_key>"

curl -X POST "https://api.minimax.io/v1/t2a_v2" \
  -H "Authorization: Bearer ${MINIMAX_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "speech-02-turbo",
    "text": "你好，欢迎使用 MiniMax Speech 02 语音合成。",
    "stream": false,
    "language_boost": "auto",
    "output_format": "hex",
    "voice_setting": {
      "voice_id": "female-shaonv",
      "speed": 1.0,
      "vol": 1.0,
      "pitch": 0,
      "emotion": "neutral"
    },
    "audio_setting": {
      "sample_rate": 32000,
      "bitrate": 128000,
      "format": "mp3",
      "channel": 1
    }
  }' \
  -o response.json

# 提取 audio hex → 落盘
python -c "import json; d=json.load(open('response.json')); open('out.mp3','wb').write(bytes.fromhex(d['data']['audio']))"
```

### 9.2 Python（最小可运行）

```python
import os, requests

API_KEY = os.environ["MINIMAX_API_KEY"]
BASE = "https://api.minimax.io"  # 海外；国内用 https://api.minimaxi.com

resp = requests.post(
    f"{BASE}/v1/t2a_v2",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    json={
        "model": "speech-02-hd",
        "text": "Hello, this is MiniMax Speech 02 HD.",
        "stream": False,
        "language_boost": "auto",
        "output_format": "hex",
        "voice_setting": {
            "voice_id": "male-qn-qingse",
            "speed": 1.0, "vol": 1.0, "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000, "bitrate": 128000,
            "format": "mp3", "channel": 1,
        },
    },
    timeout=60,
)
resp.raise_for_status()
data = resp.json()
if data["base_resp"]["status_code"] != 0:
    raise RuntimeError(data["base_resp"]["status_msg"])

open("out.mp3", "wb").write(bytes.fromhex(data["data"]["audio"]))
print(f"OK, audio_length={data['extra_info']['audio_length']}ms, "
      f"usage_chars={data['extra_info']['usage_characters']}")
```

**Sources:** [官方示例脚本](https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/scripts/minimax_tts.py)（direct evidence: payload 结构、header），[官方 curl 示例](https://platform.minimaxi.com/docs/guides/speech-t2a-async)

---

## 矛盾点 / 注意事项

1. **域名有两套**：海外 `api.minimax.io` 与国内 `api.minimaxi.com` / `api.minimax.cn` 三者共存，文档站也分 `platform.minimax.io`（海外）和 `platform.minimaxi.com`（国内）。**Endpoint 路径完全一致**，只是 host 不同——选 host 时按账号注册地选。
2. **Speech 02 是 Legacy，但 API 仍然完全可用**：官方定价页明确把 `speech-02-hd` / `speech-02-turbo` 列在 Legacy 表里，**没有下架**；OpenAPI 文档仍把它们列为合法 `model` 枚举值。研究者推断：新项目建议 2.8，已有项目继续 02 无需迁移。
3. **国内域 `api.minimax.cn` vs `api.minimaxi.com`**：官方文档里两个都出现，路径相同；研究者推断 `api.minimaxi.com` 是当前主域，`api.minimax.cn` 是历史别名。
4. **官方认证需要 GroupId（仅国内）**：海外 Bearer Token 即可；国内账号调用时部分接口还需要 `GroupId` header（见 [linzeyang/minimax-python-client](https://github.com/linzeyang/minimax-python-client)）。
5. **第三方音色名（冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean）**：来自 MiMo TTS、小渡 API 等聚合层，**不是 MiniMax 官方音色**；直接调 MiniMax API 用这些名字会返回 `voice_id not found`。如果你的上游是某个聚合平台，先确认它把这些名字映射到了哪个官方 voice_id——否则要换成官方名字。

---

## 缺失证据

- **TPM（每分钟 token/字符数）配额**：未在官方 Rate Limits 页面找到。
- **并发上限（concurrent requests）**：未在官方页找到。
- **流式 WS 的最大分片大小、首包延迟 SLA**：未在官方页找到数字承诺。
- **speech-02-hd 和 speech-02-turbo 的音质 / MOS 客观分数差异**：仅有 Arena ELO 排名，没有官方给出的具体 SNR/MOS 数值。

---

## Sources

### 保留

- [T2A HTTP OpenAPI Reference](https://platform.minimax.io/docs/api-reference/speech-t2a-http) — endpoint、payload schema、bearerAuth 认证、OpenAPI 示例 request/response。一手。
- [T2A Async Guide](https://platform.minimax.io/docs/guides/speech-t2a-async) — 异步接口、file 上传、curl/payload 示例。一手。
- [T2A WebSocket Guide](https://platform.minimax.io/docs/api-reference/speech-t2a-websocket) — 流式端点、voice_id 选项、Python 代码片段。一手。
- [System Voice ID List (海外)](https://platform.minimax.io/docs/faq/system-voice-id) — 332 个官方音色 ID 完整列表。一手。
- [System Voice ID List (国内)](https://platform.minimaxi.com/docs/faq/system-voice-id) — 327 个官方音色 ID 完整列表（与海外版略有差异）。一手。
- [Pay-as-you-go Pricing](https://platform.minimax.io/docs/guides/pricing-paygo) — $60/$100 价格、legacy 表、计费规则。一手。
- [Rate Limits](https://platform.minimax.io/docs/guides/rate-limits) — 60 RPM / 20 RPM。一手。
- [Voice Management / Get Voice API](https://platform.minimaxi.com/docs/api-reference/voice-management-get) — 动态查询 voice_id 列表、voice_type 枚举。一手。
- [Speech 02 发布博客](https://www.minimax.io/news/minimax-speech-02) — 2025-04-02 发布日、技术架构（AR Transformer + Learnable Speaker Encoder）。一手。
- [Speech 2.8 发布博客](https://www.minimaxi.com/news/minimax-speech-28) — 2026-01-23 发布日、原生语气词、10s 克隆。**任务 URL 实际指向这里**，不是 Speech 02。一手。
- [官方示例 Python 脚本](https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/scripts/minimax_tts.py) — 官方风格同步实现。一手。

### 拒绝 / 降级

- [Vapi Speech 2 HD 实测](https://humannessindex.vapi.ai/models/minimax-speech-02-hd) — 第三方基准；与官方 schema 一致，作为延迟补充。
- [knowara.com / minimax-ai.chat / humannessindex.vapi.ai / cloudprice.net](https://knowara.com/ai-tools/voice/minimax-speech-review/) — 第三方综述/价格聚合；价格数字与官方一致，作为参考，**不作为定价主源**。
- [MiMo TTS / 小渡 API 等第三方平台](https://github.com/duolabmeng6/voice_hub/blob/main/docs/mimo-tts.md) — 第三方聚合，对 MiniMax 音色做二次别名；**不能作为官方音色名来源**。
- [fal.ai / novita.ai / replicate.com 等](https://fal.ai/models/fal-ai/minimax/speech-02-hd/api) — 第三方代理 API；URL/字段/价格均与 MiniMax 直连不同，**不可直接套用**。

---

## Next steps（给项目方）

1. **不要使用 `MIMO_API_KEY` 当作 MiniMax key**——把它 export 成 `MINIMAX_API_KEY`，然后用 [官方示例脚本](https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/scripts/minimax_tts.py) 的 `requests.post` 模板跑通。
2. **音色选择先用官方 ID**：少女 = `female-shaonv`、青年男声 = `male-qn-qingse`、新闻女声 = `Chinese (Mandarin)_News_Anchor`、抒情男声 = `Chinese (Mandarin)_Lyrical_Voice`。避开第三方别名。
3. **新项目建议直接用 `speech-2.8-hd` / `speech-2.8-turbo`**——API schema 兼容、官方不再迭代 02 家族；老项目沿用 02 也无问题。
4. **国内账号**：再追加 `GroupId` header（海外版不需要）；host 用 `api.minimaxi.com`。
5. **预算预估**：HD 价 $100/M 字符 ≈ ¥720/M 字符（按 7.2 汇率）；Turbo $60/M 字符 ≈ ¥430/M。微课脚本 5 分钟≈3000 字，单条 HD 约 ¥2.2 / Turbo 约 ¥1.3。
