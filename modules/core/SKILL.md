---
name: token-saver-core
version: 6.8
summary: 輸入側壓縮核心（工具回傳/JSON/代碼/工具列表）——按需載入模組
agent_created: true
---

# token-saver-core（輸入壓縮模組）

## 用途
壓縮進入上下文的**輸入**：工具回傳、JSON、代碼、工具描述。最常用模組。

## 對應腳本（scripts/，共享單一事實源）
| 場景 | 腳本 | 實測 |
|------|------|:---:|
| 工具回傳聚合（200 行→前 5 異常＋統計） | aggregate_tool_output.py | 省 97.5% |
| JSON→CSV（含字串防呆＋收益閘門） | json_compressor.py | 省 52~68% |
| 代碼折疊（簽名＋控制流骨架） | code_context_extractor.py | 省 28~47% |
| 工具描述結構化壓縮 | ts_proxy_server.compress_tool_list | 省 46% |
| JSON tools schema 壓縮 | ts_proxy_server.compress_tools_schema | 省 40% |

## 用法（代理）
```python
from ts_proxy_server import compress_content
r = compress_content(big_text)   # 自動路由 json/tool/長文本
```

## 不壓情境（防淨成本）
- 短回傳 <300 tok；壓後不短於原文（收益閘門退回）
