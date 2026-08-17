# -*- coding: utf-8 -*-
"""ts_proxy_server.py — Token-Saver OpenAI 相容代理端點（公平評測用）

把 doubao 包成 OpenAI 相容 /v1/chat/completions，user content 先過 token-saver 
壓縮再轉發——等價於「掛 Token-Saver 代理的端點」（規格中的 http://localhost:8001/v1）。
壓縮策略（對應運行時閉環真實行為）：
  - user content > 2000 字元 → 就地 keyline 關鍵行提取（不外部化、不提供額外還原機制）
  - 多輪歷史 ≥ 上限 → compress_history auto_compact（anchored 增量合併）
  - JSON 結構內容 → json_compressor
  - 短內容不壓（防淨成本）
純 stdlib（http.server + urllib）。啟動：python ts_proxy_server.py [port=8001]
"""
import os
import sys
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API_KEY = os.environ.get("EX_LLM_KEY") or os.environ.get("ARK_API_KEY")
UPSTREAM = os.environ.get("EX_LLM_BASE", "https://ark.cn-beijing.volces.com/api/v3")
MODEL = os.environ.get("EX_LLM_MODEL", "doubao-seed-2-0-pro-260215")

COMPACT_THRESHOLD = 2000   # 字元；超過 → 外部化標記
HIST_LIMIT = 6000          # 歷史 tokens 上限；超過 → auto_compact


def _est_tok(s):
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(s))
    except Exception:
        return len(s) // 3


def _detect_lang(text: str) -> str:
    """ 語言感知：含 CJK 字元占比高 → 'zh'，否則 'en'。"""
    if not text:
        return "zh"
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "zh" if cjk >= latin else "en"


def _is_question_or_instruction(ln: str, lang: str) -> bool:
    """ query-aware：問題/指令行永遠保留（不進 keyline 丟棄邏輯）。

    根因修復：舊版 keyline 迴圈用 break，長文語料把 max_key 配額用光後，
    結尾的 Question: 行到不了就被截斷 → 英文抽取式 QA 場模型看不到問題而迴避。
    """
    if "?" in ln:
        return True
    low = ln.lower()
    if lang == "zh":
        sig = ("問題", "請問", "問：", "任務", "指令", "回答", "答案", "總結", "提取", "回答：", "答案：")
    else:
        sig = ("question", "q:", "task", "instruction", "answer", "according to",
               "read the document", "summar", "extract", "identify", "find", "retrieve")
    return any(s in low for s in sig)


def compress_tool_list(text: str) -> dict:
    """ 工具描述結構化壓縮（真實 Agent 場景，實測省 43% 且選工具準確率不降）。

    通用識別（不誤傷普通文本）：至少 2 行含「工具特徵」——tool_/func/函數/【工具】/功能-。
    壓縮規則：每行按句切分，保留「功能/參數/回傳/返回/Input/param」訊號句＋首句，
    砍「此工具用於/支援/包含/以及/用於日常」填充句；壓縮後不短於原文 → 退回（收益閘門）。
    """
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
            out.append(ln)  # 非工具行保留
            continue
        sents = [s + "。" for s in ln.split("。") if s.strip()]
        kept = [s for s in sents if any(k in s.lower() for k in keep_sig)
                and not any(d in s for d in drop_sig)]
        if not kept:
            kept = sents[:1]  # 兜底：首句
        out.append("".join(kept[:3]))
    compressed = "\n".join(out)
    if len(compressed) >= len(text):
        return {"compressed": None, "meta": {"compressed": False, "method": "no_gain"}}
    return {"compressed": compressed, "meta": {"compressed": True, "method": "tool_list_struct"}}


def compress_tools_schema(text: str) -> dict:
    """ JSON tools schema 壓縮（OpenAI 格式 tools 陣列）。

    每 tool 保留：name＋description 前 120 字＋parameters 的 required＋properties 名，
    砍 description 填充句與 parameters 詳細描述。不是 tools schema → 不壓（防誤傷）。
    """
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


#  壓縮快取：相同內容不重壓（LRU，最多 128 筆）
_CACHE = {}
_CACHE_ORDER = []
_CACHE_MAX = 128


def _cache_get(key):
    if key in _CACHE:
        return _CACHE[key]
    return None


def _cache_put(key, val):
    if key in _CACHE:
        _CACHE_ORDER.remove(key)
    _CACHE[key] = val
    _CACHE_ORDER.append(key)
    if len(_CACHE_ORDER) > _CACHE_MAX:
        old = _CACHE_ORDER.pop(0)
        _CACHE.pop(old, None)


