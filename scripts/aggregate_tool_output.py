# -*- coding: utf-8 -*-
"""
tokknife — 工具回傳自動聚合腳本
將大型 CSV/JSON 工具回傳壓縮為精簡結構，減少 80-95% 進入 LLM 上下文的 token。

用法：
    from aggregate_tool_output import aggregate_dataframe, aggregate_json
    result = aggregate_dataframe(df, key_cols=['product'], metric_cols=['sales','growth'], top_n=5)
    # result = {"meta": {...}, "summary": {...}, "top_records": [...], "anomalies": [...]}
"""
import json
from typing import List, Dict, Any, Optional


def _detect_outliers_iqr(values: List[float], threshold: float = 1.5) -> List[int]:
    """用 IQR 方法檢測異常值，返回異常值的索引列表。"""
    if len(values) < 4:
        return []
    sorted_v = sorted(values)
    n = len(sorted_v)
    q1 = sorted_v[n // 4]
    q3 = sorted_v[(3 * n) // 4]
    iqr = q3 - q1
    if iqr == 0:
        return []
    lower = q1 - threshold * iqr
    upper = q3 + threshold * iqr
    return [i for i, v in enumerate(values) if v < lower or v > upper]


def _numeric_summary(values: List[float]) -> Dict[str, float]:
    """生成數值列的統計摘要。"""
    if not values:
        return {}
    sorted_v = sorted(values)
    n = len(sorted_v)
    return {
        "count": n,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(sum(values) / n, 4),
        "median": round(sorted_v[n // 2], 4),
        "p25": round(sorted_v[n // 4], 4),
        "p75": round(sorted_v[(3 * n) // 4], 4),
    }


def aggregate_dataframe(
    df,
    key_cols: List[str],
    metric_cols: List[str],
    top_n: int = 5,
    sort_by: Optional[str] = None,
    ascending: bool = False,
    outlier_cols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    聚合 pandas DataFrame 工具回傳。

    參數：
        df: pandas DataFrame
        key_cols: 主鍵列（保留在 top_records 和 anomalies 中）
        metric_cols: 數值指標列（用於統計摘要和排序）
        top_n: 返回前 N 條記錄
        sort_by: 排序依據的指標列（預設用 metric_cols[0]）
        ascending: 是否升序（預設 False，取最大的前 N）
        outlier_cols: 要檢測異常值的指標列（預設等於 metric_cols）

    返回：
        {
            "meta": {"total_rows": int, "returned_rows": int, "aggregated": bool},
            "summary": {col: {count,min,max,mean,median,p25,p75}},
            "top_records": [{key_col: val, metric_col: val}, ...],
            "anomalies": [{key_col: val, metric_col: val, "reason": str}, ...]
        }
    """
    if outlier_cols is None:
        outlier_cols = metric_cols
    if sort_by is None:
        sort_by = metric_cols[0] if metric_cols else None

    total_rows = len(df)

    # 統計摘要
    summary = {}
    for col in metric_cols:
        if col in df.columns:
            vals = pd_to_numeric(df[col])
            if vals:
                summary[col] = _numeric_summary(vals)

    # Top-N 記錄
    top_records = []
    if sort_by and sort_by in df.columns and total_rows > 0:
        df_sorted = df.sort_values(by=sort_by, ascending=ascending).head(top_n)
        keep_cols = [c for c in key_cols + metric_cols if c in df.columns]
        for _, row in df_sorted.iterrows():
            record = {}
            for c in keep_cols:
                val = row[c]
                if isinstance(val, float):
                    val = round(val, 4)
                record[c] = val
            top_records.append(record)

    # 異常值檢測
    anomalies = []
    for col in outlier_cols:
        if col in df.columns and total_rows >= 4:
            vals = pd_to_numeric(df[col])
            if vals:
                outlier_indices = _detect_outliers_iqr(vals)
                keep_cols = [c for c in key_cols + [col] if c in df.columns]
                for idx in outlier_indices[:5]:  # 最多返回 5 個異常
                    if idx < total_rows:
                        row = df.iloc[idx]
                        anomaly = {}
                        for c in keep_cols:
                            val = row[c]
                            if isinstance(val, float):
                                val = round(val, 4)
                            anomaly[c] = val
                        anomaly["_outlier_in"] = col
                        anomalies.append(anomaly)

    return {
        "meta": {
            "total_rows": total_rows,
            "returned_rows": len(top_records),
            "anomaly_count": len(anomalies),
            "aggregated": True,
            "original_size_estimate": f"~{total_rows * len(df.columns) * 8} tokens",
            "compressed_size_estimate": f"~{len(json.dumps({'summary': summary, 'top': top_records, 'anomalies': anomalies}, ensure_ascii=False)) // 2} tokens",
        },
        "summary": summary,
        "top_records": top_records,
        "anomalies": anomalies,
    }


def aggregate_json(
    data: List[Dict[str, Any]],
    key_cols: List[str],
    metric_cols: List[str],
    top_n: int = 5,
    sort_by: Optional[str] = None,
    ascending: bool = False,
) -> Dict[str, Any]:
    """
    聚合 JSON 列表（字典陣列）工具回傳。不需要 pandas。

    參數同 aggregate_dataframe。
    """
    if not data:
        return {"meta": {"total_rows": 0, "aggregated": True}, "summary": {}, "top_records": [], "anomalies": []}

    if sort_by is None:
        sort_by = metric_cols[0] if metric_cols else None

    total_rows = len(data)

    # 統計摘要
    summary = {}
    for col in metric_cols:
        vals = [float(row[col]) for row in data if col in row and _is_numeric(row[col])]
        if vals:
            summary[col] = _numeric_summary(vals)

    # Top-N
    top_records = []
    if sort_by and total_rows > 0:
        sorted_data = sorted(
            data,
            key=lambda x: float(x.get(sort_by, 0)) if _is_numeric(x.get(sort_by, 0)) else 0,
            reverse=not ascending,
        )
        keep_cols = [c for c in key_cols + metric_cols if c in data[0]]
        for row in sorted_data[:top_n]:
            record = {}
            for c in keep_cols:
                val = row.get(c)
                if isinstance(val, float):
                    val = round(val, 4)
                record[c] = val
            top_records.append(record)

    # 異常值
    anomalies = []
    for col in metric_cols:
        vals = [float(row[col]) for row in data if col in row and _is_numeric(row[col])]
        if len(vals) >= 4:
            outlier_indices = _detect_outliers_iqr(vals)
            keep_cols = [c for c in key_cols + [col] if c in data[0]]
            for idx in outlier_indices[:5]:
                if idx < total_rows:
                    row = data[idx]
                    anomaly = {}
                    for c in keep_cols:
                        val = row.get(c)
                        if isinstance(val, float):
                            val = round(val, 4)
                        anomaly[c] = val
                    anomaly["_outlier_in"] = col
                    anomalies.append(anomaly)

    return {
        "meta": {
            "total_rows": total_rows,
            "returned_rows": len(top_records),
            "anomaly_count": len(anomalies),
            "aggregated": True,
        },
        "summary": summary,
        "top_records": top_records,
        "anomalies": anomalies,
    }


def _is_numeric(val) -> bool:
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def pd_to_numeric(series) -> List[float]:
    """將 pandas Series 轉為 float 列表，跳過非數值。"""
    result = []
    for v in series:
        try:
            result.append(float(v))
        except (ValueError, TypeError):
            continue
    return result


def format_for_llm(aggregated: Dict[str, Any], compact: bool = False) -> str:
    """
    將聚合結果格式化為適合進入 LLM 上下文的緊湊字串。
    比 JSON.dumps 再省 20-30% token。
     新增 compact=True：去重複欄位名（header 一次）＋統計濃縮一行。
    """
    if not compact:
        lines = []
        meta = aggregated.get("meta", {})
        lines.append(f"[資料摘要] 共{meta.get('total_rows', 0)}行，已聚合，返回Top{meta.get('returned_rows', 0)}+{meta.get('anomaly_count', 0)}異常")

        summary = aggregated.get("summary", {})
        if summary:
            lines.append("[統計]")
            for col, stats in summary.items():
                lines.append(f"  {col}: n={stats['count']} mean={stats['mean']} min={stats['min']} max={stats['max']} med={stats['median']}")

        top = aggregated.get("top_records", [])
        if top:
            lines.append("[Top紀錄]")
            for i, rec in enumerate(top, 1):
                lines.append(f"  {i}. " + ", ".join(f"{k}={v}" for k, v in rec.items()))

        anomalies = aggregated.get("anomalies", [])
        if anomalies:
            lines.append("[異常值]")
            for rec in anomalies:
                lines.append("  " + ", ".join(f"{k}={v}" for k, v in rec.items()))

        return "\n".join(lines)

    # ===== compact 模式 =====
    meta = aggregated.get("meta", {})
    lines = [f"[資料] {meta.get('total_rows', 0)}行 Top-{meta.get('returned_rows', 0)}"]
    summary = aggregated.get("summary", {})
    if summary:
        stat_parts = []
        for col, st in summary.items():
            stat_parts.append(f"{col}:μ{st['mean']}[{st['min']}~{st['max']}]")
        lines.append(" ".join(stat_parts))

    top = aggregated.get("top_records", [])
    if top:
        cols = list(top[0].keys())
        lines.append("|".join(cols))
        for rec in top:
            lines.append("|".join(str(rec.get(c, "")) for c in cols))

    anomalies = aggregated.get("anomalies", [])
    if anomalies:
        cols = [c for c in anomalies[0].keys() if c != "_outlier_in"]
        if cols:
            for rec in anomalies[:3]:
                lines.append("! " + "|".join(str(rec.get(c, "")) for c in cols))

    return "\n".join(lines)


def auto_aggregate_json(data: List[Dict[str, Any]], threshold: int = 20, top_n: int = 5,
                        key_cols: Optional[List[str]] = None, metric_cols: Optional[List[str]] = None) -> Dict[str, Any]:
    """工具回傳自動聚合：超過 threshold 條才聚合，否則原樣返回（避免小資料也過度處理）。
    供集成指南的 middleware 使用。"""
    if not isinstance(data, list) or len(data) <= threshold:
        return {"meta": {"total_rows": len(data), "returned_rows": len(data),
                         "anomaly_count": 0, "aggregated": False}, "raw": data}
    agg = aggregate_json(data, key_cols or [], metric_cols or [], top_n=top_n)
    # 無 key_cols 時 groupby 可能空 → 補原始前 N 條，確保有代表性內容
    if not agg.get("top_records"):
        agg["top_records"] = data[:top_n]
        agg["meta"]["returned_rows"] = min(top_n, len(data))
    return agg


# ===== 命令列使用 =====
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python aggregate_tool_output.py <input.json> [key_col1,key_col2] [metric_col1,metric_col2] [top_n]")
        print("示例: python aggregate_tool_output.py sales.json product,region sales,growth 5")
        sys.exit(1)

    input_path = sys.argv[1]
    key_cols = sys.argv[2].split(",") if len(sys.argv) > 2 else []
    metric_cols = sys.argv[3].split(",") if len(sys.argv) > 3 else []
    top_n = int(sys.argv[4]) if len(sys.argv) > 4 else 5

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        result = aggregate_json(data, key_cols, metric_cols, top_n=top_n)
    else:
        print("錯誤：輸入必須是 JSON 陣列")
        sys.exit(1)

    print(format_for_llm(result))
    print(f"\n--- 壓縮比：原始 {len(json.dumps(data, ensure_ascii=False))} 字元 → 聚合 {len(format_for_llm(result))} 字元 (省 {100*(1-len(format_for_llm(result))/len(json.dumps(data, ensure_ascii=False))):.1f}%) ---")
