# -*- coding: utf-8 -*-
"""multi_round_compound.py —  多輪複利節省測試 v2（零 API）

v1 教訓：同一份回傳「每輪都帶」時，原文/壓縮版同樣每輪都在，
節省百分比固定（只放大絕對量）——那不是真複利。

真複利在「歷史累積」：長對話中舊輪內容持續佔上下文，
incremental_compressor 把舊內容壓成狀態摘要，省的是「不再以原文佔位」的部分。
每輪上下文 = 累積歷史 + 新增內容：

  A 原文方案：每輪上下文 = Σ(所有舊輪原文) + 新內容   （歷史越長越肥）
  B 壓縮方案：每輪上下文 = 舊輪壓縮摘要(固定大小) + 新內容（歷史被壓住）

測量各輪累積輸入 token 與總節省——這個百分比會隨輪數上升。
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from incremental_compressor import IncrementalCompressor
from mcp_proxy import est_tokens


def gen_turn(i):
    """模擬第 i 輪的對話內容（會累積進上下文的）。"""
    return {"role": "user" if i % 2 == 0 else "assistant",
            "content": f"第{i+1}輪的對話內容：討論工廠看板的指標定義與資料源對接，"
                       f"包含 OEE/良率/停機次數的詳細規格說明，以及 MES 每分鐘推送的"
                       f"緩衝與重試設計。補充細節：欄位 snake_case、時區 UTC+8、"
                       f"異常處理與告警閾值設定。" * 2}


def simulate(rounds=8, keep_recent=2, max_state_tokens=300):
    """A: 累積原文；B: incremental 壓縮（保留近期原文 + 舊輪狀態摘要）。"""
    comp = IncrementalCompressor(keep_recent=keep_recent, max_state_tokens=max_state_tokens)
    plan_a, plan_b = [], []
    hist_a_tok = 0
    for i in range(rounds):
        msg = gen_turn(i)
        # A：累積全部原文
        hist_a_tok += est_tokens(msg["content"])
        plan_a.append(hist_a_tok)
        # B：incremental 壓縮
        comp.add_message(msg)
        ctx = comp.build_context(include_state=True, include_recent=True)
        ctx_tok = sum(est_tokens(m["content"]) for m in ctx)
        plan_b.append(ctx_tok)

    total_a, total_b = sum(plan_a), sum(plan_b)
    return {
        "rounds": rounds,
        "total_a": total_a,
        "total_b": total_b,
        "compound_saving_pct": round((1 - total_b / total_a) * 100, 1),
        "per_round": list(zip(range(1, rounds + 1), plan_a, plan_b)),
    }


def main():
    print("=== Token Saver 多輪歷史累積複利測試（v2，零 API）===\n")
    r = simulate(rounds=8)
    print(f"8 輪對話：原文累積 {r['total_a']} tok vs 壓縮累積 {r['total_b']} tok")
    print(f"多輪複利節省: **{r['compound_saving_pct']}%**\n")
    print("每輪上下文大小（A 原文 vs B 壓縮）：")
    for i, a, b in r["per_round"]:
        bar_a = "█" * max(1, a // 500)
        bar_b = "█" * max(1, b // 500)
        print(f"  第{i}輪: A {a:5d} tok {bar_a}")
        print(f"           B {b:5d} tok {bar_b}")

    print("\n=== 輪數 vs 節省（歷史越長，複利越大）===")
    for rnd in [4, 8, 12, 16]:
        rr = simulate(rounds=rnd)
        print(f"  {rnd} 輪: 節省 {rr['compound_saving_pct']}%（A {rr['total_a']} vs B {rr['total_b']} tok）")

    print("\n結論: 歷史壓縮的複利隨輪數上升——長對話場景才是 token-saver 節省最大的地方。")


if __name__ == "__main__":
    main()
