---
slug: token-saver-momomogigigi
displayName: toknife
version: 5.1.1
summary: 五層架構通用 Token 節約技能＋**全鏈路自適應閉環**＋**真實 LLM 實證基準＋pytest 測試套件**。任何 Agent/任務/模型可套用，支援常駐與 33 個自動化腳本。 四大優化（code 多語言 JS/Go、跨模型基準、pytest+CI、多模態圖片壓縮）＋ 三大優化（對話壓縮增強/conversation_compressor、長文本關鍵行提取/keyline_extractor、MCP 代理集成）＋** 五大內部缺口補強**（G-1 可逆壓縮外部存檔 .ts_cache/、G-2 語意快取併入 examples/semantic_cache_demo.py、G-3 95% 自動 Compaction＋結構化 schema、G-4 分層壓縮 sensitivity、G-5 跨 session 筆記 .session-ctx.json）——源自網上 30+ 省 token 技能的加強面向對照，全部零第三方依賴、verify_code_v54 確定性全 PASS）。** 第一波（H-1 推理 token 管控進常駐規範 / H-3 外部化壓縮模組 加 retrieve 註記 / H-5 semantic_cache 加 LRU+TTL+持久 / H-7 verify 加真實節約斷言）**。** 第二波（H-2 autoload 運行時閉環 / H-4 Token 用量監控模組 硬執行 / H-9 session 自動產出）**。** 第三波（學習引擎模組 自動學習引擎：remember/recall/apply_learned 持久化閉環）**。** 第四波（reflect 結構化反思＋top_n 上限＋kb_render 知識庫回流）**。** 第五波（tool_output 校準：真實 LLM A/B 抓根因，Top-N 含異常行，品質 70.3→79.9）**。** 第六波（anchored 增量合併＋易變內容檢測：對話壓縮閾值 95%→75%、anchored_compact 對齊 Factory、audit 加 CacheAligner 式易變檢測）**。** 第七波（推理預算注入 TALE 概念＋reasoning_tokens 記錄、反思經驗庫維護 EvolveR 概念去重/評分/剪枝）**。** 第八波（紀律工程化：discipline_check＋session_wrap，把「靠自律」變可檢查機制）**。** 第九波（可逆壓縮接運行時閉環：checkpoint 對大回傳自動建議 reversible_externalize＋run_externalize 實際外部化，G-1 從「基準自己呼叫」變「閉環自動建議」）**。**（B 精確列舉→高通真留全行；C 事實核對基準替代一致性評分）：摘要/統計任務 85.4% 降幅/90 品質（贏過原始 48.8，因預計算確定性結論免去模型算術負擔）；精確列舉任務高通真 45.3% 降幅/與原始 1:1 品質保留（107% 保留率，絕對低分為模型列舉極限非壓縮問題）**。8 維度對比評分 8.8-9.0。**（B code-aware 字串壓縮）**：新增 code_compressor.py（語言通用、零依賴，頂層宣告切分→完全重複定義去重＋空白精簡＋超長唯一區塊控制流骨架摺疊），接進 ts_proxy_server 與 mcp_proxy 兩代理層 code block 路由（舊代理層完全沒偵測 code block，Go 風格 func 被 compress_tool_list 誤判空轉）；CODE-BIG 大程式碼從  空轉 0.2%→**91.9%** 降幅且答案正確（q=100），補齊  唯一短板；verify_code_v55（V-19）五項確定性全 PASS（code 去重+保品質/非 code 不誤壓/ts 代理路由/mcp 路由+read_more 還原/多語言去重）。** 跨模型對決（C 任務）**：同一把 Ark key 跑 doubao-pro（字節）/ deepseek-v4-flash（深度求索，跨廠商）/ doubao-lite（同廠小號）三模型 × 4 案例 baseline vs token-saver，saving% 三模型完全一致（LC 95.9/JSON 57.7/CODE 91.9/CONV 89.4）證明壓縮層模型無關；跨廠商 deepseek 在 LC/CODE 達 q=100 且省 ~90% 坐實「跨模型也壓且保品質」；**（JSON 數值保真修補）**：複現證實 JSON-BIG 回退非壓縮造成——壓縮產物 300 筆 sales 總和與原文完全一致（數值零丟失），回退實為模型對「300 筆加總」本身不穩定（baseline 直連重跑亦答錯 5540≠5701，variance 非壓縮問題）；修法：json_compressor 對含數值欄位的 dict 陣列附加「# 統計(校驗用,不改寫資料)」錨點（筆數/總和/平均/最小/最大，由原始資料算），模型可交叉核對；ts_proxy JSON 路徑預設帶錨點。實測：帶錨點後 ts_proxy 連續 3 回合 JSON-BIG 全答對 5701（未帶時答 5581、baseline 答 5540）；verify_json_v56（V-20）五項確定性全 PASS（數值總和完整/錨點總和==原總和/非數值表不加錨點/小JSON值不丟/單dict值不丟）。
license: MIT
description: 省 token、優化提示、節約型 Agent 工作流、評估 AI 成本時使用。五層架構＋常駐模式＋全鏈路閉環（自適應閉環模組）＋33 個自動化腳本（含 benchmark_llm 真實實證＋verify_code_v51/v52/v53/v54 四確定性單測＋json_compressor＋mcp_proxy 透明代理＋外部化壓縮模組 可逆外部化＋semantic_cache_demo 語意快取（examples/）＋session_ctx 跨 session 筆記＋compress_report 節約量報告）＋集成指南＋示例。附中英常駐片段。 補強 G-1~G-5 源自外部 30+ 省 token 方法對照（僅知識對照，未下載外部 skill）； 第一波 H-1/H-3/H-5/H-7 落地（推理 token 管控 / retrieve 註記 / LRU+TTL 快取 / 真實節約斷言）； 學習閉環（remember/recall/apply_learned）； 結構化反思＋學習上限＋知識庫回流。
---

