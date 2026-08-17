# -*- coding: utf-8 -*-
"""token_router.py — Token ROI 動態調度器（v3.1 獨創功能）
不是「一刀切」套規則，而是依任務類型 × 上下文狀態，動態輸出最優優化組合。

用法：
  from token_router import optimize
  opt = optimize("data_analysis", {"tool_return_lines": 200, "history_rounds": 12})

  CLI：python token_router.py data_analysis --tool-lines 200 --rounds 12
       python token_router.py code_debug --tool-lines 30

原理：不同任務對「聚合/壓縮/輸出上限」的收益不同——
  數據分析：聚合工具回傳收益極大（Top-N+統計即可）
  程式除錯：聚合有害（需逐行細節）
  創意寫作：限輸出有害
  多輪 Agent：狀態快照壓縮收益隨輪數增長
"""
import argparse
import json
from typing import Dict, Any

# 任務類型 → 基礎策略（規則引擎核心）
BASE_STRATEGY = {
    "data_analysis": {
        "aggregate": {"on": True, "top_n": 5, "compact": True,
                      "why": "分析只需統計+Top-N+異常，原始資料浪費 90%+； 預設 compact 格式再省 ~50%"},
        "compress": {"on": True, "mode": "summary", "why": "歷史摘要保留結論即可"},
        "cap": {"words": 300, "why": "分析結論結構化，300 字內可完成"},
        "json_mode": True, "temperature": 0.0,
        "json_compress": {"on": True, "mode": "csv",
                          "why": "工具回傳 JSON 轉 CSV 去 key 名，保真省 ~50%（ 新增）"},
    },
    "code_debug": {
        "aggregate": {"on": False, "why": "除錯需逐行細節，聚合會丟失錯誤上下文"},
        "compress": {"on": True, "mode": "window", "why": "滑動窗口保留近期程式碼，舊論述可丟"},
        "cap": {"words": 800, "why": "程式輸出需放寬"},
        "json_mode": False, "temperature": 0.0,
        # v5.1 修復：code 任務（找 bug/看邏輯）不能用簽名萃取（v5.0 實證品質崩到 8/100）。
        # 改用 mode=light：整檔輕量壓縮，保留 100% 邏輯行、只去註解/空行/docstring。
        # 確定性測試證實：簽名模式會丟失 bug 邏輯行，light 模式保留且真實省 token（無封裝開銷）。
        # ：file_lines>300 大檔自動切 medium 折疊（見 _adjust）。
        "code_extract": {"mode": "light",
                         "why": "除錯/審碼需邏輯正文；light 模式保邏輯去註解，品質不傷又真省"},
    },
    "code_review": {
        "aggregate": {"on": False, "why": "審碼需看邏輯骨架，不需聚合工具資料"},
        "compress": {"on": True, "mode": "window"},
        "cap": {"words": 800, "why": "審碼結論需引用行號，放寬輸出"},
        "json_mode": False, "temperature": 0.0,
        "code_extract": {"mode": "medium", "fold_threshold": 40,
                         "why": "：折疊長函數體（簽名+前8行+控制流骨架），代碼降幅 31%→~50%；短函數整留保邏輯"},
    },
    "code_refactor": {
        "aggregate": {"on": False, "why": "重構需看結構與呼叫點"},
        "compress": {"on": True, "mode": "window"},
        "cap": {"words": 1000},
        "json_mode": False, "temperature": 0.0,
        "code_extract": {"mode": "medium", "fold_threshold": 40,
                         "why": "：重構只看結構，medium 折疊最划算（骨架+短函數體）"},
    },
    "creative": {
        "aggregate": {"on": False, "why": "創作不需工具資料"},
        "compress": {"on": True, "mode": "summary", "why": "保留主題與風格偏好即可"},
        "cap": {"words": 2000, "why": "創作需篇幅，不限輸出"},
        "json_mode": False, "temperature": 0.7,
    },
    "summarization": {
        "aggregate": {"on": True, "top_n": 3, "compact": True, "why": "摘要目標就是壓縮； 預設 compact 格式"},
        "compress": {"on": True, "mode": "summary"},
        "cap": {"words": 200, "why": "摘要輸出上限"},
        "json_mode": False, "temperature": 0.0,
    },
    "qa": {
        "aggregate": {"on": False, "why": "問答不需工具資料（除非回傳極大）"},
        "compress": {"on": False, "why": "單輪問答歷史短"},
        "cap": {"words": 100, "why": "簡單問答純結論"},
        "json_mode": False, "temperature": 0.0,
    },
    "agent_loop": {
        "aggregate": {"on": True, "top_n": 5, "compact": True,
                      "why": "迴圈中工具回傳每輪重送，聚合收益複利； 預設 compact 格式"},
        "compress": {"on": True, "mode": "state", "why": "狀態快照（目標/已完成/待辦）取代逐字歷史"},
        "cap": {"words": 300, "why": "每步結論化"},
        "json_mode": True, "temperature": 0.0,
    },
}

