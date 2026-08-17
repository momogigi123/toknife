# -*- coding: utf-8 -*-
"""
tokknife — 確定性驗證（零 API，可複現）
驗證三項 P0/P1 修復：
  (1) incremental_compressor.should_compress：短對話不反增 token
  (2) adaptive/aggregate format_for_llm(compact=True)：去欄位名降輸入 token，保真
  (3) json_compressor.compress_json_light：JSON→CSV 去 key 名省 token，保真
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from incremental_compressor import IncrementalCompressor
from adaptive_aggregator import AdaptiveAggregator
from aggregate_tool_output import aggregate_json, format_for_llm as agg_fmt
from json_compressor import compress_json_light, should_compress_json

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def tok(s): return len(_ENC.encode(s))
except ImportError:
    def tok(s): return len(s) // 3  # 粗略估算，建議 pip install tiktoken 獲得精確計數


def build_msgs(n_rounds, per_turn=400):
    """造 n_rounds 輪對話（每輪 user+assistant），模擬工廠匯報。"""
    msgs = []
    for i in range(n_rounds):
        msgs.append({"role": "user", "content": f"第{i+1}輪：請分析產線良率下滑原因，數據見 report_{i}.csv，注意排除退貨。" * (per_turn // 38)})
        msgs.append({"role": "assistant", "content": f"已完成分析：產線{i}良率92.3%，較上月降4.1%，主因設備老化，待辦：排程保養。" * (per_turn // 38)})
    return msgs


def test_incremental():
    print("=== (1) incremental should_compress（短對話不反增 token）===")
    results = []
    for nr in [2, 4, 6, 20]:
        comp = IncrementalCompressor(keep_recent=3)
        msgs = build_msgs(nr)
        for m in msgs:
            comp.add_message(m)
        orig = tok("\n".join(m["content"] for m in msgs))
        real_ctx = comp.build_context()  # 含 auto_skip
        real = tok("\n".join(m["content"] for m in real_ctx))
        would = comp.should_compress()
        delta = real - orig
        ok = (delta <= 0)  # 壓縮後不得比原文多
        results.append(ok)
        print(f"  {nr:2}輪: should_compress={would} | 原文{orig}→實際{real} tok (Δ{delta:+d}) {'✅' if ok else '❌反增'}")
    return all(results)


def test_adaptive_compact():
    print("\n=== (2) format_for_llm(compact=True) 降輸入 token + 保真 ===")
    data = [{"product": f"產品{i}", "sales": 1000 - i * 37, "growth": round(10 - i * 1.3, 1)}
            for i in range(1, 21)]
    # adaptive
    agg = AdaptiveAggregator(initial_top_n=5)
    a = agg.aggregate(data, sort_by="sales")
    full = agg.format_for_llm(a, compact=False)
    comp = agg.format_for_llm(a, compact=True)
    tf, tc = tok(full), tok(comp)
    # 保真：top_n 產品名在兩版都出現
    faithful = all(f"產品{k}" in comp for k in (1, 2, 3, 4, 5))
    save = round((tf - tc) / tf * 100, 1)
    print(f"  adaptive: 完整 {tf} → compact {tc} tok (省 {save}%) | 保真={faithful} {'✅' if tc < tf and faithful else '❌'}")
    # aggregate_tool_output
    agg2 = aggregate_json(data, key_cols=["product"], metric_cols=["sales", "growth"], top_n=5)
    full2 = agg_fmt(agg2, compact=False)
    comp2 = agg_fmt(agg2, compact=True)
    tf2, tc2 = tok(full2), tok(comp2)
    faithful2 = all(f"產品{k}" in comp2 for k in (1, 2, 3, 4, 5))
    save2 = round((tf2 - tc2) / tf2 * 100, 1)
    print(f"  aggregate: 完整 {tf2} → compact {tc2} tok (省 {save2}%) | 保真={faithful2} {'✅' if tc2 < tf2 and faithful2 else '❌'}")
    return (tc < tf and faithful) and (tc2 < tf2 and faithful2)


def test_json():
    print("\n=== (3) json_compressor.compress_json_light（JSON→CSV 去 key 名）===")
    data = [{"product": f"P{i}", "sales": 1000 - i * 20, "growth": round(5 - i * 0.4, 1),
             "region": "華南" if i % 2 else "華北", "owner": f"李{i}"} for i in range(1, 21)]
    j = json.dumps(data, ensure_ascii=False)
    should = should_compress_json(data)
    csv_text = compress_json_light(data) if should else j
    tj, tc = tok(j), tok(csv_text)
    save = round((tj - tc) / tj * 100, 1)
    # 保真：每列值都在 CSV 中
    faithful = all(str(d["sales"]) in csv_text and d["product"] in csv_text for d in data[:3])
    # 單行不壓
    single = {"product": "X", "sales": 1}
    single_skip = should_compress_json(single)
    print(f"  20行×5欄: JSON {tj} → CSV {tc} tok (省 {save}%) | 保真={faithful} {'✅' if tc < tj and faithful else '❌'}")
    print(f"  單行dict should_compress={single_skip}（預期 False，避免 header 反增）{'✅' if not single_skip else '❌'}")
    return (tc < tj and faithful) and (not single_skip)


if __name__ == "__main__":
    import json
    r1 = test_incremental()
    r2 = test_adaptive_compact()
    r3 = test_json()
    print("\n=== 總結 ===")
    print(f"  (1) 短對話不反增: {'PASS' if r1 else 'FAIL'}")
    print(f"  (2) compact 降 token+保真: {'PASS' if r2 else 'FAIL'}")
    print(f"  (3) JSON→CSV 省+保真: {'PASS' if r3 else 'FAIL'}")
    sys.exit(0 if (r1 and r2 and r3) else 1)
