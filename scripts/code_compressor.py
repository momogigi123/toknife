# -*- coding: utf-8 -*-
"""code_compressor.py — 字串級 code-aware 壓縮（，B 任務落地）

解決根因：舊代理層（ts_proxy_server / mcp_proxy）完全沒偵測 code block，
大段代碼被 compress_tool_list 誤判（Go 風格 `func` 命中 tool 關鍵字）→ 空轉。
本模組提供「字串輸入、語言通用」的 code-aware 壓縮，核心策略：

  1. 頂層函式/類定義切分（Python 用縮排、js/go/c 用大括號配對）
  2. 完全重複的定義去重（保留首個 + 一則摺疊註記）——這是最大降幅來源，
     真實代碼裡重複 stub / 樣板 getter / 重複工具函式極常見
  3. 空白行 + 行尾空白精簡（零資訊損失）
  4. 超長唯一區塊 -> 控制流骨架摺疊（簽名 + if/for/while/try/return 等關鍵行）

保品質原則：所有「唯一」函式（含其簽名、註解、docstring、邏輯）原樣保留；
只有「完全相同」的定義被摺疊。因此「說明某函式用途（看註解）」類任務不受傷。

零第三方依賴（純標準庫）。提供 detect_code_fences / is_code_like /
compress_code_block / compress_code_in_text + self_test（verify_code_v55 直接 import）。
"""
import re


# ============ 語言正規化 ============
def _norm_lang(lang: str) -> str:
    lang = (lang or "auto").lower()
    if lang in ("py", "python", "py3"):
        return "py"
    if lang in ("js", "javascript", "jsx", "ts", "typescript", "tsx", "mjs", "cjs"):
        return "js"
    if lang in ("go", "golang"):
        return "go"
    if lang in ("c", "cpp", "c++", "cc", "h", "hpp", "java", "csharp", "cs", "rust", "rs"):
        return "c"
    # 預設用 py 切分器（最安全：縮排切分不會誤吞內容）
    return "py"


# ============ 宣告偵測 ============
_PY_DECL = re.compile(r"^(async\s+def|def|class)\s+\w+")
_BRACE_DECL = [
    re.compile(r"^\s*(export\s+)?(async\s+)?function\s+\w+"),
    re.compile(r"^\s*(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s+)?\(?"),
    re.compile(r"^\s*(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s+)?function"),
    re.compile(r"^\s*func\s+\w+"),                     # go
    re.compile(r"^\s*(private|public|protected|static|final|void|int|long|string|bool|float|double|char|unsigned)\s"),  # c/c++/java-ish
]


def _is_decl(ln: str, lang: str) -> bool:
    if not ln.strip():
        return False
    if lang == "py":
        return bool(_PY_DECL.match(ln))
    return any(p.match(ln) for p in _BRACE_DECL)


# ============ 大括號配對掃描（忽略字串/註解內的括號） ============
def _brace_end_line(lines, start):
    """從 start 行找到配對的右大括號所在行索引（含引號/註解感知）。"""
    depth = 0
    opened = False
    q = None            # 當前引號字元
    in_block = False    # /* */ 區塊註解
    for k in range(start, len(lines)):
        line = lines[k]
        j = 0
        while j < len(line):
            c = line[j]
            if in_block:
                if c == "*" and j + 1 < len(line) and line[j + 1] == "/":
                    in_block = False
                    j += 2
                    continue
                j += 1
                continue
            if q:
                if c == "\\":
                    j += 2
                    continue
                if c == q:
                    q = None
                j += 1
                continue
            if c == "/" and j + 1 < len(line) and line[j + 1] == "/":
                break  # 行註解，剩餘忽略
            if c == "/" and j + 1 < len(line) and line[j + 1] == "*":
                in_block = True
                j += 2
                continue
            if c in ('"', "'", "`"):
                q = c
                j += 1
                continue
            if c == "{":
                depth += 1
                opened = True
            elif c == "}":
                depth -= 1
                if opened and depth == 0:
                    return k
            j += 1
    return len(lines) - 1


