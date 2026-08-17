# -*- coding: utf-8 -*-
"""benchmark_homecourt_v66.py — 專屬賽道對比（對方主場）

補「我們主場」對比的不足：在對方設計場景比一次。
  A. CacheAligner 主場：長 context proxy（messages 佔比接近 model_limit 才觸發壓縮）——
     構造 40 輪長對話（~6k tok，佔 8000 的 75%）→ CacheAligner.compress vs 我們 auto_compact/anchored
  B. ponytail 主場：含自檢/測試的完整輸出——任務明示「實作＋寫測試」→
     baseline vs 我們輸出規範（任務要求測試時照給）vs ponytail 規則
A 本地跑；B 需 EX_LLM_KEY（doubao）。
"""
import os
import sys
import json
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def _tk(s): return len(_ENC.encode(s))
except Exception:
    def _tk(s): return len(s) // 3


def build_long_session():
    """構造長對話：40 輪，含長工具回傳（每輪 150 tok 級），總 ~6k tok（佔 8000 的 75%）。"""
    msgs = [{"role": "system", "content": "你是工廠管理助理。追蹤持續改善專案。"}]
    for i in range(1, 41):
        msgs.append({"role": "user", "content": f"查專案 {i} 的進度與異常"})
        rows = [f"P{i:03d} 良率 {97 - i%8}% 產量 {5000 + i*17} 異常 {['封邊','貼合','烘烤','包裝'][i%4]}" for i in range(30)]
        msgs.append({"role": "assistant", "content": f"查詢結果：\n" + "\n".join(rows) + f"\n小結：專案 {i} 進度正常，下一步確認。"})
    return msgs


# ===== A. CacheAligner 主場（長 context proxy）=====
def headroom_homecourt():
    msgs = build_long_session()
    raw_tok = _tk(json.dumps(msgs, ensure_ascii=False))
    model_limit = 8000  # 佔比 ~75% → 觸發 CacheAligner
    import CacheAligner
    r = CacheAligner.compress(msgs, model="doubao-seed-2-0-pro-260215", model_limit=model_limit, optimize=True)
    out_msgs = getattr(r, "compressed_messages", None) or getattr(r, "messages", None) or []
    hr_tok = _tk(json.dumps(out_msgs, ensure_ascii=False))
    # 我們：auto_compact（同閾值 0.75）＋anchored
    from compress_history import auto_compact, anchored_compact
    ac = auto_compact(list(msgs), context_limit=model_limit, threshold=0.75, keep_recent=3)
    our_tok = _tk(json.dumps(ac["compressed_messages"], ensure_ascii=False))
    anc = anchored_compact(list(msgs), context_limit=model_limit, threshold=0.75, keep_recent=3)
    anc_tok = _tk(json.dumps(anc["compressed_messages"], ensure_ascii=False))
    print("=== A. CacheAligner 主場：長 context proxy（40 輪對話，佔比 ~75%）===")
    print(f"  raw={raw_tok} tok | model_limit={model_limit}")
    print(f"  CacheAligner : {hr_tok} tok (省 {100*(1-hr_tok/raw_tok):.1f}%)  msgs={len(out_msgs)}")
    print(f"  我們 auto_compact: {our_tok} tok (省 {100*(1-our_tok/raw_tok):.1f}%)  msgs={len(ac['compressed_messages'])}")
    print(f"  我們 anchored    : {anc_tok} tok (省 {100*(1-anc_tok/raw_tok):.1f}%)  msgs={len(anc['compressed_messages'])}")
    return {"raw": raw_tok, "CacheAligner": hr_tok, "ours_auto": our_tok, "ours_anchored": anc_tok}


# ===== B. ponytail 主場（含自檢/測試的完整輸出）=====
API_KEY = os.environ.get("EX_LLM_KEY") or os.environ.get("ARK_API_KEY")
BASE_URL = os.environ.get("EX_LLM_BASE", "https://ark.cn-beijing.volces.com/api/v3")
MODEL = os.environ.get("EX_LLM_MODEL", "doubao-seed-2-0-pro-260215")

TASK_TEST = ("實作一個 Python 函數 get_top5_sales(csv_path)：讀 CSV（欄位 product,region,sales），"
             "過濾 sales<=0，按 sales 降序，回傳前 5 筆 [product, sales]。"
             "**要求：附完整的可執行測試（含 assert 斷言）**，確保可直接跑驗證。")


def chat(system, user):
    payload = {"model": MODEL, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 2000, "temperature": 0.2, "stream": False,
        "thinking": {"type": "disabled"}}
    req = urllib.request.Request(BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def load_ponytail():
    import tempfile
    for cand in (os.path.join(tempfile.gettempdir(), "ponytail", ".clinerules", "ponytail.md"),
                 "/tmp/ponytail/.clinerules/ponytail.md"):
        if os.path.exists(cand):
            return open(cand, encoding="utf-8").read()
    return None


def ponytail_homecourt():
    if not API_KEY:
        print("B 需 EX_LLM_KEY，跳過"); return None
    pony = load_ponytail()
    groups = [
        ("baseline", "你是工程師。請完成使用者的要求。"),
        ("ours(含測試)", "你是工程師。輸出規範：先結論後細節；不寫客套；程式碼要完整可執行；**任務要求測試就給測試**。"),
        ("ponytail", pony),
    ]
    print("\n=== B. ponytail 主場：含自檢/測試的完整輸出 ===")
    results = []
    for name, sys_prompt in groups:
        try:
            resp = chat(sys_prompt, TASK_TEST)
            content = resp["choices"][0]["message"]["content"]
            out_tok = resp.get("usage", {}).get("completion_tokens", 0)
            has_assert = ("assert" in content)
            has_test = ("def test" in content or "__main__" in content or "測試" in content)
            results.append({"group": name, "out_tokens": out_tok, "has_assert": has_assert, "has_test": has_test})
            print(f"  [{name}] {out_tok} tok | assert={has_assert} 測試={has_test}")
        except Exception as e:
            results.append({"group": name, "error": str(e)})
            print(f"  [{name}] 錯誤: {e}")
    return results


if __name__ == "__main__":
    a = headroom_homecourt()
    b = ponytail_homecourt()
    print("\n=== 總結 ===")
    print(f"A(Headroom主場) raw={a['raw']} | CacheAligner={a['CacheAligner']} 我們auto={a['ours_auto']} 我們anchored={a['ours_anchored']}")
