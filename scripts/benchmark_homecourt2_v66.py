# -*- coding: utf-8 -*-
"""benchmark_homecourt2_v66.py — 其餘熱門款專屬賽道對比（caveman / Repomix / gcf-proxy）

C. caveman 主場：prose 技術報告輸出壓縮（doubao 實跑）
D. Repomix 主場：整 repo 打包壓縮（npx repomix --compress，本地）
E. gcf-proxy 主場：JSON 結構壓縮（我們 json_compressor 實測 vs gcf-proxy 基準宣稱 56%）
"""
import os
import sys
import json
import subprocess
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def _tk(s): return len(_ENC.encode(s))
except Exception:
    def _tk(s): return len(s) // 3


# ===== C. caveman 主場（prose 輸出壓縮）=====
API_KEY = os.environ.get("EX_LLM_KEY") or os.environ.get("ARK_API_KEY")
BASE_URL = os.environ.get("EX_LLM_BASE", "https://ark.cn-beijing.volces.com/api/v3")
MODEL = os.environ.get("EX_LLM_MODEL", "doubao-seed-2-0-pro-260215")

PROSE_TASK = ("寫一份產線良率改善的技術報告（約 300 字）：最近一週良率從 96.2% 掉到 94.8%，"
              "分析可能原因（貼合溫度、物料批次、人員流動），給出 3 條改善建議與預期效果。"
              "要包含具體數字與結論。")


def chat(system, user):
    payload = {"model": MODEL, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 1500, "temperature": 0.2, "stream": False,
        "thinking": {"type": "disabled"}}
    req = urllib.request.Request(BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def load_caveman():
    for cand in ("/tmp/caveman/commands/caveman.md", "/tmp/caveman/src/rules/caveman-activate.md"):
        if os.path.exists(cand):
            return open(cand, encoding="utf-8").read()
    return None


def caveman_track():
    if not API_KEY:
        print("C 需 EX_LLM_KEY，跳過"); return []
    cave = load_caveman()
    groups = [
        ("baseline", "你是工廠品質工程師。"),
        ("ours", "你是工廠品質工程師。輸出規範：先結論後細節；列表優於散文；不寫客套與開場白；數字與結論不可省。"),
        ("caveman", cave or "你是工程師。極簡技術筆記風：省略填充語、人稱、客套；保留所有技術事實、數字、錯誤。"),
    ]
    print("\n=== C. caveman 主場：prose 技術報告輸出 ===")
    results = []
    for name, sys_prompt in groups:
        try:
            resp = chat(sys_prompt, PROSE_TASK)
            content = resp["choices"][0]["message"]["content"]
            out_tok = resp.get("usage", {}).get("completion_tokens", 0)
            has_num = any(c.isdigit() for c in content)
            has_concl = ("結論" in content or "建議" in content or "改善" in content)
            results.append({"group": name, "out_tokens": out_tok, "has_numbers": has_num, "has_conclusion": has_concl})
            print(f"  [{name}] {out_tok} tok | 數字={has_num} 結論/建議={has_concl} | 前40字: {content[:40]!r}")
        except Exception as e:
            results.append({"group": name, "error": str(e)})
            print(f"  [{name}] 錯誤: {e}")
    return results


# ===== D. Repomix 主場（repo 打包）=====
def repomix_track(repo_dir=r"D:\AI\2026-08-11-16-42-02\doubao-v31",
                  packed_path=r"C:\tmp\repomix_test\packed.txt"):
    print("\n=== D. Repomix 主場：整 repo 打包 ===")
    packed = packed_path
    raw_tok = 0
    ours_tok = 0
    from code_context_extractor import compress_code_medium
    import tempfile
    for root, _, files in os.walk(repo_dir):
        for fn in files:
            if fn.startswith("packed") or not fn.endswith((".py", ".md", ".txt", ".json", ".toml", ".yml")):
                continue
            p = os.path.join(root, fn)
            try:
                txt = open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            raw_tok += _tk(txt)
            if fn.endswith(".py"):
                try:
                    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
                        f.write(txt); tmp = f.name
                    try:
                        c = compress_code_medium(tmp)
                    finally:
                        os.unlink(tmp)
                    ours_tok += _tk(c)
                except Exception:
                    ours_tok += _tk(txt)
            elif fn.endswith((".md", ".txt", ".json")):
                ours_tok += _tk(txt)  # 我們對 md 不壓（保守）
            else:
                ours_tok += _tk(txt)
    pack_tok = _tk(open(packed, encoding="utf-8", errors="ignore").read()) if os.path.exists(packed) else 0
    print(f"  raw 總計      : {raw_tok} tok")
    print(f"  Repomix(壓縮) : {pack_tok} tok (省 {100*(1-pack_tok/raw_tok):.1f}%)")
    print(f"  我們(py medium): {ours_tok} tok (省 {100*(1-ours_tok/raw_tok):.1f}%)")
    return {"raw": raw_tok, "repomix": pack_tok, "ours": ours_tok}


# ===== E. gcf-proxy 主場（JSON 結構壓縮）=====
def gcf_track():
    print("\n=== E. gcf-proxy 主場：JSON 結構壓縮 ===")
    from json_compressor import compress_json_light
    sample = json.dumps([{"product": f"P{i:03d}", "region": "North", "sales": 1234.5, "growth": 12.3, "returns": 3, "units": 100} for i in range(200)], ensure_ascii=False)
    raw_tok = _tk(sample)
    our = compress_json_light(sample)
    our_tok = _tk(our)
    print(f"  raw {raw_tok} tok")
    print(f"  我們 json_compressor: {our_tok} tok (省 {100*(1-our_tok/raw_tok):.1f}%)  [實測]")
    print(f"  gcf-proxy 基準宣稱  : 省 56% (vs JSON，2,400+ evals 轉引自其 README，本機無法直接跑——它是 streaming MCP proxy)")
    return {"raw": raw_tok, "ours": our_tok}


if __name__ == "__main__":
    c = caveman_track()
    d = repomix_track()
    e = gcf_track()