# 上下文狀態 → 動態覆寫（優先於基礎策略）
def _adjust(strategy: Dict[str, Any], ctx: Dict[str, Any], task_type: str = "") -> list:
    reasons = []
    tl = ctx.get("tool_return_lines", 0)
    rounds = ctx.get("history_rounds", 0)
    file_lines = ctx.get("file_lines", 0)
    # 工具回傳極大 → 即使基礎策略關聚合也建議開（qa 例外由閾值決定）
    if tl > 50:
        agg = strategy.get("aggregate")
        if agg and not agg.get("on"):
            agg["on"] = True; agg["top_n"] = 5
            reasons.append(f"工具回傳 {tl} 行 > 50，動態開啟聚合")
        elif tl > 200 and strategy.get("aggregate", {}).get("on"):
            strategy["aggregate"]["top_n"] = 3
            reasons.append(f"工具回傳 {tl} 行超大，Top-N 收緊到 3")
    #  修復：移除「file_lines>300 → light 自動切 medium」的動態調整。
    # 原因：code_debug 是唯一用 light 的任務， 會讓它在大檔時誤切 medium；
    # 但 benchmark_llm 實測 code 壓縮品質崩到 8.3/100（impact 0.92），medium 摺疊
    # 丟副作用/例外路徑，debug 深層邏輯會丟錯誤上下文（知識庫明載不適用）。
    # code_review/code_refactor 基礎策略即 medium，無需動態切換（原調整為死碼）。
    # 多輪 → 開啟壓縮
    if rounds > 8:
        comp = strategy.get("compress")
        if comp and not comp.get("on"):
            comp["on"] = True; comp["mode"] = "state"
            reasons.append(f"對話 {rounds} 輪 > 8，動態開啟狀態快照壓縮")
    # 輸出上限：任務要求細節 → 放寬
    if ctx.get("need_detail"):
        st = strategy.get("cap")
        if st: st["words"] = max(st["words"], 1500)
        reasons.append("任務要求細節，輸出上限放寬至 1500")
    return reasons


