# toknife 5.1.1

> **Lightweight, zero-dependency LLM context token compression toolkit — compress the input, not the answer.**
> **輕量、零依賴的 LLM 上下文 Token 壓縮工具集——壓縮輸入，不壓縮答案。**

---

## Why toknife / 為什麼選擇 toknife

### Measured Performance / 實測性能（34 samples, tiktoken cl100k_base exact count）

| Scenario / 場景 | Samples / 樣本 | Compression / 壓縮率 | Speed / 速度 | Method / 方式 |
|---|:---:|:---:|:---:|---|
| **Overall / 整體** | 34 | **66.3%** | **1.2ms** | auto-route / 自動路由 |
| JSON / API 回傳 | 8 | 47.9% | 1.2ms | JSON→CSV (value-preserving / 值全留) |
| Code / 代碼 | 8 | **77.8%** | 1.9ms | key-line + signature fold / 關鍵行+簽名折疊 |
| Conversation / 對話 | 6 | 30.8% | 0.2ms | speaker merge + fold / 說話人合併 |
| Log / 日誌 | 6 | **89.7%** | 1.7ms | structured key-line / 結構化關鍵行 |
| Prose / 散文 | 6 | 59.0% | 1.0ms | key-line extraction / 關鍵行提取 |

> **Honest note / 誠實說明**: Compression ratio varies by content type. Logs and code compress best; short conversations and small JSON have less room. These are measured results, not vendor claims — reproduce with `python scripts/benchmark.py`.
> 壓縮率因內容類型而異。日誌和代碼壓縮效果最好；短對話和小 JSON 空間有限。以上為實測數據，非廠商宣稱——可執行 `python scripts/benchmark.py` 複現。

**Raw token savings / 實測節省量**: 97,747 → 32,903 tokens across 34 samples = **64,844 tokens saved** (66.3%). At GPT-4o input pricing ($2.50/1M tokens), that's ~$0.16 saved per 34 tasks — scales to **$4.70 per 1,000 tasks**.
**原始 token 節省量**：34 個樣本共 97,747 → 32,903 tokens = **節省 64,844 tokens**（66.3%）。以 GPT-4o 輸入價格（$2.50/百萬 tokens）計算，每 34 任務省 ~$0.16——每 1,000 任務省 **$4.70**。

### What kind of tool is this / 這是什麼類型的工具

toknife is an **input-side compression** tool. It compresses what you *send to* the LLM (system prompts, tool returns, conversation history, logs, code) — not what the LLM *outputs*. This is fundamentally different from output-style tools like caveman or ponytail, which change how the LLM writes its answer.

toknife 是**輸入側壓縮**工具。它壓縮的是你*送進* LLM 的內容（系統提示詞、工具回傳、對話歷史、日誌、代碼），而不是 LLM 的*輸出*。這與 caveman、ponytail 等輸出側工具（改變 LLM 回答風格）有本質區別。

| Type / 類型 | Compresses / 壓縮對象 | Needs LLM call? / 需要 LLM 調用? | toknife? |
|---|---|:---:|:---:|
| **Input compression / 輸入壓縮** | Context sent to LLM / 送進 LLM 的上下文 | No / 否 | ✅ |
| Output compression / 輸出壓縮 | LLM's reply / LLM 的回答 | Yes / 是 | ❌ (caveman, ponytail) |
| Caching / 快取 | Repeated prompts / 重複提示 | No / 否 | Partial / 部分 |

**Why this matters / 為什麼重要**: Input tokens are usually the bigger cost in agent workflows (tool returns, long context, multi-round history). Compressing input gives you the **same answer quality** because the LLM still sees the key information — just in fewer tokens. Output compression trades answer detail for brevity; input compression does not.
**為什麼重要**：在 Agent 工作流中，輸入 token 通常是更大的成本（工具回傳、長上下文、多輪歷史）。壓縮輸入能獲得**相同的答案品質**，因為 LLM 仍然看到關鍵資訊——只是用更少的 token。輸出壓縮是以答案細節換簡潔，輸入壓縮則不會。

### Why large-model users benefit most / 為什麼大模型用戶最需要

| Model tier / 模型級別 | Input price / 輸入價格 | Savings per 1K tasks / 每千任務節省 |
|---|---|---|
| GPT-4o / Claude 3.5 | $2.50–$3 / 1M | **$4.70–$5.60** |
| GPT-4o-mini / Haiku | $0.15–$0.25 / 1M | $0.28–$0.47 |
| DeepSeek / Qwen (cheap) | $0.07–$0.14 / 1M | $0.13–$0.26 |

