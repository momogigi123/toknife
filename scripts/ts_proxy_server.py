# -*- coding: utf-8 -*-
"""ts_proxy_server.py — Toknife Lite 通用 OpenAI 相容代理（輸入端壓縮，6.1-lite）

定位（與商業 Pro 的邊界）：
  - Lite 只在「請求上路前」壓縮輸入（messages），**完全不修改模型輸出**，
    串流（SSE）也只是原樣穿透。輸出端最佳化、可逆外部化、自學習、GUI 儀表板
    等皆為 Pro 功能，不在本檔案範圍。
  - 上游可指向任意 OpenAI 相容端點（OpenAI / DeepSeek / 本機 vLLM、Ollama 等），
    預設透傳客戶端帶入的 model；不再寫死單一廠商或模型。

端點：
  POST /v1/chat/completions  壓縮輸入後轉發（支援 stream=True 原樣 SSE 穿透）
  GET  /v1/models             best-effort 轉發上游模型清單
  GET  /health               本機就緒檢查（不打上游、不洩漏金鑰）
  GET  /stats                本次啟動以來的「輸入端」累計節省（JSON，附 Pro 提示）

啟動：
  python ts_proxy_server.py 8001                         # 相容舊的位置參數
  python ts_proxy_server.py --port 8001 \
      --upstream https://api.openai.com/v1 --model gpt-4o-mini
  上游/金鑰/模型也可用環境變數：OPENAI_BASE_URL(EX_LLM_BASE)、
      OPENAI_API_KEY(EX_LLM_KEY/ARK_API_KEY)、OPENAI_MODEL(EX_LLM_MODEL)。
  若不設定金鑰，會原樣轉發客戶端的 Authorization 標頭。

純標準庫（http.server + urllib），核心零第三方依賴；tiktoken 可選。
"""
import os
import re
import sys
import json
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EDITION = "lite"
__version__ = "6.1-lite"

# ---------------------------------------------------------------- 設定（argparse + env）
def load_config(argv=None):
    """解析啟動參數；相容舊式 `python ts_proxy_server.py 8001` 位置參數。"""
    import argparse
    p = argparse.ArgumentParser(description="Toknife Lite OpenAI-compatible input-side proxy")
    p.add_argument("port_pos", nargs="?", type=int, help="port（位置參數，相容舊用法）")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--upstream", default=os.environ.get("OPENAI_BASE_URL")
                   or os.environ.get("EX_LLM_BASE"))
    p.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY")
                   or os.environ.get("EX_LLM_KEY") or os.environ.get("ARK_API_KEY"))
    p.add_argument("--model", default=os.environ.get("OPENAI_MODEL")
                   or os.environ.get("EX_LLM_MODEL"))
    p.add_argument("--host", default="127.0.0.1")
    # 被 import（含 pytest）時不解析 sys.argv，避免外部執行器參數干擾
    args, _ = p.parse_known_args(argv if argv is not None else [])
    port = args.port or args.port_pos or int(os.environ.get("PORT", "8001"))
    upstream = (args.upstream or "https://api.openai.com/v1").strip()
    return {
        "host": args.host, "port": port, "upstream": upstream,
        "api_key": args.api_key, "model": (args.model or "").strip(),
    }


CONFIG = load_config()
UPSTREAM = CONFIG["upstream"]
API_KEY = CONFIG["api_key"]
FIXED_MODEL = CONFIG["model"]            # 空字串＝透傳客戶端 model
MODEL = FIXED_MODEL                      # 向舊變數名靠攏
HOST = CONFIG["host"]

COMPACT_THRESHOLD = 2000   # 字元；超過 → Lite 採「損耗性截斷」（Pro 為可逆外部化）
HIST_LIMIT = 6000          # 歷史 tokens 上限；超過 → auto_compact
UPSTREAM_TIMEOUT = int(os.environ.get("TS_UPSTREAM_TIMEOUT", "180"))

PRO_NOTE = ("Toknife Pro adds output-side optimization, 100% reversible long-context, "
            "a savings dashboard and one-click install: https://momogigi123.github.io/toknife/")


def _join_url(base, leaf):
    """把上游 base 與端點葉名接起來。base 已帶版本段(v1/v2/v3)就直接接，否則補 /v1。"""
    b = (base or "").rstrip("/")
    if re.search(r"/v\d+$", b):
        return b + "/" + leaf
    return b + "/v1/" + leaf


CHAT_URL = _join_url(UPSTREAM, "chat/completions")
MODELS_URL = _join_url(UPSTREAM, "models")


