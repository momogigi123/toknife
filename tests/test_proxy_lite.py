# -*- coding: utf-8 -*-
"""6.1-lite 代理離線測試：本機 stub 上游，不聯外網。

覆蓋：
- URL 接合、重複行摺疊（含散文不誤傷）、短文直通/長文截斷；
- /health、/stats；非串流 model 透傳＋輸入壓縮＋輸出不被改動；
- stream=True 的 SSE 原樣穿透；無本機金鑰時轉發客戶端 Authorization。
"""
import json
import threading
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ts_proxy_server import (
    fold_repeated_lines, compress_content, _join_url, __version__,
)
import ts_proxy_server as P


# ------------------------------------------------------------- 純函式
class TestHelpers:
    def test_join_url_versions(self):
        assert _join_url("https://api.openai.com/v1", "chat/completions").endswith("/v1/chat/completions")
        assert _join_url("https://x/api/v3", "models").endswith("/v3/models")
        assert _join_url("https://host", "models").endswith("/v1/models")

    def test_fold_csv(self):
        text = "\n".join(["2026-07,case,120"] * 40)
        r = fold_repeated_lines(text)
        assert r["meta"]["compressed"] is True
        assert "[×40]" in r["compressed"]
        assert len(r["compressed"]) < len(text)

    def test_fold_alpha_header(self):
        # 純字母但高重複的 CSV 表頭也要能摺
        text = "\n".join(["id,product,qty,delta"] * 50)
        r = fold_repeated_lines(text)
        assert r["meta"]["compressed"] is True

    def test_prose_not_folded(self):
        # 自然語言多行（無結構化高重複）不得被摺疊
        lines = ["這是一段自然的說明文字，講述產品如何運作與設計考量。" for _ in range(3)]
        lines += [f"第 {i} 段描述不同的內容，語句各自獨立、沒有重複。" for i in range(12)]
        r = fold_repeated_lines("\n".join(lines))
        assert r["meta"]["compressed"] is False

    def test_short_passthrough(self):
        r = compress_content("short")
        assert r["compressed"] == "short"
        assert r["meta"]["compressed"] is False

    def test_long_prose_is_truncated_lite(self):
        # 超長散文：Lite 採損耗截斷，且標記誠實指向 Pro 可逆
        text = "自然語句沒有重複也沒有結構，" * 200
        r = compress_content(text)
        assert r["meta"]["method"] == "lite_truncate"
        assert "truncated" in r["compressed"] and "Pro" in r["compressed"]


# ------------------------------------------------- 本機 stub 上游 + 代理
class StubUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    last_request = None
    last_auth = None

    def log_message(self, *a):
        pass

    def _read(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        StubUpstream.last_auth = self.headers.get("Authorization")
        body = json.dumps({"data": [{"id": "stub-model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        StubUpstream.last_auth = self.headers.get("Authorization")
        raw = self._read()
        StubUpstream.last_request = json.loads(raw.decode("utf-8"))
        if StubUpstream.last_request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i in range(3):
                chunk = {"choices": [{"delta": {"content": f"s{i}"}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            out = {"id": "chatcmpl-stub", "model": StubUpstream.last_request.get("model"),
                   "choices": [{"index": 0, "message": {"role": "assistant", "content": "ANSWER"}}]}
            body = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


@pytest.fixture(scope="module")
def servers():
    stub = ThreadingHTTPServer(("127.0.0.1", 0), StubUpstream)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    sport = stub.server_address[1]

    saved = {k: getattr(P, k) for k in
             ("UPSTREAM", "CHAT_URL", "MODELS_URL", "API_KEY", "FIXED_MODEL", "MODEL", "STATS")}
    P.UPSTREAM = f"http://127.0.0.1:{sport}/v1"
    P.CHAT_URL = f"http://127.0.0.1:{sport}/v1/chat/completions"
    P.MODELS_URL = f"http://127.0.0.1:{sport}/v1/models"
    P.API_KEY = "stub-key"
    P.FIXED_MODEL = ""
    P.MODEL = ""
    P.STATS = {"requests": 0, "streamed": 0, "orig_input_tokens": 0,
               "compressed_input_tokens": 0, "by_method": {}}

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), P.Handler)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    pport = proxy.server_address[1]

    yield pport

    proxy.shutdown(); stub.shutdown()
    for k, v in saved.items():
        setattr(P, k, v)


def _post(pport, payload, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", pport, timeout=10)
    conn.request("POST", "/v1/chat/completions", body=json.dumps(payload),
                 headers={**{"Content-Type": "application/json"}, **(headers or {})})
    resp = conn.getresponse()
    raw = resp.read()
    ct = resp.getheader("Content-Type")
    conn.close()
    return resp.status, ct, raw


class TestProxyIntegration:
    def test_version(self):
        assert __version__ == "6.1-lite"

    def test_health(self, servers):
        conn = http.client.HTTPConnection("127.0.0.1", servers, timeout=5)
        conn.request("GET", "/health")
        r = conn.getresponse(); data = json.loads(r.read()); conn.close()
        assert r.status == 200 and data["edition"] == "lite"
        assert data["scope"] == "input-only" and data["model_mode"] == "client-passthrough"

    def test_nonstream_model_passthrough_and_meta(self, servers):
        payload = {"model": "client-model-x",
                   "messages": [{"role": "user", "content": "hi"}]}
        status, _, raw = _post(servers, payload)
        assert status == 200
        data = json.loads(raw)
        assert data["choices"][0]["message"]["content"] == "ANSWER"   # 輸出未被改動
        assert data["model"] == "client-model-x"                      # model 透傳
        assert StubUpstream.last_request["model"] == "client-model-x"
        meta = data["ts_proxy"]
        assert meta["scope"] == "input-only" and "orig_input_tokens" in meta

    def test_input_compressed_before_upstream(self, servers):
        big = "\n".join(["2026-07,gadget,120"] * 60)
        payload = {"model": "m", "messages": [{"role": "user", "content": big}]}
        status, _, raw = _post(servers, payload)
        assert status == 200
        got = StubUpstream.last_request["messages"][0]["content"]
        assert "[×60]" in got and len(got) < len(big)

    def test_stream_sse_relay_untouched(self, servers):
        payload = {"model": "m", "stream": True,
                   "messages": [{"role": "user", "content": "hello"}]}
        status, ct, raw = _post(servers, payload)
        assert status == 200 and "text/event-stream" in ct
        assert b"s0" in raw and b"s2" in raw and b"[DONE]" in raw      # 原樣穿透
        stats = self._stats(servers)
        assert stats["streamed"] == 1 and stats["scope"] == "input-only"

    def test_missing_model_400(self, servers):
        status, _, _ = _post(servers, {"messages": [{"role": "user", "content": "x"}]})
        assert status == 400

    def test_client_auth_forwarded_when_no_local_key(self, servers):
        saved = P.API_KEY
        try:
            P.API_KEY = ""
            _post(servers, {"model": "m", "messages": [{"role": "user", "content": "x"}]},
                  headers={"Authorization": "Bearer from-client"})
            assert StubUpstream.last_auth == "Bearer from-client"
        finally:
            P.API_KEY = saved

    @staticmethod
    def _stats(pport):
        conn = http.client.HTTPConnection("127.0.0.1", pport, timeout=5)
        conn.request("GET", "/stats")
        r = conn.getresponse(); data = json.loads(r.read()); conn.close()
        return data
