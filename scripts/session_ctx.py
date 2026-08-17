# -*- coding: utf-8 -*-
"""session_ctx.py —  G-5 Note-taking 跨 session 筆記模式

對齊 Anthropic 三策略之一（Compaction / Note-taking / Sub-agents）與 session-ctx
「簡寫上下文檔」：會話結尾產出 `.session-ctx.json`（簡寫 key），下個 session 開頭
讀回並 prepend 到 system prompt，避免重複解釋背景，省下重述背景的 token。

理論來源（本機知識庫，非重寫而是落地）：
  exp_manual_A.md（Agent 記憶協議）
  exp_manual_B.md（任務交接協議＋狀態序列化）
本模組即上述協議的具體實作：把「跨 session 延續」工程化為可序列化的簡寫筆記檔。

簡寫 key（對齊 session-ctx 省 40% 思路）：
  g=goal 目標 / d=done 已完成 / b=blocked 卡住 / n=next 下一步 / f=facts 關鍵事實 / t=ts 時間戳

純 Python 標準庫，零第三方依賴。

用法：
  from session_ctx import save_session_ctx, load_session_ctx, render_for_prompt
  save_session_ctx(messages, path=".session-ctx.json")      # 會話結尾
  ctx = load_session_ctx(".session-ctx.json")               # 下個 session 開頭
  print(render_for_prompt(ctx))                            # 貼進新 session system prompt
"""

# 理論來源（與本機知識庫交叉連結，便於追溯）
REFERENCES = [
    "token-saver-exp/exp_manual_A.md  (Agent 記憶協議)",
    "token-saver-exp/exp_manual_B.md  (任務交接協議 + 狀態序列化)",
    "Anthropic Note-taking 策略 (Compaction / Note-taking / Sub-agents)",
    "session-ctx 簡寫上下文檔 (省 40% 思路)",
]
import os
import re
import json
import time


# 簡寫 key 對照（g/d/b/n/f/t）
SHORT_KEYS = {"goal": "g", "done": "d", "blocked": "b", "next": "n", "facts": "f", "ts": "t"}
_REVERSE = {v: k for k, v in SHORT_KEYS.items()}


def _first_user_goal(messages) -> str:
    for m in messages:
        if m.get("role") == "user":
            return m.get("content", "")[:160].strip()
    return ""


def build_session_ctx(messages, extra: dict = None) -> dict:
    """從對話訊息抽取跨 session 筆記（簡寫 key）。"""
    try:
        from compress_history import extract_schema_state, extract_state
        schema_state = extract_schema_state(messages, schema=("done", "blocked", "next"),
                                            sensitivity="low")
        facts = extract_state(messages, sensitivity="low").get("key_facts", [])
    except Exception:
        schema_state = {"done": [], "blocked": [], "next": []}
        facts = []
    ctx = {
        SHORT_KEYS["goal"]: _first_user_goal(messages),
        SHORT_KEYS["done"]: schema_state.get("done", []),
        SHORT_KEYS["blocked"]: schema_state.get("blocked", []),
        SHORT_KEYS["next"]: schema_state.get("next", []),
        SHORT_KEYS["facts"]: facts,
        SHORT_KEYS["ts"]: int(time.time()),
    }
    if extra:
        ctx.update({SHORT_KEYS.get(k, k): v for k, v in extra.items()})
    return ctx


def save_session_ctx(messages, path: str = ".session-ctx.json", extra: dict = None) -> dict:
    """會話結尾：寫出跨 session 筆記檔。回傳建出的 ctx。"""
    ctx = build_session_ctx(messages, extra=extra)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ctx, f, ensure_ascii=False, indent=2)
    return ctx


def load_session_ctx(path: str = ".session-ctx.json") -> dict:
    """下個 session 開頭：讀回筆記；不存在回 None。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def render_for_prompt(ctx: dict, use_short: bool = True) -> str:
    """把筆記渲染成可 prepend 到新 session system prompt 的精簡上下文塊。"""
    if not ctx:
        return ""
    g = ctx.get(SHORT_KEYS["goal"], "")
    d = ctx.get(SHORT_KEYS["done"], [])
    b = ctx.get(SHORT_KEYS["blocked"], [])
    n = ctx.get(SHORT_KEYS["next"], [])
    f = ctx.get(SHORT_KEYS["facts"], [])
    lines = ["[續接上次會話·背景速覽]"]
    if g:
        lines.append(f"目標: {g}")
    if d:
        lines.append("已完成: " + "; ".join(d[:5]))
    if b:
        lines.append("卡住: " + "; ".join(b[:3]))
    if n:
        lines.append("下一步: " + "; ".join(n[:3]))
    if f:
        lines.append("關鍵事實: " + "; ".join(f[:5]))
    return "\n".join(lines)


def self_test():
    """離線自測（供 verify_code_v54）：roundtrip＋簡寫 key＋render。"""
    import tempfile
    msgs = [
        {"role": "system", "content": "你是嚴格的助手。"},
        {"role": "user", "content": "幫我重構訂單模組，路徑 order.py"},
        {"role": "assistant", "content": "已完成初步分析，發現 amount 校驗缺失。下一步要加單元測試。"},
        {"role": "user", "content": "卡住：測試環境連不上資料庫"},
        {"role": "assistant", "content": "已建立 mock 資料庫繞過，待補真實連線配置。"},
    ]
    d = tempfile.mkdtemp()
    p = os.path.join(d, ".session-ctx.json")
    built = save_session_ctx(msgs, path=p)
    loaded = load_session_ctx(p)
    roundtrip = loaded == built
    # 簡寫 key 驗證
    short_keys_ok = set(built.keys()) <= set(SHORT_KEYS.values())
    # render 含目標與已完成關鍵字
    rendered = render_for_prompt(loaded)
    render_ok = ("order.py" in rendered) and ("已完成" in rendered or "初步分析" in rendered)
    # 不存在檔回 None
    miss = load_session_ctx(os.path.join(d, "nope.json")) is None
    return {
        "roundtrip": roundtrip,
        "short_keys": short_keys_ok,
        "render_contains_ctx": render_ok,
        "missing_returns_none": miss,
    }


if __name__ == "__main__":
    import sys
    import argparse
    p = argparse.ArgumentParser(description="tokknife 跨 session 筆記")
    sub = p.add_subparsers(dest="cmd")
    ps = sub.add_parser("save", help="從對話 JSON 存筆記")
    ps.add_argument("file", help="OpenAI 格式 messages 的 JSON 檔")
    ps.add_argument("--path", default=".session-ctx.json")
    pl = sub.add_parser("load", help="讀筆記並渲染成 prompt 區塊")
    pl.add_argument("--path", default=".session-ctx.json")
    pz = sub.add_parser("self-test", help="離線自測")
    a = p.parse_args()
    if a.cmd == "save":
        with open(a.file, "r", encoding="utf-8") as f:
            msgs = json.load(f)
        ctx = save_session_ctx(msgs, path=a.path)
        print(f"已寫入 {a.path}，key={list(ctx.keys())}")
    elif a.cmd == "load":
        ctx = load_session_ctx(a.path)
        if ctx is None:
            print("[無筆記]")
        else:
            print(render_for_prompt(ctx))
    else:
        r = self_test()
        print(r)
        sys.exit(0 if all(r.values()) else 1)