> **Honest note / 誠實說明**: The more expensive your model, the more you save. For cheap models, the savings are smaller but the 1.2ms overhead is negligible. toknife is most impactful for teams running GPT-4o/Claude at scale, or anyone with long tool returns / conversation history.
> 模型越貴，省越多。對於便宜模型，節省較少但 1.2ms 的開銷可忽略。toknife 對大規模使用 GPT-4o/Claude 的團隊，或有長工具回傳/對話歷史的用戶效果最顯著。

### Universal Compatibility / 全平台通用

| Dimension / 維度 | Support / 支援 |
|---|---|
| **Models / 模型** | Any OpenAI-compatible API — GPT, Claude, Gemini, DeepSeek, Qwen, Doubao, local Ollama / 任意 OpenAI 相容 API |
| **Platforms / 平台** | Windows, macOS, Linux — pure Python, no OS-specific code / 純 Python，無作業系統特定程式碼 |
| **Languages / 語言** | CJK-aware (中文/日本語/한국어) + English — auto-detects and preserves question lines / 自動偵測語言，保留問題行 |
| **Integration / 整合方式** | CLI, Python function call, MCP proxy, OpenAI-compatible proxy server / CLI、Python 函數、MCP 代理、OpenAI 相容代理 |
| **Dependencies / 依賴** | **Zero mandatory** — tiktoken optional for exact counting, auto-falls-back to `len//3` / 零強制依賴 |
| **Python / 版本** | 3.7+ |

### Core Features / 核心特性

- **Zero-dependency core** — 13+ scripts run on Python standard library alone / 13+ 核心腳本僅需 Python 標準庫
- **OpenAI-compatible proxy** — drop-in replacement, auto-compresses user content before forwarding / 開箱即用代理，自動壓縮後轉發
- **MCP transparent proxy** — intercepts tool returns, compresses, supports `read_more` rollback / 攔截工具回傳壓縮，支援 read_more 回溯
- **Value-preserving JSON** — JSON→CSV keeps all values, 100% restorable / JSON→CSV 保留所有值，可完全還原
- **Query-aware extraction** — never drops question/instruction lines (fixes "model can't see the question" bug) / 永不丟棄問題/指令行
- **Deterministic verification** — 5 zero-API test suites, all PASS = healthy / 5 套零 API 確定性測試
- **No LLM call needed** — compression is pure rule-based, no API cost / 壓縮為純規則，無 API 調用成本
- **Short-text guard** — texts under 300 chars skip compression to avoid net cost / 短於 300 字自動跳過，避免淨成本

---

## Quick Start / 快速開始

### 1. Install / 安裝

```bash
git clone https://github.com/momomogigigi/token-saver.git
cd token-saver
```

Core functionality has **zero dependencies**. For precise token counting:
核心功能**零依賴**，直接可用。如需精確 Token 計數：

```bash
pip install tiktoken
```

### 2. Verify / 驗證安裝

```bash
# Deterministic verification (zero API, all PASS = healthy)
# 確定性驗證（零 API，全 PASS 即為正常）
python scripts/verify_code_v53.py
python scripts/verify_v52.py
python scripts/verify_code_v51.py

# Standard benchmark (no API key / GPU needed, 10-task A/B)
# 標準化基準（免 API key/GPU，10 任務 A/B 對比）
python scripts/benchmark.py

# Self-contained reproduction (3 scenarios: single-turn / tool / multi-turn)
# 自包含複現（三場景：單輪 / 工具 / 多輪）
python scripts/repro.py all
```

---

## Core Scripts / 核心腳本（零依賴）

