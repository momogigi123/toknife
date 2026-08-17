# -*- coding: utf-8 -*-
"""
tokknife — 對話歷史壓縮腳本
將多輪對話歷史壓縮為結構化狀態，減少 60-80% 進入 LLM 上下文的 token。

用法：
    from compress_history import compress_messages, sliding_window, extract_state
    compressed = compress_messages(messages, keep_recent=3, max_summary_tokens=300)
"""
import re
import json
import os
from typing import List, Dict, Any, Optional

# ===== 分工說明（ 去重合併後）=====
# 本模組（compress_history）與 incremental_compressor 都是「對話壓縮」，但粒度不同，互補不重複：
#   - incremental_compressor：『每條消息流式』維護對話狀態快照（IncrementalCompressor.add_message
#     逐條增量抽取 task_goal/completed/pending/...），並用 should_compress() 動態閾值守門
#     「壓後無省益就不壓」。適用於『活躍 session 進行中』持續精簡上下文。
#   - compress_history：『整段歷史批次』摘要。compress_messages() 把舊輪壓成結構化摘要、
#     最近 N 輪留原文；auto_compact()（G-3）是『上下文佔比 >= 95% 溢出觸發』的批次入口
#     （對齊 Claude Code Auto-Compact）；sensitivity（G-4）是分層壓縮強度。
#   二者共同守則：都遵循 incremental_compressor.should_compress 的『壓縮後比原文省才執行』原則，
#   短對話都不反增 token。不要在新腳本裡再寫一套『壓縮觸發』。
# ============================

# =====  分層壓縮（G-4）=====
# sensitivity 控制「保留多少」：high=指令/system 層（低壓縮率，強制保留）；
# low=上下文層（高壓縮率，可激進丟）。對齊 LLMLingua 最佳實踐。
SENSITIVITY_CAPS = {
    "high":    {"completed": 12, "pending": 10, "key_facts": 20, "decisions": 10},
    "balanced":{"completed": 10, "pending": 10, "key_facts": 15, "decisions": 8},
    "low":     {"completed": 5,  "pending": 5,  "key_facts": 8,  "decisions": 4},
}

#  結構化摘要 schema 關鍵字（G-3，對齊 Claude Code Auto-Compact 欄位）
SCHEMA_KEYWORDS = {
    "done":    ["已完成", "完成了", "已實現", "已修復", "已創建", "已生成", "已上傳",
                "done", "completed", "finished", "✅", "✔", "✓"],
    "blocked": ["卡住", "失敗", "錯誤", "異常", "無法", "阻擋",
                "blocked", "stuck", "failed", "error", "⛔", "❌", "✗"],
    "next":    ["待辦", "需要", "還需", "下一步", "接著", "TODO", "todo",
                "next", "follow", "之後"],
}
# schema 標籤 → SENSITIVITY_CAPS 鍵（用於取每欄上限）
_SCHEMA_CAP_MAP = {"done": "completed", "blocked": "pending", "next": "pending"}
_SCHEMA_CN = {"done": "已完成", "blocked": "卡住", "next": "下一步"}


def sliding_window(messages: List[Dict[str, str]], keep_recent: int = 3) -> List[Dict[str, str]]:
    """
    滑動窗口：只保留最近 N 輪對話。
    一輪 = user + assistant 成對。
    """
    if keep_recent <= 0:
        return []
    # 從後往前數，保留最近 keep_recent*2 條訊息（user+assistant 成對）
    keep_count = keep_recent * 2
    if len(messages) <= keep_count:
        return messages
    return messages[-keep_count:]


