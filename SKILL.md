---
name: toknife
slug: toknife-lite
displayName: Toknife Lite - Input-side Token Compression
version: "6.1-lite"
category: 效率工具 / Efficiency
tags: [AI工具, Token節省, LLM, 開源, 效率提升, token-optimizer, AI-tools, token-saving, open-source]
description: 通用 LLM「輸入端」Token 壓縮工具，支援 JSON 數值保真、Code-aware 代碼壓縮、對話歷史與工具輸出聚合，以及對任意 OpenAI 相容端點的本機透明代理（含 SSE 串流穿透）。零硬性依賴、跨平台、MIT 開源。只做輸入端；輸出端最佳化、可逆長文、自學習與 GUI 儀表板為 Pro 功能。
author: momogigi123
license: MIT
---

# Toknife Lite — 輸入端 Token 壓縮工具（開源版）
# Toknife Lite — Input-side Token Compression (Open Source)

> 中文 | [English](#english)

---

## 🇹🇼 中文

### 這是什麼
Toknife Lite 在請求送達 LLM 前壓縮**輸入**（messages），降低 token 用量。本機運行、資料不外送，核心零第三方依賴。

**能力：**
1. **JSON 數值保真壓縮**：JSON→CSV 去重複 key，數值精度保留。
2. **Code-aware 代碼壓縮**：識別代碼邊界，只精簡註釋/空白/重複行，不破壞語法。
3. **對話歷史與工具輸出聚合**：多輪歷史溢出才收斂、工具 schema/列表結構化瘦身、重複機器行摺疊。
4. **通用 OpenAI 相容透明代理**：可指向 OpenAI／DeepSeek／本機 vLLM、Ollama 等，透傳客戶端 model，**支援 SSE 串流原樣穿透**（不修改輸出）。

> 邊界：Lite **只做輸入端、固定規則、長文會截斷**。輸出端最佳化、長文 100% 可逆、自學習閉環、硬預算與視覺儀表板、一鍵 GUI 為 **Pro** 功能。

### 快速開始（代理）
```bash
# 上游用環境變數指定（也可用 --upstream/--api-key/--model）
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=sk-...
python scripts/ts_proxy_server.py --port 8001
# 相容舊式：python scripts/ts_proxy_server.py 8001
```
把客戶端 base_url 指向 `http://127.0.0.1:8001/v1` 即可。
- `GET /health`：就緒與版本（不打上游）
- `GET /stats`：本次啟動以來的**輸入端**累計節省（JSON）

### 實測怎麼看（誠實口徑）
```bash
python scripts/benchmark.py          # 離線、只計輸入端、逐場景、不取總平均
```
成效隨內容類型差異很大：代碼、密集日誌、重複資料列省幅高；短文本與一般散文會自動跳過。這是離線輸入端對比，**不是帳單承諾**，真實節省取決於內容、模型與 prompt cache。

### 環境要求
- Python 3.8+，跨平台；核心純標準庫，`tiktoken` 可選（不裝自動降級估算）。

### 許可證與致謝
MIT，可商用、需保留版權聲明。Toknife 受開源社群專案啟發（Caveman、Ponytail、RTK），特此致謝。
作者 momogigi123 — https://github.com/momogigi123/toknife

---

## 🇬🇧 English

### What it is
Toknife Lite compresses the **input** (messages) before they reach an LLM, cutting token use. It runs locally, sends nothing to third parties, and its core uses the standard library only.

**Capabilities:**
1. **Lossless-numeric JSON compression** (JSON→CSV, repeated keys removed, numbers preserved).
2. **Code-aware compression** (comments/whitespace/duplicate lines trimmed, syntax intact).
3. **Conversation-history and tool-output aggregation** (overflow-only history compaction, tool schema slimming, repeated machine-line folding).
4. **Generic OpenAI-compatible transparent proxy** for OpenAI / DeepSeek / local vLLM, Ollama, etc.; passes the client `model` through and relays **SSE streaming untouched** (it never edits output).

> Boundary: Lite is **input-only, fixed-rule, and truncates very long text**. Output-side optimization, 100%-reversible long context, a self-learning loop, hard budget caps, a visual dashboard and the one-click GUI are **Pro** features.

### Quick start (proxy)
```bash
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=sk-...
python scripts/ts_proxy_server.py --port 8001
```
Point your client's base_url to `http://127.0.0.1:8001/v1`. Endpoints: `GET /health`, `GET /stats` (cumulative **input** savings).

### Benchmarks (honest scope)
`python scripts/benchmark.py` — offline, input-only, per-scene, no cross-scene average. Gains vary a lot by content: code, dense logs and repeated rows compress well; short text and prose are skipped. It is an offline input comparison, **not a billing promise**.

### Requirements
Python 3.8+, cross-platform; standard-library core, optional `tiktoken`.

### License & acknowledgments
MIT (commercial use allowed, keep the notice). Inspired by open-source projects Caveman, Ponytail and RTK — thank you.
By momogigi123 — https://github.com/momogigi123/toknife
