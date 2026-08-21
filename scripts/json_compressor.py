# -*- coding: utf-8 -*-
"""
Token Saver v5.2 — JSON 輕量壓縮
將 JSON（dict 或 list[dict]）轉為 CSV，去除每個物件重複出現的欄位名（key），
預期省 30-55% token。採用標準 csv 模組保真：含分隔符/換行的字串會自動引號。

用法：
    from json_compressor import compress_json_light, should_compress_json
    csv_text = compress_json_light(data)          # data: list[dict]
    if should_compress_json(data):
        compressed = compress_json_light(data)
"""
import csv
import io
import json
from typing import Any, Dict, List


def _cell(v: Any) -> Any:
    """單元格序列化：None→空；dict/list→JSON 字串保留；其餘原值。"""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def compress_json_light(data: Any, delimiter: str = ",", skip_negative: bool = True,
                       append_stats: bool = True) -> str:
    """JSON → CSV 去重複 key 名，省 token 且保真。

    參數：
        data: dict 或 list[dict]
        delimiter: 分隔符（預設 ','；可用 '\\t' 進一步省 token）
        skip_negative: 收益閘門（v6.7，建議 2）——CSV 不比原文短（負收益，如
            欄位少/值短的小規律 JSON，實測 -2.4%）→ 退回原文，自動跳過負收益場景
        append_stats: v6.9.4 數值校驗錨點——對含數值欄位的 dict 陣列，於 CSV 前
            附加 `# 統計:` 行（每數值欄：筆數/總和/平均/最小/最大），由「原始資料」
            算出不改寫資料，供模型交叉核對（防大表加總算錯）；非數值表不自動加
    返回：
        CSV 字串（含 header 一行）；負收益時回傳原文 JSON
    """
    if isinstance(data, str):
        # 字串輸入防呆（v6.7）：自動解析；解析失敗原樣回傳
        try:
            data = json.loads(data)
        except Exception:
            return data
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        # 非表格資料無法轉 CSV，退回 JSON（保真優先）
        return json.dumps(data, ensure_ascii=False)

    # 收集欄位（保持首次出現順序）
    cols: List[str] = []
    for row in data:
        if isinstance(row, dict):
            for k in row.keys():
                if k not in cols:
                    cols.append(k)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(cols)
    for row in data:
        if isinstance(row, dict):
            w.writerow([_cell(row.get(c)) for c in cols])
        else:
            w.writerow([_cell(row)])
    csv_out = buf.getvalue().rstrip("\n")
    if skip_negative:
        # 收益閘門：CSV 不比原文短 → 負收益（小規律 JSON 實測 -2.4%）→ 退回原文
        orig = json.dumps(data, ensure_ascii=False)
        if len(csv_out) >= len(orig):
            return orig

    # v6.9.4 數值校驗錨點：由原始資料算出，標為提示/校驗，絕不改寫資料
    if append_stats and cols:
        stat_lines = _numeric_stats_block(rows=data, cols=cols, delimiter=delimiter)
        if stat_lines:
            csv_out = stat_lines + "\n" + csv_out
    return csv_out


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _numeric_stats_block(rows: List[Any], cols: List[str], delimiter: str = ",") -> str:
    """對 dict 陣列中每個數值欄，算 筆數/總和/平均/最小/最大（由原始資料算）。

    非數值欄或無數值欄時回空字串（不加）。錯誤時安全回空（不汙染輸出）。
    """
    try:
        if not rows or not all(isinstance(r, dict) for r in rows):
            return ""
        num_cols = [c for c in cols
                    if all(_is_number(r.get(c)) for r in rows if r.get(c) is not None)
                    and any(_is_number(r.get(c)) for r in rows)]
        if not num_cols:
            return ""
        parts = []
        for c in num_cols:
            vals = [r[c] for r in rows if _is_number(r.get(c))]
            n = len(vals)
            s = sum(vals)
            avg = s / n
            parts.append(f"{c}:筆數{n}/總和{round(s, 4) if isinstance(s, float) else s}"
                         f"/平均{round(avg, 4)}/最小{min(vals)}/最大{max(vals)}")
        return "# 統計(校驗用,不改寫資料): " + " | ".join(parts)
    except Exception:
        return ""


