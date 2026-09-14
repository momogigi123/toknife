# Toknife Lite — Input-side Token Compression (Open Source)
# Toknife Lite — 輸入端 Token 壓縮工具（開源版）

![license](https://img.shields.io/badge/license-MIT-green) ![python](https://img.shields.io/badge/python-3.8%2B-blue)

> English | [中文](#-中文)

---

## 🇬🇧 English

### What it is
Toknife Lite compresses the **input** (messages) before they reach an LLM, cutting token use and API cost. It runs locally, traffic stays between your machine and the model, and the core has **zero third-party dependencies** (standard library only; `tiktoken` is optional).

**Four capabilities**
1. **Lossless-numeric JSON compression** (JSON→CSV, repeated keys removed, numbers preserved).
2. **Code-aware multi-language compression** (comments/whitespace/duplicate lines trimmed, syntax intact).
3. **History / tool-output aggregation** (overflow-only history compaction, tool-schema slimming, repeated machine-line folding for CSV/logs/rows).
4. **Generic OpenAI-compatible transparent proxy** for OpenAI, DeepSeek, local vLLM/Ollama, etc.; passes the client `model` through and relays **SSE streaming untouched**.

> **Boundary (honest):** Lite is **input-only**, uses **fixed rules**, and **truncates** very long text.
> Output-side optimization, 100%-reversible long context with auto-rollback, a self-learning loop, hard budget caps, a visual dashboard and the one-click GUI belong to the commercial **Pro** edition. See the [website](https://momogigi123.github.io/toknife/#pricing).

### Install
```bash
git clone https://github.com/momogigi123/toknife.git
cd toknife
pip install -e .                 # optional: adds the ts / toknife-lite commands
pip install -e ".[tiktoken]"     # optional: exact token counting
```

### Quick start (transparent proxy)
```bash
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=sk-...
python scripts/ts_proxy_server.py --port 8001
```
Point your client's `base_url` to `http://127.0.0.1:8001/v1`. With no local key it forwards the client's `Authorization`; with no `--model` it passes the client model through. Endpoints: `POST /v1/chat/completions`, `GET /v1/models`, `GET /health`, `GET /stats`. Streaming responses are relayed byte-for-byte; Lite never edits output.

CLI flags: `--upstream`, `--api-key`, `--model`, `--host`, `--port` (a bare positional port also works, e.g. `python scripts/ts_proxy_server.py 8001`).

#### Python API
```python
import sys; sys.path.insert(0, "scripts")
from json_compressor import compress_json_light
from code_context_extractor import compress_code_light
from compress_history import auto_compact
```

#### CLI
```bash
ts benchmark          # offline input-side benchmark (no API key)
ts verify             # run bundled verification scripts
ts compress input.json
ts code mycode.py --mode light
```

### Benchmarks (offline, input-only, per-scene)
Run `python scripts/benchmark.py` (tiktoken cl100k_base, reproducible).

| Scenario | Before | After | Input saved | Method |
|---|---:|---:|---:|---|
| Raw data table | 914 | 92 | **89.9%** | repeated-line fold |
| Dense logs | 1957 | 93 | **95.2%** | repeated-line fold |
| Agent tool return | 445 | 57 | **87.2%** | repeated-line fold |
| Real code review | 637 | 162 | **74.6%** | code-aware |
| Long-form QA / summary / plan / email / prose / short QA | — | unchanged | 0.0% | skipped on purpose |

**How to read this:** 4 of 10 scenarios compress (**74.6%–95.2%**), all of them machine-generated repetitive content (code, logs, rows, tool returns). Ordinary prose and short text are deliberately left untouched (0%) — rewriting natural language would change meaning, and Lite won't do that. We intentionally report **no cross-scene average**. This is an offline input-side comparison, **not a billing promise**; real savings depend on your content, model and prompt-cache hits.

### Lite vs Pro
| Capability | Lite (MIT) | Pro (subscription) |
|---|:--:|:--:|
| Input compression (JSON/code/history/tool output) | ✅ | ✅ |
| Generic OpenAI-compatible proxy, SSE passthrough | ✅ | ✅ |
| **Output-side** optimization | ❌ | ✅ |
| 100%-reversible long context + auto-rollback | ❌ (truncates) | ✅ |
| Self-learning / adaptive loop | ❌ | ✅ |
| Hard budget caps, visual dashboard, one-click GUI | ❌ | ✅ |
| Multi-device license & team support | ❌ | ✅ |

Pro is subscription-only (Pro monthly/yearly, Team yearly): see the [pricing page](https://momogigi123.github.io/toknife/#pricing).

### Honest notes
- Lite truncates very long text (>2000 chars) and marks the cut point; use Pro for 100%-restorable long context.
- Advanced capabilities intentionally removed: full adaptive loop, reversible externalization, output-side optimization, the learning engine, signal-driven scheduling.
- Short text (under ~300 chars) is skipped by default, so the fixed overhead of compression never adds tokens.

### Acknowledgments
Toknife is inspired by open-source projects including **Caveman, Ponytail and RTK**. Thank you to their authors and to the open-source community.

### License
MIT — free and commercial use allowed, keep the copyright notice. By momogigi123.

---

## 🇹🇼 中文

### 這是什麼
Toknife Lite 在請求送達 LLM **之前**壓縮輸入（messages），降低 token 用量與 API 成本。它在你本機運行，請求只在你的機器與模型之間流動；核心**零第三方依賴**（純 Python 標準庫，`tiktoken` 為可選）。

**四項能力**
1. **JSON 數值保真壓縮**：JSON→CSV、去除重複 key，數值精度保留。
2. **Code-aware 多語言代碼壓縮**：識別代碼邊界，只精簡註釋、空白與重複行，不破壞語法。
3. **對話歷史 / 工具輸出聚合**：歷史只在溢出時收斂；工具 schema 結構化瘦身；重複的機器行（CSV、日誌、資料列）摺疊。
4. **通用 OpenAI 相容透明代理**：可指向 OpenAI、DeepSeek、本機 vLLM / Ollama 等任意相容端點，透傳客戶端 `model`，並**原樣穿透 SSE 串流**（不修改輸出）。

> **邊界（誠實說明）**：Lite 只做**輸入端**、使用**固定規則**，超長文本採**損耗性截斷**。
> 輸出端最佳化、長文 100% 可逆外部化與自動回滾、自學習閉環、硬預算上限、視覺儀表板與一鍵 GUI，屬於商業 **Pro** 版。兩者比較見[官網](https://momogigi123.github.io/toknife/#pricing)。

### 安裝
```bash
git clone https://github.com/momogigi123/toknife.git
cd toknife
pip install -e .                 # 可選：安裝後得到 ts / toknife-lite 命令
pip install -e ".[tiktoken]"     # 想精確計 token 才需要
```

### 快速開始（透明代理）
```bash
export OPENAI_BASE_URL=https://api.openai.com/v1     # 或 DeepSeek / 本機端點
export OPENAI_API_KEY=sk-...
python scripts/ts_proxy_server.py --port 8001
# 相容舊式位置參數：python scripts/ts_proxy_server.py 8001
```
把客戶端的 `base_url` 指向 `http://127.0.0.1:8001/v1` 即可，客戶端代碼不用改。
- 不設定金鑰時，代理會**原樣轉發客戶端的 Authorization 標頭**。
- 不指定 `--model` 時，**透傳客戶端送來的 model**。
- 端點：`POST /v1/chat/completions`、`GET /v1/models`、`GET /health`、`GET /stats`。
- `stream: true` 時 SSE 原樣回傳，Lite 不會改動任何輸出 token。

命令列參數：`--upstream`、`--api-key`、`--model`、`--host`、`--port`。

#### Python 函式
```python
import sys; sys.path.insert(0, "scripts")
from json_compressor import compress_json_light
from code_context_extractor import compress_code_light
from compress_history import auto_compact
```

#### CLI
```bash
ts benchmark          # 離線輸入端基準（不需 API key）
ts verify             # 跑自帶驗證腳本
ts compress input.json
ts code mycode.py --mode light
```

### 實測數據（離線、輸入端、逐場景）
指令：`python scripts/benchmark.py`（tiktoken cl100k_base 精確計數，可自行複現）。

| 場景 | 壓縮前 tok | 壓縮後 tok | 輸入省率 | 方法 |
|---|---:|---:|---:|---|
| 數據分析（原始表） | 914 | 92 | **89.9%** | 重複行摺疊 |
| 日誌分析（密集日誌） | 1957 | 93 | **95.2%** | 重複行摺疊 |
| Agent 迴圈（工具回傳） | 445 | 57 | **87.2%** | 重複行摺疊 |
| 代碼審查（真實長碼） | 637 | 162 | **74.6%** | code-aware |
| QA 長問答 | 164 | 164 | 0.0% | 不壓（保真） |
| 摘要長文 | 2057 | 2057 | 0.0% | 不壓（保真） |
| 計畫生成 / 郵件寫作 | 109 / 124 | 不變 | 0.0% | 不壓（保真） |
| 長文對照 / 短問答 | 2159 / 26 | 不變 | 0.0% | 不壓（保真） |

**怎麼讀這張表（重要）**
- 有壓縮的是 **4/10** 場景，區間 **74.6%–95.2%**，集中在**機器產生的重複內容**（代碼、日誌、資料列、工具回傳）。
- 一般散文、短文本刻意**不壓**（0%）——這是保真立場，不是缺陷：改寫自然語言會改變語義，Lite 不做這件事。
- **刻意不提供「跨場景平均」**，因為平均值會用大量 0% 稀壓縮場景稀釋、也會用高壓縮場景灌水，對你沒有參考意義。
- 這是**離線輸入端**對比，**不是帳單承諾**；真實節省取決於你的內容類型、模型與 prompt cache 命中。

### 開源 Lite 與商業 Pro 的差異
| 能力 | Lite（MIT 開源） | Pro（訂閱） |
|---|:--:|:--:|
| 輸入端壓縮（JSON/代碼/歷史/工具輸出） | ✅ | ✅ |
| 通用 OpenAI 相容代理、SSE 穿透 | ✅ | ✅ |
| **輸出端**最佳化（精簡冗長輸出） | ❌ | ✅ |
| 長文 100% 可逆外部化＋自動回滾 | ❌（截斷） | ✅ |
| 自學習閉環／自適應規則 | ❌ | ✅ |
| 硬預算上限、視覺儀表板、一鍵 GUI | ❌ | ✅ |
| 多裝置授權與團隊支援 | ❌ | ✅ |

Pro 採訂閱制（Pro 月繳 / 年繳、Team 年繳），詳見[官網價格頁](https://momogigi123.github.io/toknife/#pricing)。

### 誠實說明
- Lite 長文本（>2000 字元）採基礎截斷，會在原文標註截斷位置；需要 100% 可還原請用 Pro。
- 已移除的進階能力：全鏈路自適應閉環、可逆外部化、輸出端最佳化、學習引擎、信號驅動調度。
- 短文本（約 <300 字元）預設跳過，避免壓縮本身的固定開關反而增加 token。

### 致謝
Toknife 受開源社群專案啟發，包含 **Caveman、Ponytail、RTK**，感謝這些作者對開源生態的貢獻。我們站在社群的肩膀上，也歡迎回饋。

### 許可證
MIT License：開源免費、可商用，需保留版權聲明。作者 momogigi123。
