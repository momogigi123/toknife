# -*- coding: utf-8 -*-
"""
tokknife — 確定性驗證（零 API，可複現）
驗證三項 P0/P1 落地 + 兩項  回歸：
  (1) code medium 折疊：代碼降幅 31% → ~50%，短函數保邏輯、長函數保控制流骨架
  (2) adaptive_aggregator 校準：compact 輸出再降 15-20%（剔空/常數欄位 + 長 cell 截斷 + 大樣本收緊 Top-N）
  (3) MCP 透明代理：攔截壓縮決策 + read_more 回溯保真 + 短輸出直通
  (4) [回歸] 短對話動態閾值（）：短對話不反增 token
  (5) [回歸] JSON→CSV（）：多行 dict 陣列省 ≥30%
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def _tk(s): return len(_ENC.encode(s))
except Exception:
    def _tk(s): return len(s) // 3

import code_context_extractor as cce
import adaptive_aggregator as aa
import json_compressor as jc
import mcp_proxy as mp
from incremental_compressor import IncrementalCompressor


# ===== (1) code medium 折疊 =====

LARGE_MODULE = '''# -*- coding: utf-8 -*-
"""大型訂單處理模組"""

CONFIG_TIMEOUT = 30
CONFIG_RETRY = 3


class OrderService:
    """訂單服務（含訂單處理與校驗）"""

    def process(self, payload):
        # 初始化結果
        result = {"id": 0, "ok": True}
        for k, v in payload.items():
            result[k] = v  # BUG: payload 若有 id/ok 鍵會覆寫
        return result

    def validate(self, order):
        """校驗訂單"""
        if not order:
            return False
        return order.get("amount", 0) > 0


def process_orders(orders):
    """批量處理訂單：主流程（長函數，40 行內含多層控制流）"""
    processed = []
    total = 0
    for order in orders:
        if not order:
            continue
        amount = order.get("amount", 0)
        if amount <= 0:
            raise ValueError("amount 必須為正數")
        total += amount
        for item in order.get("items", []):
            if item.get("qty", 0) > 100:
                print("warning: 大量訂購")
                continue
            processed.append(item)
        # 省略更多步驟：折扣、稅金、庫存扣減、通知
        discount = amount * 0.1
        tax = discount * 0.05
        final = amount - discount + tax
        processed.append({"order_id": order.get("id"), "final": final})
        # 後續處理：物流、庫存、對帳
        shipping = final * 0.02
        warehouse = final * 0.03
        if shipping > 500:
            print("免運門檻檢查")
        if warehouse > 300:
            print("倉儲費異常")
        note = {"shipping": shipping, "warehouse": warehouse}
        processed[-1].update(note)
    if total > 100000:
        print("高額訂單需人工審核")
    return processed
'''


def test_code_medium():
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(LARGE_MODULE)
        raw = _tk(LARGE_MODULE)
        light = cce.compress_code_light(path)
        medium = cce.compress_code_medium(path, fold_threshold=25, keep_head=6)
        lt, mt = _tk(light), _tk(medium)
        # 1) medium 比 light 更省（折疊長函數體）
        save_light = (raw - lt) / raw * 100
        save_medium = (raw - mt) / raw * 100
        # 2) 短函數（OrderService.process 12 行 < 25）保留 bug 邏輯行
        keeps_short_bug = "result[k] = v" in medium
        # 3) 長函數保留控制流骨架（for / if / raise）
        keeps_flow = ("for order in orders" in medium and "if amount <= 0" in medium
                      and "raise ValueError" in medium)
        # 4) 折疊標記存在
        has_fold_mark = "省略" in medium
        ok = (save_medium >= 45.0 and save_medium > save_light
              and keeps_short_bug and keeps_flow and has_fold_mark)
        print(f"[code medium] 原 {raw} tok | light 省 {save_light:.1f}% | medium 省 {save_medium:.1f}%")
        print(f"  短函數保bug邏輯={keeps_short_bug} 長函數保骨架={keeps_flow} 折疊標記={has_fold_mark} "
              f"medium優於light={save_medium > save_light} -> {'PASS' if ok else 'FAIL'}")
        return ok
    finally:
        os.remove(path)


# ===== (2) adaptive_aggregator 校準 =====

def _realistic_data(n=60):
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "product": f"產品{i}",
            "sales": 10000 - i * 120,
            "growth": round(8 - i * 0.13, 2),
            "region": "華南",  # 常數欄位（校準應剔除）
            "empty_note": None,  # 全空欄位（校準應剔除）
            "note": f"產品{i}的詳細說明：" + "這是一段很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長的備註文本" * 2,
        })
    return rows


def test_agg_calibration():
    data = _realistic_data(60)
    agg = aa.AdaptiveAggregator(initial_top_n=5)
    #  基準：不校準、不截斷（max_cell_len=1000 近似原文）
    base = agg.aggregate(data, sort_by="sales", calibrated=False)
    base_text = agg.format_for_llm(base, compact=True, max_cell_len=1000)
    # ：校準 + 截斷
    cal = agg.aggregate(data, sort_by="sales", calibrated=True)
    cal_text = agg.format_for_llm(cal, compact=True, max_cell_len=24)
    b, c = _tk(base_text), _tk(cal_text)
    save = (b - c) / b * 100
    # 校準應剔除常數/空欄位
    cal_info = agg.calibrate(data)
    dropped = set(cal_info["dropped_cols"])
    ok = (save >= 15.0 and "region" in dropped and "empty_note" in dropped
          and cal["current_top_n"] <= 3)
    print(f"[agg 校準]  基準 {b} tok →  校準 {c} tok（再降 {save:.1f}%）")
    print(f"  剔除欄位={sorted(dropped)} Top-N={cal['current_top_n']} -> {'PASS' if ok else 'FAIL'}")
    return ok


# ===== (3) MCP 透明代理 =====

def test_mcp_engine():
    r = mp.self_test()
    # 額外：offset/length 切片回溯
    eng = mp.CompressionEngine(min_tokens=100)
    big = json.dumps([{"a": i, "b": f"v{i}"} for i in range(50)], ensure_ascii=False)
    _, meta = eng.process("search", big)
    h = meta.get("handle")
    sliced = eng.read_more(h, offset=5, length=20)
    r["readmore_slice"] = sliced == big[5:25]
    ok = all(r.values())
    print(f"[MCP 代理] 結果: {json.dumps(r, ensure_ascii=False)}")
    print(f"  -> {'PASS' if ok else 'FAIL'}")
    return ok


# ===== (4) 回歸：短對話不反增 token =====

def test_incremental_short():
    comp = IncrementalCompressor(keep_recent=2)
    msgs = [
        {"role": "user", "content": "分析 Q2 銷售，數據在 sales.csv"},
        {"role": "assistant", "content": "好的，已讀取 200 條記錄，下一步聚合產品線。"},
        {"role": "user", "content": "排除退貨數據"},
        {"role": "assistant", "content": "已完成，鏡頭膜下滑最嚴重。"},
    ]
    for m in msgs:
        comp.add_message(m)
    would = comp.should_compress()
    ctx = comp.build_context()
    # 短對話（4 輪 = keep_recent*2）應不壓縮，且 context 等於原文（不反增）
    orig_tok = _tk("\n".join(m["content"] for m in msgs))
    ctx_tok = _tk("\n".join(m["content"] for m in ctx))
    ok = (would is False) and (ctx_tok <= orig_tok)
    print(f"[短對話回歸] would_compress={would} 原文 {orig_tok} tok → ctx {ctx_tok} tok -> {'PASS' if ok else 'FAIL'}")
    return ok


# ===== (5) 回歸：JSON→CSV =====

def test_json_csv():
    data = [{"product": f"p{i}", "sales": 100 + i, "growth": round(i * 0.5, 1)} for i in range(20)]
    raw = json.dumps(data, ensure_ascii=False)
    csv_text = jc.compress_json_light(data)
    save = (len(raw) - len(csv_text)) / len(raw) * 100
    ok = jc.should_compress_json(data) and save >= 30.0
    print(f"[JSON→CSV 回歸] JSON {len(raw)} → CSV {len(csv_text)} 字元（省 {save:.1f}%） -> {'PASS' if ok else 'FAIL'}")
    return ok


# ===== (6) ：確定性 + 完整性（15 篇學習啟發 B/A）=====

def test_determinism_integrity():
    """B: 同輸入跑兩次輸出必須一致（非確定性 → cache miss + 非冪等）。
    A: handle = 內容 sha256，read_more 回溯可驗證還原的是原文。"""
    eng = mp.CompressionEngine(min_tokens=100)
    big_json = json.dumps([{"product": f"P{i}", "sales": 1000 - i,
                            "note": "長" * 30} for i in range(30)], ensure_ascii=False)
    # 同輸入兩次 → 輸出必須完全一致（含 handle）
    o1, m1 = eng.process("t", big_json)
    o2, m2 = eng.process("t", big_json)
    deterministic = o1 == o2
    # handle 是 sha256 指紋（16 進位、固定長度 12）
    h = m1.get("handle", "")
    hash_handle = len(h) == 12 and all(c in "0123456789abcdef" for c in h)
    # 完整性：read_more 還原全文 == 原文
    back = eng.read_more(h, length=10 ** 9) if h else ""
    roundtrip = back == big_json
    # 同 handle 兩次（hash 確定）→ store 不重複增長
    same_handle = m1.get("handle") == m2.get("handle")
    ok = deterministic and hash_handle and roundtrip and same_handle
    print(f"[確定性+完整性] 兩次輸出一致={deterministic} hash_handle={hash_handle} "
          f"roundtrip={roundtrip} 同handle={same_handle}")
    print(f"  -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print("=== tokknife 確定性驗證（零 API）===\n")
    tests = [
        ("code medium 折疊", test_code_medium),
        ("agg 校準 15-20%", test_agg_calibration),
        ("MCP 透明代理", test_mcp_engine),
        ("短對話回歸 ()", test_incremental_short),
        ("JSON→CSV 回歸 ()", test_json_csv),
        ("確定性+完整性 ()", test_determinism_integrity),
    ]
    ok = True
    for name, fn in tests:
        print(f"[{name}]")
        ok = fn() and ok
        print()
    print("總結:", "ALL PASS + 落地成立" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
