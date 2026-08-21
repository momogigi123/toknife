# -*- coding: utf-8 -*-
"""Token Saver — 上下文 token 壓縮工具集。

v5.3.4：統一 CLI 入口 + pip install 支持 + BOM 修復 + IQR 異常檢測。
"""
import os
import sys

# 確保腳本間的絕對導入（import mcp_proxy 等）在安裝後也能正常工作
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

__version__ = "6.0.0-lite"
__all__ = ["mcp_proxy", "compress_report", "json_compressor",
           "code_context_extractor", "token_router", "pareto_optimizer",
           "incremental_compressor", "compress_history", "audit_system_prompt",
           "token_budget", "retry_attributor"]
