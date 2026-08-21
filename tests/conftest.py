# -*- coding: utf-8 -*-
"""pytest 配置：把 scripts 目錄加入 sys.path。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
