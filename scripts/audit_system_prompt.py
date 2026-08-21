# -*- coding: utf-8 -*-
"""audit_system_prompt.py — 系統提示詞冗餘度審計
用法：
  python audit_system_prompt.py system_prompt.txt
  cat prompt.txt | python audit_system_prompt.py -
輸出：token 計數、重複句、客套語/冗餘模式、壓縮建議與節省估計。
"""
import sys, re, argparse

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def _count(s): return len(_ENC.encode(s))
except ImportError:
    def _count(s): return len(s) // 3  # 粗略估算，建議 pip install tiktoken 獲得精確計數

FILLER = ["很高興", "請隨時", "如有任何問題", "不用客氣", "作為一個", "作為一名", "資深", "經驗豐富",
          "非常", "十分", "眾所周知", "值得注意", "值得注意的是", "綜上所述", "總結來說"]

# ===== v6.3 V-4b：易變內容檢測（對齊 Headroom CacheAligner 新版＝純檢測器）=====
# 背景：prompt cache（Claude 90%/Gemini 75%/OpenAI 50% 折扣）要求前綴逐位元組穩定；
# system prompt 裡的動態值（時間戳/UUID/JWT/hash）會讓每次請求 hash 不同 → cache 永遠 miss。
# CacheAligner 舊版「改寫佔位符」被移除（違反『熱區絕不可動』不變式，越改越壞）；
# 正確做法＝純檢測：找出易變內容，建議使用者挪到 user message。
# 我們照做：只檢測+建議，永不改寫。

_VOLATILE_PATTERNS = [
    ("uuid", r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "UUID"),
    ("iso8601", r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b", "ISO 8601 時間戳"),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "JWT 令牌"),
    ("hex_hash", r"\b(?:sha256|sha1|md5)[:=]\s*[0-9a-f]{16,}\b|\b[0-9a-f]{32,64}\b", "十六進位雜湊"),
]

def detect_volatile_content(text: str, max_samples: int = 8) -> list:
    """檢測 system prompt 中的易變內容（v6.3，純檢測器，不改寫）。
    回傳 [{label, kind, sample}]。sample 只截斷取樣，絕不記錄完整內容（對齊 CacheAligner VolatileFinding）。
    """
    findings = []
    for label, pat, kind in _VOLATILE_PATTERNS:
        try:
            matches = re.findall(pat, text, re.IGNORECASE)
        except re.error:
            continue
        if matches:
            findings.append({"label": label, "kind": kind,
                             "sample": matches[0][:24] + "…" if len(matches[0]) > 24 else matches[0]})
    return findings[:max_samples]

def audit(text):
    tok = _count(text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # 重複句
    from collections import Counter
    dup = {l: c for l, c in Counter(lines).items() if c > 1}
    # 客套/冗餘命中
    hits = {f: text.count(f) for f in FILLER if f in text}
    # 過長句子
    long_s = [s for s in re.split(r"[。！？\n]", text) if len(s) > 120][:5]
    est = tok
    if hits:
        est = int(tok * 0.8)  # 砍掉客套粗估 -20%
    if dup:
        est = int(est * 0.85)
    return {"tokens": tok, "dup_lines": dup, "filler_hits": hits,
            "long_sentences": long_s, "est_after": est,
            "volatile": detect_volatile_content(text)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", default="-")
    a = ap.parse_args()
    text = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
    r = audit(text)
    print(f"token 數: {r['tokens']}")
    if r["dup_lines"]:
        print(f"重複行 {len(r['dup_lines'])} 處: {list(r['dup_lines'].items())[:5]}")
    if r["filler_hits"]:
        print(f"客套/冗餘詞命中: {r['filler_hits']}")
    if r["long_sentences"]:
        print(f"過長句 {len(r['long_sentences'])} 處: {[s[:60]+'…' for s in r['long_sentences']]}")
    if r.get("volatile"):
        print("⚠️ 易變內容（會讓 prompt cache 永遠 miss，建議挪到 user message）：")
        for v in r["volatile"]:
            print(f"  - {v['kind']}（{v['label']}）樣本: {v['sample']}")
    print(f"建議壓縮後預估: ~{r['est_after']} tokens（可省 ~{r['tokens']-r['est_after']}）")
