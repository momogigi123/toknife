#!/bin/bash
# start_ts_proxy.sh — 手動/備用啟動 toknife 壓縮代理（預設 8121）
# 用法: EX_LLM_KEY=xxx bash scripts/start_ts_proxy.sh [port]
# 說明: 代理端點依賴上游 LLM Key，請以環境變數傳入，勿硬編進腳本。
set -e
PORT="${1:-8121}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

if command -v netstat >/dev/null 2>&1 && netstat -ano 2>/dev/null | grep -q ":${PORT}.*LISTENING"; then
  echo "代理已在跑 (${PORT})"
  exit 0
fi

PY="${PYTHON:-python3}"
: "${EX_LLM_KEY:?請先設定 EX_LLM_KEY 環境變數（上游 LLM 金鑰）}"
EX_LLM_KEY="$EX_LLM_KEY" nohup "$PY" "$HERE/ts_proxy_server.py" "$PORT" > /tmp/ts_proxy_live.log 2>&1 &
sleep 3
if command -v netstat >/dev/null 2>&1 && netstat -ano 2>/dev/null | grep -q ":${PORT}.*LISTENING"; then
  echo "代理已啟動 ${PORT}"
else
  echo "啟動失敗，看 /tmp/ts_proxy_live.log"
fi