def extract_state(messages: List[Dict[str, str]], sensitivity: str = "balanced") -> Dict[str, Any]:
    """
    從對話歷史中提取結構化狀態（規則方法，不需要 LLM）。
    返回：{task_goal, completed, pending, key_facts, decisions}
    sensitivity（ G-4）：high=指令層保留多 / low=上下文層激進壓。
    """
    state = {
        "task_goal": "",
        "completed": [],
        "pending": [],
        "key_facts": [],
        "decisions": [],
    }

    full_text = "\n".join(m.get("content", "") for m in messages)

    # 提取任務目標（第一條 user 訊息）
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if user_msgs:
        first_user = user_msgs[0].get("content", "")[:200]
        state["task_goal"] = first_user.strip()

    # 提取已完成項（匹配 "已完成"/"完成了"/"✅"/"done" 等模式）
    done_patterns = [
        r"(?:已完成|完成了|已實現|已修復|已創建|已生成|已上傳)[：:]?\s*(.+?)(?:\n|$)",
        r"[✅✔✓]\s*(.+?)(?:\n|$)",
        r"(?:done|completed|finished)[：:]?\s*(.+?)(?:\n|$)",
    ]
    for pattern in done_patterns:
        for match in re.finditer(pattern, full_text, re.IGNORECASE):
            item = match.group(1).strip()[:100]
            if item and item not in state["completed"]:
                state["completed"].append(item)

    # 提取待辦項（匹配 "待辦"/"需要"/"TODO"/"❌" 等模式）
    todo_patterns = [
        r"(?:待辦|需要|還需|下一步|TODO|todo)[：:]?\s*(.+?)(?:\n|$)",
        r"[❌✗✗]\s*(.+?)(?:\n|$)",
    ]
    for pattern in todo_patterns:
        for match in re.finditer(pattern, full_text, re.IGNORECASE):
            item = match.group(1).strip()[:100]
            if item and item not in state["pending"]:
                state["pending"].append(item)

    # 提取關鍵事實（數字、路徑、ID 等）
    fact_patterns = [
        r"(?:文件|路徑|path)[：:]?\s*(\S+\.\w+)",
        r"(?:大小|size)[：:]?\s*([\d.]+(?:KB|MB|GB)?)",
        r"(?:版本|version)[：:]?\s*([\d.]+)",
        r"(?:ID|id)[：:]?\s*(\w+)",
    ]
    for pattern in fact_patterns:
        for match in re.finditer(pattern, full_text, re.IGNORECASE):
            fact = match.group(0).strip()[:80]
            if fact and fact not in state["key_facts"]:
                state["key_facts"].append(fact)

    #  關鍵句保護：偏好/記憶/決策訊號句併入 key_facts
    # （IR001 使用者偏好場景：歷史壓縮後偏好句不再丟失）
    pref_patterns = [
        r"(?:記住|請記住|偏好|喜歡|習慣|請務必|重要|規則|必須)[：:]?\s*(.+?)(?:\n|$)",
    ]
    for pattern in pref_patterns:
        for match in re.finditer(pattern, full_text):
            sent = match.group(0).strip()[:100]
            if sent and sent not in state["key_facts"]:
                state["key_facts"].append(sent)
    # 決策訊號句（「決定/採用/確認/同意」）
    dec_patterns = [
        r"(?:決定|採用|確認|同意|拍板)[：:]?\s*(.+?)(?:\n|$)",
    ]
    for pattern in dec_patterns:
        for match in re.finditer(pattern, full_text):
            sent = match.group(0).strip()[:100]
            if sent and sent not in state["decisions"]:
                state["decisions"].append(sent)

    # 限制每個列表的長度（sensitivity：high=保留多 / low=激進壓）
    caps = SENSITIVITY_CAPS.get(sensitivity, SENSITIVITY_CAPS["balanced"])
    state["completed"] = state["completed"][:caps["completed"]]
    state["pending"] = state["pending"][:caps["pending"]]
    state["key_facts"] = state["key_facts"][:caps["key_facts"]]
    state["decisions"] = state["decisions"][:caps["decisions"]]

    return state


def format_state(state: Dict[str, Any]) -> str:
    """將結構化狀態格式化為緊湊字串。"""
    lines = ["[對話狀態摘要]"]
    if state.get("task_goal"):
        lines.append(f"目標: {state['task_goal']}")
    if state.get("completed"):
        lines.append("已完成:")
        for item in state["completed"]:
            lines.append(f"  - {item}")
    if state.get("pending"):
        lines.append("待辦:")
        for item in state["pending"]:
            lines.append(f"  - {item}")
    if state.get("key_facts"):
        lines.append("關鍵事實:")
        for fact in state["key_facts"]:
            lines.append(f"  - {fact}")
    return "\n".join(lines)