def _est_tok(s):
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(s))
    except Exception:
        cjk = sum(1 for ch in (s or "") if "一" <= ch <= "鿿")
        return int(round(cjk * 1.5 + (len(s or "") - cjk) * 0.25))


def _detect_lang(text: str) -> str:
    """語言感知：CJK 占比高 → 'zh'，否則 'en'。"""
    if not text:
        return "zh"
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "zh" if cjk >= latin else "en"


def _is_question_or_instruction(ln: str, lang: str) -> bool:
    """問題/指令行永遠保留（不進關鍵行丟棄邏輯）。"""
    if "?" in ln or "？" in ln:
        return True
    low = ln.lower()
    if lang == "zh":
        sig = ("問題", "請問", "問：", "任務", "指令", "回答", "答案", "總結", "提取")
    else:
        sig = ("question", "q:", "task", "instruction", "answer", "according to",
               "read the document", "summar", "extract", "identify", "find", "retrieve")
    return any(s in low for s in sig)


def compress_tool_list(text: str) -> dict:
    """工具描述結構化壓縮（真實 Agent 場景）：保留功能/參數句，砍填充句，收益閘門把關。"""
    lines = text.splitlines()
    tool_sig = ("tool_", "func", "函數", "【工具", "功能-", "功能：", "tool:")
    hits = sum(1 for ln in lines if any(s in ln.lower() for s in tool_sig))
    if hits < 2:
        return {"compressed": None, "meta": {"compressed": False, "method": "not_tool_list"}}
    keep_sig = ("功能", "參數", "回傳", "返回", "input", "param", "tool_")
    drop_sig = ("此工具用於", "支援", "包含", "以及", "用於日常", "含異常", "與日誌", "批量")
    out = []
    for ln in lines:
        if not any(s in ln.lower() for s in tool_sig):
            out.append(ln)
            continue
        sents = [s + "。" for s in ln.split("。") if s.strip()]
        kept = [s for s in sents if any(k in s.lower() for k in keep_sig)
                and not any(d in s for d in drop_sig)]
        if not kept:
            kept = sents[:1]
        out.append("".join(kept[:3]))
    compressed = "\n".join(out)
    if len(compressed) >= len(text):
        return {"compressed": None, "meta": {"compressed": False, "method": "no_gain"}}
    return {"compressed": compressed, "meta": {"compressed": True, "method": "tool_list_struct"}}


def compress_tools_schema(text: str) -> dict:
    """OpenAI tools 陣列結構化壓縮：保留 name/required/屬性名，砍冗長 description。"""
    try:
        data = json.loads(text)
    except Exception:
        return {"compressed": None, "meta": {"compressed": False, "method": "not_json"}}
    tools = data if isinstance(data, list) else data.get("tools", [])
    if not isinstance(tools, list) or not tools:
        return {"compressed": None, "meta": {"compressed": False, "method": "not_tools"}}
    is_tools = any(isinstance(t, dict) and (t.get("type") == "function" or "function" in t) for t in tools)
    if not is_tools:
        return {"compressed": None, "meta": {"compressed": False, "method": "not_tools"}}
    out = []
    for t in tools:
        fn = t.get("function", t) if isinstance(t, dict) else {}
        name = fn.get("name", "")
        desc = fn.get("description", "")
        if isinstance(desc, str) and len(desc) > 120:
            desc = desc[:120] + "…"
        p = fn.get("parameters") or {}
        psum = {}
        if isinstance(p, dict):
            if p.get("required"):
                psum["required"] = p["required"]
            props = p.get("properties")
            if isinstance(props, dict):
                psum["props"] = {k: (v.get("type", "") if isinstance(v, dict) else "") for k, v in props.items()}
        out.append({"name": name, "desc": desc, "params": psum})
    compressed = json.dumps(out, ensure_ascii=False)
    if len(compressed) >= len(text):
        return {"compressed": None, "meta": {"compressed": False, "method": "no_gain"}}
    return {"compressed": compressed, "meta": {"compressed": True, "method": "tools_schema_struct"}}


