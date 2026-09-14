# -*- coding: utf-8 -*-
"""benchmark.py — 離線輸入端基準（**真呼叫本倉庫的壓縮器**）

## 這個腳本做什麼

對下列每個場景，把**同一段輸入**分別送進本倉庫的 `ts_proxy_server.compress_content()`，
比較「壓縮前 vs 壓縮後」的 token 數：

    save_in% = (prompt_direct − prompt_proxied) / prompt_direct × 100%

## 這個腳本刻意**不做**什麼（重要）

1. **不計輸出端**：離線沒有模型產出，任何輸出端數字都會是編造的。
2. **不給跨場景總平均**：不同場景性質差異極大（見下表 0% 與 60% 並存），
   把他們平均成一個數字沒有意義，也容易誤導。請看逐場景結果。
3. **不接受「估算」的 token 數**：若環境沒有 `tiktoken`，本腳本會**直接中止**
   （exit 2）而不是印出估算值 —— 計數器不明，量測即無效。

## 這不是「你省了多少錢」的證明

本表是**離線、輸入端、單機**的相對比較，**不等於**你在 LLM API 帳單上的實際節省。
實際節省取決於你的輸入內容類型、所用模型、以及是否命中 prompt cache。
請把它當作「哪些內容類型值得壓」的參考，不是省錢承諾。

用法：
    python benchmark.py                 # 人類可讀
    python benchmark.py --json          # 機器可讀（含環境指紋）
    python benchmark.py --allow-estimated   # 明示接受估算值（不建議）
"""
import json
import platform
import sys

# ---------------------------------------------------------------- token 計數
try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def count(text):
        return len(_ENC.encode(text))

    TOKENIZER = "tiktoken:cl100k_base"
    IS_ESTIMATED = False
except Exception:
    # 無 tiktoken → 只提供「明顯粗糙」的估算，且預設拒絕輸出（見 main）。
    def count(text):
        cjk = sum(1 for ch in (text or "") if "\u4e00" <= ch <= "\u9fff")
        return int(round(cjk * 1.5 + (len(text or "") - cjk) * 0.25))

    TOKENIZER = "ESTIMATED(cjk*1.5/ascii*0.25)"
    IS_ESTIMATED = True


def compress(text):
    """呼叫本倉庫的壓縮器；失敗則明確報錯（不得靜默退回手寫對照）。"""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ts_proxy_server as proxy
    return proxy.compress_content(text) or {}


def fingerprint():
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": platform.platform(),
        "tokenizer": TOKENIZER,
        "estimated": IS_ESTIMATED,
    }


