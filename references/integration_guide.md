# Token Saver — 平台集成指南（v3.0）

> 各平台的具體集成代碼片段，可直接複製使用。⚠️ 指南中引用的函數以 `scripts/aggregate_tool_output.py`（`aggregate_json` / `auto_aggregate_json` / `format_for_llm`）為準。

---

## 1. OpenAI API（原生）

### 1.1 工具回傳自動聚合中間件

```python
from aggregate_tool_output import auto_aggregate_json, format_for_llm
# auto_aggregate_json(data, threshold=20, top_n=5)：list 超過 threshold 條時自動聚合

def chat_with_aggregation(messages, tools, model="gpt-4o"):
    """包裝 OpenAI 調用，工具回傳自動聚合。"""
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )

    msg = response.choices[0].message
    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            # 執行工具，獲取原始結果
            raw_result = execute_tool(tool_call.function.name, tool_call.function.arguments)

            # 自動聚合（如果是列表且超過 20 條）
            if isinstance(raw_result, list) and len(raw_result) > 20:
                aggregated = auto_aggregate_json(raw_result, top_n=5)
                content = format_for_llm(aggregated)
            else:
                content = json.dumps(raw_result, ensure_ascii=False)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": content,  # 聚合後的精簡內容
            })

        # 繼續對話
        return chat_with_aggregation(messages, tools, model)

    return msg.content
```

### 1.2 Prompt Caching（OpenAI 自動）

OpenAI 對 ≥1024 token 的共享前綴自動啟用快取，無需手動配置。確保：
- system prompt 和工具定義放在 messages 最前面
- 動態內容（時間、用戶問題）放在最後

### 1.3 JSON Mode + 動態 max_tokens

```python
def call_llm(task_type, messages):
    max_tokens_map = {
        "classification": 10,
        "summary": 200,
        "analysis": 500,
        "code": 1000,
        "creative": 2000,
    }
    return client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=max_tokens_map.get(task_type, 500),
        response_format={"type": "json_object"} if task_type != "creative" else None,
        temperature=0 if task_type in ["classification", "summary", "analysis"] else 0.7,
    )
```

---

## 2. Anthropic Claude API

### 2.1 Prompt Caching（手動配置 cache_control）

```python
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1000,
    system=[
        {
            "type": "text",
            "text": "你是一個數據分析助手...",  # 穩定前綴
            "cache_control": {"type": "ephemeral"},  # 標記可快取
        },
        {
            "type": "text",
            "text": json.dumps(tools_definition),  # 工具定義也可快取
            "cache_control": {"type": "ephemeral"},
        },
    ],
    messages=messages,
)
```

注意：快取寫入成本 1.25×，只讀一次虧，複用一次打平。

---

## 3. LangChain 集成

### 3.1 對話歷史自動壓縮

```python
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from compress_history import compress_messages, estimate_tokens

class TokenSaverMemory:
    """LangChain 記憶體中間件，自動壓縮歷史。"""

    def __init__(self, max_tokens=4000, keep_recent=3):
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent
        self.messages = []

    def add(self, message):
        self.messages.append(message)
        # 超過閾值時自動壓縮
        if estimate_tokens(self._to_dict) > self.max_tokens:
            self._compress

    def _to_dict(self):
        return [{"role": m.type, "content": m.content} for m in self.messages]

    def _compress(self):
        compressed = compress_messages(self._to_dict, keep_recent=self.keep_recent)
        self.messages = [
            SystemMessage(content=c["content"]) if c["role"] == "system"
            else HumanMessage(content=c["content"]) if c["role"] == "user"
            else AIMessage(content=c["content"])
            for c in compressed
        ]

    def get_messages(self):
        return self.messages
```

### 3.2 工具懶載入

```python
from langchain_core.tools import tool

# 核心工具（始終載入）
CORE_TOOLS = [search_tool, read_file_tool, write_file_tool]

# 擴展工具（按需載入）
EXTENDED_TOOLS = {
    "code": [python_repl_tool, git_tool],
    "data": [pandas_tool, sql_tool],
    "web": [browser_tool, scrape_tool],
}

def get_tools_for_intent(user_input):
    """根據用戶意圖動態載入工具。"""
    tools = list(CORE_TOOLS)
    # 簡單意圖檢測
    if any(kw in user_input.lower for kw in ["代碼", "code", "python", "git"]):
        tools.extend(EXTENDED_TOOLS["code"])
    elif any(kw in user_input.lower for kw in ["數據", "data", "sql", "分析"]):
        tools.extend(EXTENDED_TOOLS["data"])
    elif any(kw in user_input.lower for kw in ["網頁", "browser", "爬蟲"]):
        tools.extend(EXTENDED_TOOLS["web"])
    return tools
```

---

## 4. OpenClaw / WorkBuddy 集成

### 4.1 常駐片段配置

在 OpenClaw / WorkBuddy 的設定中找到「Custom Instructions」或「系統提示詞」，貼上：

```
[Token Saver Always-On] Apply to every task:
- Simple Q&A: <=100 words, pure conclusion
- Analysis: <=300 words, structured
- Creation/Code: relax cap, keep detail
- Tool output >50 lines: aggregate before context (summary+Top-N+anomalies)
- Single-turn <300 tokens: skip this rule
- Conclusion first, lists over prose, no greetings
- Don't restate existing context
```