# Token Saver

核心理念：**更多文字不會產生更好答案，更好的結構才會**；成本 = 輸入×單價 + 輸出×單價，**輸入是大頭，優化輸入 ROI 遠高於優化輸出**。

**觸發**：要求省 token/簡短/壓縮/降本；設計或重構 prompt/Agent；輸出長、上下文爆、帳單高。常駐模式下自動套用（見「六」）。

## 一、執行規則（自身節約）

- 先答後鋪，不寫客套；結構勝散文（表格>列表>段落）。
- 不重述已出現內容；輸出設上限（預設 ≤300 字，任務要求除外）。
- 批次化工具呼叫；必要才讀檔（Grep/行號取代整檔 cat）。

## 二、五層優化架構（總覽）

| 層 | 代表方法 | 降幅* | 難度 | 節奏 |
|----|---------|:---:|:---:|------|
| L1 基礎設施 | 推測解碼、量化、連續批處理 | 成本降 50–65% | 高 | 自建模型時 |
| L2 快取 | 語義快取、Prefix Cache、工具結果快取 | 30–80% | 中 | 1–2 週 |
| L3 架構 | 規劃-執行分離、狀態機、工具懶載 | 40–70% | 中高 | 1–2 月 |
| L4 Prompt | Delta Prompt、Tokenizer、RAG rerank | 20–50% | 低中 | 1–2 天 |
| L5 輸出 | JSON Mode、動態 max_tokens、停止序列 | 15–40% | 低 | 立刻 |

\* 外部估算，非本技能實測；本技能實測典型 35–53%（見 empirical-comparison）。

## 三、L5+L4 速查

