# -*- coding: utf-8 -*-
"""benchmark_ponytail_v66.py — 輸出側真實 A/B：Token Saver 輸出規範 vs ponytail 規則 vs baseline

ponytail（DietrichGebert/ponytail，~95k★）是輸出側規則插件：決策樹讓模型少寫代碼。
賽道＝輸出側（與我們輸入側正交；我們也有輸出側常駐規範可對比）。

對比設計（公平）：
  同一代碼任務 × 3 組：
    baseline  : 無任何輸出約束
    ours      : 我們常駐規範輸出階梯（先結論/一行/少廢話）
    ponytail  : 注入 ponytail .clinerules/ponytail.md 決策樹規則
  指標：輸出 token（usage.completion_tokens 真實）、代碼行數、LLM judge 功能完整度（0-100）。
用 EX_LLM_KEY（火山方舟 doubao-seed-2-0-pro）；key 走環境變量。
"""
import os
import sys
import json
import urllib.request

API_KEY = os.environ.get("EX_LLM_KEY") or os.environ.get("ARK_API_KEY")
BASE_URL = os.environ.get("EX_LLM_BASE", "https://ark.cn-beijing.volces.com/api/v3")
MODEL = os.environ.get("EX_LLM_MODEL", "doubao-seed-2-0-pro-260215")

TASK = ("實作一個 Python 函數：讀取 CSV 檔案（欄位 product,region,sales），"
        "過濾掉 sales<=0 的行，按 sales 降序排序，回傳前 5 筆的 [product, sales] 列表。"
        "檔案路徑由參數傳入，檔案可能不存在需處理。")


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


OURS_SYS = ("你是工程師。輸出規範（強制）：先結論後細節；能一行不寫兩行；"
            "不寫客套與解釋性廢話；只回傳可執行的程式碼與必要說明；輸出總長度≤300 字。")
PONY_SYS = None  # 讀自 ponytail 規則檔


def load_ponytail():
    import tempfile
    p = os.path.join(tempfile.gettempdir(), "ponytail", ".clinerules", "ponytail.md")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    for cand in ("/tmp/ponytail/.clinerules/ponytail.md",):
        if os.path.exists(cand):
            return open(cand, encoding="utf-8").read()
    return None


def main():
    if not API_KEY:
        print("ERROR: 設 EX_LLM_KEY"); sys.exit(1)
    pony = load_ponytail()
    if not pony:
        print("ERROR: 找不到 ponytail 規則檔"); sys.exit(1)
    groups = [
        ("baseline", "你是工程師。請完成使用者的要求。"),
        ("ours", OURS_SYS),
        ("ponytail", pony),
    ]
    print(f"=== 輸出側真實 A/B（{MODEL}）：baseline vs 我們輸出規範 vs ponytail ===")
    results = []
    for name, sys_prompt in groups:
        try:
            resp = chat(sys_prompt, TASK)
            content = resp["choices"][0]["message"]["content"]
            usage = resp.get("usage", {})
            out_tok = usage.get("completion_tokens", 0)
            lines = len([l for l in content.splitlines() if l.strip()])
            results.append({"group": name, "out_tokens": out_tok, "code_lines": lines,
                            "content": content, "preview": content[:60].replace("\n", " ")})
            print(f"[{name}] 輸出 {out_tok} tok / {lines} 行 | 前 60 字: {content[:60]!r}")
        except Exception as e:
            results.append({"group": name, "error": str(e)})
            print(f"[{name}] 錯誤: {e}")
    # LLM judge：功能完整度（看完整程式碼）
    print("\n=== LLM judge 功能完整度（看完整程式碼）===")
    for r in results:
        if "error" in r or "content" not in r:
            continue
        judge_sys = ("你是評審。給下面程式碼的「功能完整度」打分 0-100："
                     "是否處理檔案不存在、過濾 sales<=0、降序排序、回傳前5筆 [product,sales]。只回數字。")
        try:
            j = chat(judge_sys, r["content"])
            r["judge"] = j["choices"][0]["message"]["content"][:20].strip()
            print(f"  {r['group']}: judge={r.get('judge')}")
        except Exception as e:
            print(f"  {r['group']}: judge 失敗 {e}")
    print("\n結果:", json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
