# -*- coding: utf-8 -*-
"""discipline_check.py — 波次紀律檢查器（）

把「讀知識庫／跑反思／回流知識庫」從「靠 Agent 自律」變成「可檢查的工程狀態」。
動機（2026-08-14 用戶抓包）：連 Agent 自己都做不到常態執行規矩——靠「記得」必然失敗，
token-saver 的核心理念「工具好但不自動 → 工程化」必須用在自己身上。

檢查三項紀律狀態：
  1. kb_read   本 session 是否「真讀過」知識庫（非只預檢三檔）——真讀後呼叫 mark_kb_read()
  2. reflect   反思是否最近（.ts_learn/reflections.jsonl 最後寫入時間）
  3. kb_flow   知識庫 log.md 是否回流（最後修改時間）

用法：
  python discipline_check.py               # 檢查三項狀態 + 多久沒做
  python discipline_check.py --mark-read   # 標記「已真讀知識庫」+ 顯示檢查結果
回傳 exit 0 = 全過；1 = 有欠（供閘門使用）。

純 stdlib、零依賴。狀態檔放技能目錄 .ts_learn/。
"""
import os
import sys
import json
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TS_LEARN = os.path.join(HERE, "..", ".ts_learn")
KB_READ_FLAG = os.path.join(TS_LEARN, "kb_read.json")
REFLECTIONS = os.path.join(TS_LEARN, "reflections.jsonl")
# 知識庫路徑（Windows）
KB_LOG = r"D:\AI\知識庫ob\workbuddy-ob知識庫\log.md"
# 容許的間隔（小時）：超過視為「欠」
REFLECT_MAX_HOURS = 6      # 反思：一波工作後 6 小時內該記
FLOW_MAX_HOURS = 6         # 回流：同樣 6 小時內該做


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def mark_kb_read(pages: list, path: str = KB_READ_FLAG) -> dict:
    """記錄「真讀過知識庫哪些頁」（每次實質讀取後呼叫，非預檢三檔）。
    頁清單如 ["concepts/反思機制.md", "topics/TokenSaver進階技術.md"]。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rec = {"ts": _now_iso(), "pages": pages}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec


def _hours_since(path):
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        age = (datetime.datetime.now().timestamp() - mtime) / 3600.0
        return round(age, 1)
    except OSError:
        return None


def check() -> dict:
    """檢查三項紀律狀態。回傳每項 {ok, age_hours, detail}。"""
    out = {}

    # 1) kb_read：真讀過知識庫？（kb_read.json 存在即視為本 session 讀過）
    if os.path.exists(KB_READ_FLAG):
        try:
            with open(KB_READ_FLAG, "r", encoding="utf-8") as f:
                rec = json.load(f)
            pages = rec.get("pages", [])
            out["kb_read"] = {"ok": True, "detail": f"已真讀 {len(pages)} 頁: {', '.join(pages[:3])}"}
        except (OSError, ValueError):
            out["kb_read"] = {"ok": False, "detail": "kb_read.json 損壞，請重新標記"}
    else:
        out["kb_read"] = {"ok": False,
                          "detail": "未標記真讀知識庫——實質讀過相關頁後跑: python discipline_check.py --mark-read '頁面清單'"}

    # 2) reflect：反思是否最近
    age = _hours_since(REFLECTIONS)
    if age is None:
        out["reflect"] = {"ok": False, "detail": "從未跑過 reflect()——波次收尾記得 session_wrap() 或 reflect()"}
    else:
        ok = age <= REFLECT_MAX_HOURS
        out["reflect"] = {"ok": ok, "age_hours": age,
                          "detail": f"最後反思 {age}h 前（閾值 {REFLECT_MAX_HOURS}h）" + ("" if ok else " → 欠，補跑 reflect()")}

    # 3) kb_flow：知識庫回流是否最近
    age2 = _hours_since(KB_LOG)
    if age2 is None:
        out["kb_flow"] = {"ok": False, "detail": "找不到知識庫 log.md（路徑配置需檢查）"}
    else:
        ok2 = age2 <= FLOW_MAX_HOURS
        out["kb_flow"] = {"ok": ok2, "age_hours": age2,
                          "detail": f"知識庫 log.md 最後回流 {age2}h 前（閾值 {FLOW_MAX_HOURS}h）" + ("" if ok2 else " → 欠，補回流")}
    return out


def main():
    args = sys.argv[1:]
    if "--mark-read" in args:
        idx = args.index("--mark-read")
        pages = [p for p in args[idx + 1:] if not p.startswith("--")] or ["（未填頁面）"]
        rec = mark_kb_read(pages)
        print(f"✅ 已標記真讀知識庫（{_now_iso()}）：{', '.join(pages)}")
    r = check()
    all_ok = True
    for k, v in r.items():
        mark = "✅" if v["ok"] else "❌"
        print(f"{mark} [{k}] {v['detail']}")
        all_ok = all_ok and v["ok"]
    print("\n總結:", "紀律狀態全過" if all_ok else "有欠項——補完再繼續下一波（見上方 ❌）")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