def compress_messages(
    messages: List[Dict[str, str]],
    keep_recent: int = 3,
    use_llm_summary: bool = False,
    llm_client=None,
    max_summary_tokens: int = 300,
    sensitivity: str = "balanced",
    schema: tuple = None,
) -> List[Dict[str, str]]:
    """
    壓縮對話歷史：舊對話 → 結構化摘要，最近 N 輪保留原文。

    參數：
        messages: OpenAI 格式的訊息列表 [{"role": "user"/"assistant"/"system", "content": "..."}]
        keep_recent: 保留最近幾輪原文
        use_llm_summary: 是否用 LLM 生成摘要（需要傳入 llm_client）
        llm_client: OpenAI 相容客戶端（可選）
        max_summary_tokens: 摘要最大 token 數
        sensitivity:  G-4，high=指令層保留多 / low=上下文層激進壓
        schema:  G-3，結構化摘要欄位（如 ("done","blocked","next")）；給定則用 schema 摘要

    返回：
        壓縮後的訊息列表：system 指令原樣保留 + 一條歷史摘要 system + 最近 N 輪原文
    """
    #  G-4：system 訊息（指令層）永遠原樣保留，不進壓縮
    sys_msgs = [m for m in messages if m.get("role") == "system"]
    others = [m for m in messages if m.get("role") != "system"]
    if len(others) <= keep_recent * 2:
        return messages  # 不需要壓縮（system 也一併保留）

    # 分離舊對話和最近對話
    recent_count = keep_recent * 2
    old_messages = others[:-recent_count]
    recent_messages = others[-recent_count:]

    # 生成摘要
    if use_llm_summary and llm_client is not None:
        summary_text = _llm_summarize(old_messages, llm_client, max_summary_tokens)
    elif schema:
        summary_text = format_schema_state(extract_schema_state(old_messages, schema=schema,
                                                                sensitivity=sensitivity))
    else:
        summary_text = format_state(extract_state(old_messages, sensitivity=sensitivity))

    #  偏好/關鍵句保護：使用者偏好與決策句附加到摘要，
    # 防歷史壓縮丟失（IR001 長期記憶場景：偏好句不再被摘要吃掉）
    pref_sents = _extract_pref_sents(old_messages)
    if pref_sents:
        summary_text += "\n[使用者偏好/關鍵句]\n" + "\n".join("- " + s for s in pref_sents)

    # 構建壓縮後的訊息列表（system 指令置前，避免被摘要稀釋）
    compressed = list(sys_msgs)
    compressed.append({"role": "system",
                       "content": f"[歷史對話摘要，用於上下文延續]\n{summary_text}"})
    compressed.extend(recent_messages)

    return compressed


def _extract_pref_sents(messages: List[Dict[str, str]], max_n: int = 12) -> List[str]:
    """：從舊訊息收集使用者偏好/決策句（記住/偏好/喜歡/請務必/規則/決定/採用/確認）。
    只收集 user 訊息的完整句，避免摘要吃掉長期記憶（IR001 場景）。"""
    import re
    signals = ["記住", "請記住", "偏好", "我喜歡", "請務必", "規則", "必須", "決定", "採用", "確認"]
    pat = re.compile("|".join(re.escape(s) for s in signals))
    out, seen = [], set()
    for m in messages:
        if m.get("role") != "user":
            continue
        for line in m.get("content", "").splitlines():
            line = line.strip()
            if line and pat.search(line) and line not in seen and len(line) <= 120:
                seen.add(line)
                out.append(line)
                if len(out) >= max_n:
                    return out
    return out


def _llm_summarize(messages: List[Dict[str, str]], client, max_tokens: int = 300) -> str:
    """用 LLM 生成對話摘要（需要 OpenAI 相容客戶端）。"""
    old_text = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in messages)
    prompt = f"""請將以下對話歷史壓縮為結構化摘要，控制在 {max_tokens} token 以內。
格式：
- 任務目標：一句話
- 已完成：列出 3-5 項
- 待辦：列出 1-3 項
- 關鍵決策：列出 1-3 項

對話歷史：
{old_text[:4000]}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # 用便宜模型做摘要
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0,
        )
        return response.choices[0].message.content
    except Exception as e:
        # LLM 失敗時退回規則方法
        state = extract_state(messages)
        return format_state(state)


def estimate_tokens(messages: List[Dict[str, str]]) -> int:
    """估算訊息列表的 token 數（粗略：中文 1.5 token/字，英文 0.3 token/字，每條 +4 開銷）。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        # 簡單估算：中文字元數 * 1.5 + 英文字數 * 0.3
        chinese = len(re.findall(r'[\u4e00-\u9fff]', content))
        other = len(content) - chinese
        total += int(chinese * 1.5 + other * 0.3) + 4  # 每條訊息 4 token 結構開銷
    return total