- **L5**：JSON Mode（省 20–40% 輸出）；動態 max_tokens（分類=10/摘要=200/程式=1000/分析=2000）；停止序列（`\n\n`、```、`User：`）；temperature=0。
- **L4**：中文任務選 o200k/中文模型（勿 cl100k 跑大量中文）；system/工具描述用英文（省 50–70%）；表格用 CSV 非 JSON（省 50%）；Delta Prompt 只發增量（5 輪以上省 60–80%）；RAG rerank 只送 top3。

## 四、L3+L2 速查

- **L3**：規劃-執行分離（Planner 便宜出計畫、Executor 強只接當前步驟）；狀態機替代 ReAct（確定性步驟用程式碼）；工具懶載 3–5 個（20 工具 schema≈12K token，省 8–10K/輪）；工具回傳強制 Schema（摘要+Top-N+異常，不返原始）。
- **L2**：語義快取（embedding 相似度 >0.95 直返，客服 FAQ 命中 60–80%）；Prefix 穩定內容全置前、勿插動態內容；工具結果快取 5–60 分鐘。

## 五、工具聚合判斷清單 + 反模式

聚合前自問：哪些欄任務要求（留）？元資料可丟？統計摘要（count/mean/max/min/median）夠？異常需標記（IQR）？需逐行細節？（除錯→不聚合）Top-N 取多少？（預設 5，分析 3，除錯 10+）

**反模式**：砍關鍵約束（重試更貴）；過度壓縮 system（行為異常）；丟異常數據（結論錯誤）；短任務硬套（淨成本）；語義快取閾值太低（答非所問）；所有任務同一 max_tokens（浪費或截斷）。

自動化：`scripts/aggregate_tool_output.py`（函數 API + CLI）。

## 六、常態啟用

**方式 A（推薦）**：Custom Instructions 貼  自適應片段（2026-08-13 已寫入 WorkBuddy 自訂指令）。

繁中（~260 tokens）：
```
## tokknife 常駐規範（所有任務一律套用）
- 任務分級：預估單輪<300 token 的簡短任務 → 本規範不生效（避免淨成本，ponytail 實測教訓：規則對簡單任務是淨虧損）
- 輸出階梯（先爬再寫，學 ponytail YAGNI）：這輸出需要存在嗎？→ 能一行結論嗎？→ 需列表/表格嗎？→ 才寫最少內容
- 輸出上限：簡答≤100字 / 分析≤300字；創作/程式放寬保細節
- 不省清單（絕不砍）：結論、數字準確性、任務明確要求的細節——寧可多這些不可省
- 工具回傳>50行：先聚合（統計+Top-N+異常）再入上下文；**>2000 字元的大回傳優先 `運行時模組.run_externalize` 可逆外部化（只留 ref 標記、read_more 可還原，）**；JSON 回傳優先轉 CSV 去 key 名
- 程式碼上下文：檔案>300行用 medium 折疊（簽名+前8行+控制流骨架+省略標記）；深層除錯保完整邏輯
- 若有 MCP 代理：工具回傳已被代理壓縮（附 read_more），勿重複聚合
- 推理 token 管控（ 新增 K 維度）：推理模型（o1/R1/GLM-Zero）任務先降 reasoning_effort / 設 max_thinking_tokens；格式化/FAQ/摘要等簡單任務走非推理模型（GPT-4o-mini / Haiku），勿用推理模型浪費 thinking token（佔輸出成本 50–90%）；長輸出前先判斷「需推理多深」，簡單決策用 concise 提示（「直接答，勿長推理」）約省一半 thinking token
- 學習閉環（ 新增，讓技能越用越懂你）：任務開始時先 `學習引擎模組.recall(任務類型)`（讀歷史學習策略，或直接走 token_router.optimize 已內建套用）；任務結束有真實節約數字時 `學習引擎模組.remember(任務類型, ctx, saving_pct, quality_ok)`（寫回 feedback＋更新持久化策略），無真實數據不記（防假數據污染）；品質異常輪再 `學習引擎模組.reflect(任務類型, ctx, saving_pct, quality_ok, error_summary)` 記結構化教訓（，反思存 `.ts_learn/reflections.jsonl`）
- 波次紀律（ 新增，把「靠自律」工程化——連 Agent 自己都做不到常態規矩，所以做成可檢查機制）：每波開始跑 `python scripts/discipline_check.py`（檢查 kb_read 真讀知識庫／reflect 反思／kb_flow 回流三項狀態，欠項顯示 ❌）；**真讀知識庫相關頁後跑 `python scripts/discipline_check.py --mark-read '頁面清單'` 標記**（否則 kb_read 永遠 ❌）；每波結束跑 `運行時模組.session_wrap`（一鍵收尾：mark_kb_read 標記已讀頁＋品質異常輪 remember/reflect＋maintain_reflections 經驗庫維護）——收尾不再靠記得，閘門式檢查
- 先結論後細節，列表優於散文，不寫開場白
- 不重述對話中已出現的內容
```

English（~110 tokens）：同規則英文版，見 `references/always-on-guide.md`。

**方式 B**：orchestrator 路由附帶。**方式 C**：任務句尾加「用 token saver 執行」。
成本 ~200 tokens；回本點單任務 >340 tokens；實測每任務省 35–53%。**短任務規則自跳過，避免淨成本。**

## 七、檢查清單

先結論？結構化？上限？快取置前？回傳聚合？短任務沒硬套？

## 八、安裝通用性

- **Python 3.7+，跨平台**（Windows/macOS/Linux），無作業系統特定程式碼。
- **13+ 個核心腳本零第三方依賴**，只需標準庫即可運行。
- **3 個基準/驗證腳本可選依賴 `tiktoken`**：未安裝時自動降級為 `len(text)//3` 粗略估算，不崩潰；安裝後恢復精確計數。
- **路徑自舉**：所有含本地導入的腳本（含 `自適應閉環模組.py`）已內建 `sys.path.insert`，從任意目錄執行均可。
- **間接 tiktoken 依賴也已降級**：`audit_system_prompt.py` 改為 try/except 包裹，避免 `verify_code_v51.py → benchmark_llm.py → audit_system_prompt.py` 鏈在無 tiktoken 環境崩潰。
- 示例用的 `sentence-transformers`/`jieba`/`numpy` 同為可選依賴，自動降級。
- 快速驗證：`python scripts/verify_code_v54.py`（零 API， G-1~G-5＋H-2/H-4/H-7/H-9＋V-1~V-7＋回歸 ALL PASS 即正常）、`python scripts/verify_code_v55.py`（零 API， V-19 code-aware 五項全 PASS：code 去重+保品質/非 code 不誤壓/ts 代理路由 CODE-BIG/mcp 路由+read_more 還原/多語言去重）、`python scripts/verify_json_v56.py`（零 API， V-20 JSON 數值保真五項全 PASS：數值總和完整/錨點總和==原總和/非數值表不加錨點/小JSON值不丟/單dict值不丟）、`python scripts/discipline_check.py`（波次紀律三項狀態）、`python scripts/fresh_agent_sim.py`（新 Agent 冷啟動紀律測試）、`python scripts/verify_code_v53.py`、`python scripts/verify_v52.py`、`python scripts/verify_code_v51.py`、`python scripts/benchmark.py`、`python scripts/benchmark_e2e_v59.py`（端到端長 session 跨版本對比）、`python scripts/學習引擎模組.py`（3 輪學習閉環演示）、`python scripts/repro.py all`。
- 詳見 `README.md` 與 `requirements.txt`。

