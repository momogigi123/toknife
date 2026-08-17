#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multimodal_compressor.py —  多模態輕量壓縮（圖片→元數據+佔位符）

零依賴實現：用文件頭字節解析圖片尺寸，不依賴 Pillow。
支援格式：PNG、JPEG、GIF、WebP、BMP。

用法:
  python multimodal_compressor.py image.png           # 輸出元數據佔位符
  python multimodal_compressor.py image.png --ocr     # 可選 OCR（需 pytesseract）
  python multimodal_compressor.py image.png --json    # JSON 格式輸出

集成到 MCP 代理：檢測工具回傳是否為圖片路徑/base64，自動調用。
"""
import argparse
import base64
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ===== 圖片尺寸解析（零依賴，讀文件頭） =====

def get_image_size(filepath):
    """從文件頭解析圖片尺寸，返回 (width, height, format)。"""
    with open(filepath, "rb") as f:
        header = f.read(32)

    # PNG: 89 50 4E 47 0D 0A 1A 0A，IHDR chunk 寬高在 16-24 字節
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", header[16:24])
        return w, h, "PNG"

    # GIF: GIF87a/GIF89a，寬高在 6-10 字節（小端）
    if header[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", header[6:10])
        return w, h, "GIF"

    # BMP: BM，寬高在 18-26 字節（小端）
    if header[:2] == b"BM":
        w, h = struct.unpack("<ii", header[18:26])
        return abs(w), abs(h), "BMP"

    # JPEG: FF D8 FF，遍歷 marker 找 SOF0/SOF2
    if header[:2] == b"\xff\xd8":
        with open(filepath, "rb") as f:
            f.read(2)  # 跳過 SOI
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    break
                if marker[0] != 0xFF:
                    # 不是 marker，讀下一個字節
                    f.seek(-1, 1)
                    continue
                mtype = marker[1]
                if mtype in (0xC0, 0xC1, 0xC2, 0xC3):  # SOF0-SOF3
                    f.read(3)  # length + precision
                    h, w = struct.unpack(">HH", f.read(4))
                    return w, h, "JPEG"
                elif mtype in (0xD8, 0xD9):  # SOI/EOI
                    break
                else:
                    # 跳過這個 segment
                    seg_len = struct.unpack(">H", f.read(2))[0]
                    f.read(seg_len - 2)

    # WebP: RIFF....WEBP
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        with open(filepath, "rb") as f:
            f.read(12)  # RIFF + size + WEBP
            while True:
                chunk_header = f.read(8)
                if len(chunk_header) < 8:
                    break
                chunk_type = chunk_header[:4]
                chunk_size = struct.unpack("<I", chunk_header[4:8])[0]
                if chunk_type == b"VP8 ":
                    # VP8 關鍵幀：3 字節幀標籤 + 3 字節寬高
                    data = f.read(10)
                    if len(data) >= 10 and data[3:6] == b"\x9d\x01\x2a":
                        w = struct.unpack("<H", data[6:8])[0] & 0x3FFF
                        h = struct.unpack("<H", data[8:10])[0] & 0x3FFF
                        return w, h, "WebP"
                    break
                elif chunk_type == b"VP8L":
                    # VP8L：1 字節 + 4 字節寬高
                    data = f.read(5)
                    if len(data) >= 5:
                        b0, b1, b2, b3, b4 = data
                        w = 1 + (((b2 & 0x3F) << 8) | b1)
                        h = 1 + (((b4 & 0xF) << 10) | (b3 << 2) | (b2 >> 6))
                        return w, h, "WebP"
                    break
                elif chunk_type == b"VP8X":
                    # VP8X：擴展格式，寬高在 8-14 字節（24-bit 小端）
                    data = f.read(10)
                    if len(data) >= 10:
                        w = 1 + (data[4] | (data[5] << 8) | (data[6] << 16))
                        h = 1 + (data[7] | (data[8] << 8) | (data[9] << 16))
                        return w, h, "WebP"
                    break
                else:
                    f.read(chunk_size + (chunk_size % 2))  # 對齊

    return None, None, "unknown"


def get_image_info(filepath):
    """獲取圖片完整信息：尺寸、格式、大小、佔位符文本。"""
    if not os.path.isfile(filepath):
        return {"error": f"文件不存在: {filepath}"}

    size_bytes = os.path.getsize(filepath)
    w, h, fmt = get_image_size(filepath)

    info = {
        "filename": os.path.basename(filepath),
        "format": fmt,
        "width": w,
        "height": h,
        "size_bytes": size_bytes,
        "size_kb": round(size_bytes / 1024, 1),
    }

    if w and h:
        info["aspect_ratio"] = round(w / h, 2)
        info["megapixels"] = round(w * h / 1_000_000, 2)

    return info


def compress_image(filepath, ocr=False, json_output=False):
    """壓縮圖片為元數據佔位符。"""
    info = get_image_info(filepath)

    if "error" in info:
        return info["error"]

    # 可選 OCR
    ocr_text = ""
    if ocr:
        try:
            import pytesseract
            from PIL import Image
            ocr_text = pytesseract.image_to_string(Image.open(filepath)).strip()
        except ImportError:
            ocr_text = "[OCR 未啟用：需安裝 pytesseract 和 Pillow]"
        except Exception as e:
            ocr_text = f"[OCR 失敗: {e}]"

    if json_output:
        result = dict(info)
        if ocr_text:
            result["ocr_text"] = ocr_text
        return json.dumps(result, ensure_ascii=False, indent=2)

    # 文本佔位符
    lines = [f"[圖片: {info['filename']}]"]
    lines.append(f"  格式: {info['format']}")
    if info["width"]:
        lines.append(f"  尺寸: {info['width']}x{info['height']} ({info.get('megapixels', '?')} MP)")
    lines.append(f"  大小: {info['size_kb']} KB")
    if ocr_text:
        lines.append(f"  OCR 文字:\n{ocr_text}")
    lines.append("  [原始圖片數據已摺疊，需要可通過 read_more 回溯]")
    return "\n".join(lines)


def is_image_file(filepath):
    """判斷是否為圖片文件（按擴展名）。"""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif")


def is_base64_image(text):
    """判斷是否為 base64 編碼的圖片（data:image/...）。"""
    return text.startswith("data:image/") or text.startswith("iVBOR") or text.startswith("/9j/")


def compress_base64_image(b64_text):
    """壓縮 base64 圖片為元數據佔位符。"""
    # 提取 base64 數據
    if b64_text.startswith("data:image/"):
        fmt = b64_text.split(";")[0].split("/")[-1].upper()
        b64_data = b64_text.split(",", 1)[1]
    else:
        fmt = "unknown"
        b64_data = b64_text

    try:
        raw = base64.b64decode(b64_data)
        size_kb = round(len(raw) / 1024, 1)
        # 寫臨時文件解析尺寸
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=f".{fmt.lower()}", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        w, h, _ = get_image_size(tmp_path)
        os.unlink(tmp_path)
        dims = f"{w}x{h}" if w else "未知尺寸"
        return f"[base64圖片: {fmt}, {dims}, {size_kb} KB] [原始數據已摺疊]"
    except Exception as e:
        return f"[base64圖片: 解析失敗 ({e})]"


def main():
    ap = argparse.ArgumentParser(description="多模態圖片輕量壓縮（）")
    ap.add_argument("path", help="圖片文件路徑")
    ap.add_argument("--ocr", action="store_true", help="啟用 OCR（需 pytesseract+Pillow）")
    ap.add_argument("--json", action="store_true", help="JSON 格式輸出")
    a = ap.parse_args()

    print(compress_image(a.path, ocr=a.ocr, json_output=a.json))


if __name__ == "__main__":
    main()
