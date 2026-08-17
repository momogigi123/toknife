# -*- coding: utf-8 -*-
"""
tokknife — 增量式上下文壓縮
不是定期壓縮，而是每條新消息進來時增量更新對話狀態。
舊消息可以直接丟棄，狀態向量控制在 200 token 以內。

分工（ 去重合併後）：本模組 =『每條消息流式』維護狀態 + should_compress() 動態閾值守門；
批次式『整段歷史摘要 / 上下文溢出 95% 觸發』請看 compress_history.compress_messages / auto_compact
（auto_compact 是對齊 Claude Code Auto-Compact 的批次入口）。二者互補，勿重寫觸發邏輯。

用法：
    from incremental_compressor import IncrementalCompressor
    comp = IncrementalCompressor()
    comp.add_message({"role": "user", "content": "分析Q2銷售數據"})
    comp.add_message({"role": "assistant", "content": "我來幫你分析..."})
    state = comp.get_state()  # 返回精簡的對話狀態
    context = comp.build_context()  # 返回狀態 + 最近N輪
"""
import re
import json
from typing import Dict, List, Any, Optional


def _est_tokens(text: str) -> int:
    """估算 token 數（中文 1.5/字，其他 0.3/字元）； 提取為 module-level 供 should_compress 用。"""
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    other = len(text) - chinese
    return int(chinese * 1.5 + other * 0.3)


