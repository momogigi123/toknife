# -*- coding: utf-8 -*-
"""roundtrip_qa5.py — 同題目來回問答 5 次：進/出分開統計平均省

場景：同一個任務題目（分析 MES 數據），工具回傳一份大 JSON 後，
user↔assistant 來回問答 5 次，每次都引用這份回傳。

量測（分開統計）：
  進（input）：每輪 prompt = 歷史問答 + 回傳（baseline 原文 vs TS 壓縮）
  出（output）：每輪回覆（baseline 完整敘述 vs TS 結論化精簡）

輸出：5 次問答的 進平均省%、出平均省%、總平均省%。
零 API，實際內容長度計量。
"""
import os, sys, json, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # 本套件腳本目錄
from mcp_proxy import CompressionEngine, est_tokens

ROUNDS = 5
random.seed(42)


def gen_tool_return():
    return json.dumps([{"product": f"P{i:03d}", "region": ["北","南","東","西"][i%4],
                        "sales": round(random.uniform(100, 9999), 2),
                        "growth": round(random.uniform(-40, 80), 2),
                        "note": "很長備註" * 3} for i in range(120)], ensure_ascii=False)


def gen_full_reply(i):
    """baseline 完整回覆：多段敘述（模擬未壓輸出的 agent）。"""
    return (f"根據第 {i+1} 次分析，這批 MES 數據共 120 筆記錄，"
            f"涵蓋北中南東四個區域。銷售額最高的幾個產品分別是……"
            f"進一步觀察成長率分布，可以發現東區的表現最為突出，"
            f"而北區則有明顯的波動。整體而言，數據呈現以下幾個特徵："
            f"第一，銷售額集中在少數頭部產品；第二，成長率與區域相關性強；"
            f"第三，異常值主要集中在特定產品線。基於以上分析，建議後續"
            f"重點關注東區與頭部產品，並對異常值進行深入排查。" * 3)


def gen_short_reply(i):
    """TS 結論化回覆（常駐規範：≤300 字、先結論）。"""
    return (f"第 {i+1} 次結論：數據 120 筆，東區最突出、北區波動大；"
            f"銷售集中頭部、異常在特定產品線。建議：追東區+頭部，查異常。")


def main():
    raw = gen_tool_return()
    eng = CompressionEngine(min_tokens=100)
    comp, meta = eng.process("t", raw)

    print(f"=== 同題目來回問答 {ROUNDS} 次（同一份數據）===\n")
    print(f"數據回傳: 原文 {est_tokens(raw)} tok → TS 壓縮 {est_tokens(comp)} tok"
          f"（單次省 {(1-est_tokens(comp)/est_tokens(raw))*100:.1f}%）\n")

    print(f"{'輪':<3}{'進-原文':>10}{'進-TS':>9}{'進省%':>8}{'出-原文':>10}{'出-TS':>9}{'出省%':>8}")
    in_a = in_b = out_a = out_b = 0
    for i in range(ROUNDS):
        # 進：歷史問答 + 回傳（baseline 原文 / TS 壓縮）
        hist = f"Q{i}: 分析這批數據 | A: {gen_full_reply(i)}\n" if i == 0 else \
               f"Q{i}: 繼續分析 | A: {gen_short_reply(i-1)}\n"
        prompt_a = hist + raw
        prompt_b = hist + comp
        ia, ib = est_tokens(prompt_a), est_tokens(prompt_b)
        # 出：完整 vs 精簡
        oa, ob = est_tokens(gen_full_reply(i)), est_tokens(gen_short_reply(i))
        in_a += ia; in_b += ib; out_a += oa; out_b += ob
        print(f"{i+1:<3}{ia:>10}{ib:>9}{(1-ib/ia)*100:>7.1f}%{oa:>10}{ob:>9}{(1-ob/oa)*100:>7.1f}%")

    avg_in = (1 - in_b/in_a) * 100
    avg_out = (1 - out_b/out_a) * 100
    total_a, total_b = in_a + out_a, in_b + out_b
    print(f"\n=== 5 次平均 ===")
    print(f"進（input）: 原文 {in_a} → TS {in_b} tok，平均省 **{avg_in:.1f}%**")
    print(f"出（output）: 原文 {out_a} → TS {out_b} tok，平均省 **{avg_out:.1f}%**")
    print(f"總（進+出）: 原文 {total_a} → TS {total_b} tok，平均省 **{(1-total_b/total_a)*100:.1f}%**")


if __name__ == "__main__":
    main()