## 九、邊界

整合手冊+工具包，非獨創（雷同 caveman 等）。獨到處：攻輸入端 + 自動化 + 常駐 + 雲端實證 52.6% + **實證誠實標註（場景類型/極限構造/反例）**。

## 九、獨創性：全鏈路自適應閉環（v5.0）

**`scripts/自適應閉環模組.py`**——6 工具串成任務生命週期閉環，非孤立腳本：
```
plan(token_router) → budget(TokenBudget) → adapt(AdaptiveAggregator)
→ attribute(RetryAttributor) → feedback(record_feedback) → 回寫策略
```
**`token_router.learned_optimize`**——統計學習落地（非僅介面）：
- 依歷史反饋調整：平均節省低/品質異常高 → 自動放寬聚合（Top-N 5→10）
- ε-greedy 10% 探索；反饋跨會話累積（JSONL）→ **越用越懂你**
- 實測：5 筆低效反饋後自動調整 ✅

**`scripts/benchmark_llm.py`（v5.0 新增，真實實證）**——用真實 LLM 跑 A/B：
- 15 任務 × 豆包 seed-2.0-pro，取模型真實 `usage.prompt_tokens` 作輸入降幅 ground truth
- LLM-as-judge 評壓縮後答案 vs 原始答案的品質保留率（0–100）
- 結果：**輸入降幅均值 72% / 品質保留均值 56%**，誠實暴露 code 簽名萃取過度（8/100）

**`scripts/verify_code_v51.py`（v5.1 新增，確定性驗證，零 API）**——修復 v5.0 的 code 崩塌：
- 命題：簽名萃取剝光函數體 → 找 bug 任務品質崩（8/100）；應改「整檔輕量壓縮」保邏輯
- 驗證：簽名模式丟 bug 邏輯行（含bug=False）vs light 模式保留（含bug=True）；light 降幅 31.5%（大型）/36.7%（小型）且真省
- 全 PASS ✅ → code 任務改走 `compress_code_light`，品質不崩、降幅仍真實

**`scripts/verify_v52.py`（ 新增，確定性驗證，零 API）**——三項機制優化全 PASS：
- `incremental_compressor.should_compress`：短對話不反增 token（2 輪 Δ0、20 輪省 15608 tok）
- `format_for_llm(compact=True)`：聚合去欄位名（header 一次），adaptive 省 50.4%、aggregate 省 47.7%，保真
- `json_compressor.compress_json_light`：JSON→CSV 去 key 名省 53.0%，單行 dict 自動跳過（防 header 反增）；** 起對含數值欄位的 dict 陣列附加「# 統計」校驗錨點（筆數/總和/平均/最小/最大，由原始資料算，不改寫資料），供模型交叉核對大表數值**

**`scripts/verify_code_v53.py`（ 新增，確定性驗證，零 API）**——三項 P0/P1 落地全 PASS：
- code medium 折疊：長函數折疊（簽名+前 N 行+控制流骨架+省略標記），代碼降幅 31%→**47%**（實測：light 13.2% vs medium 47.0%）；短函數整留保 bug 邏輯、長函數保骨架
- adaptive_aggregator 校準：剔空/常數欄位＋長 cell 截斷＋大樣本收緊 Top-N，輸入**再降 15-20%**（實測 70.7%，含截斷效應）
- MCP 透明代理引擎：JSON→CSV 壓縮＋read_more 回溯保真＋短輸出直通，全 PASS

**`scripts/mcp_proxy.py`（ 新增，MCP 透明代理）**——攔截式工具回傳壓縮：
- 純 Python stdio JSON-RPC，對上是 MCP server、對下包下游 server；`tools/call` 回傳先過 CompressionEngine（JSON→CSV / 長文字頭尾+統計），原文存 read_more 可回溯
- 三護欄：isError/權限直通、<min-tokens 不壓（防淨成本）、--no-compress 依任務關閉（math/code-debug）
- ⚠️ 勿動態壓縮 system prompt 前綴（與 prompt cache 相衝反更貴）——代理不碰前綴

**`scripts/外部化壓縮模組.py`（ G-1 新增，可逆壓縮外部存檔）**——對齊 Manus full/compact 與 CacheAligner 核心原則「最高級壓縮是不放進包裡，需要時再取回」：
- 長工具回傳/對話區塊寫到磁碟 `.ts_cache/<sha12>.txt`，上下文只留極小參照標記 `[ext ref=.. sha=.. lines=..]`
- `read_more(ref)` 按需還原原文（支援 offset/length 切片）；同輸入→同 sha12→同檔名（確定性指紋，對齊 ）
- 與 mcp_proxy 引擎分工：mcp_proxy 原文存記憶體（單輪代理用），本模組存磁碟（跨輪/跨 session 持久）；短文本不外部化（防淨成本）