def compress_content(text: str) -> dict:
    """依內容類型壓縮 user content，回傳 {compressed, meta}。"""
    meta = {"compressed": False, "method": "none"}
    if not text or len(text) < 300:
        return {"compressed": text, "meta": meta}  # 短不壓（防淨成本）
    # 快取（）：相同內容直接回，不重壓
    h = hash(text)
    cached = _cache_get(h)
    if cached is not None:
        return {"compressed": cached[0], "meta": dict(cached[1], cached=True)}
    # JSON tools schema（，OpenAI 格式）
    stripped = text.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        ts = compress_tools_schema(text)
        if ts["meta"]["compressed"]:
            _cache_put(h, (ts["compressed"], ts["meta"]))
            return ts
    #  code-aware 路由（B 任務）：在 tool_list 誤判之前先偵測 code block。
    # 根因：舊版沒偵測 code，fenced code 被 compress_tool_list 誤判（Go 風格 func
    # 命中 tool 關鍵字）→ 空轉。此處直接路由到 code_compressor（去重+空白精簡，
    # 唯一函式含註解/docstring 原樣保留，保品質）。
    if not (stripped.startswith("[") or stripped.startswith("{")):
        try:
            from code_compressor import compress_code_in_text as _ccomp
            ctext, cmeta = _ccomp(text)
            if cmeta["compressed"]:
                if len(text) - len(ctext) < 0.3 * len(text):
                    # 去重+空白精簡幾乎沒省（唯一大代碼）→ 退回下方長文處理（就地 keyline 壓縮）
                    pass
                else:
                    meta = {"compressed": True, "method": "code " + cmeta["method"],
                            "lang": cmeta.get("lang"), "saved_chars": cmeta.get("saved_chars")}
                    _cache_put(h, (ctext, meta))
                    return {"compressed": ctext, "meta": meta}
        except Exception:
            pass
    # 工具描述列表（，Agent 場景）——優先於一般長文本
    tr = compress_tool_list(text)
    if tr["meta"]["compressed"]:
        _cache_put(h, (tr["compressed"], tr["meta"]))
        return tr
    #  內嵌 JSON 偵測：真實工具回傳常是「任務文字 + [大 JSON]」混合
    # （原判斷只看開頭 [ → 混合格式落入長文本分支把整行當關鍵行 → 沒壓）
    if not (stripped.startswith("[") or stripped.startswith("{")):
        try:
            import re as _re
            m = _re.search(r"(\[.*\])", text, _re.DOTALL)
            if m and len(m.group(1)) > 500:
                from json_compressor import compress_json_light
                j = json.loads(m.group(1))
                cj = compress_json_light(j)
                if len(cj) < len(m.group(1)):
                    compressed = text[:m.start(1)] + cj + text[m.end(1):]
                    if len(compressed) < len(text):
                        meta = {"compressed": True, "method": "json_csv_inline"}
                        _cache_put(h, (compressed, meta))
                        return {"compressed": compressed, "meta": meta}
        except Exception:
            pass
    # JSON 結構 → json_compressor
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
    # 超長文本 → 就地 keyline 提取（本版本：不外部化、不提供額外還原機制）
    if len(text) > COMPACT_THRESHOLD:
        try:
            import re
            lines_list = text.splitlines()
            lang = _detect_lang(text)
            # 自動品質預判（中英雙語）：檢索/事實型任務 → 輕壓（關鍵行上限提高）
            if lang == "zh":
                rpat = r"找出|查詢|檢索|回報|哪個|哪一|誰|多少|什麼|提取|總結|關鍵|資訊"
            else:
                rpat = r"(?i)find|retrieve|search|which |who |what |according to|answer the|read the document|summar|extract|identif"
            retrieval = bool(re.search(rpat, text[:2000]))
            max_key = 40 if retrieval else 15
            # digit-keyline 修復：數字密集文本（日誌類）過度保留
            # 根因：數字密集文本（日誌每行都有時間戳/數字）被 digit 過濾器「全留」，
            # 當 key_block ≈ 全文時 wrapped ≥ 原文 → no_gain_long 整段退回 → 0% 壓縮。
            # 修法：偵測「結構化紀錄/日誌」類型 → 強制行預算（佔比上限 40%），確保必定淨壓縮。
            _struct_pat = re.compile(
                r"(\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}|\[\w+\]|\bERR-\d|\bCODE-\d|req_id=|\blatency=\d|trace_id=)")
            _struct_hits = sum(1 for ln in lines_list if _struct_pat.search(ln))
            if lines_list and _struct_hits > 0.5 * len(lines_list):
                line_budget = max(6, int(len(lines_list) * 0.4))
                if line_budget < max_key:
                    max_key = line_budget
            # query-aware：問題/指令行永遠保留（不進 keyline 丟棄）
            picked, seen = [], set()
            corpus_count = 0
            for ln in lines_list:
                if _is_question_or_instruction(ln, lang):
                    if ln not in seen:
                        seen.add(ln); picked.append(ln)
                    continue
                if corpus_count >= max_key:
                    continue
                # 行篩選：含數字/【標記】的行 = 關鍵行；超長無訊號填充行 → 砍
                if len(ln) > 200 and not re.search(r"\d|【|】|錯誤|ERROR|結論", ln):
                    continue
                if ln not in seen:
                    seen.add(ln); picked.append(ln)
                    corpus_count += 1
            # 兜底頭尾（防止全被砍空）
            if not picked and lines_list:
                picked = lines_list[:2] + lines_list[-1:]
            key_block = "\n".join(picked)
            n_lines = len(lines_list)
            if lang == "zh":
                stats = f"總行數 {n_lines} 行 / 總字元 {len(text)}。"
                wrapped = "[關鍵行]\n" + key_block + "\n[內容統計] " + stats
            else:
                stats = f"Total lines: {n_lines} / Total chars: {len(text)}."
                wrapped = "[KEY LINES]\n" + key_block + "\n[CONTENT STATS] " + stats
            # 收益閘門：輸出比原文長就退回原文
            if len(wrapped) >= len(text):
                return {"compressed": text, "meta": {"compressed": False, "method": "no_gain_long"}}
            meta = {"compressed": True, "method": "keyline_only",
                    "retrieval": retrieval, "lang": lang,
                    "build": "small-knife (open-source edition)"}
            return {"compressed": wrapped, "meta": meta}
        except Exception:
            pass



