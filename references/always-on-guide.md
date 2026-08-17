# Token Saver 常駐啟用指南（）

目標：**安裝一次，之後不管怎麼切換任務都自動套用節約規範**，不必每次手動觸發。

> ✅ **2026-08-13 已實作**：本片段已寫入使用者 WorkBuddy 自訂指令（`~/.workbuddy/app/app-config.json` 的 `personalization.customPrompt`），新對話即自動生效。

## 為什麼可以常駐

token saver 的規範不是「某一類任務專用」，而是「所有任務送進大模型那一投」的通用改造：
精簡 system、工具回傳聚合、結構化輸出、上限。因此它與「任務內容」無關，可以全域常駐。

## 三種啟用方式

| 方式 | 做法 | 適用 |
|------|------|------|
| **A. Custom Instructions 常駐** | 把下方片段貼進平台自訂指令/系統提示 | 每天大量任務的人（推薦） |
| **B. 任務路由器掛鉤** | 讓 orchestrator 類技能路由時自動附帶規範 | 已有任務編排器的使用者 |
| **C. 任務內呼叫** | 任務句尾加「用 token saver 執行」 | 偶爾使用、不想付常駐成本 |

## 方式 A：Custom Instructions 常駐片段（ 任務自適應，複製即用）

**繁體中文（~210 tokens）**：
```
## tokknife 常駐規範（所有任務一律套用）
- 簡單問答：輸出≤100字，純結論；分析任務：輸出≤300字，結構化列點
- 創作/程式：放寬上限，保細節
- 工具回傳>50行：先聚合（統計+Top-N+異常）再入上下文；JSON 回傳優先轉 CSV 去 key 名
- 程式碼上下文：檔案>300行用 medium 折疊（簽名+前8行+控制流骨架+省略標記）；深層除錯保完整邏輯
- 若有 MCP 代理：工具回傳已被代理壓縮（附 read_more），勿重複聚合
- 預估單輪<300 token 的短任務：本規範不生效（避免淨成本）
- 先結論後細節，列表優於散文，不寫開場白
- 不重述對話中已出現的內容
```

**English v3（~150 tokens，外國使用者用）**:
```
[tokknife Always-On Rules] Apply to every task:
- Simple Q&A: output <=100 words, conclusion only; analysis: <=300 words, structured
- Creative/code tasks: relax cap, keep detail
- Tool return >50 lines: aggregate (stats+Top-N+anomalies) before context; JSON -> CSV
- Code context: files >300 lines use medium folding (signature+head 8+control-flow skeleton+omitted marker); deep debug keeps full logic
- If an MCP proxy is active: tool returns are already compressed (read_more attached), do not re-aggregate
- Short tasks (<300 tokens estimated): skip these rules (avoid net cost)
- Conclusion first; lists over prose; no filler; do not restate conversation content
```

- 片段成本：繁中 ~210 / 英文 ~150 tokens，約 $0.00006/次（DeepSeek 輸入價）。
- 回本點：單任務 token 基數 > 340 tokens 即一次回本；短任務規則自跳過，避免淨成本。
- 實測收益：每任務省 35–53%（雲端實測 #4/#5）；多輪 Agent 迴圈越高。

## 平台配置速查（常駐片段貼哪）

| 平台 | 設定位置 |
|------|---------|
| **WorkBuddy** | 左下角頭像 → 設置 → 自訂指令（部分版本在「個性化」分類下） |
| **CodeBuddy / Codex 系** | 設置 → 個性化 → 自訂指令；或使用者目錄 `AGENTS.md` |
| **OpenClaw / ClawHub** | 技能裝進 skills 目錄後，於平台設定（Custom Instructions / 個人偏好）貼片段 |
| **LangChain / AutoGen** | 無「自訂指令」概念：用 middleware/回呼實作——工具回傳先過 `aggregate_tool_output.py`，歷史過 `compress_history.py`，再進 prompt 組裝 |
| **OpenAI / Anthropic 官網 Playground** | 直接放進 system prompt（穩定前綴置前，順便命中 caching） |

## 方式 B：與 skill-orchestrator 類路由器整合

若使用者已安裝任務編排器（如 skill-orchestrator），做法：
1. 把上面的常駐片段提供給路由器作為「全域執行規範」。
2. 路由器在派發任何任務時，附帶該規範；或直接把片段寫入路由器的預設指令。
3. 效果：任務切到哪，規範跟到哪，且不會重複載入整個 SKILL.md（省 token）。

## 常駐 vs 臨時呼叫的取捨

| 情境 | 建議 |
|------|------|
| 每天 10+ 任務、多輪迴圈、工具回傳大 | 常駐（A 或 B） |
| 偶爾用、單輪問答為主 | 任務內呼叫（C） |
| 任務需要極致細節（論文級輸出） | 暫關常駐或放寬上限 |

## 常見問題

**Q：常駐會影響答案品質嗎？**
A：實證 #1/#2/#5 兩版答案資訊等價；#3 顯示過度過濾可能損細節——所以規範要求「聚合到 Top-N + 異常標記」而非一刀砍光。

**Q：179 tokens 常駐真的划算？**
A：是。只要 session 內任務基數 >340 tokens 就回本；實測省 52.6%。你一天跑幾十個任務，常駐一天省下的是幾十倍的片段成本。

**Q：換平台/換模型要重設嗎？**
A：不用。規範與模型無關（原理是上下文管理），片段貼到哪個平台就對哪個平台生效。

**Q：裝了技能就會自動壓縮工具回傳嗎？**
A：**不會自動**。工具回傳進上下文那一刻 token 已花掉，平台大多沒有「回傳前攔截」hook。常駐片段是行為引導（agent 照做），真正執行靠兩條路：① 走 MCP 的工具有 `mcp_proxy.py` 回傳前自動壓（真省當輪）；② 原生工具（Bash/Read）靠 customPrompt 強約定「>50 行先跑腳本」壓縮後續引用。詳細對比見 `integration_guide.md` 4.3 節。

**Q：端到端到底省多少？**
A：單項機制級（JSON→CSV 74%、code medium 47%）≠ 端到端。15 任務 LLM 實測：平均省 **59.6%**、品質 70.3（`scripts/benchmark_llm_results_v532.json`）。宣稱降幅請引用端到端數據。

## 實證支撐

- 雲端全迴圈（Deepseek-V4-Flash）：0.95 → 0.45 = **省 52.6%**
- 單次作答：0.97 → 0.63 = 省 35.1%
- 完整 5 輪實證：見 references/empirical-comparison.md；可自行複現：`scripts/repro.py`