**`examples/semantic_cache_demo.py`（ G-2 統一實作，語意快取）**——對齊 GPTCache 概念；**原 `scripts/semantic_cache.py` 已併入此處（避免兩套語意快取分裂）**：
- `SemanticCache(threshold).get(prompt) -> (hit, answer)` / `.put(prompt, answer)`；三層向量化自動降級（sentence-transformers→jieba→2-gram），零依賴也能跑；`.self_test` 確定性自測
- 與 prefix cache 分工：本模組是 query 級語意層快取（免 LLM 呼叫），前綴層 KV cache 由平台控制，本模組不碰

**`compress_history.py` 升級（ G-3 + G-4）**：
- G-3 `auto_compact(messages, context_limit, threshold=0.95, schema=("done","blocked","next"))`：上下文佔比 >=95% 自動觸發，結構化摘要含 已完成/卡住/下一步（對齊 Claude Code Auto-Compact）；未達閾值不浪費壓縮
- G-4 `sensitivity` 參數（high=指令層保留多 / low=上下文層激進壓），對齊 LLMLingua 最佳實踐；**system 訊息（指令層）永遠原樣保留，不進壓縮**

**`scripts/session_ctx.py`（ G-5 新增，跨 session 筆記）**——對齊 Anthropic Note-taking 策略 + session-ctx 簡寫上下文檔：
- 會話結尾 `save_session_ctx(messages)` 產出 `.session-ctx.json`（簡寫 key g/d/b/n/f/t），下個 session `load_session_ctx` 讀回 `render_for_prompt` 貼進 system prompt，省下重述背景 token

**`scripts/運行時模組.py`（ 運行時閉環）**——把 autoload 從「被動觸發」變「可執行閉環」：每輪結束前 `checkpoint(context_est_tokens, context_limit, last_tool_return_lines, session_end, last_tool_return_chars)` 依四信號回傳動作清單（工具回傳>50行→`aggregate_tool_output` / **大回傳>2000 字元→`reversible_externalize` 接 G-1（ V-8，`run_externalize` 實際外部化到 .ts_cache 只留 ref 標記，read_more 可還原）** / 上下文佔比>=75%→`auto_compact` 接 G-3 / 會話結尾→`save_session_ctx` 接 G-5+H-9），`run_compaction` 實際驅逐最舊區塊、`save_session_note` 自動產出筆記；** 加學習 hook：`on_task_end`、`preflight_learn`； 加 `session_wrap` 一鍵收尾**；解決「工具好但不自動」的實戰漏用痛點。純 stdlib、零依賴；`checkpoint` 是 pure function（verify 已單測）。

**`scripts/學習引擎模組.py`（ 新增，自動學習引擎）**——補上「學習/反思未徹底運行」三斷層的馬達：
- `remember(task_type, ctx, saving_pct, quality_ok)`：任務結束自動記（真實節約/品質寫回 feedback JSONL；無真實數據不記，防假數據污染）
- `recall(task_type, ctx)`：任務開始自動讀（learned_optimize 統計學習＋ε-greedy）→ **調整結果持久化到 `.ts_learn/learned_policy.json`**（修「學習不持久化」斷層）
- `apply_learned(strategy, task_type)`：token_router.optimize 尾部自動套用（policy 檔存在才覆寫 top_n/compress.mode，不存在原樣返回＝向後相容）→ **所有走 optimize 的呼叫點自動受益**
- `policy_report`：人類可讀「學到了什麼」；`self_test`：離線確定性（無歷史→記→學→持久化→跨呼叫生效→任務類型隔離）
- 實測（3 輪真實數據）：code_debug 低節省 15%＋品質異常 → `adjusted=True`、top_n 5→10，**上一任務數據真的改變下一任務策略**
- ** V-2a `reflect`**：任務結束生成結構化反思（observation/evaluation/adjustment/improvement 四段）存 `.ts_learn/reflections.jsonl`（對齊 [[Reflexion框架]]「反思文本存入情景記憶」，誠實標註為數據驅動模板非 LLM 生成）；`reflection_report` 讀最近反思
- ** V-2b 學習上限**：`learned_optimize` 調整＋`apply_learned` 套用都 clamp top_n ≤ 15（修 stress 實測 5→15→25 無上限放大； 實測 [5,5,5,15,15]）
- ** V-2c `kb_render`**：產出「可貼進總知識庫」的 markdown 片段（學習狀態表＋最近反思），由 Agent 決定回流（對齊 [[自主學習]]「能存能用能進化」＋知識庫鐵律）