# =====  G-3 結構化摘要 schema =====

def extract_schema_state(messages: List[Dict[str, str]], schema: tuple = ("done", "blocked", "next"),
                         sensitivity: str = "balanced") -> Dict[str, Any]:
    """按 schema 欄位抽取結構化狀態（對齊 Claude Code Auto-Compact 的 done/blocked/next）。
    schema 標籤不在 SCHEMA_KEYWORDS 時，以標籤本身當關鍵字。"""
    caps = SENSITIVITY_CAPS.get(sensitivity, SENSITIVITY_CAPS["balanced"])
    full_text = "\n".join(m.get("content", "") for m in messages)
    state = {label: [] for label in schema}
    for label in schema:
        kws = SCHEMA_KEYWORDS.get(label, [label])
        pat = r"(?:" + "|".join(re.escape(k) for k in kws) + r")[：:]?\s*(.+?)(?:\n|$)"
        cap_key = _SCHEMA_CAP_MAP.get(label, "completed")
        cap = caps[cap_key]
        for m in re.finditer(pat, full_text, re.IGNORECASE):
            item = m.group(1).strip()[:100]
            if item and item not in state[label]:
                state[label].append(item)
        state[label] = state[label][:cap]
    return state


def format_schema_state(state: Dict[str, Any]) -> str:
    """將 schema 狀態格式化為緊湊字串。"""
    lines = ["[對話狀態摘要]"]
    for label, items in state.items():
        cn = _SCHEMA_CN.get(label, label)
        lines.append(f"{cn}:")
        if items:
            for it in items:
                lines.append(f"  - {it}")
        else:
            lines.append("  - (無)")
    return "\n".join(lines)


def auto_compact(messages: List[Dict[str, str]], context_limit: int,
                 threshold: float = 0.75, schema: tuple = ("done", "blocked", "next"),
                 keep_recent: int = 3, sensitivity: str = "balanced",
                 current_tokens: int = None) -> Dict[str, Any]:
    """ G-3：當上下文用量佔比 >= threshold 自動觸發壓縮（ 閾值 95%→75%，
    對齊 Factory/產業標準 70–75%——95% 讓模型在劣化區間跑太久，zylos 2026 實證）。

    與 incremental_compressor.build_context 的分工：本函式是『批次式 / 上下文溢出觸發』入口
    （給定整段 messages + context_limit，佔比過高才壓）；incremental_compressor 是『每條消息流式』
    維護狀態。二者都遵循 should_compress 的『壓後無省益則不壓』原則。

    回傳 {triggered, compressed_messages, ratio, saved_tokens}。
    未達閾值 → triggered=False，原訊息原樣回傳（不浪費壓縮成本）。
    """
    cur = current_tokens if current_tokens is not None else estimate_tokens(messages)
    ratio = (cur / context_limit) if context_limit > 0 else 0.0
    if ratio < threshold:
        return {"triggered": False, "compressed_messages": messages,
                "ratio": ratio, "saved_tokens": 0}
    compressed = compress_messages(messages, keep_recent=keep_recent,
                                  sensitivity=sensitivity, schema=schema)
    saved = cur - estimate_tokens(compressed)
    return {"triggered": True, "compressed_messages": compressed,
            "ratio": ratio, "saved_tokens": saved}


# =====  V-4a：anchored 增量合併壓縮（對齊 Factory Anchored Iterative Summarization）=====
# 產業實證（Factory，36,000 真實 session 消息）：「把新摘要增量合併進持久錨點」優於
# 「每次整段重建」——細節漂移更少、跨多次壓縮保持連貫。錨點四欄對齊 Factory：
#   intent（任務目標）/ changes（已完成變更）/ decisions（已做決策）/ next（下一步）。
# 零 API：增量摘要用規則提取（schema 模式），非 LLM 生成——誠實標註。

ANCHOR_SCHEMA = ("done", "blocked", "next", "decisions", "intent")

