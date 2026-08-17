# -*- coding: utf-8 -*-
"""verify_code_v55.py —  code-aware 壓縮確定性驗證（V-19，零 API）

驗證 code_compressor + 兩代理層 code 路由：
  V-19a 重複定義去重：400 個相同 stub + 20 個唯一 FUNC-XX → 只留 1 stub + 摺疊註記，
        降幅顯著（>80%）且 FUNC-07 區塊（含註解/docstring）完整保留（保品質）
  V-19b 非 code 文字不被誤壓（代理層 routing 不誤觸發）
  V-19c ts_proxy_server.compress_content 對 CODE-BIG 格式路由到 code 方法且降幅 >50%
  V-19d mcp_proxy.CompressionEngine.process 對 code 路由 + read_more 還原保真
  V-19e 多語言（Go/JS）去重生效
純標準庫；ALL PASS 才算通過。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import code_compressor as cc
import ts_proxy_server as ts
from mcp_proxy import CompressionEngine


def _make_code_big(stub_repeat=400):
    stub = "def _util_helper(x):\n    # 通用預處理\n    return x\n"
    funcs = ""
    for i in range(1, 21):
        funcs += (f"# === FUNC-{i:02d} 說明：處理第{i}類資料校驗 ===\n"
                  f"def validate_{i:02d}(data):\n"
                  f"    \"\"\"FUNC-{i:02d}: 校驗輸入規則\"\"\"\n"
                  f"    if not data:\n        return False\n    return True\n\n")
    return stub * stub_repeat + funcs


def verify_v19a():
    code = _make_code_big()
    c = cc.compress_code_block(code, "py")
    cond = [
        (code.count("_util_helper") - c.count("_util_helper")) >= 399,   # 去重掉 399 個 stub
        "FUNC-07" in c and "處理第7類" in c,                              # 答案函式完整保留
        len(c) < 0.2 * len(code),                                          # 降幅 >80%
        "\n\n" not in c,                                                   # 無空白行
    ]
    return all(cond), {"removed_stubs": code.count("_util_helper") - c.count("_util_helper"),
                      "func07_ok": "FUNC-07" in c and "處理第7類" in c,
                      "ratio": round(len(c) / len(code), 3)}


def verify_v19b():
    prose = "這是一段普通的說明文字，描述需求與系統背景，沒有程式碼，只是敘述。\n" * 30
    out, meta = cc.compress_code_in_text(prose)
    # 代理層也不應把純文字當 code 壓
    r = ts.compress_content(prose)
    cond = [
        meta["compressed"] is False,
        r["meta"]["method"] != "code_block" and r["meta"]["method"] != "code_inline",
    ]
    return all(cond), {"code_in_text_method": meta["method"], "ts_method": r["meta"]["method"]}


def verify_v19c():
    code = _make_code_big()
    msg = (f"以下是某專案的程式碼：\n```python\n{code}\n```\n"
           f"請說明 FUNC-07 這個函式的用途（看註解說明）。")
    r = ts.compress_content(msg)
    saved = len(msg) - len(r["compressed"])
    cond = [
        r["meta"]["method"].startswith("code "),
        saved / len(msg) > 0.5,
        "FUNC-07" in r["compressed"] and "處理第7類" in r["compressed"],
    ]
    return all(cond), {"method": r["meta"]["method"], "saving_pct": round(100 * saved / len(msg), 1)}


def verify_v19d():
    code = _make_code_big()
    eng = CompressionEngine(min_tokens=50)
    msg = f"```python\n{code}\n```"
    out, meta = eng.process("read_file", msg)
    # 原文存 read_more，壓後 code 內聯
    handle = meta.get("handle")
    back = eng.read_more(handle, length=10 ** 9) if handle else ""
    cond = [
        meta["kind"].startswith("code "),
        back == msg,                                       # read_more 還原保真
        "FUNC-07" in out,                                  # 壓後仍含關鍵函式
    ]
    return all(cond), {"kind": meta["kind"], "roundtrip": back == msg}


def verify_v19e():
    go = ("package main\n\nfunc helper(x int) int {\n\treturn x\n}\n\n") * 50
    gc = cc.compress_code_block(go, "go")
    js = ("function adder(a, b) {\n  // 註解\n  return a + b;\n}\n") * 40
    jc = cc.compress_code_block(js, "js")
    cond = [
        (go.count("func helper") - gc.count("func helper")) >= 49,
        (js.count("function adder") - jc.count("function adder")) >= 39,
        len(gc) < 0.1 * len(go),
    ]
    return all(cond), {"go_removed": go.count("func helper") - gc.count("func helper"),
                      "js_removed": js.count("function adder") - jc.count("function adder")}


def main():
    cases = {
        "V-19a code dedup + 保品質": verify_v19a,
        "V-19b 非 code 不誤壓": verify_v19b,
        "V-19c ts 代理路由 CODE-BIG": verify_v19c,
        "V-19d mcp 代理路由 + read_more": verify_v19d,
        "V-19e 多語言去重": verify_v19e,
    }
    all_pass = True
    print("=== verify_code_v55 (V-19 code-aware, 零 API) ===")
    for name, fn in cases.items():
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, {"error": str(e)}
        all_pass = all_pass and ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    print("=== " + ("ALL PASS ✅" if all_pass else "FAIL ❌") + " ===")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
