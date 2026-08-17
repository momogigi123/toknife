# -*- coding: utf-8 -*-
"""Token Saver 核心功能 pytest 測試（v5.4）。

覆蓋：JSON 壓縮、BOM 處理、異常檢測、代碼壓縮（Py/JS/Go）、
MCP 代理、品質指標、批量壓縮。
"""
import json
import os
import tempfile

import pytest

# conftest 已把 scripts 加入 path
from json_compressor import compress_json_light, compress_json_enhanced, should_compress_json
from mcp_proxy import CompressionEngine, est_tokens
from adaptive_aggregator import AdaptiveAggregator
from code_context_extractor import (
    compress_code_light, compress_code_medium,
    compress_code_js_light, compress_code_js_medium,
    compress_code_go_light, compress_code_go_medium,
)
from quality_metrics import compute_quality


# ===== JSON 壓縮 =====

class TestJsonCompression:
    def test_light_basic(self):
        data = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        out = compress_json_light(data)
        assert "a,b" in out
        assert "1,x" in out

    def test_enhanced_constants(self):
        data = [{"id": i, "cat": "same", "v": i} for i in range(10)]
        out = compress_json_enhanced(data)
        assert "# const:" in out
        assert '"cat": "same"' in out

    def test_enhanced_drop_empty(self):
        data = [{"id": i, "empty": None, "v": i} for i in range(10)]
        out = compress_json_enhanced(data)
        assert "empty" not in out.split("# cols:")[1].split("\n")[0]

    def test_enhanced_flatten(self):
        data = [{"id": i, "user": {"name": f"u{i}"}} for i in range(5)]
        out = compress_json_enhanced(data)
        assert "user.name" in out

    def test_should_compress(self):
        assert should_compress_json([{"a": 1}] * 3) is True
        assert should_compress_json([{"a": 1}] * 2) is False
        assert should_compress_json([1, 2, 3]) is False

    def test_enhanced_saves_more_than_light(self):
        data = [{"id": i, "cat": "const", "empty": None, "meta": {"x": i}} for i in range(50)]
        light = len(compress_json_light(data))
        enhanced = len(compress_json_enhanced(data))
        assert enhanced < light


# ===== BOM 處理 =====

class TestBOM:
    def test_bom_json_detected(self):
        bom = "\ufeff" + json.dumps([{"id": i} for i in range(20)])
        eng = CompressionEngine(min_tokens=100)
        _, meta = eng.process("tool", bom)
        assert meta.get("kind") == "json→csv"

    def test_no_bom_json(self):
        normal = json.dumps([{"id": i} for i in range(20)])
        eng = CompressionEngine(min_tokens=100)
        _, meta = eng.process("tool", normal)
        assert meta.get("kind") == "json→csv"


# ===== 異常檢測 =====

class TestAnomalyDetection:
    def test_small_sample_anomaly(self):
        data = [{"p": f"P{i}", "s": v} for i, v in enumerate(
            [100, 200, 150, 99999, 180, 120, 250, 88888])]
        agg = AdaptiveAggregator()
        agg.calibrate(data)
        r = agg.aggregate(data, sort_by="s", top_n=5, calibrated=True, exclude_anomalies=True)
        assert len(r.get("anomalies", [])) >= 1
        top_ids = [x["p"] for x in r.get("top_n", [])]
        assert "P3" not in top_ids  # 異常值不應在 Top-N

    def test_normal_sample(self):
        data = [{"p": f"P{i}", "s": 100 + i} for i in range(50)]
        agg = AdaptiveAggregator()
        agg.calibrate(data)
        r = agg.aggregate(data, sort_by="s", top_n=5, calibrated=True)
        assert len(r.get("top_n", [])) == 5


# ===== 代碼壓縮 =====

class TestCodeCompression:
    def _write(self, content, ext):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=f".{ext}", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return f.name

    def test_py_light(self):
        path = self._write("def f():\n    # comment\n    return 1\n", "py")
        out = compress_code_light(path)
        assert "return 1" in out
        assert "# comment" not in out
        os.unlink(path)

    def test_py_medium(self):
        code = "def short():\n    return 1\n\n" + \
               "def long():\n" + "\n".join([f"    x{i} = {i}" for i in range(50)]) + "\n    return x\n"
        path = self._write(code, "py")
        out = compress_code_medium(path, fold_threshold=20)
        assert "def short():" in out
        assert "省略" in out
        os.unlink(path)

    def test_js_light(self):
        path = self._write("// comment\nfunction f() { return 1; }\n", "js")
        out = compress_code_js_light(path)
        assert "return 1" in out
        assert "// comment" not in out
        os.unlink(path)

    def test_js_medium_fold(self):
        code = "function short() { return 1; }\n\n" + \
               "function long() {\n" + "\n".join([f"  let x{i} = {i};" for i in range(50)]) + "\n  return x;\n}\n"
        path = self._write(code, "js")
        out = compress_code_js_medium(path, fold_threshold=20)
        assert "function short()" in out
        assert "省略" in out
        os.unlink(path)

    def test_go_light(self):
        path = self._write("// comment\nfunc f() int { return 1 }\n", "go")
        out = compress_code_go_light(path)
        assert "return 1" in out
        os.unlink(path)

    def test_go_medium(self):
        code = "func Add(a, b int) int { return a + b }\n\n" + \
               "func Long() {\n" + "\n".join([f"\tx{i} := {i}" for i in range(50)]) + "\n}\n"
        path = self._write(code, "go")
        out = compress_code_go_medium(path, fold_threshold=20)
        assert "func Add" in out
        os.unlink(path)

    def test_auto_detect_lang(self):
        path = self._write("function f() { return 1; }\n", "js")
        out = compress_code_light(path, lang="auto")
        assert "return 1" in out
        os.unlink(path)