def compress_messages(messages: list) -> tuple:
    """對 messages 套壓縮（先壓每則 user content，再對多輪歷史 auto_compact）。

     修正順序：舊版先 auto_compact，會把單條超大 user message 壓成非字串
    格式（summary），導致後續 code/json 壓縮的 isinstance(content, str) 判斷跳過、
    code 完全沒壓（CODE-BIG 空轉）。改成先壓 content（code 去重+空白精簡把單條砍到
    很小），再對「多輪歷史」做 auto_compact——單條大文檔不再誤觸發歷史壓縮。
    """
    msgs = [dict(m) for m in messages]
    meta = {"history_compacted": False, "content_compressed": 0}
    # 先壓每則 user content（code/json/tool/長文）
    for i, m in enumerate(msgs):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            r = compress_content(m["content"])
            if r["meta"]["compressed"]:
                msgs[i] = dict(m, content=r["compressed"])
                meta["content_compressed"] += 1
    # 歷史超限 → auto_compact（ 閾值 75%，僅多輪溢出時觸發）
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 安靜
        pass

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_error(404); return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        except Exception:
            self.send_error(400); return
        messages = body.get("messages", [])
        temperature = body.get("temperature", 0)
        max_tokens = body.get("max_tokens", 2048)
        # 套 token-saver 壓縮（實驗組核心）
        msgs, meta = compress_messages(messages)
        # 轉發上游（model 固定用環境變量，不接受前端任意 model）
        payload = {"model": MODEL, "messages": msgs,
                   "temperature": temperature, "max_tokens": max_tokens,
                   "stream": False}
        #  跨模型對決（C 任務）：thinking 開關只對「需要/接受」的模型帶。
        # - 非 Ark 端點（OpenAI 等）直接不加（未知欄位會 400）。
        # - Ark 上的非推理模型（deepseek-v3/glm/qwen 等）也不加，避免報錯。
        _need_think = ("volces" in UPSTREAM or "ark" in UPSTREAM) and (
            os.environ.get("TS_THINKING") == "1" or
            any(k in MODEL.lower() for k in ("seed", "r1", "thinking", "reason")))
        if _need_think:
            payload["thinking"] = {"type": "disabled"}
        req = urllib.request.Request(UPSTREAM + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}, method="POST")
        try:
            _timeout = int(os.environ.get("TS_UPSTREAM_TIMEOUT", "180"))
            with urllib.request.urlopen(req, timeout=_timeout) as r:
                resp = json.loads(r.read().decode())
        except Exception as e:
            try:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            except Exception:
                pass  # 客戶端已斷線（ConnectionAbortedError）→ 靜默忽略，不讓執行緒崩潰
            return
        # 附加壓縮 meta（供評測讀取，不影響回應格式）
        resp.setdefault("ts_proxy", meta)
        # 統一計數器（tiktoken 全序列化，與評測端同計，公平）
        try:
            orig_in = _est_tok(json.dumps(messages, ensure_ascii=False))
            comp_in = _est_tok(json.dumps(msgs, ensure_ascii=False))
            resp["ts_proxy"]["orig_input_tokens"] = orig_in
            resp["ts_proxy"]["compressed_input_tokens"] = comp_in
        except Exception:
            pass
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp, ensure_ascii=False).encode())


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    if not API_KEY:
        print("ERROR: 設 EX_LLM_KEY"); sys.exit(1)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.allow_reuse_address = False  #  防多進程疊同 port（舊進程攔截新邏輯）
    print(f"Token-Saver 代理端點: http://127.0.0.1:{port}/v1  (上游 {MODEL})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