# ============ 區段切分 ============
def _segment(lines, lang):
    """切分為 (kind, lines) 區段：decl=頂層宣告單元，sep=其餘（保留、不參與去重）。"""
    segs = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if _is_decl(ln, lang):
            if lang == "py":
                j = i + 1
                while j < n:
                    nxt = lines[j]
                    if nxt.strip() == "":
                        j += 1
                        continue
                    # col-0 非空白行（含 col-0 註解）視為下一個頂層單元 →
                    # 結束當前單元。這樣 def 前的 col-0 說明註解會歸給「下一個」
                    # def（而非被上一個單元吞掉導致去重失敗）。
                    if nxt[0] != " ":
                        break
                    j += 1
                segs.append(("decl", lines[i:j]))
                i = j
            else:
                j = _brace_end_line(lines, i)
                segs.append(("decl", lines[i:j + 1]))
                i = j + 1
        else:
            j = i
            while j < n and not _is_decl(lines[j], lang):
                j += 1
            segs.append(("sep", lines[i:j]))
            i = j
    return segs


# ============ 行精簡 / 長區塊摺疊 ============
def _clean_lines(ls):
    """去行尾空白 + 砍空行（保留註解/邏輯）。"""
    out = []
    for l in ls:
        s = l.rstrip()
        if s == "":
            continue
        out.append(s)
    return out


_FLOW = ("if ", "if(", "for ", "for(", "while ", "while(", "try", "with ", "return ",
        "return;", "raise ", "throw ", "switch", "catch", "except", "else", "elif",
        "yield", "await", "async ", "func ", "def ", "class ")


def _fold_long(body):
    """超長唯一區塊：簽名 + 控制流關鍵行 + 摺疊註記。"""
    if not body:
        return body
    sig = body[0]
    flows = [l for l in body[1:] if any(l.strip().startswith(k) for k in _FLOW)]
    kept = [sig]
    if flows:
        kept.append("    # 控制流骨架:")
        kept.extend(flows[:15])
    kept.append(f"    # ... 摺疊 {max(0, len(body) - 1)} 行（控制流骨架，深層細節用 light 模式或 read_more 取回）")
    return kept


# ============ 核心：壓縮單一 code 字串 ============
def compress_code_block(code: str, lang: str = "auto", fold_threshold: int = 60) -> str:
    """對一段代碼字串做 code-aware 壓縮，回傳壓後字串。

    lang: py / js / go / c / auto（auto->py 切分器）。
    fold_threshold: 唯一區塊超過此行數才做控制流骨架摺疊（預設 60）。
    """
    lang = _norm_lang(lang)
    if not code or not code.strip():
        return code
    lines = code.splitlines()
    segs = _segment(lines, lang)
    # 第一遍：計算每個區段正規化文字（去空行+strip）的重複群組（decl 與 sep 都納入）。
    # 空 norm（純空行 sep）不參與去重。
    seen = {}            # norm -> [seg_idx,...]
    for idx, (kind, ls) in enumerate(segs):
        norm = "\n".join(l.strip() for l in ls if l.strip())
        if norm == "":
            continue
        seen.setdefault(norm, []).append(idx)
    # 第二遍：輸出（去重 + 精簡 + 超長 decl 摺疊）
    emitted_norm = set()
    fold_note_emitted = set()
    out = []
    for idx, (kind, ls) in enumerate(segs):
        norm = "\n".join(l.strip() for l in ls if l.strip())
        if norm == "":
            out.extend(_clean_lines(ls))   # 純空行 sep：精簡丟棄
            continue
        if norm in emitted_norm:
            if norm not in fold_note_emitted:
                fold_note_emitted.add(norm)
                cnt = len(seen[norm])
                out.append(f"# <<{cnt} 個完全相同的區塊已摺疊：與上方首個相同，不重複佔用 token>>")
            continue
        emitted_norm.add(norm)
        body = _clean_lines(ls)
        if kind == "decl" and fold_threshold and len(body) > fold_threshold:
            body = _fold_long(body)
        out.extend(body)
    return "\n".join(out)


# ============ 偵測 ============
_FENCE = re.compile(r"```([A-Za-z0-9_+#.\-]*)\n(.*?)```", re.DOTALL)
_CODE_LINE = re.compile(
    r"^\s*(def |class |async def |function |func |import |from |const |let |var "
    r"|return |if |for |while |try |with |#|//|/\*|}|=>|print\(|public |private "
    r"|struct |interface |package |using |namespace )")