def fold_repeated_lines(text: str) -> dict:
    """摺疊「機器產生的重複行」（CSV/日誌/資料列），純輸入端固定規則（Lite 可用）。

    保守閘門（避免誤傷自然語言）：
      - 至少 12 行；精確重複行累計 ≥6 次才動作；
      - 只在看起來像機器文本（含 ,/=/|/定位冒號/時間戳或數字密度高）時啟用；
      - 同一行第 2 次起收斂成「原行 [×N]」；實際省幅需 ≥25%，否則退回原文。
    """
    lines = text.splitlines()
    if len(lines) < 12:
        return {"compressed": None, "meta": {"compressed": False, "method": "not_repetitive"}}
    counts = {}
    for ln in lines:
        counts[ln] = counts.get(ln, 0) + 1
    dup_total = sum(c for c in counts.values() if c >= 2)
    if dup_total < 6:
        return {"compressed": None, "meta": {"compressed": False, "method": "few_dup"}}
    joined = "\n".join(lines)
    dup_ratio = dup_total / len(lines)
    has_delim = bool(re.search(r"[,|\t=]", joined))
    strong_machine = bool(re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}|[,:=]\s*-?\d", joined))
    alpha_ratio = sum(ch.isalpha() and ord(ch) < 128 for ch in joined) / max(1, len(joined))
    # 高重複率 + 結構分隔符號即視為機器文本（補上純字母重複表頭的案例）；其餘仍保守
    machineish = (strong_machine and alpha_ratio < 0.70) or (
        has_delim and (alpha_ratio < 0.55 or dup_ratio >= 0.5))
    if not machineish:
        return {"compressed": None, "meta": {"compressed": False, "method": "prose_skip"}}
    seen = {}
    out = []
    for ln in lines:
        if counts.get(ln, 0) >= 2:
            seen[ln] = seen.get(ln, 0) + 1
            if seen[ln] == 1:
                out.append(ln + f"  [×{counts[ln]}]")
            # 第 2 次起丟棄（已在首次標註總次數）
        else:
            out.append(ln)
    compressed = "\n".join(out)
    if len(compressed) >= 0.75 * len(text):
        return {"compressed": None, "meta": {"compressed": False, "method": "no_gain"}}
    return {"compressed": compressed, "meta": {"compressed": True, "method": "repeated_line_fold"}}


_CACHE = {}
_CACHE_ORDER = []
_CACHE_MAX = 128


def _cache_get(key):
    return _CACHE.get(key)


def _cache_put(key, val):
    if key in _CACHE:
        _CACHE_ORDER.remove(key)
    _CACHE[key] = val
    _CACHE_ORDER.append(key)
    if len(_CACHE_ORDER) > _CACHE_MAX:
        old = _CACHE_ORDER.pop(0)
        _CACHE.pop(old, None)


def compress_content(text: str) -> dict:
    """依內容類型壓縮 user content（只動輸入），回傳 {compressed, meta}。"""
    meta = {"compressed": False, "method": "none"}
    if not text or len(text) < 300:
        return {"compressed": text, "meta": meta}  # 短不壓（防淨成本）
    h = hash(text)
    cached = _cache_get(h)
    if cached is not None:
        return {"compressed": cached[0], "meta": dict(cached[1], cached=True)}
    stripped = text.strip()
    # JSON tools schema
    if stripped.startswith("[") or stripped.startswith("{"):
        ts = compress_tools_schema(text)
        if ts["meta"]["compressed"]:
            _cache_put(h, (ts["compressed"], ts["meta"]))
            return ts
    # code-aware 路由（先於工具列表，避免 Go func 誤判）
    if not (stripped.startswith("[") or stripped.startswith("{")):
        try:
            from code_compressor import compress_code_in_text as _ccomp
            ctext, cmeta = _ccomp(text)
            if cmeta["compressed"] and len(text) - len(ctext) >= 0.3 * len(text):
                meta = {"compressed": True, "method": "code " + cmeta["method"],
                        "lang": cmeta.get("lang"), "saved_chars": cmeta.get("saved_chars")}
                _cache_put(h, (ctext, meta))
                return {"compressed": ctext, "meta": meta}
        except Exception:
            pass
    # 工具描述列表
    tr = compress_tool_list(text)
    if tr["meta"]["compressed"]:
        _cache_put(h, (tr["compressed"], tr["meta"]))
        return tr
    # 行內 JSON 區塊
    if not (stripped.startswith("[") or stripped.startswith("{")):
        try:
            m = re.search(r"(\[.*\])", text, re.DOTALL)
            if m and len(m.group(1)) > 500:
                from json_compressor import compress_json_light
                cj = compress_json_light(json.loads(m.group(1)))
                if len(cj) < len(m.group(1)):
                    compressed = text[:m.start(1)] + cj + text[m.end(1):]
                    if len(compressed) < text:
                        meta = {"compressed": True, "method": "json_csv_inline"}
                        _cache_put(h, (compressed, meta))
                        return {"compressed": compressed, "meta": meta}
        except Exception:
            pass
    # 純 JSON
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            from json_compressor import compress_json_light
            c = compress_json_light(text)
            if len(c) < len(text):
                meta = {"compressed": True, "method": "json_csv"}
                _cache_put(h, (c, meta))
                return {"compressed": c, "meta": meta}
        except Exception:
            pass
    # 重複機器行（CSV/日誌/資料）摺疊
    rr = fold_repeated_lines(text)
    if rr["meta"]["compressed"]:
        _cache_put(h, (rr["compressed"], rr["meta"]))
        return rr
    # 超長文本 → Lite 損耗性截斷（Pro 為 100% 可逆外部化）
    if len(text) > COMPACT_THRESHOLD:
        original_len = len(text)
        text = (text[:COMPACT_THRESHOLD]
                + f"\n…[toknife-lite: truncated, original {original_len} chars; "
                  + "Pro keeps it 100% restorable]")
        meta = {"compressed": True, "method": "lite_truncate", "original_chars": original_len}
        return {"compressed": text, "meta": meta}
    return {"compressed": text, "meta": meta}


