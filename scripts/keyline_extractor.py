#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""keyline_extractor.py — v5.5 長文本關鍵行提取（高品質保證）

替代單純的 head+tail 截斷，智能提取關鍵行：
1. 數據行：包含數字/百分比/金額的行
2. 問題行：包含錯誤/異常/警告/失敗的行
3. 結論行：包含結論/結果/總計/摘要的行
4. 去重：連續重複的行只保留第一條
5. 兜底：保留 head N 行 + tail M 行

品質保證：
- 關鍵行優先，數據/錯誤/結論不丟
- 保留上下文頭尾，避免斷章取義
- 完整內容可通過 read_more 回溯
- 不做語義理解，純正則規則，確定性可重現
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# 關鍵行模式
DATA_PATTERNS = [
    re.compile(r'\d+\.?\d*\s*%'),  # 百分比
    re.compile(r'\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?'),  # 金額/大數字
    re.compile(r'\b\d{4,}\b'),  # 4位以上數字
    re.compile(r'\b(?:mean|median|avg|average|sum|total|count|min|max|std)\b', re.I),  # 統計詞
]

ERROR_PATTERNS = [
    re.compile(r'\b(?:error|exception|fail|failed|failure|bug|crash|traceback)\b', re.I),
    re.compile(r'\b(?:warning|warn|deprecated|timeout|timed out)\b', re.I),
    re.compile(r'\b(?:異常|錯誤|失敗|警告|崩潰|超時)\b'),
]

CONCLUSION_PATTERNS = [
    re.compile(r'\b(?:conclusion|result|summary|note|therefore|hence|thus)\b', re.I),
    re.compile(r'\b(?:total|overall|final|complete|done|success)\b', re.I),
    re.compile(r'\b(?:結論|結果|摘要|總計|總體|最終|完成|成功)\b'),
]


def _line_score(line):
    """計算行的關鍵度分數（0-3）。"""
    score = 0
    for p in DATA_PATTERNS:
        if p.search(line):
            score += 1
            break
    for p in ERROR_PATTERNS:
        if p.search(line):
            score += 2  # 錯誤行權重更高
            break
    for p in CONCLUSION_PATTERNS:
        if p.search(line):
            score += 1
            break
    return score


def _is_duplicate(line, prev_lines, threshold=0.9):
    """簡單重複檢測：與前幾行高度相似則視為重複。"""
    if not prev_lines:
        return False
    line_stripped = line.strip()
    if not line_stripped:
        return False
    for prev in prev_lines[-3:]:  # 只比較最近3行
        prev_stripped = prev.strip()
        if not prev_stripped:
            continue
        # 完全相同
        if line_stripped == prev_stripped:
            return True
        # 前90%相同（簡單相似度）
        min_len = min(len(line_stripped), len(prev_stripped))
        if min_len > 20:
            common = sum(1 for a, b in zip(line_stripped, prev_stripped) if a == b)
            if common / min_len > threshold:
                return True
    return False


def extract_key_lines(text, head=10, tail=5, max_key=40, dedup=True):
    """從長文本中提取關鍵行。

    參數:
        text: 原始文本
        head: 保留開頭行數（兜底）
        tail: 保留結尾行數（兜底）
        max_key: 最多提取的關鍵行數
        dedup: 是否去重

    返回:
        (compressed_text, meta)
        meta 包含: total_lines, kept_lines, key_lines, head_lines, tail_lines, deduped
    """
    lines = text.split("\n")
    total = len(lines)

    # 短文本直通
    if total <= head + tail + 10:
        return text, {"total_lines": total, "kept_lines": total, "compressed": False}

    # 1. 標記每行的分數和原始索引
    scored = []
    for i, line in enumerate(lines):
        score = _line_score(line)
        if score > 0:
            scored.append((i, score, line))

    # 2. 按分數排序
    scored.sort(key=lambda x: (-x[1], x[0]))

    # 2a. 高優先級行（score>=3，即錯誤行）不受 max_key 限制，全部保留
    key_indices = set()
    high_priority_count = 0
    prev_key_lines = []
    for idx, score, line in scored:
        if score < 3:
            break  # 後面都是低分行了
        if idx < head or idx >= total - tail:
            continue
        key_indices.add(idx)
        prev_key_lines.append(line)
        high_priority_count += 1

    # 2b. 普通關鍵行（score 1-2）受 max_key 限制
    normal_count = 0
    for idx, score, line in scored:
        if score >= 3:
            continue  # 已處理
        if normal_count >= max_key:
            break
        if idx < head or idx >= total - tail:
            continue
        if idx in key_indices:
            continue
        # 去重（分數>=2的數據/結論行不去重，只有低分普通行才去重）
        if dedup and score < 2 and _is_duplicate(line, prev_key_lines):
            continue
        key_indices.add(idx)
        prev_key_lines.append(line)
        normal_count += 1

    # 3. 合併 head + key + tail，按原始順序排列
    keep_indices = set(range(head)) | key_indices | set(range(total - tail, total))
    keep_sorted = sorted(keep_indices)

    # 4. 構建輸出，在跳過的區域加省略標記
    output = []
    prev_idx = -1
    deduped = 0
    for idx in keep_sorted:
        if prev_idx >= 0 and idx > prev_idx + 1:
            skipped = idx - prev_idx - 1
            output.append(f"... [省略 {skipped} 行]")
        output.append(lines[idx])
        prev_idx = idx

    compressed = "\n".join(output)
    meta = {
        "total_lines": total,
        "kept_lines": len(keep_sorted),
        "key_lines": high_priority_count + normal_count,
        "high_priority_lines": high_priority_count,
        "head_lines": head,
        "tail_lines": tail,
        "deduped": deduped,
        "compressed": True,
        "kind": "keyline",
    }
    return compressed, meta


def main():
    import argparse
    ap = argparse.ArgumentParser(description="長文本關鍵行提取（v5.5）")
    ap.add_argument("path", help="輸入文件路徑")
    ap.add_argument("--head", type=int, default=10, help="保留開頭行數")
    ap.add_argument("--tail", type=int, default=5, help="保留結尾行數")
    ap.add_argument("--max-key", type=int, default=40, help="最多關鍵行數")
    ap.add_argument("--no-dedup", action="store_true", help="關閉去重")
    a = ap.parse_args()

    with open(a.path, "r", encoding="utf-8-sig") as f:
        text = f.read()

    compressed, meta = extract_key_lines(
        text, head=a.head, tail=a.tail, max_key=a.max_key, dedup=not a.no_dedup
    )
    print(compressed)
    print(f"\n--- 統計 ---")
    print(f"原始: {meta['total_lines']} 行")
    print(f"保留: {meta['kept_lines']} 行（head {meta['head_lines']} + key {meta['key_lines']} + tail {meta['tail_lines']}）")
    print(f"降幅: {round((1 - meta['kept_lines']/meta['total_lines'])*100, 1)}%")


if __name__ == "__main__":
    main()