# ===== MCP 代理 =====

class TestMCPProxy:
    def test_short_passthrough(self):
        eng = CompressionEngine(min_tokens=2000)
        text = "short result"
        out, meta = eng.process("tool", text)
        assert meta.get("compressed") is False
        assert out == text

    def test_json_compressed(self):
        eng = CompressionEngine(min_tokens=100)
        data = json.dumps([{"id": i, "v": i} for i in range(30)])
        out, meta = eng.process("tool", data)
        assert meta.get("compressed") is True
        assert "read_more" in meta or meta.get("handle")

    def test_read_more_roundtrip(self):
        eng = CompressionEngine(min_tokens=100)
        text = json.dumps([{"id": i} for i in range(30)])
        _, meta = eng.process("tool", text)
        handle = meta.get("handle")
        if handle:
            full = eng.read_more(handle)
            assert full == text


# ===== 品質指標 =====

class TestQualityMetrics:
    def test_top_n_hit(self):
        data = [{"id": i, "v": i * 10} for i in range(100)]
        result = compute_quality(data, sort_by="v", top_n=5)
        assert result["top_n_hit_rate"] == 1.0
        assert result["quality_score"] >= 80

    def test_anomaly_detection(self):
        data = [{"id": i, "v": 100 + i} for i in range(50)]
        data.append({"id": 999, "v": 99999})
        result = compute_quality(data, sort_by="v", top_n=5)
        assert result["anomaly_recall"] >= 0.5


# ===== est_tokens =====

class TestEstTokens:
    def test_basic(self):
        assert est_tokens("hello world") > 0
        assert est_tokens("") == 0

    def test_chinese(self):
        # 中文估算用 len//3，至少不崩潰
        assert est_tokens("你好世界") > 0


# ===== 對話壓縮（v5.5） =====

class TestConversationCompression:
    def test_basic(self):
        from conversation_compressor import compress_conversation
        msgs = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        out, meta = compress_conversation(msgs)
        assert "U:" in out
        assert "A:" in out
        assert meta["total_messages"] == 2

    def test_long_message_truncation(self):
        from conversation_compressor import compress_conversation
        long_content = "x" * 500
        msgs = [{"role": "user", "content": long_content}]
        out, meta = compress_conversation(msgs, max_chars=100)
        assert "截斷" in out
        assert meta["folded_count"] == 1

    def test_dedup(self):
        from conversation_compressor import compress_conversation
        msgs = [{"role": "user", "content": "same"}, {"role": "user", "content": "same"}]
        out, meta = compress_conversation(msgs, dedup=True)
        assert meta["dedup_count"] == 1
        assert "相同" in out

    def test_detect_conversation(self):
        from conversation_compressor import _detect_conversation
        assert _detect_conversation([{"role": "user", "content": "hi"}]) is True
        assert _detect_conversation([{"a": 1}]) is False
        assert _detect_conversation([]) is False

    def test_read_more(self):
        from conversation_compressor import compress_conversation, read_more_conversation
        msgs = [{"role": "user", "content": "hello world"}]
        _, meta = compress_conversation(msgs)
        back = read_more_conversation(meta, 0)
        assert "hello world" in back


# ===== 關鍵行提取（v5.5） =====

class TestKeylineExtractor:
    def test_short_passthrough(self):
        from keyline_extractor import extract_key_lines
        text = "line1\nline2\nline3"
        out, meta = extract_key_lines(text)
        assert meta["compressed"] is False
        assert out == text

    def test_error_lines_kept(self):
        from keyline_extractor import extract_key_lines
        lines = ["debug line"] * 100 + ["ERROR: something failed"] + ["debug"] * 100
        text = "\n".join(lines)
        out, meta = extract_key_lines(text, head=2, tail=2, max_key=10)
        assert "ERROR" in out
        assert meta["compressed"] is True

    def test_data_lines_kept(self):
        from keyline_extractor import extract_key_lines
        lines = ["filler text"] * 100 + ["total=1000, avg=50.5"] + ["filler"] * 100
        text = "\n".join(lines)
        out, meta = extract_key_lines(text, head=2, tail=2, max_key=10)
        assert "total=1000" in out

    def test_head_tail_kept(self):
        from keyline_extractor import extract_key_lines
        lines = [f"line {i}" for i in range(200)]
        text = "\n".join(lines)
        out, meta = extract_key_lines(text, head=5, tail=5)
        assert "line 0" in out
        assert "line 199" in out

    def test_omission_marker(self):
        from keyline_extractor import extract_key_lines
        lines = [f"line {i}" for i in range(200)]
        text = "\n".join(lines)
        out, _ = extract_key_lines(text, head=3, tail=3, max_key=5)
        assert "省略" in out