### 4.2 技能安裝

將本套件（toknife）目錄放入技能目錄：
- OpenClaw: `~/.openclaw/skills/`
- WorkBuddy: `~/.workbuddy/skills/`

重啟後技能自動載入。

### 4.3 三層壓縮的正確使用方式（ 實測經驗，重要）

**先理解機制邊界**：在 OpenClaw/WorkBuddy 等平台，**工具回傳進上下文的那一刻 token 已花掉**——平台大多沒有「回傳前攔截」的 hook。所以壓縮要分三層，效果不同：

| 層級 | 什麼時候發生 | 省什麼 | 平台支援 |
|------|-------------|--------|---------|
| **① MCP 代理**（`mcp_proxy.py`） | 回傳**進入前**被攔截壓縮 | 省**當輪** token（真省） | 僅走 MCP 的工具；原生 Bash/Read 不經過 |
| **② 主動跑腳本**（`compress_report.py` 等） | 看到回傳**之後**跑 | 省**後續重複引用**（壓縮版存下來再用） | 需 agent 紀律（customPrompt 約定） |
| **③ 行為層**（agent 自己摘要） | 回傳進上下文時 | 省**輸出** token | 靠 agent 自律，無需技能 |

**正確用法（其他安裝者照做可得最佳效果）：**

1. **能走 MCP 就走 MCP**：把下游工具包進 `python mcp_proxy.py --downstream "..." --min-tokens 2000`，回傳自動壓、附 `[read_more:handle]` 可回溯——這是最接近「自動」的一層。
2. **customPrompt 加「每輪工具回傳 >50 行先跑腳本」強約定**（見 always-on-guide 方式 A），讓 agent 對原生工具回傳主動跑 ②——雖非平台自動，但比純輸出規範省得多。
3. **不要誤以為「裝了技能就自動壓」**：技能本體是按需載入，常駐片段只是行為引導；真正執行要 agent 跑腳本或 MCP 代理介入。
4. **實測差距**：機制級單項壓縮率（JSON→CSV 74%、code medium 47%）≠ 端到端降幅（15 任務實測 59.6%）。宣稱降幅請引用 `benchmark_llm_results_v532.json` 的端到端數據，勿用單項數字。

---

## 5. 語義快取集成（GPTCache）

### 5.1 最小可運行示例（零依賴版）

見 `examples/semantic_cache_demo.py`，用詞袋+餘弦相似度實現。

### 5.2 生產環境（GPTCache + Redis）

```python
# pip install gptcache redis
from gptcache import cache
from gptcache.adapter import openai
from gptcache.embedding import Onnx
from gptcache.manager import CacheBase, VectorBase, get_data_manager
from gptcache.similarity_evaluation.distance import SearchDistanceEvaluation

# 初始化
onnx = Onnx
cache_base = CacheBase("redis", redis_host="localhost", redis_port=6379)
vector_base = VectorBase("faiss", dimension=onnx.dimension)
data_manager = get_data_manager(cache_base, vector_base)

cache.init(
    embedding_func=onnx.to_embeddings,
    data_manager=data_manager,
    similarity_evaluation=SearchDistanceEvaluation(max_distance=0.2),  # 閾值
)

# 使用：直接替換 openai 調用
response = openai.ChatCompletion.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "省電對碳排放的影響"}],
)
# 相似查詢會自動返回快取結果，不調用 API
```

---

## 6. Token 用量報告（開源版）

> 本開源版不內建即時 Token 用量監控子系統（該能力屬完整版引擎）。開源版請改用 `compress_report.py` 做一次性節約量報告，或自行接入用量統計。

### 6.1 一次性節約量報告

```python
from compress_report import report_saving

original = "..."  # 原始上下文文字
compressed = "..."  # 壓縮後文字
report_saving(original, compressed)  # 輸出 原 X tok → 壓後 Y tok（降幅 Z%）
```

### 6.2 批次目錄報告

```bash
python scripts/compress_report.py --batch ./logs/ --ext .txt
```

> 需要長期趨勢對比時，自行將每筆報告寫入 JSONL 並做前後期分析。

---

## 7. 規劃-執行分離集成

見 `examples/plan_execute_demo.py`，完整的 Planner+Executor 架構示例。

生產環境要點：
1. Planner 用便宜模型（Qwen3-8B / DeepSeek-Flash / GPT-4o-mini）
2. Executor 用強模型（GPT-4o / Claude Sonnet）
3. 步驟間只傳遞結果摘要，不傳完整數據
4. 確定性步驟用代碼實現，不調 LLM

---

## 8. 快速集成檢查清單

- [ ] System prompt 改成英文，壓到 200 token 以內
- [ ] 工具定義懶載入，初始只載 3-5 個核心工具
- [ ] 工具回傳超過 20 條自動聚合（用 aggregate_tool_output.py）
- [ ] 對話歷史超過閾值自動壓縮（用 compress_history.py）
- [ ] 按任務類型設置動態 max_tokens
- [ ] 開啟 JSON Mode（非創作任務）
- [ ] 加 Token 監控裝飾器（用 Token 用量監控模組.py）
- [ ] System prompt + 工具定義放在 messages 最前面（Prefix Cache）
- [ ] 語義快取（高頻重複任務）
- [ ] 複雜多步任務用規劃-執行分離架構
