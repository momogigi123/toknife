# toknife 5.1.1 — Release Notes / 發布說明

> Open-source release. toknife is a lightweight, zero-dependency LLM context token compression toolkit.
> 開源發布版。toknife 是一個輕量、零依賴的 LLM 上下文 Token 壓縮工具集。

---

## Highlights / 本次更新重點

### 1. Bug Fix: Low compression on log / structured numeric text / Bug 修復：日誌 / 結構化數字密集文本壓縮率異常偏低

- **Root cause / 根因**: The digit-keyline filter preserved every line containing digits (log lines all have timestamps → all kept), filling the key-line quota. When compressed length ≥ original, the "no-gain fallback" triggered, resulting in 0% compression on some log samples.
  digit-keyline 過濾器對「含數字」行一律保留（日誌每行都有時間戳→全留），導致關鍵行配額被撐滿，壓縮後長度≥原文而觸發「無收益退回」，部分日誌樣本壓縮率為 0%。
- **Fix / 修法**: Detect "structured record / log" type → enforce line budget cap (40% of total lines, minimum 6), ensuring key-line extraction always yields net compression. Non-structured text (e.g. few-shot narrative) is unaffected.
  偵測「結構化紀錄 / 日誌」類型→強制行預算上限（總行數 × 40%，最少 6 行），確保關鍵行提取必定產生淨壓縮。非結構化文本（如 few-shot 敘事）不觸發，保持原有行為。
- **Measured comparison / 實測對比** (same test set, N=30/category):

| Category / 類別 | Before / 修復前 | After / 修復後 |
|---|---:|---:|
| **log** | Some samples 0% / 部分樣本 0% | **~83%** ✅ |
| code | ~85% | ~85% |
| json | 27.2% | 27.2% (value-preserving / 保值設計) |
| prose | 0.0% | 0.0% (<2000 chars skipped / <2000 字跳過) |

### 2. Feature Modules / 功能模組

This version includes the following core capabilities:
本版本包含以下核心能力：

- `ts_proxy_server.py` — OpenAI-compatible proxy endpoint, auto-compresses user content before forwarding / OpenAI 相容代理端點，user content 自動壓縮後轉發
- `mcp_proxy.py` — MCP transparent proxy, intercepts & compresses tool returns / MCP 透明代理，攔截工具回傳壓縮
- `keyline_extractor.py` — Long-text key-line extraction (CJK language-aware, query-aware question line preservation) / 長文本關鍵行提取（CJK 語言感知、query-aware 問題行保留）
- `json_compressor.py` — JSON→CSV lightweight compression (value-preserving) / JSON→CSV 輕量壓縮（保值，值全留）
- `code_compressor.py` / `code_context_extractor.py` — Code context extraction & lightweight compression / 代碼上下文提取與輕量壓縮
- `conversation_compressor.py` — Conversation history compression (speaker merge, long-message fold, duplicate detection) / 對話歷史壓縮（說話人合併、長消息折疊、重複檢測）
- `compress_history.py` — Batch conversation history compression (keep recent N rounds) / 對話歷史批量壓縮（保留最近 N 輪）
- `multimodal_compressor.py` — Multimodal image info summary (zero-dependency header parsing) / 多模態圖片資訊摘要（零依賴讀檔頭）
- `token_router.py` / `token_budget.py` — Dynamic scheduling & budget allocation / 動態調度與預算分配
- `quality_metrics.py` — Compression quality deterministic metrics (Top-N hit / anomaly recall) / 壓縮品質確定性指標（Top-N 命中、異常召回）
- `cli.py` — Unified CLI entry (compress / report / agg / code / verify) / 統一 CLI 入口

### 3. Verification & Benchmarks / 驗證與基準

- `verify_code_v51.py` / `verify_v52.py` / `verify_code_v53.py` / `verify_code_v55.py` / `verify_json_v56.py` — Zero-API deterministic unit tests, all PASS = healthy / 零 API 確定性單測，全 PASS 即為正常
- `benchmark.py` — 10-task standard benchmark, tiktoken precise counting, no API key needed / 10 任務標準化基準，tiktoken 精確計數，免 API key
- `repro.py` — Self-contained reproduction, 3-scenario A/B (single-turn / tool / multi-turn) / 自包含複現，三場景 A/B 對比
- `tests/` — pytest deterministic test suite / pytest 確定性測試套件

---

## Package Contents / 開源包內容清單

```
toknife-v5.1.1/
├── SKILL.md
├── README.md
├── product-intro.md
├── RELEASE-NOTES.md
├── .gitignore
├── install.sh
├── requirements.txt
├── pyproject.toml
├── scripts/        (core engine + automation scripts / 核心引擎 + 自動化腳本)
├── modules/        (core / trimmer submodules / 子模組)
├── rules/
├── tests/
├── references/     (usage / integration / token reference / 使用與整合指南)
└── examples/       (plan_execute / semantic_cache demo)
```

---

## Version Info / 版本號說明

- **Release version / 對外發布號**: `toknife 5.1.x`
- **Python / Python 版本**: 3.7+, zero mandatory dependencies (tiktoken optional for precise counting / 零強制依賴，tiktoken 可選用於精確計數)
- **License / 授權**: MIT

## Brand / 品牌

- **Project / 項目名**: **toknife**
- **Author / 作者**: momomogigigi
- **Repository / 倉庫**: https://github.com/momomogigigi/token-saver
