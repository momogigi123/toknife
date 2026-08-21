# -*- coding: utf-8 -*-
"""code_context_extractor.py — 代碼場景上下文自動精簡（豆包二輪 P0 落地）
把程式碼壓成「簽名級」上下文再送 LLM，比整檔省 80%+ token。
用法：
  python code_context_extractor.py app.py                 # 單檔簽名
  python code_context_extractor.py src/ --recursive        # 目錄遞迴
  python code_context_extractor.py app.py --include-body    # 含函數體（前 15 行）
支援 Python（ast，零依賴）；其他語言降級為「行數統計 + 前 N 行」。
"""
import ast
import argparse
import os
import sys
from typing import List, Dict


def _strip_body(src_lines: List[str]) -> str:
    """v5.1：壓縮函數體——去註解/空行/docstring，保留邏輯行。
    目的：code-review 需看邏輯找 bug，但註解/空行/docstring 不影響判斷，可省。"""
    kept = []
    in_doc = False
    for ln in src_lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        # 跳過 docstring（成對三重引號）
        if s.startswith('"""') or s.startswith("'''"):
            if s.count('"""') == 2 or s.count("'''") == 2:
                continue  # 單行 docstring
            in_doc = not in_doc
            continue
        if in_doc:
            continue
        kept.append(ln.rstrip())
    return "\n".join(kept)


def extract_signatures_py(path: str, include_body: bool = False,
                          compress_body: bool = False) -> List[Dict]:
    """用 ast 提取 Python 函數/類簽名，不含實現（可選含函數體）。
    compress_body=True：含體但去註解/空行/docstring（v5.1 code-review 模式，保留邏輯省 token）。"""
    with open(path, encoding="utf-8-sig") as f:
        tree = ast.parse(f.read())
    out = []
    src = open(path, encoding="utf-8-sig").read().splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            ret = ast.unparse(node.returns) if node.returns else ""
            doc = ast.get_docstring(node) or ""
            sig = f"def {node.name}({', '.join(args)})" + (f" -> {ret}" if ret else "")
            body = ""
            if include_body:
                body_lines = src[node.lineno:node.end_lineno]
                if compress_body:
                    body = _strip_body(body_lines)
                else:
                    body = "\n".join(body_lines[:15])
            out.append({"type": "function", "signature": sig,
                        "doc": doc.splitlines()[0] if doc else "", "body": body})
        elif isinstance(node, ast.ClassDef):
            out.append({"type": "class", "signature": f"class {node.name}",
                        "doc": (ast.get_docstring(node) or "").splitlines()[0] if ast.get_docstring(node) else ""})
    return out


def compress_code_light(path: str) -> str:
    """v5.1：整檔輕量壓縮（保留 100% 邏輯行，去註解/空行/docstring）。
    用途：code-review/debug 任務——bug 通常藏在邏輯行，註解/空行/docstring 不影響判斷。
    相比簽名萃取：不丟任何邏輯，品質不傷；相比含原文正文：真的省 token（無封裝開銷）。"""
    src = open(path, encoding="utf-8-sig").read().splitlines()
    return _strip_body(src)


# ===== v5.3：code medium 折疊（第三檔，降幅 31% → ~50%） =====

def _sig_line(node) -> str:
    """重組函數/方法簽名（不含體）。"""
    args = [a.arg for a in node.args.args]
    ret = ast.unparse(node.returns) if node.returns else ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(args)}):" + (f" -> {ret}" if ret else "")


def _collect_flow(stmt, src, out, seen, depth=0):
    """收集控制流關鍵行（if/for/while/try/with/return/raise），去重保序；不進入巢狀函式/類。"""
    if depth > 4:
        return
    if isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.Return, ast.Raise)):
        line = src[stmt.lineno - 1].strip()
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    for child in ast.iter_child_nodes(stmt):
        _collect_flow(child, src, out, seen, depth + 1)


def _dedent(text: str) -> str:
    """去除整段統一的縮排（折疊重排用）。"""
    import textwrap
    return textwrap.dedent(text)


def _fold_function(node, src, fold_threshold, keep_head) -> list:
    """折疊單一函數：短函數整留（保邏輯）；長函數簽名+前N行+控制流骨架+省略標記。"""
    body_lines = src[node.lineno - 1:node.end_lineno]
    body_n = len(body_lines)
    deco = [src[d.lineno - 1].strip() for d in node.decorator_list if d.lineno]
    out = deco + [_sig_line(node)]
    if body_n <= fold_threshold:
        body = _dedent(_strip_body(body_lines[1:]))
        if body:
            out.append("\n".join("    " + l for l in body.splitlines()))
        return out
    # 長函數：前 keep_head 行
    head = _dedent(_strip_body(body_lines[1:1 + keep_head]))
    if head:
        out.append("\n".join("    " + l for l in head.splitlines()))
    # 控制流骨架（遍歷函數體各語句，而非函數節點本身）
    skel = []
    for stmt in node.body:
        _collect_flow(stmt, src, skel, set())
    if skel:
        out.append("    # 控制流骨架:")
        for s in skel[:12]:
            out.append("    " + s)
    out.append(f"    # ... 省略 {max(0, body_n - 1 - keep_head)} 行（折疊，需要細節可用 light 模式）")
    return out


