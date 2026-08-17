# -*- coding: utf-8 -*-
"""verify_code_v51.py — v5.1 code 調度修復的確定性驗證（零 API 依賴，可複現）

驗證核心命題：
  v5.0 的 code 任務用「簽名萃取」(include_body=False) —— 剝光函數體，
  導致需要看邏輯的任務（找 bug / 審碼）品質崩塌（v5.0 LLM 基準實測 8.3/100）。
  v5.1 改用「整檔輕量壓縮」(compress_code_light) —— 保留 100% 邏輯行、
  只去註解/空行/docstring，品質不傷且真實省 token。

驗證項：
  1. 簽名模式會丟失 bug 邏輯行（含bug邏輯=False）
  2. light 模式保留 bug 邏輯行（含bug邏輯=True）
  3. light 模式在小型模組上仍保留 bug 邏輯行（v5.0 簽名模式在同一模組丟失）
  4. light 模式在大型模組上仍省 token 且保留邏輯

用法：
  python verify_code_v51.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def _tk(s): return len(_enc.encode(s))
except Exception:
    def _tk(s): return len(s) // 3

import code_context_extractor as cce
import benchmark_llm as B  # 取 gen_code 生成大型模組

# 關鍵邏輯行（bug 所在）——若出現在萃取結果中，代表「找 bug 任務仍可進行」
BUG_LINE = "result[k] = v"

SMALL = '''# -*- coding: utf-8 -*-
"""訂單處理模組"""

class OrderService:
    """處理訂單的服務"""

    def process(self, payload):
        # 初始化結果
        result = {"id": 0, "ok": True}
        for k, v in payload.items():
            result[k] = v   # BUG: payload 若有 id/ok 鍵會覆寫
        return result

    def validate(self, order):
        """簡單校驗"""
        if not order:
            return False
        return order.get("amount", 0) > 0
'''


def _run(src: str):
    fd, tmp = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(src)
        raw = _tk(src)
        sig = cce.extract_context(tmp, include_body=False)
        light = cce.compress_code_light(tmp)
        return {
            "raw_tok": raw,
            "sig_tok": _tk(sig), "sig_saving": round((raw - _tk(sig)) / raw * 100, 1),
            "sig_has_bug": BUG_LINE in sig,
            "light_tok": _tk(light), "light_saving": round((raw - _tk(light)) / raw * 100, 1),
            "light_has_bug": BUG_LINE in light,
        }
    finally:
        try: os.remove(tmp)
        except Exception: pass


def main():
    cases = [("小型真實模組(含註解/docstring/bug)", SMALL),
             ("大型生成模組(30 函數)", B.gen_code(30))]
    print("=== v5.1 code 調度修復驗證（確定性，無 API）===\n")
    ok = True
    for name, src in cases:
        r = _run(src)
        print(f"[{name}] 原 {r['raw_tok']} tok")
        print(f"  簽名(v5.0): {r['sig_tok']:5}tok 省 {r['sig_saving']:6}% | 含bug邏輯={r['sig_has_bug']}")
        print(f"  light(v5.1): {r['light_tok']:5}tok 省 {r['light_saving']:6}% | 含bug邏輯={r['light_has_bug']}")
        a1 = (r["sig_has_bug"] is False)
        a2 = (r["light_has_bug"] is True)
        a3 = (r["light_saving"] > 0)
        if name.startswith("小型"):
            # 小型模組關鍵命題：light 保留邏輯、簽名模式丟邏輯（v5.1 的價值所在）
            a4 = (r["light_has_bug"] is True and r["sig_has_bug"] is False)
        else:
            a4 = True
        case_ok = a1 and a2 and a3 and a4
        ok = ok and case_ok
        print(f"  斷言: 簽名丟邏輯={a1} light保留邏輯={a2} light真省={a3} 小型light保邏輯/簽名丟={a4} -> {'PASS' if case_ok else 'FAIL'}\n")
    print("總結:", "ALL PASS v5.1 修復成立" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
