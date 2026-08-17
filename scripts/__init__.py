# -*- coding: utf-8 -*-
"""tokknife — 上下文 token 壓縮工具集。

：統一 CLI 入口 + pip install 支持 + BOM 修復 + IQR 異常檢測。
"""
import os
import sys

# 確保腳本間的絕對導入（import mcp_proxy 等）在安裝後也能正常工作
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

__version__ = "5.1.1"
__all__ = ["mcp_proxy", "compress_report", "adaptive_aggregator", "json_compressor",
           "code_context_extractor", "token_router", "pareto_optimizer",
           "incremental_compressor", "compress_history", "audit_system_prompt",
           "token_budget", "retry_attributor"]