| Script / 腳本 | Function / 功能 | Usage / 用法 |
|---|---|---|
| `ts_proxy_server.py` | OpenAI-compatible proxy, auto-compresses user content / OpenAI 相容代理，自動壓縮 user content | `python scripts/ts_proxy_server.py` |
| `mcp_proxy.py` | MCP transparent proxy, intercepts & compresses tool returns / MCP 透明代理，攔截工具回傳壓縮 | `python scripts/mcp_proxy.py --downstream "python my_server.py" --min-tokens 2000` |
| `keyline_extractor.py` | Key-line extraction from long text (CJK-aware, query-aware) / 長文本關鍵行提取（CJK 語言感知、query-aware） | Function call / 函數調用 |
| `json_compressor.py` | JSON→CSV lightweight compression (value-preserving) / JSON→CSV 輕量壓縮（保值） | Function call / 函數調用 |
| `code_compressor.py` | Code compression (signature + light fold) / 代碼壓縮（簽名 + 輕量折疊） | Function call / 函數調用 |
| `code_context_extractor.py` | Code context extraction / 代碼上下文提取 | `python scripts/code_context_extractor.py mycode.py --light` |
| `conversation_compressor.py` | Conversation compression (speaker merge, long-message fold) / 對話壓縮（說話人合併、長消息折疊） | Function call / 函數調用 |
| `compress_history.py` | Batch conversation history compression / 對話歷史批量壓縮 | `python scripts/compress_history.py chat.json 3` |
| `compress_report.py` | Savings report (original → compressed, ratio) / 節約量報告 | `echo "<text>" \| python scripts/compress_report.py -` |
| `aggregate_tool_output.py` | Tool output aggregation (stats + anomalies + Top-N) / 工具輸出聚合（統計+異常+Top N） | `python scripts/aggregate_tool_output.py data.json col1,col2 metric1 5` |
| `adaptive_aggregator.py` | Adaptive aggregation (granularity by LLM citation) / 自適應聚合 | Function call / 函數調用 |
| `incremental_compressor.py` | Incremental compression (long-conversation state snapshot) / 增量壓縮（長對話狀態快照） | Function call / 函數調用 |
| `token_router.py` | Dynamic scheduler, optimization strategy by task type / 動態調度器，依任務類型出優化策略 | `python scripts/token_router.py data_analysis --tool-lines 100` |
| `token_budget.py` | Token budget allocation & monitoring / Token 預算分配與監控 | Function call / 函數調用 |
| `audit_system_prompt.py` | System prompt redundancy audit / System Prompt 冗餘審計 | `python scripts/audit_system_prompt.py prompt.md` |
| `multimodal_compressor.py` | Multimodal image summary (zero-dep header parse) / 多模態圖片資訊摘要（零依賴讀檔頭） | `python scripts/multimodal_compressor.py image.png` |
| `quality_metrics.py` | Compression quality deterministic metrics (Top-N hit / anomaly recall) / 壓縮品質確定性指標 | `python scripts/quality_metrics.py data.json --sort-by price --top-n 5` |
| `retry_attributor.py` | Retry cause attribution (compression-induced vs other) / 重試原因歸因 | Function call / 函數調用 |
| `pareto_optimizer.py` | Pareto parameter optimization / 帕累托參數優化 | Function call / 函數調用 |
| `cli.py` | Unified CLI entry (compress/report/agg/code/verify) / 統一 CLI 入口 | `python scripts/cli.py --help` |

## Benchmarks & Verification / 基準與驗證

| Script / 腳本 | Function / 功能 |
|---|---|
| `benchmark.py` | 10-task standard benchmark, tiktoken precise counting / 10 任務標準化基準 |
| `repro.py` | Self-contained reproduction, 3-scenario A/B / 自包含複現，三場景 A/B |
| `verify_code_v51.py` | v5.1 code fix deterministic verification / v5.1 代碼修復確定性驗證 |
| `verify_v52.py` | v5.2 three-mechanism deterministic verification / v5.2 三機制確定性驗證 |
| `verify_code_v53.py` | v5.3 three-landing deterministic verification / v5.3 三落地確定性驗證 |
| `benchmark_llm.py` | Real LLM empirical benchmark (API key required) / 真實 LLM 實證基準（需 API key） |

---

## Usage Examples / 使用示例

### Dynamic Routing / 動態調度

```python
import sys
sys.path.insert(0, "scripts")
from token_router import optimize

strategy = optimize("data_analysis", {"tool_return_lines": 200})
print(strategy)
```

### Code Light Compression / 代碼輕量壓縮

```bash
python scripts/code_context_extractor.py myproject/ --light
```

### Compression Report / 節約量報告

```bash
echo "Your long text here..." | python scripts/compress_report.py -
```

---

## Always-On Setup / 常態運行設置

You don't need to call toknife manually every time. Three ways to run it always-on:
不需要每次手動調用 toknife。三種常態運行方式：

### Option A: OpenAI-Compatible Proxy (easiest) / 方案 A：OpenAI 相容代理（最簡單）

Point your LLM client at `http://localhost:8001/v1` instead of the real API. toknife auto-compresses all user content before forwarding.
把你的 LLM 客戶端指向 `http://localhost:8001/v1` 而非真實 API。toknife 會在轉發前自動壓縮所有 user 內容。