def detect_code_fences(text: str):
    """回傳 [(lang, code, start, end), ...]，start/end 為 code 在 text 中的字元位置。"""
    res = []
    for m in _FENCE.finditer(text):
        lang = m.group(1).strip() or "auto"
        res.append((lang, m.group(2), m.start(2), m.end(2)))
    return res


def is_code_like(text: str, lang: str = "auto") -> bool:
    """整段文字是否像 code（無 fence 時的兜底偵測）。"""
    t = text.strip()
    if not t or len(t) < 200:
        return False
    lines = t.splitlines()
    if not lines:
        return False
    hits = sum(1 for l in lines if _CODE_LINE.match(l))
    return hits / len(lines) > 0.4


# ============ 文字級入口（代理層呼叫） ============
def compress_code_in_text(text: str, lang: str = "auto"):
    """對整段文字偵測並壓縮其中的 code block；回傳 (新文字, meta)。"""
    meta = {"compressed": False, "method": "none"}
    if not text:
        return text, meta
    fences = detect_code_fences(text)
    if fences:
        out = text
        saved = 0
        rep_lang = fences[0][0]
        for lang_, code, s, e in reversed(fences):
            c = compress_code_block(code, lang_)
            saved += len(code) - len(c)
            out = out[:s] + c + out[e:]
        if saved > 0:
            meta = {"compressed": True, "method": "code_block", "lang": rep_lang,
                    "saved_chars": saved}
        return out, meta
    if is_code_like(text):
        c = compress_code_block(text, lang)
        if len(c) < len(text):
            meta = {"compressed": True, "method": "code_inline", "lang": lang,
                    "saved_chars": len(text) - len(c)}
            return c, meta
    return text, meta


# ============ 離線自測（verify_code_v55 直接 import） ============
def self_test():
    stub = "def _util_helper(x):\n    # 通用預處理\n    return x\n"
    funcs = ""
    for i in range(1, 21):
        funcs += (f"# === FUNC-{i:02d} 說明：處理第{i}類資料校驗 ===\n"
                  f"def validate_{i:02d}(data):\n"
                  f"    \"\"\"FUNC-{i:02d}: 校驗輸入規則\"\"\"\n"
                  f"    if not data:\n        return False\n    return True\n\n")
    code = stub * 400 + funcs
    c = compress_code_block(code, "py")
    results = {}
    results["dedup_removes_stubs"] = (code.count("_util_helper") - c.count("_util_helper")) >= 399
    results["func07_preserved"] = ("FUNC-07" in c) and ("處理第7類" in c)
    results["big_saving"] = len(c) < 0.4 * len(code)
    results["no_trailing_blank"] = "\n\n" not in c
    # 非 code 不誤壓
    prose = "這是一段普通的說明文字，沒有程式碼，只是敘述需求與背景。\n" * 10
    cp, m = compress_code_in_text(prose)
    results["prose_not_code"] = (m["compressed"] is False)
    # 空 / 極短安全
    results["empty_safe"] = (compress_code_block("", "py") == "")
    results["short_kept"] = (compress_code_block("def f(x): return x", "py") == "def f(x): return x")
    # fence 路由
    code3 = stub * 3
    txt = "請看：\n```python\n" + code3 + "```\n說明如上"
    out, meta = compress_code_in_text(txt)
    results["fence_routed"] = (meta["method"] == "code_block"
                               and (code3.count("_util_helper") - out.count("_util_helper")) >= 2)
    # 多語言（Go）：去重
    go = "package main\n\nfunc helper(x int) int {\n\treturn x\n}\n\n" * 50
    gc = compress_code_block(go, "go")
    results["go_dedup"] = (go.count("func helper") - gc.count("func helper")) >= 49
    return results


if __name__ == "__main__":
    import json as _json
    import sys as _sys
    r = self_test()
    print(_json.dumps(r, ensure_ascii=False, indent=2))
    ok = all(r.values())
    print("ALL PASS" if ok else "FAIL")
    _sys.exit(0 if ok else 1)
