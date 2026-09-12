# Toknife - 通用 Token 壓縮工具（開源版）
# Toknife - Universal Token Compression Tool (Open Source Lite)

> 中文 | [English](#english)

---

## 🇹🇼 中文

### 這是什麼

Toknife 是一個通用的 LLM 輸入端 Token 壓縮工具集，幫你在調用大語言模型 API 時節省輸入 Token，從而降低成本。

**三大核心功能：**

1. **JSON 數值保真壓縮** — JSON→CSV 去 key 名，數值精度 100% 保留
2. **Code-aware 多語言代碼壓縮** — 自動識別代碼邊界，只壓縮註釋/空白，不破壞語法
3. **MCP/API 透明代理** — 對 LLM API 完全透明，無需修改客戶端代碼，改 base_url 即自動壓縮

### 快速開始

#### 方式一：透明代理（最簡單）

```bash
python scripts/ts_proxy_server.py 8001
```

把 LLM 客戶端的 base_url 指向 `http://localhost:8001/v1`，所有請求自動壓縮。

#### 方式二：Python 函數調用

```python
import sys
sys.path.insert(0, "scripts")

# JSON 壓縮
from json_compressor import compress_json_light
data = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
compressed = compress_json_light(data)
print(compressed)  # name,age\nAlice,30\nBob,25

# 代碼壓縮
from code_context_extractor import compress_code_light
compressed_code = compress_code_light("mycode.py")

# 動態調度
from token_router import optimize
strategy = optimize("data_analysis", {"tool_return_lines": 200})
```

#### 方式三：CLI 命令行

```bash
# 壓縮文件
python scripts/cli.py compress input.json

# 壓縮並顯示節約量
echo "大段文本" | python scripts/compress_report.py -

# 代碼壓縮
python scripts/cli.py code mycode.py --mode light
```

### 環境要求

- Python 3.7+，跨平台（Windows/macOS/Linux）
- **零第三方依賴**（核心全標準庫）
- `tiktoken` 可選（精確計數，未裝自動降級）

### 適用場景

✅ JSON 數據傳遞｜✅ 代碼文件傳遞｜✅ 多輪對話歷史｜✅ 工具輸出聚合｜✅ Agent 迴圈｜✅ 日誌分析

❌ 短文本（<200 token，自動跳過）｜❌ 需要精確原文引用的場景｜❌ 高度敏感數據

### 誠實說明

- 本版為開源 Lite 版，長文本（>2000字元）用基礎截斷，需要 100% 可還原請用商業版
- 已移除專利相關進階功能（全鏈路閉環、可逆外部化、自適應聚合、輸出端優化、學習引擎、信號驅動調度）
- 短文本自動跳過，避免壓縮開銷大於收益

### 許可證

MIT License — 開源免費，可商用，需保留版權聲明。

### 作者

momogigi123 — GitHub: https://github.com/momogigi123

---

## 🇬🇧 English

### What is this

Toknife is a universal LLM input-side Token compression toolkit that helps you save input tokens when calling large language model APIs, thereby reducing costs.

**Three Core Features:**

1. **JSON Lossless Numeric Compression** — JSON→CSV removes key names, 100% numeric precision preserved
2. **Code-aware Multi-language Compression** — Automatically detects code boundaries, only compresses comments/whitespace, does not break syntax
3. **MCP/API Transparent Proxy** — Fully transparent to LLM APIs, no client code modification needed, auto-compress by changing base_url

### Quick Start

#### Method 1: Transparent Proxy (Simplest)

```bash
python scripts/ts_proxy_server.py 8001
```

Point your LLM client's base_url to `http://localhost:8001/v1`, all requests are auto-compressed.

#### Method 2: Python Function Call

```python
import sys
sys.path.insert(0, "scripts")

# JSON Compression
from json_compressor import compress_json_light
data = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
compressed = compress_json_light(data)
print(compressed)  # name,age\nAlice,30\nBob,25

# Code Compression
from code_context_extractor import compress_code_light
compressed_code = compress_code_light("mycode.py")

# Dynamic Routing
from token_router import optimize
strategy = optimize("data_analysis", {"tool_return_lines": 200})
```

#### Method 3: CLI Command Line

```bash
# Compress file
python scripts/cli.py compress input.json

# Compress and show savings
echo "large text" | python scripts/compress_report.py -

# Code compression
python scripts/cli.py code mycode.py --mode light
```

### Requirements

- Python 3.7+, cross-platform (Windows/macOS/Linux)
- **Zero third-party dependencies** (core uses standard library only)
- `tiktoken` optional (precise counting, auto-degrades if not installed)

### Use Cases

✅ JSON data transfer | ✅ Code file transfer | ✅ Multi-turn conversation history | ✅ Tool output aggregation | ✅ Agent loops | ✅ Log analysis

❌ Short text (<200 tokens, auto-skip) | ❌ Scenes requiring exact original citation | ❌ Highly sensitive data

### Honest Disclosure

- This is the open source Lite version. Long text (>2000 chars) uses basic truncation. For 100% restorable compression, please use the commercial version.
- Patent-related advanced features have been removed (full-loop adaptive closure, reversible externalization, adaptive aggregation, output-side optimization, learning engine, signal-driven scheduling).
- Short text is auto-skipped to avoid compression overhead exceeding savings.

### License

MIT License — Open source and free, commercial use allowed, copyright notice must be retained.

### Author

momogigi123 — GitHub: https://github.com/momogigi123
