# -*- coding: utf-8 -*-
"""mcp_proxy.py —  MCP 透明代理（攔截式工具回傳壓縮）

在「Agent ↔ 下游 MCP server」之間插一層透明代理：`tools/call` 的回傳先過
CompressionEngine，大回傳壓縮（JSON→CSV / 長文字頭尾+統計）後才送回 LLM，
原文存於 read_more 可回溯。純 Python 標準庫，零第三方依賴，stdio JSON-RPC。

用法：
  # 包住一個下游 MCP server（stdio 傳輸）
  python mcp_proxy.py --downstream "python my_mcp_server.py" \
      --min-tokens 2000 --no-compress "math_,code_,search_strict"

  # 自測（不啟下游，驗證壓縮引擎）
  python mcp_proxy.py --self-test

設計原則（研究實證的護欄）：
  1. isError / 權限類訊息直通不壓
  2. 短輸出（< min_tokens）不壓——避免淨成本（should_compress 動態閾值思路）
  3. read_more 可回溯——非靜默丟棄
  4. --no-compress 可依任務型別關閉（math / code-debug / 法務）
  5. 勿動態壓縮 system prompt 前綴（與 prompt cache 相衝，反更貴）——本代理不碰前綴
"""
import json
import hashlib
import re
import shlex
import subprocess
import sys


def est_tokens(text: str) -> int:
    """估算 token：優先 tiktoken（精確），缺省 len//3（降級）。"""
    try:
        import tiktoken
        _enc = tiktoken.get_encoding("cl100k_base")
        return len(_enc.encode(text))
    except Exception:
        return len(text) // 3


