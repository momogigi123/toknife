# -*- coding: utf-8 -*-
"""roundtrip_5r.py — 同一指令反覆對話 5 輪，工具回傳每輪累積，比總 token

用戶點破：token-saver 的優勢是「回傳進上下文後被壓縮，後續每輪都省」，
不是單次壓縮率。所以測試設計 = 同一個任務指令下，反覆對話 5 輪，
每輪都有新工具回傳（大 JSON），歷史持續累積在上下文中：

  A 原文方案：每輪上下文 = 之前所有原始回傳 + 新回傳（歷史越長越肥）
  B TS 方案： 每輪上下文 = 之前回傳的壓縮版(歷史壓縮) + 新回傳壓縮 + read_more 回溯
  C HR 方案： 每輪把全部 messages 丟給 CacheAligner compress（它自己的多輪壓縮）

量測：5 輪累積輸入 token 總量 + 最後一輪上下文大小。
"""
import os, sys, json, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # 本套件腳本目錄（外部基準依賴為可選，未安裝時略過）

from mcp_proxy import CompressionEngine, est_tokens
from incremental_compressor import IncrementalCompressor

ROUNDS = 5


def gen_tool_return(seed):
    """每輪的工具回傳：120 筆 JSON（同結構新數據）。"""
    random.seed(seed)
    return json.dumps([{"product": f"P{i:03d}", "region": ["北","南","東","西"][i%4],
                        "sales": round(random.uniform(100, 9999), 2),
                        "growth": round(random.uniform(-40, 80), 2),
                        "note": "很長備註" * 3} for i in range(120)], ensure_ascii=False)


def plan_A(rounds):
    """原文方案：所有回傳原文累積。"""
    ctxs, total = [], 0
    for i in range(rounds):
        text = gen_tool_return(100 + i)
        ctxs.append(text)
        ctx = "\n".join(ctxs)
        total += est_tokens(ctx)
    return total


def plan_B(rounds):
    """TS 方案：每輪回傳先壓縮（存原文 read_more），歷史累積壓縮版。"""
    eng = CompressionEngine(min_tokens=100)
    comp_hist, total = [], 0
    for i in range(rounds):
        text = gen_tool_return(100 + i)
        new, meta = eng.process("tool", text)
        comp_hist.append(new)  # 壓縮版入歷史
        ctx = "\n".join(comp_hist)
        total += est_tokens(ctx)
    return total


def plan_C(rounds):
    """CacheAligner 方案：每輪把全部 messages 丟給它的 compress。"""
    from CacheAligner.compress import compress
    msgs, total = [], 0
    for i in range(rounds):
        text = gen_tool_return(100 + i)
        msgs.append({"role": "user", "content": text})
        r = compress(msgs, model="gpt-4o-mini", config=None)
        total += r.tokens_after if r.tokens_after else len(json.dumps(r.messages, ensure_ascii=False)) // 3
    return total


def main():
    print(f"=== 同一指令反覆對話 {ROUNDS} 輪（每輪 120 筆 JSON 回傳累積）===\n")
    a = plan_A(ROUNDS)
    b = plan_B(ROUNDS)
    print(f"A 原文方案:   {a:6d} tok（5 輪累積）")
    print(f"B TS 壓縮方案: {b:6d} tok（5 輪累積）")
    print(f"  TS 相對原文省: {(1 - b/a)*100:.1f}%\n")

    print("--- CacheAligner 多輪（誠實標註：零 API 退化模式）---")
    try:
        c = plan_C(ROUNDS)
        print(f"C CacheAligner:   {c:6d} tok（5 輪累積）")
        print(f"  HR 相對原文: {(1 - c/a)*100:+.1f}%")
    except Exception as e:
        print(f"  CacheAligner 失敗: {type(e).__name__}: {str(e)[:100]}")

    print(f"\n結論: 同一指令反覆對話場景，TS 的『回傳壓縮複利』累積省 {(1-b/a)*100:.1f}%——"
          f"這就是『回傳後的減少』在多輪對話中的真實價值。")


if __name__ == "__main__":
    main()