def compress_code_medium(path: str, fold_threshold: int = 40, keep_head: int = 8) -> str:
    """v5.3：medium 檔代碼壓縮——折疊長函數體（簽名+前N行+控制流骨架），短函數整留。

    定位：在 light（保全部邏輯、省 ~13-31%）與 signature（只抽簽名、省 ~90% 但丟邏輯）
    之間取折衷：大檔程式碼降幅拉高到 ~50%，同時保留控制流骨架與短函數完整邏輯。
    風險：長函數深處的副作用/例外路徑/效能細節會被折疊掉 → 深層 debug 任務仍用 light。
    """
    with open(path, encoding="utf-8-sig") as f:
        src = f.read().splitlines()
    try:
        tree = ast.parse("\n".join(src))
    except SyntaxError:
        return _strip_body(src)  # 非合法 Python 降級 light
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.extend(_fold_function(node, src, fold_threshold, keep_head))
        elif isinstance(node, ast.ClassDef):
            out.append(f"class {node.name}:")
            doc = ast.get_docstring(node)
            if doc:
                out.append(f"    # {doc.splitlines()[0]}")
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for l in _fold_function(m, src, fold_threshold, keep_head):
                        out.append("    " + l)
                elif isinstance(m, ast.ClassDef):
                    out.append(f"    class {m.name}:")
        elif isinstance(node, ast.Assign):
            # 保留模組級全大寫常數（設定類資訊，審碼常需要）
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    out.append(_strip_body(src[node.lineno - 1:node.end_lineno]))
                    break
    return "\n".join(out)


def extract_context(path: str, recursive: bool = False, include_body: bool = False,
                    compress_body: bool = False) -> str:
    if os.path.isdir(path):
        files = []
        for root, _, names in os.walk(path) if recursive else [(path, [], os.listdir(path))]:
            files += [os.path.join(root, n) for n in names if n.endswith(".py")]
        files = files[:20]  # 上限 20 檔，防爆
    else:
        files = [path]
    lines = [f"[代碼上下文] {len(files)} 個檔案"
             + ("（簽名＋壓縮函數體，保留邏輯）" if include_body and compress_body
                else "（僅簽名，未含實現）" if not include_body else "（含函數體原文）") + ":"]
    total_src = 0
    for f in files:
        if f.endswith(".py"):
            sigs = extract_signatures_py(f, include_body, compress_body)
            total_src += sum(1 for _ in open(f, encoding="utf-8-sig"))
            if not sigs:
                lines.append(f"\n## {f}（無函數/類，{total_src} 行）")
            else:
                lines.append(f"\n## {f}")
                for s in sigs[:30]:
                    lines.append(f"  {s['signature']}" + (f"  # {s['doc']}" if s["doc"] else ""))
                    if s.get("body"):
                        lines.append("    " + s["body"].replace("\n", "\n    "))
        else:
            n = sum(1 for _ in open(f, encoding="utf-8-sig", errors="ignore"))
            lines.append(f"\n## {f}（非 Python，{n} 行，僅統計）")
    return "\n".join(lines)


# ===== v5.4：多語言支援（JS/Go，正則實現，零依賴） =====

import re


def _detect_lang(path: str) -> str:
    """按擴展名檢測語言。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".py", ".pyw"):
        return "py"
    if ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
        return "js"
    if ext in (".go", ".golang"):
        return "go"
    return "py"  # 預設 Python


def _strip_c_style(lines: List[str]) -> str:
    """去 C 風格註解（// 行註解、/* */ 塊註解）和空行，適用 JS/Go。"""
    kept = []
    in_block = False
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if in_block:
            if "*/" in s:
                in_block = False
                # 塊註解結束後的內容保留
                after = s[s.index("*/") + 2:].strip()
                if after and not after.startswith("//"):
                    kept.append(ln.rstrip())
            continue
        # 行註解
        if s.startswith("//"):
            continue
        # 塊註解開始
        if s.startswith("/*"):
            if "*/" in s[2:]:
                continue  # 單行塊註解
            in_block = True
            continue
        # 行內註解（簡單處理：去掉 // 後面的內容，但要排除 URL 等）
        # 這裡保守處理：只去掉以 // 開頭的行註解，行內註解保留（避免誤刪正則/字串中的 //）
        kept.append(ln.rstrip())
    return "\n".join(kept)