def optimize(task_type: str, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """依任務類型 + 上下文狀態，輸出推薦優化組合。"""
    ctx = ctx or {}
    base = BASE_STRATEGY.get(task_type)
    if base is None:
        base = BASE_STRATEGY["general"] if "general" in BASE_STRATEGY else {
            "aggregate": {"on": True, "top_n": 5}, "compress": {"on": True, "mode": "summary"},
            "cap": {"words": 300}, "json_mode": True, "temperature": 0.0}
        task_type = "general（預設）"
    strategy = json.loads(json.dumps(base))  # deep copy
    reasons = _adjust(strategy, ctx, task_type=task_type)
    # 學習策略套用：完整版引擎具備歷史反饋自適應；開源本版本不含此子系統，
    # 以下為向後相容 no-op（規則引擎原樣返回，不依賴學習模組）。
    pass
    est = _estimate_saving(task_type, ctx)
    return {"task_type": task_type, "strategy": strategy,
            "dynamic_reasons": reasons, "est_saving": est}


def _estimate_saving(task_type: str, ctx: Dict[str, Any]) -> str:
    tl, rounds = ctx.get("tool_return_lines", 0), ctx.get("history_rounds", 0)
    if tl > 200 or rounds > 10:
        return "60–80%（工具/歷史佔比大）"
    if tl > 50 or rounds > 5:
        return "40–60%"
    return "20–40%（輕量場景，避免過度優化反傷）"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Token ROI 動態調度器")
    ap.add_argument("task_type", choices=list(BASE_STRATEGY.keys()) + ["general"])
    ap.add_argument("--tool-lines", type=int, default=0, help="工具回傳行數")
    ap.add_argument("--rounds", type=int, default=0, help="對話輪數")
    ap.add_argument("--need-detail", action="store_true", help="任務要求細節")
    a = ap.parse_args()
    r = optimize(a.task_type, {"tool_return_lines": a.tool_lines,
                               "history_rounds": a.rounds, "need_detail": a.need_detail})
    print(json.dumps(r, ensure_ascii=False, indent=2))


# ===== 反饋學習介面（v3.1+）：記錄決策成效，供統計調參 =====
import json as _json, os as _os

_FEEDBACK_PATH = _os.environ.get("TOKEN_ROUTER_FEEDBACK", "token_router_feedback.jsonl")


def record_feedback(task_type: str, ctx: dict, actual_saving_pct: float,
                    quality_ok: bool = True, path: str = _FEEDBACK_PATH) -> None:
    """記錄一次實際調度成效。累積後可統計「哪些策略組合最有效」，供調參。"""
    entry = {"task_type": task_type, "ctx": {k: v for k, v in (ctx or {}).items()},
             "actual_saving_pct": round(actual_saving_pct, 1), "quality_ok": quality_ok}
    with open(path, "a", encoding="utf-8") as f:
        f.write(_json.dumps(entry, ensure_ascii=False) + "\n")


def feedback_report(path: str = _FEEDBACK_PATH) -> dict:
    """匯總反饋：各任務類型平均節省、品質異常率。"""
    if not _os.path.exists(path):
        return {"error": "尚無反饋記錄（先 record_feedback）"}
    rows = [_json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    from collections import defaultdict
    agg = defaultdict(list); bad = defaultdict(int)
    for r in rows:
        agg[r["task_type"]].append(r["actual_saving_pct"])
        if not r.get("quality_ok"): bad[r["task_type"]] += 1
    return {k: {"平均節省%": round(sum(v)/len(v), 1), "樣本": len(v), "品質異常": bad.get(k, 0)}
            for k, v in agg.items()}


# ===== v4.2 反饋學習落地：統計學習 + ε-greedy 探索（非僅介面） =====
import random as _random

def learned_optimize(task_type: str, ctx: dict | None = None,
                     feedback_path: str = _FEEDBACK_PATH, epsilon: float = 0.1) -> dict:
    """依歷史反饋調整策略推薦（越用越準）：
    - 無數據：回退規則引擎 optimize()，並以 ε 探索
    - 有數據：該任務類型歷史「平均節省」高 → 維持；低 → 收緊聚合/壓縮力度
    - ε-greedy：10% 機率探索更激進組合（避免陷入局部最優）
    """
    ctx = ctx or {}
    opt = optimize(task_type, ctx)
    history = []
    if _os.path.exists(feedback_path):
        history = [_json.loads(l) for l in open(feedback_path, encoding="utf-8") if l.strip()]
    hist = [r for r in history if r.get("task_type") == task_type]
    learning = {"samples": len(hist), "explored": False, "adjusted": False}
    if hist:
        avg = sum(r.get("actual_saving_pct", 0) for r in hist) / len(hist)
        quality_bad = sum(1 for r in hist if not r.get("quality_ok", True))
        learning["avg_saving"] = round(avg, 1)
        learning["quality_bad"] = quality_bad
        # 學習調整：平均節省低或品質異常高 → 收緊（少聚合/少壓縮，保品質）
        if avg < 30 or quality_bad > 0:
            agg = opt["strategy"].get("aggregate")
            if agg and agg.get("on"):
                # ：上限 15，防連續品質異常時 top_n 無上限放大（stress 實測 5→15→25）
                agg["top_n"] = min(max(agg.get("top_n", 5) + 5, 10), 15)
                learning["adjusted"] = True
                learning["adjust_reason"] = f"歷史平均節省 {avg:.0f}% 偏低/品質異常 {quality_bad} 筆，放寬聚合（≤15）"
        # ε-greedy 探索
        if _random.random() < epsilon:
            comp = opt["strategy"].get("compress")
            if comp and comp.get("on"):
                comp["mode"] = "window" if comp.get("mode") == "summary" else "summary"
                learning["explored"] = True
    return {**opt, "learning": learning}


if __name__ == "__main__" and False:  # 僅供 import；CLI 見 token_router.py 主入口
    pass