def compress_messages(messages: list) -> tuple:
    """先壓每則 user content，再對溢出的多輪歷史 auto_compact。"""
    msgs = [dict(m) for m in messages]
    meta = {"history_compacted": False, "content_compressed": 0, "methods": {}}
    for i, m in enumerate(msgs):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            r = compress_content(m["content"])
            if r["meta"]["compressed"]:
                msgs[i] = dict(m, content=r["compressed"])
                meta["content_compressed"] += 1
                mm = r["meta"].get("method", "?")
                meta["methods"][mm] = meta["methods"].get(mm, 0) + 1
    hist_tok = _est_tok(json.dumps(msgs, ensure_ascii=False))
    if hist_tok > HIST_LIMIT:
        try:
            from compress_history import auto_compact
            res = auto_compact(msgs, context_limit=HIST_LIMIT, threshold=0.75, keep_recent=3)
            if res.get("triggered"):
                msgs = res["compressed_messages"]
                meta["history_compacted"] = True
        except Exception:
            pass
    return msgs, meta


# ---------------------------------------------------------------- 累計節省（輸入端）
STATS_LOCK = threading.Lock()
STATS = {
    "requests": 0, "streamed": 0,
    "orig_input_tokens": 0, "compressed_input_tokens": 0,
    "by_method": {},
}


def _record(meta, orig_in, comp_in, streamed):
    with STATS_LOCK:
        STATS["requests"] += 1
        STATS["streamed"] += 1 if streamed else 0
        STATS["orig_input_tokens"] += orig_in
        STATS["compressed_input_tokens"] += comp_in
        for k, v in (meta.get("methods") or {}).items():
            STATS["by_method"][k] = STATS["by_method"].get(k, 0) + v