def _find_matching_brace(lines: List[str], start_line: int, start_col: int = 0) -> int:
    """從 start_line 的 start_col 開始找匹配的右大括號，返回結束行索引（0-based）。"""
    depth = 0
    for i in range(start_line, len(lines)):
        line = lines[i]
        for j, ch in enumerate(line):
            if i == start_line and j < start_col:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
    return len(lines) - 1


# JS 函數簽名正則
_JS_FUNC_PATTERNS = [
    re.compile(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)'),
    re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>'),
    re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function'),
    re.compile(r'^\s*(\w+)\s*\(([^)]*)\)\s*\{'),  # 物件方法/類方法
]

# Go 函數簽名正則
_GO_FUNC_PATTERN = re.compile(r'^\s*func\s+(?:\(([^)]*)\)\s+)?(\w+)\s*\(([^)]*)\)\s*(.*?)\{')


def _extract_js_functions(lines: List[str]) -> List[Dict]:
    """用正則提取 JS 函數位置和簽名。"""
    funcs = []
    for i, line in enumerate(lines):
        for pat in _JS_FUNC_PATTERNS:
            m = pat.match(line)
            if m:
                name = m.group(1)
                # 找函數體開始的 {（用 rfind，避免匹配到參數中的 {}）
                brace_col = line.rfind("{")
                if brace_col == -1:
                    # 箭頭函數可能沒有 {（單行返回），跳過
                    continue
                end_line = _find_matching_brace(lines, i, brace_col)
                sig = line.strip()
                # 去掉行尾的 {
                if sig.endswith("{"):
                    sig = sig[:-1].strip()
                funcs.append({"name": name, "sig": sig, "start": i, "end": end_line})
                break
    return funcs


def _extract_go_functions(lines: List[str]) -> List[Dict]:
    """用正則提取 Go 函數位置和簽名（用行尾 { 前面的內容做簽名，避免返回類型中的 {} 干擾）。"""
    funcs = []
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("func ") and "{" in s:
            brace_col = line.rfind("{")
            sig = line[:brace_col].rstrip()
            # 提取函數名（用於標識）
            name_match = re.search(r'func\s+(?:\([^)]*\)\s+)?(\w+)', sig)
            name = name_match.group(1) if name_match else "unknown"
            end_line = _find_matching_brace(lines, i, brace_col)
            funcs.append({"name": name, "sig": sig, "start": i, "end": end_line})
    return funcs


def _compress_c_medium(lines: List[str], funcs: List[Dict],
                       fold_threshold: int = 40, keep_head: int = 8) -> str:
    """C 風格語言 medium 折疊：短函數整留，長函數簽名+前N行+控制流骨架。"""
    # 標記函數行範圍
    func_ranges = [(f["start"], f["end"]) for f in funcs]
    in_func = [False] * len(lines)
    for start, end in func_ranges:
        for i in range(start, end + 1):
            if 0 <= i < len(in_func):
                in_func[i] = True

    out = []
    func_idx = 0
    i = 0
    while i < len(lines):
        # 檢查是否是函數開始
        if func_idx < len(funcs) and funcs[func_idx]["start"] == i:
            f = funcs[func_idx]
            body_lines = lines[f["start"]:f["end"] + 1]
            body_n = len(body_lines)
            out.append(f["sig"] + " {")
            if body_n <= fold_threshold:
                # 短函數：去註解後保留
                stripped = _strip_c_style(body_lines[1:-1]) if body_n > 2 else ""
                if stripped:
                    for l in stripped.splitlines():
                        out.append("    " + l.strip())
                out.append("}")
            else:
                # 長函數：前 keep_head 行 + 控制流骨架
                head_lines = body_lines[1:1 + keep_head]
                head_stripped = _strip_c_style(head_lines)
                if head_stripped:
                    for l in head_stripped.splitlines():
                        out.append("    " + l.strip())
                # 控制流骨架（if/for/while/switch/return/throw）
                flow_keywords = ("if ", "if(", "for ", "for(", "while ", "while(",
                                 "switch ", "switch(", "return ", "return;", "throw ", "try ", "catch ")
                skel = []
                for l in body_lines[1 + keep_head:]:
                    s = l.strip()
                    if any(s.startswith(kw) for kw in flow_keywords):
                        skel.append(s)
                if skel:
                    out.append("    // 控制流骨架:")
                    for s in skel[:12]:
                        out.append("    " + s)
                out.append(f"    // ... 省略 {max(0, body_n - 1 - keep_head)} 行（折疊）")
                out.append("}")
            i = f["end"] + 1
            func_idx += 1
        else:
            # 非函數行：去註解空行後保留（import/const/變數宣告等）
            s = lines[i].strip()
            if s and not s.startswith("//") and not s.startswith("/*"):
                out.append(lines[i].rstrip())
            i += 1
    return "\n".join(out)