class CompressionEngine:
    """攔截式壓縮引擎：決定是否壓、壓縮、存原文、read_more 回溯。"""

    def __init__(self, min_tokens: int = 2000, store=None):
        self.min_tokens = min_tokens
        self.store = store if store is not None else {}
        self.counter = 0
        self.stats = {"compressed": 0, "passthrough_short": 0, "passthrough_error": 0,
                      "bytes_saved": 0}

    def _store_full(self, text: str) -> str:
        #  修復：handle 改用內容 sha256（前 12 位）取代遞增計數器。
        # 舊版計數器讓同輸入跑兩次 handle 不同（r1/r2...）→ 輸出非確定性 → cache miss + 非冪等。
        # hash handle 天然確定性，且即為原文指紋（完整性驗證 A：可確認 read_more 還原的是原文）。
        handle = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]
        self.store[handle] = text
        return handle

    def read_more(self, handle: str, offset: int = 0, length: int = 2000) -> str:
        """回溯被壓縮的原文（offset/length 切片）。"""
        text = self.store.get(handle)
        if text is None:
            return f"[read_more] handle {handle} 不存在（原文可能已過期）"
        return text[offset:offset + length]

    def process(self, tool_name: str, result_text: str) -> tuple:
        """處理一段工具回傳，回傳 (新文本, meta)。

        規則：
        - 短輸出 → 直通（不壓，避免淨成本）
        - JSON 多行 dict 陣列 → JSON→CSV（去重複 key 名）
        - 其他長文字 → 頭 30 行 + 尾 10 行 + 統計 + read_more
        """
        meta = {"compressed": False, "tool": tool_name}
        if not result_text:
            return result_text, meta
        tok = est_tokens(result_text)
        if tok < self.min_tokens:
            self.stats["passthrough_short"] += 1
            meta["reason"] = f"short({tok}<{self.min_tokens})"
            return result_text, meta

        stripped = result_text.strip()
        #  BOM 修復：Windows 檔案常帶 \ufeff，會擋住 JSON 判斷
        if stripped[:1] == "\ufeff":
            stripped = stripped[1:]
        # JSON 類 → json_compressor（多行 dict 陣列才值得，單行 dict 反增 header）
        if stripped[:1] in ("[", "{"):
            try:
                data = json.loads(stripped)
                # ：對話格式優先用 conversation_compressor
                from conversation_compressor import _detect_conversation, compress_conversation
                if _detect_conversation(data):
                    compressed, cmeta = compress_conversation(data, max_chars=200)
                    handle = self._store_full(result_text)
                    saved = len(result_text) - len(compressed)
                    self.stats["compressed"] += 1
                    self.stats["bytes_saved"] += saved
                    meta.update(compressed=True, kind="conversation", handle=handle,
                                saved_chars=saved, total_messages=cmeta.get("total_messages"),
                                folded_count=cmeta.get("folded_count"))
                    return compressed + f"\n[read_more:{handle}]", meta
                from json_compressor import should_compress_json, compress_json_enhanced
                if should_compress_json(data):
                    compressed = compress_json_enhanced(data)  #  增強版：常數欄位+空欄位+巢狀扁平化
                    handle = self._store_full(result_text)
                    saved = len(result_text) - len(compressed)
                    self.stats["compressed"] += 1
                    self.stats["bytes_saved"] += saved
                    meta.update(compressed=True, kind="json→csv", handle=handle,
                                saved_chars=saved)
                    return compressed + f"\n[read_more:{handle}]", meta
            except (ValueError, json.JSONDecodeError):
                pass

        #  code-aware 路由（B 任務）：fenced code / code-like → 去重+空白精簡。
        # 原文存 read_more（深層 debug 可還原），壓後 code 內聯送回（keyline 會丟邏輯，不適用 code）。
        try:
            from code_compressor import compress_code_in_text as _cc
            ctext, cmeta = _cc(result_text)
            if cmeta["compressed"]:
                handle = self._store_full(result_text)
                saved = len(result_text) - len(ctext)
                self.stats["compressed"] += 1
                self.stats["bytes_saved"] += saved
                meta.update(compressed=True, kind="code " + cmeta["method"], handle=handle,
                            saved_chars=saved, lang=cmeta.get("lang"))
                return ctext + f"\n[read_more:{handle}]", meta
        except Exception:
            pass

        # ：長文字用關鍵行提取（替代單純 head/tail，數據/錯誤/結論行優先）
        from keyline_extractor import extract_key_lines
        lines = result_text.splitlines()
        if len(lines) > 50:  # 只有超過50行才用關鍵行提取
            compressed, kmeta = extract_key_lines(result_text, head=10, tail=5, max_key=40)
            handle = self._store_full(result_text)
            saved = len(result_text) - len(compressed)
            self.stats["compressed"] += 1
            self.stats["bytes_saved"] += saved
            meta.update(compressed=True, kind="text keyline", handle=handle,
                        saved_chars=saved, total_lines=kmeta.get("total_lines"),
                        kept_lines=kmeta.get("kept_lines"), key_lines=kmeta.get("key_lines"))
            return compressed + f"\n[read_more:{handle}]", meta

        # 中等長度文字：頭 30 + 尾 10 + 統計
        head = "\n".join(lines[:30])
        tail = "\n".join(lines[-10:])
        handle = self._store_full(result_text)
        new = (f"[工具回傳已壓縮 {len(lines)} 行 / {tok} tok：頭30行+尾10行，"
               f"原文可 read_more 回溯]\n{head}\n...（中間省略）...\n{tail}\n[read_more:{handle}]")
        saved = len(result_text) - len(new)
        self.stats["compressed"] += 1
        self.stats["bytes_saved"] += saved
        meta.update(compressed=True, kind="text head/tail", handle=handle, saved_chars=saved)
        return new, meta


