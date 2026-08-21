#!/usr/bin/env python3
"""compress_report.py — v5.3.5 工具回傳壓縮 + 節約量報告（薄包裝）

在既有 CompressionEngine（mcp_proxy）之上加「節約量報告層」：
同一套壓縮邏輯（JSON→CSV 增強版、長文字頭30+尾10+統計、read_more 回溯），
行為與 MCP 透明代理完全一致，多出來的只有第一行的 [壓縮報告] 數字。

v5.3.5 新增：目錄批量壓縮 + JSON 報告輸出。

用法:
  python compress_report.py <file>              # 壓縮單一檔案
  python compress_report.py <dir> --batch       # 批量壓縮目錄下所有檔案
  python compress_report.py <dir> --batch --json # 批量並輸出 JSON 報告
  echo "..." | python compress_report.py -       # 從 stdin
  python compress_report.py --help               # 顯示說明
"""
import argparse
import json
import os
import sys

# v5.3.2 路徑自舉：從外部目錄執行也能 import 本地模組
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_proxy import CompressionEngine, est_tokens

# 支援的檔案類型
SUPPORTED_EXTS = {".json", ".txt", ".md", ".py", ".js", ".ts", ".csv", ".log", ".xml", ".yaml", ".yml"}


def _compress_one(eng, text):
    """壓縮單一內容，返回 (new_text, meta, orig_tok, new_tok, pct)。"""
    orig = est_tokens(text)
    try:
        new_text, meta = eng.process("tool_result", text)
    except Exception as e:
        return text, {"compressed": False, "error": str(e)}, orig, orig, 0.0
    new_tok = est_tokens(new_text)
    pct = (1 - new_tok / orig) * 100 if orig else 0.0
    return new_text, meta, orig, new_tok, pct


def _batch_compress(eng, src_dir, recursive=False, output_dir=None):
    """批量壓縮目錄下所有檔案，返回結果列表。"""
    results = []
    for root, dirs, files in os.walk(src_dir):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED_EXTS:
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, src_dir)
            try:
                with open(fpath, encoding="utf-8-sig", errors="replace") as f:
                    text = f.read()
            except Exception as e:
                results.append({"file": rel_path, "error": str(e)})
                continue

            if not text.strip():
                results.append({"file": rel_path, "skipped": "empty"})
                continue

            new_text, meta, orig, new_tok, pct = _compress_one(eng, text)
            entry = {
                "file": rel_path,
                "orig_tokens": orig,
                "comp_tokens": new_tok,
                "saving_pct": round(pct, 1),
                "compressed": meta.get("compressed", False),
                "kind": meta.get("kind", "passthrough"),
            }
            results.append(entry)

            # 寫出壓縮後檔案
            if output_dir:
                out_path = os.path.join(output_dir, rel_path)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(new_text)
        if not recursive:
            break
    return results


def main():
    ap = argparse.ArgumentParser(
        description="壓縮工具回傳並回報節約量（薄包裝 CompressionEngine）")
    ap.add_argument("src", nargs="?", default="-",
                    help="輸入檔/目錄路徑；'-' 或省略 = 從 stdin 讀取")
    ap.add_argument("--min-tokens", type=int, default=2000,
                    help="低於此 token 的回傳不壓（防淨成本），預設 2000")
    ap.add_argument("--batch", action="store_true",
                    help="批量模式：src 為目錄時遍歷所有檔案")
    ap.add_argument("--recursive", "-r", action="store_true",
                    help="批量模式下遞迴子目錄")
    ap.add_argument("--output-dir", "-o",
                    help="批量模式下壓縮後檔案輸出目錄")
    ap.add_argument("--json", action="store_true",
                    help="批量模式下以 JSON 格式輸出報告")
    a = ap.parse_args()

    eng = CompressionEngine(min_tokens=a.min_tokens)

    # 批量模式
    if a.batch and a.src != "-" and os.path.isdir(a.src):
        results = _batch_compress(eng, a.src, recursive=a.recursive, output_dir=a.output_dir)

        if a.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print("=" * 60)
            print(f"【批量壓縮報告】目錄: {a.src}")
            print("=" * 60)
            total_orig = sum(r.get("orig_tokens", 0) for r in results)
            total_comp = sum(r.get("comp_tokens", 0) for r in results)
            total_pct = (1 - total_comp / total_orig) * 100 if total_orig else 0
            print(f"  檔案數: {len(results)}")
            print(f"  原始 token: {total_orig}")
            print(f"  壓縮 token: {total_comp}")
            print(f"  總降幅: {total_pct:.1f}%")
            print("-" * 60)
            for r in results:
                if "error" in r:
                    print(f"  ❌ {r['file']}: {r['error']}")
                elif "skipped" in r:
                    print(f"  ⏭  {r['file']}: {r['skipped']}")
                else:
                    status = "✅" if r["compressed"] else "⏭"
                    print(f"  {status} {r['file']}: {r['orig_tokens']}→{r['comp_tokens']} tok ({r['saving_pct']}%↓) {r['kind']}")
            print("=" * 60)
        return

    # 單檔模式
    if a.src == "-":
        text = sys.stdin.read()
    else:
        with open(a.src, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()

    if not text.strip():
        print("[壓縮報告: 空回傳，不處理]")
        return

    new_text, meta, orig, new_tok, pct = _compress_one(eng, text)

    if not meta.get("compressed"):
        print(f"[壓縮報告: 短回傳 {orig} tok 不壓，避免淨成本]")
        print(new_text)
        return

    handle = meta.get("handle", "")
    rm = f" [read_more:{handle}]" if handle else ""
    print(f"[壓縮報告: 原 {orig} tok → 壓後 {new_tok} tok（降幅 {pct:.1f}%）{rm}]")
    print(new_text)


if __name__ == "__main__":
    main()
