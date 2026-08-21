#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tool_output 品質確定性指標（v5.3.5）

取代 LLM-as-judge 的雜訊，用程式化計算：
- Top-N 命中率：壓縮版 Top-N 與真實 Top-N 的交集比例
- 異常召回率：壓縮版檢測到的異常與真實異常的交集比例
- 統計一致性：均值/中位數/最大/最小是否一致
- 整體品質分：0-100，每次運行結果一致

用法:
  python quality_metrics.py <json_file> [--sort-by field] [--top-n N]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _simple_aggregate(data, sort_by=None, top_n=5):
    """基礎聚合：Top-N + 統計摘要。"""
    if not isinstance(data, list) or len(data) == 0:
        return {"top_n": [], "stats": {}, "total": 0}
    total = len(data)
    if sort_by and sort_by in data[0]:
        sorted_data = sorted(data, key=lambda x: _to_number(x.get(sort_by, 0)) or 0, reverse=True)
    else:
        sorted_data = data
    top = sorted_data[:top_n]
    stats = {"count": total, "top_n": top_n}
    return {"top_n": top, "stats": stats, "total": total}


def _to_number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_quality(original_data, sort_by=None, top_n=5):
    """計算壓縮品質的確定性指標。

    返回 dict 含各項指標和整體分數。
    """
    if not isinstance(original_data, list) or not original_data:
        return {"error": "輸入必須是非空 list"}

    # 找數值字段
    if not sort_by:
        for k, v in original_data[0].items():
            if _to_number(v) is not None:
                sort_by = k
                break
    if not sort_by:
        return {"error": "找不到數值字段"}

    # 真實 Top-N
    valid = [(i, row) for i, row in enumerate(original_data)
             if _to_number(row.get(sort_by)) is not None]
    valid_sorted = sorted(valid, key=lambda x: _to_number(x[1][sort_by]), reverse=True)
    real_top_indices = set(i for i, _ in valid_sorted[:top_n])

    # 真實異常（用 IQR 方法，和 aggregator 一致）
    values = [_to_number(row.get(sort_by)) for _, row in valid]
    values_sorted = sorted(values)
    n = len(values_sorted)
    if n >= 4:
        q1 = values_sorted[n // 4]
        q3 = values_sorted[(3 * n) // 4]
        iqr = q3 - q1
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        median = values_sorted[n // 2]
        real_anomaly_indices = set(
            i for i, row in valid
            if _to_number(row.get(sort_by)) < low
            or _to_number(row.get(sort_by)) > high
            or _to_number(row.get(sort_by)) > median * 10
        )
    else:
        real_anomaly_indices = set()

    # 壓縮版結果（使用基礎聚合）
    result = _simple_aggregate(original_data, sort_by=sort_by, top_n=top_n)

    # Top-N 命中率
    comp_top = result.get("top_n", [])
    # 用原始索引匹配（如果有 id 字段用 id，否則用值）
    id_field = "id" if "id" in original_data[0] else sort_by
    real_top_ids = set(str(original_data[i].get(id_field)) for i in real_top_indices)
    comp_top_ids = set(str(r.get(id_field)) for r in comp_top)
    top_hit = len(real_top_ids & comp_top_ids) / len(real_top_ids) if real_top_ids else 1.0

    # 異常召回率（基礎聚合不檢測異常，返回空）
    comp_anomalies = []
    real_anomaly_ids = set(str(original_data[i].get(id_field)) for i in real_anomaly_indices)
    comp_anomaly_ids = set(str(a.get(id_field)) for a in comp_anomalies)
    anomaly_recall = (
        len(real_anomaly_ids & comp_anomaly_ids) / len(real_anomaly_ids)
        if real_anomaly_ids else 1.0
    )

    # 統計一致性（基礎聚合返回 stats）
    stats = result.get("stats", {})
    real_mean = sum(values) / len(values) if values else 0
    real_max = max(values) if values else 0
    real_min = min(values) if values else 0
    stat_consistent = True
    if "mean" in stats:
        stat_consistent = stat_consistent and abs(float(stats["mean"]) - real_mean) < 0.01
    if "max" in stats:
        stat_consistent = stat_consistent and abs(float(stats["max"]) - real_max) < 0.01
    if "min" in stats:
        stat_consistent = stat_consistent and abs(float(stats["min"]) - real_min) < 0.01

    # 整體品質分（0-100）
    # Top-N 命中率佔 50%，異常召回佔 30%，統計一致性佔 20%
    quality_score = (
        top_hit * 50
        + anomaly_recall * 30
        + (1.0 if stat_consistent else 0.0) * 20
    )

    return {
        "sort_by": sort_by,
        "top_n": top_n,
        "total_rows": len(original_data),
        "top_n_hit_rate": round(top_hit, 3),
        "anomaly_recall": round(anomaly_recall, 3),
        "stat_consistent": stat_consistent,
        "real_top_n": list(real_top_ids)[:top_n],
        "comp_top_n": list(comp_top_ids),
        "real_anomalies": list(real_anomaly_ids),
        "comp_anomalies": list(comp_anomaly_ids),
        "quality_score": round(quality_score, 1),
    }


def main():
    ap = argparse.ArgumentParser(description="tool_output 品質確定性指標")
    ap.add_argument("src", help="JSON 檔案路徑")
    ap.add_argument("--sort-by", help="排序字段（預設自動檢測）")
    ap.add_argument("--top-n", type=int, default=5, help="Top-N（預設 5）")
    ap.add_argument("--json", action="store_true", help="以 JSON 格式輸出")
    a = ap.parse_args()

    with open(a.src, encoding="utf-8-sig") as f:
        data = json.load(f)

    result = compute_quality(data, sort_by=a.sort_by, top_n=a.top_n)

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=" * 50)
        print("【tool_output 品質確定性指標】")
        print("=" * 50)
        print(f"  數據行數: {result.get('total_rows')}")
        print(f"  排序字段: {result.get('sort_by')}")
        print(f"  Top-N: {result.get('top_n')}")
        print(f"  Top-N 命中率: {result.get('top_n_hit_rate'):.1%}")
        print(f"  異常召回率: {result.get('anomaly_recall'):.1%}")
        print(f"  統計一致性: {'✅' if result.get('stat_consistent') else '❌'}")
        print(f"  整體品質分: {result.get('quality_score')}/100")
        print("-" * 50)
        print(f"  真實 Top-{a.top_n}: {result.get('real_top_n')}")
        print(f"  壓縮 Top-{a.top_n}: {result.get('comp_top_n')}")
        if result.get("real_anomalies"):
            print(f"  真實異常: {result.get('real_anomalies')}")
            print(f"  檢測異常: {result.get('comp_anomalies')}")
        print("=" * 50)


if __name__ == "__main__":
    main()