def anchored_compact(messages: List[Dict[str, str]], context_limit: int,
                     anchor_path: str = None, threshold: float = 0.75,
                     keep_recent: int = 3, schema: tuple = ANCHOR_SCHEMA,
                     current_tokens: int = None) -> Dict[str, Any]:
    """：上下文佔比 >= threshold 時，只對「新丟棄區段」（messages[:-keep_recent]）做增量摘要，
    合併進持久錨點（讀既有 .ts_anchored-summary.json，無則建），輸出 = 錨點摘要 + 最近 keep_recent 輪。

    回傳 {triggered, anchor, compressed_messages, saved_tokens, ratio, merged_items}。
    未達閾值 → triggered=False 原樣回傳（防淨成本）。anchor_path=None → 不持久化（僅記憶體）。
    """
    cur = current_tokens if current_tokens is not None else estimate_tokens(messages)
    ratio = (cur / context_limit) if context_limit > 0 else 0.0
    if ratio < threshold:
        return {"triggered": False, "compressed_messages": messages,
                "ratio": ratio, "saved_tokens": 0, "anchor": None, "merged_items": 0}
    # 1) 讀既有錨點（增量基礎）
    anchor = {"intent": [], "changes": [], "decisions": [], "next": []}
    if anchor_path and os.path.exists(anchor_path):
        try:
            with open(anchor_path, "r", encoding="utf-8") as f:
                anchor = json.load(f)
            for k in anchor:
                if k not in ("intent", "changes", "decisions", "next"):
                    anchor[k] = []
        except (OSError, ValueError):
            anchor = {"intent": [], "changes": [], "decisions": [], "next": []}
    # 2) 只摘要「新丟棄區段」（增量，非整段重建）
    drop = messages[:-keep_recent] if len(messages) > keep_recent else messages
    state = extract_schema_state(drop, schema=("done", "blocked", "next"))
    merged = 0
    # 增量合併：新 items 追加進錨點（去重），intent 取最初目標
    for src_key, dst_key in (("done", "changes"), ("blocked", "next"), ("next", "next")):
        for it in state.get(src_key, []):
            if it not in anchor[dst_key]:
                anchor[dst_key].append(it)
                merged += 1
    if not anchor["intent"]:
        # 從首輪 user 消息提取任務意圖（粗略）
        for m in messages:
            if m.get("role") == "user":
                anchor["intent"].append(m["content"][:80])
                merged += 1
                break
    # 3) 組裝輸出：錨點摘要訊息 + 最近 N 輪
    anchor_text = format_anchor(anchor)
    head = [{"role": "system", "content": anchor_text}]
    compressed = head + messages[-keep_recent:]
    saved = cur - estimate_tokens(compressed)
    # 4) 持久化錨點
    if anchor_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(anchor_path)), exist_ok=True)
            with open(anchor_path, "w", encoding="utf-8") as f:
                json.dump(anchor, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
    return {"triggered": True, "anchor": anchor, "compressed_messages": compressed,
            "ratio": ratio, "saved_tokens": saved, "merged_items": merged}


def format_anchor(anchor: Dict[str, Any]) -> str:
    """錨點格式化為緊湊 system 摘要（intent/changes/decisions/next 四欄，對齊 Factory）。"""
    cn = {"intent": "任務目標", "changes": "已完成變更", "decisions": "已做決策", "next": "下一步"}
    lines = ["[anchored 對話狀態摘要]"]
    for k in ("intent", "changes", "decisions", "next"):
        lines.append(f"{cn.get(k, k)}:")
        items = anchor.get(k, [])
        if items:
            for it in items[-10:]:
                lines.append(f"  - {it}")
        else:
            lines.append("  - (無)")
    return "\n".join(lines)


# ===== 命令列使用 =====
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python compress_history.py <messages.json> [keep_recent]")
        print("示例: python compress_history.py chat_history.json 3")
        sys.exit(1)

    input_path = sys.argv[1]
    keep_recent = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    with open(input_path, "r", encoding="utf-8") as f:
        messages = json.load(f)

    original_tokens = estimate_tokens(messages)
    compressed = compress_messages(messages, keep_recent=keep_recent)
    compressed_tokens = estimate_tokens(compressed)

    print(f"原始: {len(messages)} 條訊息，約 {original_tokens} tokens")
    print(f"壓縮後: {len(compressed)} 條訊息，約 {compressed_tokens} tokens")
    print(f"節省: {100*(1-compressed_tokens/original_tokens):.1f}%")
    print("\n=== 壓縮結果 ===")
    for msg in compressed:
        role = msg["role"]
        content = msg["content"][:200] + "..." if len(msg["content"]) > 200 else msg["content"]
        print(f"\n[{role}]\n{content}")
