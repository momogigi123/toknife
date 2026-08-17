# Token Saver 參考表（100 條精華）

> 來源：2026 年 WebSearch/WebFetch 權威與實測文獻。依知識庫鐵律，此為操作參考，非重複知識庫內容。

## A. 分詞基礎（Token化）

- BPE：GPT/LLaMA/DeepSeek，從 byte 起迭代合併高頻對。
- WordPiece：BERT，合併準則最大化似然，續接加 `##`。
- Unigram LM：T5/XLNet，EM 演算法剪詞表。
- SentencePiece：語言無關，吃 raw Unicode（空白=▁），LLaMA/Gemma。
- 換算：英文 1 token≈4 字元≈0.75 詞；中文 1 字≈1–2 token；代碼 1 token≈3–4 字元。
- 中文費 token：cl100k_base 中文 1.85 tok/char vs 英文 0.23（約 1/8）；o200k_base（GPT-4o）壓到 1.00 仍未抹平。
- 數字每 digit 一 token；長數字/ID 貴。JSON 比同資訊 YAML 貴 ~30%。
- 切詞器與權重綁定：換 tokenizer 留權重 → 靜默失敗（掉到隨機）。
- 計 token 用 tiktoken（快 3–6×、無 OOV）；勿用 len/4。每 msg ≈4 token 結構開銷。

## B. 上下文窗口與 KV Cache

- KV Cache 快取每層每 token 的 K/V，避免重算；未來只用自己的 Q 匹配歷史 K/V。
- 成本：無 cache O(n²)/token，有 cache O(n)/token；Llama-3.1-7B 加速 10–20×。
- 顯存：2×層數×hidden×序列長×dtype×batch；LLaMA-3-70B ≈327KB/token(fp16)，4K≈1.3GB。
- 推理常 memory-bound，升 GPU 算力幫助有限。
- PagedAttention（vLLM）：分頁 + copy-on-write 共享。
- Prefix/Prompt Caching：相同前綴只算一次；企業 60–80% 共享前綴，吞吐 +2–4×。
- 前綴復用嚴格：必須 token-by-token 完全相同。
- 上下文四模式/月成本：Full 18K、Sliding 4K、Summary 5K+、RAG 3K+emb；10萬對話/月 Full→RAG 省 $35K。

## C. 計價與槓桿（2026-08 實測）

| 模型 | 輸入 $/M | 輸出 $/M | 備註 |
|------|---------|---------|------|
| DeepSeek V4 Flash | 0.14 | 0.28 | 最便宜實用 |
| Mimo V2.5 | 0.08 | 0.24 | 預算批處理 |
| Qwen3.5 Flash | 0.20 | 0.80 | 高速推論 |
| GLM-5 | 0.30 | 1.00 | 中文優化 |
| Gemini 3.1 Pro | 2.00 | 12.00 | >200K 翻倍 |
| Claude Opus 4/5 | 5.00 | 25.00 | 最強輸出 |
| GPT-5.5 | 15.00 | 60.00 | 前沿 |

- 價差 300×；輸出比輸入貴 2–6×。
- 快取折扣（cached input）：Claude 90% off、Gemini 90% off、DeepSeek 90% off($0.0028)、OpenAI GPT-4o 50%/GPT-5 90%。
- Anthropic 快取寫入 1.25×，只讀一次虧，複用一次打平；$720→$72/月實例。
- OpenAI 隱式快取：≥1024 token 共享 prefix 自動折扣。
- Batch API：三大家皆 50% off；可堆疊 batch×cache=95% off（Sonnet $3→$1.5→$0.15/M）。
- 實例：10M in/2M out 支援聊天 DeepSeek V3 $1.96 vs GPT-4o $45；編碼 20M in/10M out DeepSeek $5.60 vs Sonnet $210。
- 價格每季變動（年降 ~10× 同能力）；用 routing layer + config，每季重測。

## D. 節約技術（免費勝利）

- 結構化提示：300–400→30–60 token。
- 層級上下文：只送最小必要層。
- 語意壓縮：900→90 token（輕量模型）。
- 相關性評分：只傳 score>閾值，消 70% token。
- Delta prompts：只送與上輪差異。
- 記憶壓縮：{session_summary, key_facts, pending_goals} 取代逐字稿。
- 輸出約束：結構化輸出 + 設 max 長度，砍 30–50%。
- 快取三層：Exact(5–15%)/Semantic(20–50%, -20~40% 成本)/原生 Prompt Cache(75–90% off)。
- 工具：定義精簡（20 工具 12K→3–5K，年省 $2,400+）、預篩選、平行呼叫、結構化回傳。
- 系統提示審計：>2000 token 就壓，常砍 40% 品質不變。
- 實例：2500→340 token，月成本 -78%、延遲 -55%。

## E. Agent 令牌效率

- 成本五大來源：重送上下文 > 工具定義 > 模型選擇 > 輸出長度 > 重試迴圈。
- 工具回傳先過濾（50KB→必要欄位）；超大結果存 prompt 外。
- 歷史三法：滑動窗口 / 摘要（過閾值用便宜模型）/ 結構化狀態。
- 工具 schema 精簡（search_customer_database 90→30 token）+ 只載相關工具。
- 模型路由每步；陷阱是建昂貴 router，用簡單信號起步。
- 停止重試迴圈（具體錯誤 + cap retries）；要 JSON 用 structured output。
- 確定性工作移出推理迴圈。
- 微軟 arxiv 2606.10209：full 71% 完成/1.48M token → 剪 5 次呼叫 79%/−64% → +摘要 91.6%。
- Glean：30 workflow 150K→按需 3K token。
- 先量後優：top 5 pattern 佔 70–80% 支出。