# ---------------------------------------------------------------- 場景語料
# 每個場景只提供「一份輸入」。**沒有任何手寫的『理想壓縮版』**——
# 壓縮結果一律由本倉庫的壓縮器產生。
CASES = [
    ("QA 事實問答（長要求）",
     "system: 你是知識淵博的助理。請就使用者問題，從歷史沿革、底層原理、工程實作、"
     "常見誤區、邊界條件、與其他方案的比較、未來演進七個面向完整論述，"
     "每面向至少三段，並在結尾給出可直接照做的檢查清單。\n"
     "user: 請完整說明「光合作用」與「人工光合成」的差異。"),

    ("摘要任務（長文）",
     "system: 你擅長總結。請完整閱讀以下長文並詳盡總結每個段落，保留所有數字與專有名詞。\n"
     "user: " + ("本產品採用高密度發泡材料，具備緩衝與隔熱雙重特性，"
                 "於冷鏈運輸可維持溫度曲線穩定，並通過落摔測試。") * 24),

    ("數據分析（原始表）",
     "system: 你是資深數據分析師。請逐一分析下列原始資料的每一列，"
     "指出趨勢、異常與可能成因，並給出後續追蹤建議。\n"
     "user:\n" + ("2026-07,手機殼,120\n" * 60)),

    ("代碼審查（真實長碼）",
     "system: 你是資深工程師。請逐步分析下列程式碼的缺陷並提出重構方案。\n"
     "user:\n" + "\n".join([
         "def process(items):",
         "    result = []",
         "    for i in items:",
         "        if i == None:",
         "            continue",
         "        try:",
         "            v = i['value']",
         "            if v > 0:",
         "                result.append(v * 2)",
         "            else:",
         "                result.append(0)",
         "        except Exception as e:",
         "            print('error', e)",
         "    return result",
     ] * 8)),

    ("日誌分析（密集日誌）",
     "system: 你是 SRE。請分析下列服務日誌，找出異常模式與根因。\n"
     "user:\n" + ("2026-09-12T03:14:15Z ERROR timeout retry=3 traceback service=api\n"
                  "2026-09-12T03:14:16Z WARN  INFO latency=1520ms error=timeout\n") * 40),

    ("Agent 迴圈（工具回傳）",
     "system: 你是 Agent，請逐步分析工具回傳並決定下一步。\n"
     "user: 工具回傳（原始 CSV）：\n" + ("id,product,qty,delta\n" * 50)),

    ("計畫生成（長需求）",
     "system: 請為下列目標制定詳細分步計劃，每步說明原因、風險與備選方案，"
     "並標出關鍵路徑與可並行段落。\n"
     "user: 完成一個可對外的產品官方網站（含多語、SEO、效能預算）。"),

    ("郵件寫作（長背景）",
     "system: 請寫一封語氣得體、結構完整的正式郵件，含問候、背景、"
     "詳細請求、替代方案、時程與禮貌結尾。\n"
     "user: 向客戶申請延期兩週，背景是上游供應鏈缺料，"
     "已完成 80% 且可先交付部分成果。"),

    ("長文（非日誌對照）",
     "system: 請仔細閱讀以下文本，回答文末問題。\n"
     "user: " + ("在包裝材料的選擇上，需同時考量緩衝性能、成本與環保規範，"
                 "不同密度與成型工藝會顯著影響最終表現。") * 30),

    ("短問答（反例）",
     "system: 簡潔回答\nuser: 什麼是光合作用？"),
]


def main():
    as_json = "--json" in sys.argv
    allow_est = "--allow-estimated" in sys.argv
    fp = fingerprint()

    if fp["estimated"] and not allow_est:
        print("=" * 64)
        print("[中止] 環境沒有 tiktoken → 只能用粗估 token 數，量測無效，故不輸出。")
        print(f"  tokenizer : {fp['tokenizer']}")
        print(f"  executable: {fp['executable']}")
        print("  請先 `pip install tiktoken`；或加 --allow-estimated 明示接受估算值。")
        print("=" * 64)
        return 2

    rows = []
    for name, text in CASES:
        res = compress(text)
        meta = res.get("meta") or {}
        a, b = count(text), count(res.get("compressed") or text)
        rows.append({
            "scene": name,
            "orig_tok": a,
            "comp_tok": b,
            "save_in_pct": round((a - b) / a * 100.0, 2) if a else 0.0,
            "method": meta.get("method") or "none",
            "compressed": bool(meta.get("compressed")),
        })

    if as_json:
        print(json.dumps({
            "fingerprint": fp,
            "scope": "offline-input-only",
            "formula": "save_in% = (prompt_direct - prompt_proxied) / prompt_direct * 100",
            "rows": rows,
        }, ensure_ascii=False, indent=2))
        return 0

    print("=== Toknife 離線輸入端基準（真呼叫本倉庫壓縮器）===")
    print("環境指紋：")
    print(f"  python {fp['python']} | {fp['platform']}")
    print(f"  executable: {fp['executable']}")
    print(f"  tokenizer : {fp['tokenizer']}  (estimated={fp['estimated']})")
    print("口徑：save_in% = (壓縮前 − 壓縮後) / 壓縮前 × 100%（只計輸入端）")
    print(f"{'場景':<22}{'原tok':>8}{'壓後tok':>9}{'輸入省率':>10}  method")
    for r in rows:
        print(f"{r['scene']:<22}{r['orig_tok']:>8}{r['comp_tok']:>9}"
              f"{r['save_in_pct']:>9.1f}%  {r['method']}")

    hit = [r["save_in_pct"] for r in rows if r["save_in_pct"] > 0]
    print(f"\n有壓縮的場景 {len(hit)}/{len(rows)} 個"
          + (f"，區間 {min(hit):.1f}%–{max(hit):.1f}%（不取跨場景平均）" if hit else ""))
    print("⚠️ 離線輸入端口徑，非端到端、非省錢承諾。實際節省取決於你的內容類型、"
          "模型與 prompt cache 命中。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