def compress_code_js_light(path: str) -> str:
    """JS 輕量壓縮：去註解/空行，保留全部邏輯。"""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    return _strip_c_style(lines)


def compress_code_js_medium(path: str, fold_threshold: int = 40, keep_head: int = 8) -> str:
    """JS medium 折疊：短函數整留，長函數簽名+前N行+控制流骨架。"""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    funcs = _extract_js_functions(lines)
    if not funcs:
        return _strip_c_style(lines)
    return _compress_c_medium(lines, funcs, fold_threshold, keep_head)


def compress_code_go_light(path: str) -> str:
    """Go 輕量壓縮：去註解/空行，保留全部邏輯。"""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    return _strip_c_style(lines)


def compress_code_go_medium(path: str, fold_threshold: int = 40, keep_head: int = 8) -> str:
    """Go medium 折疊：短函數整留，長函數簽名+前N行+控制流骨架。"""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    funcs = _extract_go_functions(lines)
    if not funcs:
        return _strip_c_style(lines)
    return _compress_c_medium(lines, funcs, fold_threshold, keep_head)


# 多語言統一入口（覆蓋原有函數，保持向後相容）

def compress_code_light(path: str, lang: str = "auto") -> str:
    """v5.4：多語言輕量壓縮（auto=按擴展名檢測）。"""
    if lang == "auto":
        lang = _detect_lang(path)
    if lang == "js":
        return compress_code_js_light(path)
    if lang == "go":
        return compress_code_go_light(path)
    # Python（原有實現）
    src = open(path, encoding="utf-8-sig").read().splitlines()
    return _strip_body(src)


def compress_code_medium(path: str, fold_threshold: int = 40, keep_head: int = 8, lang: str = "auto") -> str:
    """v5.4：多語言 medium 折疊（auto=按擴展名檢測）。"""
    if lang == "auto":
        lang = _detect_lang(path)
    if lang == "js":
        return compress_code_js_medium(path, fold_threshold, keep_head)
    if lang == "go":
        return compress_code_go_medium(path, fold_threshold, keep_head)
    # Python（原有實現）
    with open(path, encoding="utf-8-sig") as f:
        src = f.read().splitlines()
    try:
        tree = ast.parse("\n".join(src))
    except SyntaxError:
        return _strip_body(src)
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.extend(_fold_function(node, src, fold_threshold, keep_head))
        elif isinstance(node, ast.ClassDef):
            out.append(f"class {node.name}:")
            doc = ast.get_docstring(node)
            if doc:
                out.append(f"    # {doc.splitlines()[0]}")
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for l in _fold_function(m, src, fold_threshold, keep_head):
                        out.append("    " + l)
                elif isinstance(m, ast.ClassDef):
                    out.append(f"    class {m.name}:")
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    out.append(_strip_body(src[node.lineno - 1:node.end_lineno]))
                    break
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--recursive", action="store_true")
    ap.add_argument("--include-body", action="store_true")
    ap.add_argument("--compress-body", action="store_true", help="含函數體但去註解/空行/docstring")
    ap.add_argument("--light", action="store_true", help="v5.1：整檔輕量壓縮（保邏輯去註解，code-review 用）")
    ap.add_argument("--medium", action="store_true",
                    help="v5.3：medium 折疊（簽名+前N行+控制流骨架，長函數折疊，降幅→~50%%）")
    ap.add_argument("--fold-threshold", type=int, default=40, help="medium：函數體超過此行數才折疊")
    ap.add_argument("--lang", choices=["py", "js", "go", "auto"], default="auto",
                    help="v5.4：指定語言（auto=按擴展名檢測）")
    a = ap.parse_args()
    if a.light:
        print(compress_code_light(a.path, lang=a.lang))
    elif a.medium:
        print(compress_code_medium(a.path, fold_threshold=a.fold_threshold, lang=a.lang))
    else:
        ctx = extract_context(a.path, a.recursive, a.include_body, a.compress_body)
        print(ctx)
        if os.path.isfile(a.path):
            src_n = sum(1 for _ in open(a.path, encoding="utf-8-sig"))
            print(f"\n--- 原始 {src_n} 行 → 上下文 {len(ctx.splitlines())} 行 ---")
