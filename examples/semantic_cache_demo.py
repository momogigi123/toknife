# -*- coding: utf-8 -*-
"""semantic_cache_demo.py — Token Saver 語意快取（ 統一實作，由 v3.1 demo 升級）

對齊 GPTCache / 各廠商 prefix cache 概念：重複或近義查詢直返快取答案，
省下重跑 LLM 的輸入＋輸出 token。

本模組是 **G-2 的正式落點**。原 `scripts/semantic_cache.py`（ 初版）已併入此處，
避免「兩套語意快取」分裂——統一以本檔為準。

向量化依賴層級（自動降級，沿用 v3.1 demo 的三層優雅降級）：
 1) sentence-transformers（最優）→ 中文命中率 >90%（外部估算）
 2) jieba 分詞 + 詞袋 → 60–70%（外部估算）
 3) 2-gram 字符 n-gram → 30–40%（外部估算，零依賴）
安裝可選依賴：pip install sentence-transformers （或 jieba）

API：
 sc = SemanticCache(threshold=0.92)
 sc.put("重慶天氣如何", "多雲 28°C")
 hit, ans = sc.get("重慶的天氣怎樣？") # (True, "多雲 28°C") 或 (False, "")

與 prefix cache 的分工（重要）：
 - 本模組是「語意層快取」（query 級），命中即免 LLM 呼叫。
 - prefix cache 是「前綴層快取」（KV cache 級，平台級），由 WorkBuddy 控制，本模組不碰。

生產建議（來自 v3.1 demo）：embedding 閾值 0.90–0.98 + TTL 過期 + 用戶回饋糾錯。
"""
from typing import List, Tuple, Dict, Any
import os
import json
import math
import time


# ---- 向量化：依可用依賴優雅降級 ----
def _make_vectorizer:
 try:
 from sentence_transformers import SentenceTransformer
 model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
 enc = model.encode
 return lambda t: enc([t])[0], "sentence-transformers（中文命中率 >90%，外部估算）"
 except ImportError:
 pass
 try:
 import jieba
 def vec_jieba(t):
 from collections import Counter
 c = Counter(jieba.lcut(t))
 n = math.sqrt(sum(v * v for v in c.values)) or 1
 return {k: v / n for k, v in c.items}
 return vec_jieba, "jieba + 詞袋（中文命中率 60–70%，外部估算）"
 except ImportError:
 def vec_2gram(t):
 from collections import Counter
 c = Counter(t[i:i + 2] for i in range(len(t) - 1))
 n = math.sqrt(sum(v * v for v in c.values)) or 1
 return {k: v / n for k, v in c.items}
 return vec_2gram, "2-gram 字符（零依賴，中文命中率 30–40%，外部估算）"


def _cos(a, b):
 """餘弦相似度；a/b 為 embedding 或詞袋字典，統一處理。無 numpy 也不崩。"""
 if hasattr(a, "shape"): # embedding 向量（numpy）
 try:
 import numpy as np
 return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) or 1))
 except Exception:
 a = a.tolist
 if hasattr(b, "shape"):
 b = b.tolist
 # 詞袋字典
 if isinstance(a, dict) and isinstance(b, dict):
 keys = set(a) | set(b)
 dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
 na = math.sqrt(sum(v * v for v in a.values)) or 1
 nb = math.sqrt(sum(v * v for v in b.values)) or 1
 return dot / (na * nb)
 # 等長數值序列（退回標準庫）
 if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b):
 dot = sum(x * y for x, y in zip(a, b))
 na = math.sqrt(sum(x * x for x in a)) or 1
 nb = math.sqrt(sum(y * y for y in b)) or 1
 return dot / (na * nb)
 return 0.0