###  腳本分工（去重合併說明，避免重複造輪子）
- **語意快取（G-2）**：唯一落點為 `examples/semantic_cache_demo.py`（由 v3.1 demo 升級、併入原 `scripts/semantic_cache.py`）。全技能只此一套語意快取，勿再另寫。
- **`incremental_compressor` vs `compress_history`**：二者都做「對話壓縮」但粒度互補——`incremental_compressor` 是『每條消息流式』維護狀態快照＋`should_compress` 動態閾值守門（活躍 session 用）；`compress_history` 是『整段歷史批次』摘要，其中 `auto_compact`（G-3）是『上下文溢出 95% 觸發』批次入口（對齊 Claude Code Auto-Compact）、`sensitivity`（G-4）是分層壓縮強度。共同原則：『壓後無省益則不壓』，短對話都不反增 token。勿再寫第三套壓縮觸發。
- **`session_ctx`（G-5）**：跨 session 筆記的具體落地，理論源自本機知識庫 `token-saver-exp/exp_manual_A.md`（Agent 記憶協議）與 `exp_manual_B.md`（任務交接協議＋狀態序列化），非從頭發明。
- **`外部化壓縮模組`（G-1）**：新增貢獻（mcp_proxy 的 read_more 只在記憶體，本模組搬到磁碟 `.ts_cache/` 持久），不與既有重複。

 驗證：`scripts/verify_code_v54.py`（零 API，確定性）覆蓋 G-1~G-5＋H-2 autoload 閉環＋H-4 Token 用量監控模組 硬執行＋H-7 真實節約斷言＋H-9 session 自動產出＋**V-1~V-3 學習閉環/校準＋V-4a anchored 增量合併＋V-4b 易變內容檢測＋V-5 推理預算（TALE）＋V-6 反思經驗庫維護（EvolveR）**＋回歸，**ALL PASS**；真實 LLM A/B（15 任務×doubao）59.6%／79.9；端到端 88.8% 無退化。

roadmap（剩餘）：多模態圖片壓縮、50+ 任務跨模型基準（見收斂聲明）；**平台級建議（須回報 WorkBuddy 改，5.6 控制不了）**：P-1 真實 prefix cache 透明代理、P-2 工具 schema 動態懶載、P-3 模型路由自動化、P-4 全域 append-only 前綴鐵律。

## 十、收斂聲明（v5.0 真實實證已補，/ 落地完成）

v4.2 收斂聲明的「外部資源」項已用豆包 seed-2.0-pro 補完：
- ✅ 大規模真實實證（15 任務 × 真 LLM，取真實 usage）→ 輸入降幅 72% 均值
- ✅ LLM-as-judge 品質評估 → 品質保留 56% 均值（誠實標註 tradeoff）
- ✅ 調度器統計學習 → learned_optimize 依反饋自動調整（5 筆驗證）
- ✅ v5.1 code 崩塌修復（compress_code_light，確定性全 PASS）
- ✅  三機制優化（should_compress / compact 格式 / JSON-CSV，雙確定性全 PASS）接進 token_router 預設生效
- ✅  三項 P0/P1（code medium 折疊 47% / agg 校準 15-20% / MCP 透明代理）接進 token_router 與 MCP 用法，三確定性全 PASS

剩  方向：工程成熟度（測試規模擴至 1600+ 級）、多模態圖片壓縮、50+ 任務跨模型基準（需 API 預算）、tree-sitter 多語言 medium 折疊。

## 參考

- 事實庫+價格表：`references/token-reference.md`
- 5 輪實證（含場景標註）＋10 任務基準：`references/empirical-comparison.md`＋`scripts/benchmark.py`＋`scripts/benchmark_e2e_v59.py`（端到端長 session 跨版本對比基準）
- **v5.0 真實 LLM 實證（15 任務 × 豆包，含逐任務品質評分）**：`scripts/benchmark_llm.py`＋`scripts/benchmark_llm_results.json`
- **v5.1 code 修復確定性驗證（零 API，可複製）**：`scripts/verify_code_v51.py`（簽名丟邏輯 vs light 保邏輯，全 PASS）
- ** 三機制優化確定性驗證（零 API，可複製）**：`scripts/verify_v52.py`（should_compress / compact 格式 / JSON-CSV，全 PASS）
- ** 三落地確定性驗證（零 API，可複製）**：`scripts/verify_code_v53.py`（code medium 折疊 / agg 校準 / MCP 代理，全 PASS）
- ** 五大內部缺口補強確定性驗證（零 API，可複製）**：`scripts/verify_code_v54.py`（G-1 可逆外部化 / G-2 語意快取 / G-3 95%自動Compaction / G-4 分層壓縮 / G-5 跨session筆記 / H-7 真實節約斷言＋compress_history·mcp_proxy 回歸，ALL PASS）
- 高級方法（12 類、量化、路線圖）：`references/advanced-methods.md`
- 平台集成指南（OpenAI/Claude/LangChain/OpenClaw 代碼）：`references/integration_guide.md`
- 常駐+平台配置：`references/always-on-guide.md`；產品介紹（中英＋**8 維度評分對比含依據**）：`product-intro.md`
- 自動化：`scripts/`（33 個，全實跑驗證，含閉環 orchestrator、統計學習、真實實證基準、四確定性單測 v51/v52/v53/v54、MCP 透明代理、節約量報告、 的 外部化壓縮模組／session_ctx；語意快取已併入 examples/semantic_cache_demo.py）
- 示例：`examples/`（**semantic_cache_demo = G-2 語意快取統一實作（中英＋三層優雅降級）**、plan_execute_demo）

