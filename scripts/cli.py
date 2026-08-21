#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ts — Token Saver 統一 CLI 入口（v5.3.4，合併豆包版）。

用法:
  ts compress <file>           自動檢測類型，壓縮檔案內容
  ts report <file>             壓縮並顯示節約量報告
  ts mcp --downstream <cmd>    啟動 MCP 透明代理
  ts agg <file> [--sort-by f]  校準聚合（Top-N + 異常 + 統計）
  ts code <file> [--mode]      代碼壓縮（light/medium）
  ts verify                    運行全部驗證腳本
  ts benchmark                 運行 LLM 端到端基準
  ts --version                 顯示版本

所有子命令支援 --help 查看詳細參數。
"""
import argparse
import json
import os
import sys

# 確保能 import 同目錄模組
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

__version__ = "6.0.0-lite"


def cmd_compress(args):
    """壓縮檔案內容（自動檢測 JSON/文本/代碼）。"""
    from mcp_proxy import CompressionEngine, est_tokens

    if args.src == "-":
        text = sys.stdin.read()
    else:
        with open(args.src, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()

    if not text.strip():
        print("[壓縮] 空內容，不處理")
        return 0

    eng = CompressionEngine(min_tokens=args.min_tokens)
    try:
        new_text, meta = eng.process("tool_result", text)
    except Exception as e:
        print(f"[壓縮] 失敗，直通原文（{type(e).__name__}: {e}）")
        print(text)
        return 1

    orig = est_tokens(text)
    if not meta.get("compressed"):
        print(f"[壓縮] 短回傳 {orig} tok 不壓（門檻 {args.min_tokens}）")
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            print(text)
        return 0

    new_tok = est_tokens(new_text)
    pct = (1 - new_tok / orig) * 100 if orig else 0
    print(f"[壓縮] {orig} → {new_tok} tok（降幅 {pct:.1f}%）方式={meta.get('kind')}")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(new_text)
        print(f"[壓縮] 已寫入 {args.output}")
    else:
        print("---")
        print(new_text)
    return 0


def cmd_report(args):
    """壓縮並回報節約量（compress_report 的 CLI 封裝）。"""
    from mcp_proxy import CompressionEngine, est_tokens

    if args.src == "-":
        text = sys.stdin.read()
    else:
        with open(args.src, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()

    if not text.strip():
        print("[壓縮報告] 空回傳，不處理")
        return 0

    eng = CompressionEngine(min_tokens=args.min_tokens)
    try:
        new_text, meta = eng.process("tool_result", text)
    except Exception as e:
        print(f"[壓縮報告] 壓縮失敗，直通原文（{type(e).__name__}: {e}）")
        print(text)
        return 1

    orig = est_tokens(text)
    if not meta.get("compressed"):
        print(f"[壓縮報告] 短回傳 {orig} tok 不壓，避免淨成本")
        print(text)
        return 0

    new_tok = est_tokens(new_text)
    pct = (1 - new_tok / orig) * 100 if orig else 0
    handle = meta.get("handle", "")
    rm = f" [read_more:{handle}]" if handle else ""
    print(f"[壓縮報告: 原 {orig} tok → 壓後 {new_tok} tok（降幅 {pct:.1f}%）{rm}]")
    print(new_text)
    return 0


def cmd_mcp(args):
    """啟動 MCP 透明代理。"""
    from mcp_proxy import McpProxy

    if not args.downstream and not args.self_test:
        print("[MCP] 需指定 --downstream 或 --self-test", file=sys.stderr)
        return 1

    if args.self_test:
        from mcp_proxy import self_test
        r = self_test()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if all(r.values()) else 1

    proxy = McpProxy(
        args.downstream,
        min_tokens=args.min_tokens,
        no_compress=[p for p in args.no_compress.split(",") if p]
    )
    print(f"[MCP] 啟動代理，下游={args.downstream}，min_tokens={args.min_tokens}", file=sys.stderr)
    proxy.serve()
    return 0


def cmd_code(args):
    """代碼壓縮（light/medium）。"""
    from code_context_extractor import compress_code_light, compress_code_medium

    with open(args.src, encoding="utf-8", errors="replace") as f:
        code = f.read()

    if args.mode == "medium":
        result = compress_code_medium(args.src, fold_threshold=args.fold_threshold)
    else:
        result = compress_code_light(args.src)

    print(result)
    orig_lines = len(code.splitlines())
    comp_lines = len(result.splitlines())
    print(f"\n[代碼壓縮] {orig_lines} → {comp_lines} 行（mode={args.mode}）", file=sys.stderr)
    return 0


def cmd_verify(args):
    """運行全部驗證腳本。"""
    import subprocess
    script_dir = os.path.dirname(os.path.abspath(__file__))
    verify_script = os.path.join(script_dir, "verify_code_v53.py")

    if not os.path.exists(verify_script):
        print("[驗證] 找不到 verify_code_v53.py", file=sys.stderr)
        return 1

    print("[驗證] 運行 verify_code_v53.py ...")
    result = subprocess.run(
        [sys.executable, verify_script],
        capture_output=True, text=True, cwd=script_dir
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def cmd_benchmark(args):
    """運行 LLM 端到端基準。"""
    import subprocess
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bench_script = os.path.join(script_dir, "benchmark_llm.py")

    if not os.path.exists(bench_script):
        print("[基準] 找不到 benchmark_llm.py", file=sys.stderr)
        return 1

    print("[基準] 運行 benchmark_llm.py（需配置 API key）...")
    cmd = [sys.executable, bench_script]
    if args.model:
        cmd.extend(["--model", args.model])
    if args.tasks:
        cmd.extend(["--tasks", str(args.tasks)])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=script_dir)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        prog="ts",
        description="Token Saver — 上下文 token 壓縮工具集（v5.3.4，合併豆包版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--version", action="version", version=f"Token Saver v{__version__}")

    sub = parser.add_subparsers(dest="command", help="子命令")

    # compress
    p_comp = sub.add_parser("compress", help="壓縮檔案內容（自動檢測類型）")
    p_comp.add_argument("src", nargs="?", default="-", help="輸入檔路徑；'-' 或省略=stdin")
    p_comp.add_argument("--output", "-o", help="輸出檔路徑（預設輸出到 stdout）")
    p_comp.add_argument("--min-tokens", type=int, default=2000, help="壓縮門檻（預設 2000）")
    p_comp.set_defaults(func=cmd_compress)

    # report
    p_rep = sub.add_parser("report", help="壓縮並回報節約量")
    p_rep.add_argument("src", nargs="?", default="-", help="輸入檔路徑；'-' 或省略=stdin")
    p_rep.add_argument("--min-tokens", type=int, default=2000, help="壓縮門檻（預設 2000）")
    p_rep.set_defaults(func=cmd_report)

    # mcp
    p_mcp = sub.add_parser("mcp", help="啟動 MCP 透明代理")
    p_mcp.add_argument("--downstream", help="下游 MCP server 啟動命令（如 'python my_server.py'）")
    p_mcp.add_argument("--min-tokens", type=int, default=2000, help="壓縮門檻")
    p_mcp.add_argument("--no-compress", default="", help="逗號分隔的工具名正則，命中則不壓")
    p_mcp.add_argument("--self-test", action="store_true", help="離線自測壓縮引擎")
    p_mcp.set_defaults(func=cmd_mcp)

    # code
    p_code = sub.add_parser("code", help="代碼壓縮（Python）")
    p_code.add_argument("src", help="Python 檔案路徑")
    p_code.add_argument("--mode", choices=["light", "medium"], default="light",
                        help="light=去註釋空行；medium=AST折疊長函數（預設 light）")
    p_code.add_argument("--fold-threshold", type=int, default=40, help="medium 模式折疊門檻（行）")
    p_code.set_defaults(func=cmd_code)

    # verify
    p_ver = sub.add_parser("verify", help="運行全部驗證腳本")
    p_ver.set_defaults(func=cmd_verify)

    # benchmark
    p_bench = sub.add_parser("benchmark", help="運行 LLM 端到端基準")
    p_bench.add_argument("--model", help="模型名（需配置 API key）")
    p_bench.add_argument("--tasks", type=int, help="任務數")
    p_bench.set_defaults(func=cmd_benchmark)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
