#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conversation_compressor.py —  對話壓縮增強（高品質保證）

在 JSON→CSV 基礎上，針對多輪對話做專用壓縮：
1. 說話人角色合併（user→U, assistant→A, system→S）
2. 長消息折疊（超過 N 行 → 前2行+後1行+[折疊M行]）
3. 重複消息檢測（完全相同的消息合併計數）
4. 時間戳精簡（去掉冗餘時間戳）
5. **品質保證**：每輪消息保留索引，可通過 read_more 回溯完整內容

用法:
  python conversation_compressor.py conversation.json
  python conversation_compressor.py conversation.json --max-lines 3
  python conversation_compressor.py conversation.json --json
"""
import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


ROLE_MAP = {
    "user": "U",
    "assistant": "A",
    "system": "S",
    "tool": "T",
    "function": "F",
}


def _role_short(role):
    return ROLE_MAP.get(role, role[0].upper() if role else "?")


def _content_lines(msg):
    """提取消息內容的行列表。"""
    content = msg.get("content", "")
    if isinstance(content, list):
        # 多模態內容，提取文本部分
        texts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(part.get("text", ""))
        content = "\n".join(texts)
    return str(content).split("\n") if content else []


def _fold_message(lines, max_lines=3, max_chars=200):
    """折疊長消息：
    - 多行：前 max_lines 行 + 後1行 + 折疊標記
    - 單行長文本：前 max_chars 字符 + 截斷標記
    """
    # 單行長文本截斷
    if len(lines) == 1 and len(lines[0]) > max_chars:
        head = lines[0][:max_chars]
        truncated = len(lines[0]) - max_chars
        return [f"{head} ... [截斷 {truncated} 字符]"], 0

    if len(lines) <= max_lines + 1:
        return lines, 0

    head = lines[:max_lines]
    tail = lines[-1:] if lines[-1].strip() else []
    folded = len(lines) - max_lines - len(tail)
    marker = f"  ... [折疊 {folded} 行]"
    return head + [marker] + tail, folded


def _msg_hash(msg):
    """計算消息哈希用於重複檢測。"""
    content = msg.get("content", "")
    if isinstance(content, list):
        content = json.dumps(content, sort_keys=True, ensure_ascii=False)
    role = msg.get("role", "")
    return hashlib.md5(f"{role}:{content}".encode("utf-8")).hexdigest()[:8]


def compress_conversation(messages, max_lines=3, max_chars=200, dedup=True):
    """壓縮對話，返回 (compressed_text, meta)。

    meta 包含：
    - total_messages: 原始消息數
    - compressed_messages: 壓縮後消息數
    - folded_count: 被折疊的長消息數
    - dedup_count: 被合併的重複消息數
    - total_folded_lines: 總共折疊的行數
    - full_messages: 完整消息列表（用於 read_more 回溯）
    """
    if not messages:
        return "", {"total_messages": 0, "compressed_messages": 0}

    total = len(messages)
    folded_count = 0
    total_folded_lines = 0
    dedup_count = 0
    seen_hashes = {}
    output_lines = []
    full_messages = []

    for idx, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        short_role = _role_short(role)
        lines = _content_lines(msg)
        msg_hash = _msg_hash(msg)

        # 保存完整內容用於回溯
        full_messages.append({
            "index": idx,
            "role": role,
            "content": msg.get("content", ""),
            "hash": msg_hash,
        })

        # 重複檢測
        if dedup and msg_hash in seen_hashes:
            prev_idx = seen_hashes[msg_hash]
            output_lines.append(f"[{idx}] {short_role}: [與 #{prev_idx} 相同]")
            dedup_count += 1
            continue
        seen_hashes[msg_hash] = idx

        # 長消息折疊（多行超過閾值，或單行超過字符閾值）
        is_long = (len(lines) > max_lines + 1) or (len(lines) == 1 and len(lines[0]) > max_chars)
        if is_long:
            folded, n_folded = _fold_message(lines, max_lines, max_chars)
            folded_count += 1
            total_folded_lines += n_folded
            output_lines.append(f"[{idx}] {short_role}:")
            for line in folded:
                output_lines.append(f"  {line}")
        else:
            # 短消息直接輸出
            if len(lines) == 1:
                output_lines.append(f"[{idx}] {short_role}: {lines[0]}")
            else:
                output_lines.append(f"[{idx}] {short_role}:")
                for line in lines:
                    output_lines.append(f"  {line}")

    compressed = "\n".join(output_lines)
    meta = {
        "total_messages": total,
        "compressed_messages": total - dedup_count,
        "folded_count": folded_count,
        "dedup_count": dedup_count,
        "total_folded_lines": total_folded_lines,
        "full_messages": full_messages,
        "kind": "conversation",
    }
    return compressed, meta


def read_more_conversation(meta, index):
    """回溯指定索引的完整消息。"""
    full = meta.get("full_messages", [])
    if 0 <= index < len(full):
        msg = full[index]
        return f"[{msg['index']}] {msg['role']}:\n{msg['content']}"
    return f"消息索引 {index} 不存在"


def _detect_conversation(data):
    """檢測 JSON 數據是否為對話格式。"""
    if not isinstance(data, list):
        return False
    if len(data) == 0:
        return False
    first = data[0]
    if not isinstance(first, dict):
        return False
    # 對話消息通常有 role + content
    has_role = "role" in first
    has_content = "content" in first
    return has_role and has_content


def main():
    ap = argparse.ArgumentParser(description="對話壓縮增強（，高品質保證）")
    ap.add_argument("path", help="對話 JSON 文件路徑")
    ap.add_argument("--max-lines", type=int, default=3, help="長消息折疊閾值（預設3行）")
    ap.add_argument("--max-chars", type=int, default=200, help="單行長消息截斷閾值（預設200字符）")
    ap.add_argument("--no-dedup", action="store_true", help="關閉重複消息檢測")
    ap.add_argument("--json", action="store_true", help="JSON 格式輸出")
    a = ap.parse_args()

    with open(a.path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if not _detect_conversation(data):
        print("警告：輸入文件不是標準對話格式（需要 role+content 的數組）")
        # 嘗試常見的嵌套格式
        if isinstance(data, dict) and "messages" in data:
            data = data["messages"]
        else:
            return

    compressed, meta = compress_conversation(
        data, max_lines=a.max_lines, max_chars=a.max_chars, dedup=not a.no_dedup
    )

    if a.json:
        out = {
            "compressed": compressed,
            "meta": {k: v for k, v in meta.items() if k != "full_messages"},
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(compressed)
        print(f"\n--- 壓縮統計 ---")
        print(f"原始消息: {meta['total_messages']} 輪")
        print(f"壓縮後: {meta['compressed_messages']} 輪")
        print(f"折疊長消息: {meta['folded_count']} 條（共折疊 {meta['total_folded_lines']} 行）")
        print(f"重複合併: {meta['dedup_count']} 條")


if __name__ == "__main__":
    main()