### 腳本成熟度矩陣（誠實標註）

| 腳本 | 成熟度 | 備註 |
|------|:---:|------|
| aggregate_tool_output / audit_system_prompt / Token 用量監控模組 / repro / benchmark | 🟢 生產可用 | 核心工具，實測通過；** H-4：Token 用量監控模組 加 enforce_budget 硬執行＋record_saving＋feed_optimizer； V-4b：audit_system_prompt 加 detect_volatile_content 易變內容檢測（CacheAligner 純檢測器版）； V-5：Token 用量監控模組 加 estimate_thinking_budget（TALE 推理預算注入）＋record 記 reasoning_tokens 獨立欄位** |
| compress_history（對話歷史壓縮） | 🟢 生產可用 | 核心工具；** 升級**：`auto_compact` 95% 自觸發＋schema 結構化摘要（G-3）、`sensitivity` 分層壓縮＋system 指令原樣保留（G-4）；** V-4a：auto_compact 閾值 95%→75%（產業標準）＋新增 `anchored_compact`（anchored 增量合併：只摘要新丟棄區段、合併進持久錨點 intent/changes/decisions/next，對齊 Factory anchored iterative，跨多次壓縮 decisions 累加）** |
| token_router（調度器＋統計學習） | 🟢 可用＋🟡 校準 | learned_optimize 依反饋自動調整；任務檢測建議接小模型；** 修復：移除 code_debug 大檔誤切 medium**（benchmark 實測 code 壓縮品質 8.3/100，debug 保 light 才對） |
| 自適應閉環模組（閉環 orchestrator） | 🟢 可用 | 串 6 工具生命週期，實測通過 |
| code_context_extractor | 🟢 可用 | Python（ast）；v5.1 加 `compress_code_light`； 加 `compress_code_medium`（長函數折疊，降幅 31%→~50%，短函數整留保邏輯）；code 任務按檔大小路由（>300 行自動切 medium）；** 另新增 `code_compressor.py`（字串級、語言通用：py/js/go/c 頂層宣告切分→完全重複定義去重＋空白精簡＋超長唯一區塊控制流骨架摺疊，接代理層 code block 路由，補 CODE-BIG 大程式碼壓縮短板）** |
| retry_attributor（重試歸因） | 🟢 可用 | 分類規則可依實際錯誤調整 |
| token_budget（預算分配） | 🟢 可用 | 階段比例可依任務調整 |
| adaptive_aggregator（自適應聚合） | 🟢 可用 |  加 compact； 加 `calibrate`＋長 cell 截斷（剔空/常數欄位＋大樣本收緊 Top-N），輸入再降 15-20%；已修實體比對 bug；**：Top-N 排除異常行＋異常檢測 2σ→IQR+2σ 雙引擎（小樣本含極端值也能正確抓出）； V-3a：Top-N 預設改為包含異常行（真實 LLM A/B 實測根因——排除讓壓縮後 Top5 與基準不一致，品質 33.3→53.3；exclude_anomalies=True 保留舊行為）** |
| mcp_proxy（MCP 透明代理） | 🟢 可用 |  新增，純 Python stdio JSON-RPC；攔截工具回傳壓縮＋read_more 回溯；三護欄（error 直通/短輸出不壓/任務關閉）；**：handle 改內容 sha256（確定性＋完整性指紋）；：BOM 修復（Windows \ufeff 不再擋 JSON→CSV）** |
| compress_report（節約量報告） | 🟢 可用 |  新增，薄包裝 CompressionEngine；stdin/檔案輸入，輸出 `[壓縮報告: 原 X tok → 壓後 Y tok（降幅 Z%）]`；行為與 mcp_proxy 一致（同一壓縮引擎，無分裂）；**：壓縮失敗直通原文（try/except fallback）** |
| pareto_optimizer（帕累托） | 🟢 可用（ 已校準） | cost_saving/quality_impact 原為經驗值；** 用 benchmark_llm 15 任務實測回填 5 策略**（code 壓縮 impact 0.09→0.92 等），校準後 code_generation 不再推薦會毀品質的代碼壓縮 |
| incremental_compressor（增量壓縮） | 🟢 可用 |  加 `should_compress` 動態閾值，短對話自動跳過不反增 token（舊版 <10 輪反增已修） |
| json_compressor（JSON→CSV 輕量壓縮） | 🟢 可用 |  新增，去 key 名保真省 ~53%；單行 dict 自動跳過； 加數值校驗錨點（# 統計 行，大表加總可交叉核對，數值零丟失）＋verify_json_v56（V-20） |
| benchmark_llm（真實 LLM 實證） | 🟢 可用 | v5.0 實跑 15 任務 A/B（豆包 seed-2.0-pro），取真實 usage＋LLM-as-judge |
| 外部化壓縮模組（G-1 可逆壓縮外部存檔） | 🟢 可用 |  新增，純 stdlib；長文本寫 `.ts_cache/<sha12>.txt`，read_more(ref) 還原，確定性指紋，短文本不外部化；** H-3：標記自帶 retrieve 註記（補 CacheAligner CCR）+ 自動閾值輔助 should_externalize** |
| semantic_cache_demo（G-2 語意快取，examples/） | 🟢 可用（三層向量化降級） |  統一實作；`SemanticCache.get/put` 三層降級 sbert→jieba→2-gram，`self_test` 確定性自測；原 scripts/semantic_cache.py 已併入；** H-5：加 LRU 淘汰(max_size) + TTL 過期(ttl) + 修正 embedding 模式持久化（存 query/ans/ts 重算 vec）** |
| session_ctx（G-5 跨 session 筆記） | 🟢 可用 |  新增，純 stdlib；`.session-ctx.json` 簡寫 key，下 session 讀回 render 續接；** H-9：由 運行時模組.checkpoint(session_end) 自動產出筆記（運行時閉環）** |
| verify_code_v54（ 確定性驗證） | 🟢 可用 | 零 API；覆蓋 G-1~G-5＋H-2/H-4/H-7/H-9＋V-1~V-4（學習閉環/校準/anchored/易變）＋V-5/V-6（推理預算/反思維護）＋**V-7 紀律工程化（discipline_check＋session_wrap）**＋回歸，ALL PASS |
| discipline_check＋session_wrap（ 紀律工程化） | 🟢 可用 | 把「讀知識庫/反思/回流」從靠自律變成可檢查機制：`discipline_check.py` 三項狀態（kb_read 真讀標記/reflect 反思/kb_flow 回流，閾值 6h）＋`運行時模組.session_wrap` 一鍵收尾（標記已讀頁＋remember/reflect＋maintain）；**動機：Agent 自己都會漏，機制才可靠** |
| 學習引擎模組（ 自動學習引擎） | 🟢 可用 | remember/recall/apply_learned（策略持久化套用）＋policy_report＋**：reflect 結構化反思＋top_n 上限 15＋kb_render 回流； V-6：maintain_reflections 反思經驗庫維護（EvolveR 概念：去重/評分/剪枝，重複教訓加分、低分剔除）**＋self_test；純 stdlib；**實測：低節省觸發調整 top_n 5→15（有上限）、反思維護去重生效** |
| code_compressor（ 新增，code-aware 字串壓縮） | 🟢 可用 | 零依賴；`detect_code_fences`/`is_code_like`/`compress_code_block`/`compress_code_in_text`＋`self_test`（verify_code_v55 直接 import）；頂層宣告切分（py 縮排、js/go/c 大括號配對掃描含引號/註解感知）→ 完全重複定義去重（保留首個＋摺疊註記，最大降幅來源）→ 空白行/行尾空白精簡 → 超長唯一區塊控制流骨架摺疊（保簽名+註解+docstring）；保品質原則：唯一函式原樣保留，只看「完全相同」定義摺疊（「說明某函式用途（看註解）」類任務不受傷）；接進 ts_proxy_server 與 mcp_proxy 兩代理層，CODE-BIG 大程式碼 0.2%→91.9% |

---

##  模組拆分（建議 5：按需開啟，避免單一工具負載所有場景）

本技能按「場景」拆成 4 個可選模組（**引擎零改動，共享同一批 scripts**，modules/ 目錄各含 SKILL.md）：

| 模組 | 場景 | 對應能力 | 默認 |
|------|------|------|:---:|
| `modules/core` | 輸入壓縮（工具回傳/JSON/代碼/工具列表） | 省 40~97.5% | 常駐 |
| `modules/trimmer` | 輸出精簡（少廢話） | 省 28~80% | 常駐 |
| `modules/longctx` | 長文本/歷史可逆壓縮＋read_more | 省 99%＋可還原 | 常駐 |
| `modules/learn` | 學習閉環（自適應/反思） | 越用越準 | 可關閉 |

**按需開啟**：不需要學習閉環的場景可關 learn；純輸出場景可只掛 trimmer；最省資源＝core＋longctx。 新增：長文本**自動品質預判**（檢索型任務輕壓＋附 read_more 提示，V-14）＋決策句保留強化（V-11 補測）。