def _stats_payload():
    with STATS_LOCK:
        o, c = STATS["orig_input_tokens"], STATS["compressed_input_tokens"]
        saved = o - c
        return {
            "edition": EDITION, "version": __version__, "scope": "input-only",
            "requests": STATS["requests"], "streamed": STATS["streamed"],
            "orig_input_tokens": o, "compressed_input_tokens": c,
            "saved_input_tokens": saved,
            "saved_input_pct": round(100.0 * saved / o, 2) if o else 0.0,
            "by_method": dict(STATS["by_method"]),
            "note": "Input-side only. Output optimization, reversible long-context, "
                    "hard budget caps and a visual dashboard are in Toknife Pro.",
            "pro": "https://momogigi123.github.io/toknife/",
        }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # -- helpers ---------------------------------------------------------
    def _send_json(self, code, obj, extra=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _auth_headers(self, content_type=True):
        h = {}
        if content_type:
            h["Content-Type"] = "application/json"
        if API_KEY:
            h["Authorization"] = f"Bearer {API_KEY}"
        elif self.headers.get("Authorization"):
            h["Authorization"] = self.headers.get("Authorization")
        return h

    # -- GET -------------------------------------------------------------
    def do_GET(self):
        path = self.path.rstrip("/").split("?")[0]
        if path in ("/health",):
            self._send_json(200, {
                "status": "ok", "edition": EDITION, "version": __version__,
                "upstream_host": re.sub(r"^https?://", "", UPSTREAM).split("/")[0],
                "model_mode": "fixed:" + FIXED_MODEL if FIXED_MODEL else "client-passthrough",
                "scope": "input-only",
            })
            return
        if path in ("/stats",):
            self._send_json(200, _stats_payload())
            return
        if path in ("/v1/models", "/models"):
            self._proxy_models()
            return
        self._send_json(404, {"error": "not_found",
                              "endpoints": ["/v1/chat/completions", "/v1/models",
                                            "/health", "/stats"]})

    def _proxy_models(self):
        headers = self._auth_headers(content_type=False)
        if "Authorization" not in headers:
            self._send_json(503, {"error": "no_upstream_key",
                                  "hint": "set OPENAI_API_KEY or send an Authorization header"})
            return
        req = urllib.request.Request(MODELS_URL, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=min(UPSTREAM_TIMEOUT, 30)) as r:
                raw = r.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except Exception as e:
            self._send_json(502, {"error": "upstream_models_failed", "detail": str(e)})

    # -- POST ------------------------------------------------------------
    def do_POST(self):
        path = self.path.rstrip("/").split("?")[0]
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_json(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "bad_json_body"})
            return

        messages = body.get("messages", [])
        if not isinstance(messages, list) or not messages:
            self._send_json(400, {"error": "messages_required"})
            return
        want_stream = bool(body.get("stream", False))
        model = FIXED_MODEL or body.get("model")
        if not model:
            self._send_json(400, {"error": "model_required",
                                  "hint": "send 'model' in the body or start the proxy with --model"})
            return

        msgs, meta = compress_messages(messages)
        payload = dict(body)                 # 保留 tools/溫度/stream 等所有客戶端欄位
        payload["messages"] = msgs
        payload["model"] = model
        orig_in = _est_tok(json.dumps(messages, ensure_ascii=False))
        comp_in = _est_tok(json.dumps(msgs, ensure_ascii=False))

        headers = self._auth_headers()
        if "Authorization" not in headers:
            self._send_json(503, {"error": "no_upstream_key",
                                  "hint": "set OPENAI_API_KEY or send an Authorization header"})
            return
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(CHAT_URL, data=data, headers=headers, method="POST")

        try:
            upstream = urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:
                detail = str(e)
            self._send_json(502, {"error": "upstream_http_error", "status": e.code, "detail": detail})
            return
        except Exception as e:
            self._send_json(502, {"error": "upstream_unreachable", "detail": str(e)})
            return

        # ---- 串流：原樣 SSE 穿透（Lite 不修改輸出） ----
        if want_stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    chunk = upstream.read(2048)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                pass
            finally:
                upstream.close()
            _record(meta, orig_in, comp_in, True)
            sys.stderr.write(f"[toknife-lite] stream input {orig_in}->{comp_in} tok "
                             f"({_pct(orig_in, comp_in)}) methods={meta.get('methods')}\n")
            return

        # ---- 非串流：回 JSON，附加輸入端計數（不動 choices 輸出） ----
        try:
            resp = json.loads(upstream.read().decode("utf-8"))
        except Exception as e:
            self._send_json(502, {"error": "bad_upstream_json", "detail": str(e)})
            return
        finally:
            upstream.close()
        resp.setdefault("ts_proxy", {})
        resp["ts_proxy"].update({
            "edition": EDITION, "scope": "input-only",
            "orig_input_tokens": orig_in, "compressed_input_tokens": comp_in,
            "saved_input_pct": round(100.0 * (orig_in - comp_in) / orig_in, 2) if orig_in else 0.0,
            "methods": meta.get("methods"),
        })
        _record(meta, orig_in, comp_in, False)
        self._send_json(200, resp)
        sys.stderr.write(f"[toknife-lite] input {orig_in}->{comp_in} tok "
                         f"({_pct(orig_in, comp_in)}) methods={meta.get('methods')}\n")


def _pct(o, c):
    return f"-{100.0 * (o - c) / o:.1f}%" if o else "0%"


def main():
    # 只有作為主程式執行時才真正解析命令列，並重綁定全域設定
    cfg = load_config(sys.argv[1:])
    g = globals()
    g["CONFIG"] = cfg
    g["UPSTREAM"] = cfg["upstream"]
    g["API_KEY"] = cfg["api_key"]
    g["FIXED_MODEL"] = cfg["model"]
    g["MODEL"] = cfg["model"]
    g["HOST"] = cfg["host"]
    g["CHAT_URL"] = _join_url(cfg["upstream"], "chat/completions")
    g["MODELS_URL"] = _join_url(cfg["upstream"], "models")
    srv = ThreadingHTTPServer((HOST, cfg["port"]), Handler)
    srv.allow_reuse_address = True
    print(f"Toknife Lite {__version__} — input-side OpenAI-compatible proxy")
    print(f"  listen : http://{HOST}:{cfg['port']}/v1  (health=/health stats=/stats)")
    print(f"  upstream: {cfg['upstream']}  model: {cfg['model'] or 'client passthrough'}")
    print(f"  api key : {'configured' if cfg['api_key'] else 'not set (will forward client Authorization)'}")
    print("  scope  : input-only. " + PRO_NOTE)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