class IncrementalCompressor:
    """增量式對話狀態壓縮器。"""

    def __init__(self, keep_recent: int = 3, max_state_tokens: int = 200):
        """
        參數：
            keep_recent: 保留最近 N 輪原文
            max_state_tokens: 狀態向量的最大 token 數（估算）
        """
        self.keep_recent = keep_recent
        self.max_state_tokens = max_state_tokens
        self.messages: List[Dict] = []
        self.state = {
            "task_goal": "",
            "completed": [],
            "pending": [],
            "key_facts": [],
            "decisions": [],
            "constraints": [],
        }

    def add_message(self, message: Dict[str, str]) -> Dict:
        """
        添加一條消息，增量更新狀態。
        返回更新後的狀態。
        """
        self.messages.append(message)
        content = message.get("content", "")
        role = message.get("role", "user")

        # 增量提取信息
        self._extract_task_goal(content, role)
        self._extract_completed(content, role)
        self._extract_pending(content, role)
        self._extract_key_facts(content)
        self._extract_decisions(content)
        self._extract_constraints(content)

        # 限制狀態大小
        self._truncate_state()

        return self.state

    def _extract_task_goal(self, content: str, role: str):
        """提取任務目標（通常在第一條 user 消息中）。"""
        if role == "user" and not self.state["task_goal"]:
            # 取前 100 字作為任務目標
            self.state["task_goal"] = content[:100].strip()
        elif role == "user" and len(self.messages) <= 2:
            # 第二條用戶消息可能補充目標
            if len(content) < 50:
                self.state["task_goal"] += "；" + content.strip()

    def _extract_completed(self, content: str, role: str):
        """提取已完成項（從 assistant 消息中）。"""
        if role != "assistant":
            return

        # 匹配 "已完成"、"已經"、"完成了" 等模式
        patterns = [
            r'(?:已完成|已經|完成了|搞定了|實現了|实现了)[：:]\s*(.+?)(?:[\n。；;]|$)',
            r'(?:✓|✅)\s*(.+?)(?:[\n]|$)',
            r'(?:step|步驟|步骤)\s*\d+\s*(?:完成|done)[：:]\s*(.+?)(?:[\n]|$)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for m in matches:
                m = m.strip()[:80]
                if m and m not in self.state["completed"]:
                    self.state["completed"].append(m)

        # 限制已完成項數量
        if len(self.state["completed"]) > 10:
            self.state["completed"] = self.state["completed"][-10:]

    def _extract_pending(self, content: str, role: str):
        """提取待辦項。"""
        patterns = [
            r'(?:待辦|待办|下一步|接下來|todo|next)[：:]\s*(.+?)(?:[\n。；;]|$)',
            r'(?:需要|應該|应该|要)\s*(?:先|再)?\s*(.+?)(?:[\n。；;]|$)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for m in matches:
                m = m.strip()[:80]
                if m and m not in self.state["pending"] and len(m) > 3:
                    self.state["pending"].append(m)

        # 限制待辦項數量
        if len(self.state["pending"]) > 8:
            self.state["pending"] = self.state["pending"][-8:]

    def _extract_key_facts(self, content: str):
        """提取關鍵事實（數字、日期、具體值）。"""
        # 匹配數字+單位
        number_patterns = [
            r'(\d+(?:\.\d+)?\s*(?:%|萬|万|億|亿|k|K|m|M|g|G|t|T|元|美元|美金|度|個|个|次|輪|轮))',
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',  # 日期
            r'(Q[1-4]\s*\d{4})',  # 季度
        ]
        for pattern in number_patterns:
            matches = re.findall(pattern, content)
            for m in matches:
                if isinstance(m, tuple):
                    m = m[0]
                m = m.strip()
                if m and m not in self.state["key_facts"]:
                    self.state["key_facts"].append(m)

        # 限制關鍵事實數量
        if len(self.state["key_facts"]) > 15:
            self.state["key_facts"] = self.state["key_facts"][-15:]

    def _extract_decisions(self, content: str):
        """提取決策（選擇了某個方案）。"""
        patterns = [
            r'(?:決定|决定|選擇|选择|採用|采用|用了)\s*(.+?)(?:[\n。；;]|$)',
            r'(?:最終|最终|最後|最后)\s*(?:選擇|选择|決定|决定)\s*(.+?)(?:[\n。；;]|$)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, content)
            for m in matches:
                m = m.strip()[:80]
                if m and m not in self.state["decisions"] and len(m) > 2:
                    self.state["decisions"].append(m)

        if len(self.state["decisions"]) > 8:
            self.state["decisions"] = self.state["decisions"][-8:]

    def _extract_constraints(self, content: str):
        """提取約束條件。"""
        patterns = [
            r'(?:必須|必须|一定要|不能|不要|禁止|限制)\s*(.+?)(?:[\n。；;]|$)',
            r'(?:注意|提醒|warning)[：:]\s*(.+?)(?:[\n。；;]|$)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, content)
            for m in matches:
                m = m.strip()[:80]
                if m and m not in self.state["constraints"] and len(m) > 2:
                    self.state["constraints"].append(m)

        if len(self.state["constraints"]) > 5:
            self.state["constraints"] = self.state["constraints"][-5:]

    def _truncate_state(self):
        """限制狀態總大小。"""
        total = _est_tokens(json.dumps(self.state, ensure_ascii=False))
        while total > self.max_state_tokens and (self.state["key_facts"] or self.state["completed"]):
            # 優先刪除最舊的 key_facts 和 completed
            if self.state["key_facts"]:
                self.state["key_facts"].pop(0)
            elif self.state["completed"]:
                self.state["completed"].pop(0)
            total = _est_tokens(json.dumps(self.state, ensure_ascii=False))

    def get_state(self) -> Dict:
        """返回當前對話狀態。"""
        return self.state.copy()

    def get_recent_messages(self) -> List[Dict]:
        """返回最近 N 輪消息。"""
        return self.messages[-self.keep_recent * 2:]  # 每輪 user+assistant

    def should_compress(self) -> bool:
        """ 動態閾值：只有壓縮後真的比原文省，才值得壓。

        根因（v5.1 實證）：短對話（<=keep_recent*2 輪）全部內容本就在保留範圍內，
        硬壓反而因 system 狀態摘要開銷而『反增 token』。
        修法：先 token 估算『原文 vs 壓縮後』，壓縮後更小才回 True。
        """
        if not self.messages:
            return False
        # 全部消息都在 keep_recent 輪內 → 壓縮=把原文搬進 state+recent，必反增
        if len(self.messages) <= self.keep_recent * 2:
            return False
        orig = _est_tokens("\n".join(m.get("content", "") for m in self.messages))
        comp_ctx = self.build_context(include_state=True, include_recent=True, auto_skip=False)
        comp = _est_tokens("\n".join(m.get("content", "") for m in comp_ctx))
        return comp < orig

    def build_context(self, include_state: bool = True, include_recent: bool = True,
                      auto_skip: bool = True) -> List[Dict]:
        """
        構建精簡上下文：狀態 + 最近 N 輪。
        可以直接傳給 LLM。
        ：auto_skip=True 時，若 should_compress() 為 False（短對話無省益），
        直接回傳原始消息，避免反增 token。
        """
        if auto_skip and not self.should_compress():
            return [{"role": m["role"], "content": m["content"]} for m in self.messages]

        context = []

        if include_state and self.state["task_goal"]:
            state_text = self.format_state()
            context.append({"role": "system", "content": f"[對話狀態]\n{state_text}"})

        if include_recent:
            context.extend(self.get_recent_messages())

        return context

    def format_state(self) -> str:
        """將狀態格式化為緊湊字符串。"""
        lines = []
        if self.state["task_goal"]:
            lines.append(f"任務: {self.state['task_goal']}")
        if self.state["completed"]:
            lines.append(f"已完成: {'; '.join(self.state['completed'][-5:])}")
        if self.state["pending"]:
            lines.append(f"待辦: {'; '.join(self.state['pending'][-5:])}")
        if self.state["key_facts"]:
            lines.append(f"關鍵數據: {', '.join(self.state['key_facts'][-8:])}")
        if self.state["decisions"]:
            lines.append(f"決策: {'; '.join(self.state['decisions'][-5:])}")
        if self.state["constraints"]:
            lines.append(f"約束: {'; '.join(self.state['constraints'])}")
        return "\n".join(lines)

    def stats(self) -> Dict:
        """返回壓縮統計。"""
        original_tokens = _est_tokens("\n".join(m.get("content", "") for m in self.messages))
        ctx = self.build_context(auto_skip=False)
        compressed_tokens = _est_tokens("\n".join(m.get("content", "") for m in ctx))
        would = self.should_compress()
        real_ctx = self.build_context()  # 含 auto_skip
        real_tokens = _est_tokens("\n".join(m.get("content", "") for m in real_ctx))

        return {
            "total_messages": len(self.messages),
            "would_compress": would,
            "original_estimate_tokens": int(original_tokens),
            "compressed_estimate_tokens": int(compressed_tokens),
            "real_effective_tokens": int(real_tokens),
            "real_saving_percent": f"{(1 - real_tokens/original_tokens)*100:.1f}%" if original_tokens > 0 and real_tokens <= original_tokens else "0%（auto_skip 未壓縮）",
            "state_tokens": int(_est_tokens(self.format_state())) if self.state["task_goal"] else 0,
            "recent_messages_count": len(self.get_recent_messages()),
        }


# ===== 演示 =====
if __name__ == "__main__":
    comp = IncrementalCompressor(keep_recent=2)

    print("=== 增量式上下文壓縮演示 ===\n")

    # 模擬一個多輪對話
    messages = [
        {"role": "user", "content": "幫我分析 Q2 2026 的銷售數據，找出下滑最嚴重的產品線，數據在 sales.csv"},
        {"role": "assistant", "content": "好的，我來幫你分析。首先讀取 sales.csv 文件。已完成：讀取文件，共 200 條記錄，時間範圍 2026-04 到 2026-06。下一步：按產品線聚合銷售額。"},
        {"role": "user", "content": "好的，繼續。注意不要包含退貨數據"},
        {"role": "assistant", "content": "已完成：按產品線聚合，排除退貨。發現鏡頭膜下滑 73.9% 最嚴重，手機殼下滑 45%。決定：重點分析鏡頭膜下滑原因。待辦：查詢鏡頭膜的競品價格和評論。"},
        {"role": "user", "content": "競品價格查了嗎？"},
        {"role": "assistant", "content": "已完成：查詢 5 個競品，平均價格比我們低 20%。關鍵數據：我們售價 29.9 元，競品平均 23.9 元。建議降價或增加差異化功能。"},
    ]

    for msg in messages:
        comp.add_message(msg)

    print("--- 對話狀態（增量提取）---")
    print(comp.format_state())

    print("\n--- 精簡上下文（狀態 + 最近2輪）---")
    ctx = comp.build_context()
    for m in ctx:
        role = m["role"]
        content = m["content"][:100] + "..." if len(m["content"]) > 100 else m["content"]
        print(f"[{role}] {content}")

    print("\n--- 壓縮統計 ---")
    for k, v in comp.stats().items():
        print(f"  {k}: {v}")

    print("\n說明：狀態提取用規則匹配，生產環境建議用小模型做增量摘要。")