def should_compress_json(data: Any, min_rows: int = 3) -> bool:
    """只有『多行 dict 陣列』才值得轉 CSV。

    單行 dict 或純值陣列轉 CSV 反增 header 開銷（對標 incremental 的 auto_skip 思路）。
    """
    if isinstance(data, list) and len(data) >= min_rows and all(isinstance(r, dict) for r in data):
        return True
    return False


# ===== v5.3.5 增強版：常數欄位提取 + 空欄位剔除 + 巢狀扁平化 =====

def _flatten_dict(d: Dict, prefix: str = "", sep: str = ".") -> Dict:
    """巢狀 dict 扁平化：{"a": {"b": 1}} → {"a.b": 1}。"""
    result = {}
    for k, v in d.items():
        key = f"{prefix}{sep}{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten_dict(v, key, sep))
        elif isinstance(v, list) and all(isinstance(i, (str, int, float, bool)) for i in v):
            result[key] = json.dumps(v, ensure_ascii=False)
        else:
            result[key] = v
    return result


def compress_json_enhanced(
    data: Any,
    delimiter: str = ",",
    flatten_nested: bool = True,
    drop_empty_cols: bool = True,
    extract_constants: bool = True,
    truncate_long: int = 0,
) -> str:
    """JSON → CSV 增強版（v5.3.5）。

    在輕量版基礎上增加：
    - 巢狀 dict 扁平化（a.b 欄位）
    - 全空欄位剔除
    - 常數欄位提取到 meta 行（每行值相同的欄位只寫一次）
    - 長文字截斷（truncate_long > 0 時生效，附 … 標記）

    輸出格式：
        # const: {"category": "electronics", "is_active": true}
        # cols: id,name,price,description
        1,item1,100,desc1
        2,item2,200,desc2

    參數：
        data: dict 或 list[dict]
        delimiter: 分隔符
        flatten_nested: 是否扁平化巢狀 dict
        drop_empty_cols: 是否剔除全空欄位
        extract_constants: 是否提取常數欄位到 meta
        truncate_long: 長文字截斷長度（0=不截斷）
    """
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        return json.dumps(data, ensure_ascii=False)

    # 扁平化
    if flatten_nested:
        rows = [_flatten_dict(r) if isinstance(r, dict) else r for r in data]
    else:
        rows = data

    # 收集所有欄位
    cols: List[str] = []
    for row in rows:
        if isinstance(row, dict):
            for k in row.keys():
                if k not in cols:
                    cols.append(k)

    # 剔除全空欄位
    if drop_empty_cols and cols:
        non_empty = []
        for c in cols:
            has_value = any(
                isinstance(r, dict) and r.get(c) not in (None, "", [], {})
                for r in rows
            )
            if has_value:
                non_empty.append(c)
        cols = non_empty

    # 提取常數欄位
    constants = {}
    if extract_constants and cols:
        variable_cols = []
        for c in cols:
            vals = [r.get(c) for r in rows if isinstance(r, dict)]
            if len(vals) == len(rows) and len(set(str(v) for v in vals)) == 1:
                constants[c] = rows[0].get(c)
            else:
                variable_cols.append(c)
        cols = variable_cols

    # 長文字截斷
    def _trunc(v):
        if truncate_long > 0 and isinstance(v, str) and len(v) > truncate_long:
            return v[:truncate_long] + "…"
        return v

    # 輸出
    lines = []
    if constants:
        lines.append(f"# const: {json.dumps(constants, ensure_ascii=False)}")
    lines.append(f"# cols: {delimiter.join(cols)}")

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(cols)
    for row in rows:
        if isinstance(row, dict):
            w.writerow([_cell(_trunc(row.get(c))) for c in cols])
        else:
            w.writerow([_cell(_trunc(row))])
    csv_body = buf.getvalue().rstrip("\n")

    return "\n".join(lines) + "\n" + csv_body


# ===== 演示 =====
if __name__ == "__main__":
    sample = [
        {"product": "鏡頭膜", "sales": 1200, "growth": -73.9, "region": "華南"},
        {"product": "手機殼", "sales": 3400, "growth": -45.0, "region": "華南"},
        {"product": "保護貼", "sales": 2100, "growth": 12.5, "region": "華北"},
        {"product": "支架", "sales": 880, "growth": 3.2, "region": "華北"},
    ]
    csv_text = compress_json_light(sample)
    print("=== CSV 輸出 ===")
    print(csv_text)
    print(f"\nJSON {len(json.dumps(sample, ensure_ascii=False))} 字元 → CSV {len(csv_text)} 字元")