class SemanticCache:
 """語意快取：get(query) -> (hit: bool, answer: str) / put(query, answer)。

 H-5 加強：新增 LRU 淘汰（max_size）、TTL 過期（ttl 秒）、修正 embedding 模式
 持久化（只存 query/answer/ts，載入時重算向量，避免 numpy 陣列無法 JSON 序列化）。
 """

 def __init__(self, threshold: float = 0.92, cache_file: str = None,
 max_size: int = 1000, ttl: int = 0):
 """
 threshold: 相似度命中閾值。
 embedding 模式用原值（0.90–0.98）；詞袋/2-gram 模式自動下修 0.35（見 get）。
 cache_file: 可選 JSON 持久化路徑（跨程序保留快取）。
 max_size: LRU 容量上限，超過即淘汰最久未用（ H-5）。
 ttl: 條目存活秒數，0 表示不過期；超過視為 miss（ H-5）。
 """
 self.threshold = threshold
 self.cache_file = cache_file
 self.max_size = max_size
 self.ttl = ttl
 self.vec, self.mode = _make_vectorizer
 self._store: List[Tuple[str, str, Any, float]] = [] # (query, answer, vec, ts)
 if cache_file and os.path.exists(cache_file):
 self._load

 def get(self, query) -> Tuple[bool, str]:
 """查詢快取。回傳 (是否命中, 答案)；未命中為 (False, \"\")。
 命中會把條目移到末尾（LRU touch）；TTL 過期當 miss。"""
 qv = self.vec(query)
 best, ans, bidx = 0.0, "", -1
 now = time.time
 for i, (q, a, v, ts) in enumerate(self._store):
 if self.ttl > 0 and (now - ts) > self.ttl:
 continue # 過期：當 miss（不主動刪，prune 處理）
 s = _cos(qv, v)
 if s > best:
 best, ans, bidx = s, a, i
 # 詞袋/2-gram 模式相似度尺度較低，自動下修閾值（沿用 v3.1 demo）
 th = self.threshold if "sentence" in self.mode else self.threshold - 0.35
 if best >= th and bidx >= 0:
 entry = self._store.pop(bidx) # LRU：命中移到末尾
 self._store.append(entry)
 self._save
 return True, ans
 return False, ""

 def put(self, query, answer) -> None:
 """寫入快取（向量化後存入；超 max_size 淘汰最舊）。"""
 self._store.append((query, answer, self.vec(query), time.time))
 while len(self._store) > self.max_size: # LRU 淘汰最舊
 self._store.pop(0)
 self._save

 # ---- 可選持久化（ 修正：只存 query/answer/ts，載入重算向量）----
 def _save(self) -> None:
 if not self.cache_file:
 return
 try:
 payload = {
 "threshold": self.threshold,
 "max_size": self.max_size,
 "ttl": self.ttl,
 "store": [{"q": q, "a": a, "ts": ts} for (q, a, v, ts) in self._store],
 }
 with open(self.cache_file, "w", encoding="utf-8") as f:
 json.dump(payload, f, ensure_ascii=False, indent=2)
 except OSError:
 pass

 def _load(self) -> None:
 try:
 with open(self.cache_file, "r", encoding="utf-8") as f:
 data = json.load(f)
 self.threshold = data.get("threshold", self.threshold)
 self.max_size = data.get("max_size", self.max_size)
 self.ttl = data.get("ttl", self.ttl)
 # 重算向量（embedding 模式 numpy 陣列不適合 JSON 持久化）
 self._store = [(d["q"], d["a"], self.vec(d["q"]),
 d.get("ts", time.time)) for d in data.get("store", [])]
 except (OSError, ValueError, KeyError):
 self._store = []

 # ---- 離線自測（供 verify_code_v54， 加 LRU/TTL 斷言）----
 def self_test(self) -> Dict[str, bool]:
 """確定性自測：API + 同句必命中 + 異句必 miss + LRU 淘汰 + TTL 過期。
 不依賴向量化器，全環境穩過。"""
 api_ok = hasattr(self, "put") and hasattr(self, "get")
 sc = SemanticCache(threshold=0.92)
 sc.put("重慶天氣如何", "多雲 28°C")
 hit, ans = sc.get("重慶天氣如何") # 同句 → 必命中（cosine=1.0）
 identical_hit = (hit is True and ans == "多雲 28°C")
 miss, _ = sc.get("上海股價多少") # 完全不相關 → 必 miss
 diff_miss = (miss is False)
 # LRU 淘汰：max_size=2 寫入 3 筆，最早一筆被驅逐
 sl = SemanticCache(threshold=0.92, max_size=2)
 sl.put("甲", "A")
 sl.put("乙", "B")
 sl.put("丙", "C") # 甲被驅逐
 lru_miss, _ = sl.get("甲")
 lru_ok = (lru_miss is False)
 # TTL 過期：手動把唯一一筆 ts 設為過期 → 視為 miss
 st = SemanticCache(threshold=0.92, ttl=10)
 st.put("x", "1")
 q, a, v, ts = st._store[0]
 st._store[0] = (q, a, v, time.time - 1000)
 ttl_miss, _ = st.get("x")
 ttl_ok = (ttl_miss is False)
 return {"api": api_ok, "identical_hit": identical_hit, "diff_miss": diff_miss,
 "lru_evict": lru_ok, "ttl_expire": ttl_ok}


if __name__ == "__main__":
 cache = SemanticCache
 print(f"向量化模式：{cache.mode}\n")
 # 中文示例（本版真正支援；降級模式命中率有限，安裝 embedding 可 >90%）
 q1 = "省電對於碳排放的影響"
 a1 = "電力佔全球碳排約 40%，省電是成本最低的減碳手段。"
 cache.put(q1, a1)
 q_sim = "節約用電對碳排放有什麼影響？"
 hit, ans = cache.get(q_sim)
 print(f"中文相似句（『{q_sim}』）：{'✅ 命中 → ' + ans if hit else '✗ 未命中'}（模式：{cache.mode.split('（')[0]}）")
 hit2, _ = cache.get("今天天氣怎麼樣？")
 print(f"中文不相關句：{'⚠️ 誤命中' if hit2 else '✅ 正確未命中'}")
 # 英文示例
 cache.put("How to read CSV in Python?", "Use pandas.read_csv.")
 hit3, _ = cache.get("How do I load a CSV file with Python?")
 print(f"英文相似句：{'✅ 命中' if hit3 else '✗ 未命中'}")
 print("\n⚠️ 生產建議：embedding 閾值 0.90–0.98 + TTL 過期 + 用戶回饋糾錯。")
 print("離線自測：", cache.self_test)
