# -*- coding: utf-8 -*-
"""Toknife Lite — 通用 LLM 輸入端 token 壓縮工具集（開源版）。

- 只做輸入端壓縮；輸出端最佳化、可逆外部化、自學習、GUI 儀表板為商業 Pro 功能。
- 核心零第三方依賴（tiktoken 可選，未安裝自動降級為估算）。
"""
import os
import sys

# 凍結依賴本目錄的寬鬆匯入（import mcp_proxy 等在安裝環境也能正常工作）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

__version__ = "6.1-lite"
__all__ = ["mcp_proxy", "json_compressor", "code_compressor",
           "code_context_extractor", "conversation_compressor",
           "keyline_extractor", "incremental_compressor", "compress_history",
           "ts_proxy_server"]