class McpProxy:
    """stdio JSON-RPC 透明代理：對上是 MCP server，對下是下游 MCP server（子程序）。"""

    def __init__(self, downstream_cmd, min_tokens: int = 2000, no_compress=None):
        self.downstream_cmd = shlex.split(downstream_cmd)
        self.engine = CompressionEngine(min_tokens=min_tokens)
        self.no_compress = no_compress or []
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            self.downstream_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1)

    def _call_downstream(self, msg) -> dict:
        """送一行 JSON-RPC 給下游並讀回一行。"""
        if self.proc is None:
            self.start()
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        return json.loads(line) if line.strip() else None

    def _should_compress(self, tool_name: str) -> bool:
        for pat in self.no_compress:
            if re.search(pat, tool_name):
                return False
        return True

    def handle(self, msg: dict):
        """處理一行 MCP JSON-RPC 訊息，回傳響應（notification 回 None）。"""
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if msg_id is None:
            # notification（如 initialized）→ 直通下游，無響應
            self._call_downstream(msg)
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        if method == "tools/list":
            resp = self._call_downstream(msg)
            if resp and isinstance(resp.get("result"), dict):
                tools = resp["result"].setdefault("tools", [])
                tools.append({
                    "name": "read_more",
                    "description": "回溯被 MCP 代理壓縮的工具回傳原文（由 [read_more:handle] 標記給出 handle）。",
                    "inputSchema": {"type": "object",
                                    "properties": {
                                        "handle": {"type": "string"},
                                        "offset": {"type": "integer", "default": 0},
                                        "length": {"type": "integer", "default": 2000}},
                                    "required": ["handle"]},
                })
            return resp

        if method == "tools/call":
            name = params.get("name", "")
            if name == "read_more":
                args = params.get("arguments", {})
                text = self.engine.read_more(args.get("handle", ""),
                                             int(args.get("offset", 0)),
                                             int(args.get("length", 2000)))
                return {"jsonrpc": "2.0", "id": msg_id,
                        "result": {"content": [{"type": "text", "text": text}], "isError": False}}
            resp = self._call_downstream(msg)
            # 攔截壓縮工具回傳
            if resp and isinstance(resp.get("result"), dict) and self._should_compress(name):
                res = resp["result"]
                if not res.get("isError"):
                    texts = [c.get("text", "") for c in res.get("content", [])
                             if isinstance(c, dict) and c.get("type") == "text"]
                    if texts:
                        new_text, meta = self.engine.process(name, "\n".join(texts))
                        if meta.get("compressed"):
                            res["content"] = [{"type": "text", "text": new_text}]
                            sc = res.setdefault("structuredContent", {})
                            sc["_proxy"] = meta
            return resp

        # 其他方法（resources/*、prompts/* 等）→ 直通
        return self._call_downstream(msg)

    def serve(self):
        """主迴圈：讀 stdin 一行一行處理（MCP stdio 傳輸 = 每行一個 JSON-RPC）。"""
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            resp = self.handle(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


def self_test():
    """離線自測：驗證壓縮決策與 read_more 回溯（供 verify_code_v53 直接 import 使用）。"""
    eng = CompressionEngine(min_tokens=200)
    big_json = json.dumps([{"product": f"產品{i}", "sales": 1000 - i * 10,
                            "note": "很長很長很長很長很長很長很長很長很長很長很長很長很長" * 3}
                           for i in range(1, 31)], ensure_ascii=False)
    new, meta = eng.process("search", big_json)
    results = {
        "json_compressed": meta.get("compressed") is True and meta.get("kind") == "json→csv",
        "json_saved": (len(big_json) - len(new)) > 0,
        "json_has_readmore": "[read_more:" in new,
    }
    # read_more 回溯保真（指定足夠大的 length 取回全文）
    h = meta.get("handle")
    back = eng.read_more(h, length=10 ** 9) if h else ""
    results["readmore_roundtrip"] = back == big_json
    # 短輸出直通
    short, m2 = eng.process("search", "hello world")
    results["short_passthrough"] = (m2.get("compressed") is False) and short == "hello world"
    # 長文字壓縮（：超過50行走 keyline，否則走 head/tail）
    long_text = "\n".join(f"line {i:03d} " + "資料內容" * 8 for i in range(100))
    new2, m3 = eng.process("db_query", long_text)
    results["text_headtail"] = (m3.get("compressed") is True
                                and m3.get("kind") in ("text head/tail", "text keyline")
                                and "line 000" in new2 and "line 099" in new2)
    # 錯誤直通（process 不處理 isError，由 Proxy 層保證——這裡驗證引擎不誤壓短/錯誤）
    return results


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="tokknife MCP 透明代理")
    ap.add_argument("--downstream", help="下游 MCP server 啟動命令（stdio），如 'python my_server.py'")
    ap.add_argument("--min-tokens", type=int, default=2000, help="低於此 token 的回傳不壓（防淨成本）")
    ap.add_argument("--no-compress", default="", help="逗號分隔的工具名正則，命中則不壓（如 'math_,code_'）")
    ap.add_argument("--self-test", action="store_true", help="離線自測壓縮引擎（不需下游）")
    a = ap.parse_args()

    if a.self_test:
        r = self_test()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if all(r.values()) else 1)
    if not a.downstream:
        ap.error("需指定 --downstream 或 --self-test")
    proxy = McpProxy(a.downstream, min_tokens=a.min_tokens,
                     no_compress=[p for p in a.no_compress.split(",") if p])
    proxy.serve()