```bash
# Set your real API key and endpoint
export EX_LLM_KEY="your-api-key"
export EX_LLM_BASE="https://api.openai.com/v1"  # or any OpenAI-compatible endpoint

# Start the proxy
python scripts/ts_proxy_server.py 8001
```

Then use `http://localhost:8001/v1` as your API base. Zero code changes.
然後用 `http://localhost:8001/v1` 作為 API 位址。無需修改代碼。

### Option B: MCP Proxy / 方案 B：MCP 代理

If you use MCP tools, wrap your MCP server with toknife's proxy. Large tool returns are auto-compressed with `read_more` rollback.
如果你使用 MCP 工具，用 toknife 代理包裹你的 MCP 服務器。大工具回傳自動壓縮，支援 `read_more` 回溯。

```bash
python scripts/mcp_proxy.py --downstream "python your_mcp_server.py" --min-tokens 2000
```

### Option C: Always-On Snippet (for chat UI) / 方案 C：常駐片段（聊天介面用）

Paste this into your platform's Custom Instructions / System Prompt. Works for any chat UI (ChatGPT, Claude, Doubao, etc.).
把以下內容貼到平台的自訂指令/系統提示詞。適用任何聊天介面。

**English (91 tokens)**:
```
[Token Saver Rules] Apply to every task:
- Conclusion first, details after; lists over prose; no greetings or filler
- Do not restate content/context already in the conversation
- Filter or aggregate tool/retrieval outputs before context; keep only necessary fields
- Cap output length (default <=300 words unless task requires more)
- Batch what can be done in one call
```

**繁體中文 (179 tokens)**:
```
【Token Saver 常駐規範】所有任務一律套用：
- 先結論後細節，列表優於散文，不寫開場白與客套
- 不重述對話中已出現的內容與背景
- 工具/檢索回傳進上下文前先過濾或聚合，只留必要欄位
- 輸出設定長度上限（預設≤300字，任務另有要求除外）
- 能一次完成的批次化，不拆多次呼叫
```

> **Break-even / 回本點**: The snippet costs ~91-179 tokens. Any task with >340 input tokens pays back in one run.
> 片段成本約 91-179 tokens。任何輸入 >340 tokens 的任務一次就回本。

---

## FAQ / 常見問題

**Q: `ModuleNotFoundError: No module named 'token_router'`**
A: All scripts with local imports have built-in path bootstrapping and run from any directory. If using as function calls, add `sys.path.insert(0, "scripts")`.
所有有本地導入的腳本已內建路徑自舉，從任意目錄運行均可。若以函數調用方式使用，請加 `sys.path.insert(0, "scripts")`。

**Q: `ModuleNotFoundError: No module named 'tiktoken'`**
A: tiktoken is optional. Without it, falls back to `len(text)//3` estimation. For precise counting: `pip install tiktoken`.
tiktoken 是可選依賴，不安裝時自動用 `len(text)//3` 粗略估算。如需精確計數：`pip install tiktoken`。

---

## Enterprise & Advanced Version / 企業版與高階版本

This open-source version covers core input compression. For teams and users needing more, an advanced version is under active development with:
本開源版涵蓋核心輸入壓縮。對於有更多需求的團隊和用戶，高階版本正在持續開發中，包含：

- **Reversible compression / 可逆壓縮** — offload long text to side storage with `[ext ref]` markers, 100% restorable on demand. Achieves 90%+ on logs while keeping full information accessible. / 長文本外部化存儲，附 `[ext ref]` 標記，可按需 100% 還原。日誌壓縮率達 90%+ 同時保留完整資訊。
- **Adaptive closed-loop / 自適應閉環** — the system learns from LLM citation patterns and automatically adjusts compression granularity per task type. Gets more accurate the more you use it. / 系統從 LLM 引用模式中學習，按任務類型自動調整壓縮粒度。越用越準。
- **Token monitoring & budgeting / Token 監控與預算** — real-time usage tracking, per-task cost attribution, hard budget enforcement. / 即時用量追蹤、按任務成本歸因、硬預算執行。
- **Priority support & custom integration / 優先支援與定制整合** — for enterprise deployments. / 企業部署優先技術支援。

**For enterprise inquiries, custom integration, or early access to the advanced version / 企業諮詢、定制整合或高階版本優先體驗**: contact the author via GitHub or open an issue labeled `enterprise`.
透過 GitHub 聯繫作者，或開一個標記為 `enterprise` 的 issue。

---

## Author / 作者

- **Project / 項目**: toknife
- **Author / 作者**: momomogigigi
- **Repository / 倉庫**: https://github.com/momomogigigi/token-saver
- **License / 授權**: MIT
