# -*- coding: utf-8 -*-
"""
tokknife — LLM 真實實證基準 (benchmark_llm.py)
======================================================
用真實 LLM（豆包 seed-2.0-pro，OpenAI 相容）做 A/B 對比：
  - 同一任務，Baseline = 原始上下文；Optimized = token-saver 優化後上下文
  - 取模型真實回傳 usage.prompt_tokens 作為「輸入降幅」ground truth
  - 用 LLM-as-judge 評「壓縮後答案」vs「原始答案」的品質保留率 (0-100)

目標：補 v4.2 對比評分最弱的兩維度 —— 實證 (empirical evidence) 與工程成熟度。

用法：
  export EX_LLM_KEY=ark-xxxx
  python benchmark_llm.py --tasks 12 --out results.json
"""
import os, sys, json, time, argparse, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from typing import List, Dict, Any, Optional

random.seed(42)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ---- 優化腳本 ----
import aggregate_tool_output as agg
import compress_history as ch
import code_context_extractor as cce
import audit_system_prompt as asp
import incremental_compressor as ic
import token_router as tr  # v5.1: code 任務依路由決定是否含正文
import json_compressor as jc  # : tool_output 改走 JSON→CSV（ 機制）
import adaptive_aggregator as aa  # : tool_output 校準聚合（剔常數欄位+Top-N+compact）

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def _tk(s): return len(_ENC.encode(s))
except Exception:
    def _tk(s): return len(s) // 3

# ---- LLM 客戶端 (OpenAI 相容, 純 urllib, 零依賴) ----
API_KEY = os.environ.get("EX_LLM_KEY") or os.environ.get("ARK_API_KEY")
BASE_URL = os.environ.get("EX_LLM_BASE", "https://ark.cn-beijing.volces.com/api/v3")
MODEL = os.environ.get("EX_LLM_MODEL", "doubao-seed-2-0-pro-260215")

def chat(messages: List[Dict[str, str]], max_tokens: int = 800, temperature: float = 0.2) -> Dict[str, Any]:
    import urllib.request
    payload = {"model": MODEL, "messages": messages, "max_tokens": max_tokens,
               "temperature": temperature, "stream": False,
               "thinking": {"type": "disabled"}}
    last_err = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(BASE_URL + "/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last_err = e
            if attempt < 3:
                time.sleep(3 + attempt * 2)
    raise last_err if last_err else RuntimeError("chat failed")

def complete(system: str, user: str, **kw) -> Dict[str, Any]:
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user})
    return chat(msgs, **kw)


# ===================== 數據生成 =====================
def gen_tool_output(n: int = 200) -> List[Dict]:
    products = [f"P{i:03d}" for i in range(1, n + 1)]
    regions = ["North", "South", "East", "West", "Central"]
    rows = []
    for p in products:
        rows.append({
            "product": p,
            "region": random.choice(regions),
            "sales": round(random.uniform(100, 9999), 2),
            "growth": round(random.uniform(-40, 80), 2),
            "returns": random.randint(0, 50),
            "units": random.randint(10, 5000),
        })
    # 注入一個明顯異常
    rows[42]["sales"] = 99999.0
    return rows

def gen_conversation(turns: int = 40) -> List[Dict[str, str]]:
    base = [
        ("user", "我想做一個工廠自動化看板，先幫我列需求"),
        ("assistant", "好的，我先確認範圍：要監控哪些產線指標？已完成需求清單初稿。"),
        ("user", "OEE、良率、停機次數，三個就夠"),
        ("assistant", "收到，已加入 OEE/良率/停機三指標。下一步做資料源對接設計。"),
        ("user", "資料從 MES 過來，每分鐘一筆"),
        ("assistant", "明白，MES 每分鐘推送，我會設計緩衝與重試。已完成資料流架構。"),
    ]
    msgs = []
    for i in range(turns):
        role, text = base[i % len(base)]
        msgs.append({"role": role, "content": f"[第{i+1}輪] {text} 細節補充：欄位命名用 snake_case，時區用 UTC+8。"})
    return msgs

def gen_code(n_funcs: int = 30) -> str:
    lines = ["# -*- coding: utf-8 -*-", '"""自動生成的大型業務模組（基準用）"""', "import os, json, time", "",
             "class DataPipeline:", "    def __init__(self, cfg):", "        self.cfg = cfg", ""]
    for i in range(n_funcs):
        lines += [
            f"    def process_{i}(self, payload):",
            f"        # 處理第 {i} 類負載",
            f"        if not payload:",
            f"            return None",
            f"        result = {{'id': {i}, 'ok': True}}",
            f"        for k, v in payload.items():",
            f"            result[k] = v",
            f"        return result",
            "",
            f"def helper_{i}(x):",
            f"    # 輔助函數 {i}",
            f"    return x * {i} if x else 0",
            "",
        ]
    lines += ["if __name__ == '__main__':", "    p = DataPipeline({})", "    print(p.process_0({'a': 1}))"]
    return "\n".join(lines)

def gen_system_prompt() -> str:
    filler = ["很高興為您服務", "請隨時告訴我您的需求", "如有任何問題，不用客氣", "作為一個經驗豐富的資深專家"]
    parts = [
        "你是一個工廠持續改善專案助手。",
        "很高興為您服務，請隨時告訴我您的需求。",
        "你的職責是追蹤專案進度並生成匯報。",
        "作為一個經驗豐富的資深專家，你會主動提醒風險。",
        "如有任何問題，不用客氣，請直接提出。",
        "你應該使用繁體中文回覆用戶。",
        "你的職責是追蹤專案進度並生成匯報。",  # 重複句
        "請使用繁體中文回覆用戶。",                # 重複句
        "很高興為您服務，請隨時告訴我您的需求。",  # 重複 filler
        "匯報格式應包含：進度、風險、下一步。",
    ]
    return "\n".join(parts)


# ===================== 優化器 =====================
def optimize_tool_output(raw: List[Dict], query: str = "") -> str:
    #  B：依查詢路由——
    #   精確排名/異常列舉類（query 含 Top/排名/異常…）→ 高通真 json_compressor 留全行（~53%）
    #   其餘 → AdaptiveAggregator 保真降壓（ 行為）
    text, _mode = aa.route_tool_output(raw, query=query, sort_by="sales", calibrated=True)
    return text

def optimize_conversation(raw: List[Dict]) -> List[Dict[str, str]]:
    return ch.compress_messages(raw, keep_recent=3, use_llm_summary=False)

def optimize_code(raw: str, mode: str | None = None) -> str:
    """v5.1：code 優化模式由 token_router 決定（code_debug → 'light'）。
    ：mode=None 讀路由 code_debug → 'light'（ 修復後 debug 恆保 light）；
    可強制 'signature' / 'light' / 'medium' / 'raw'（用於 A/B，含 medium 折疊專測）。"""
    import tempfile
    if mode is None:
        mode = tr.optimize("code_debug").get("strategy", {}).get("code_extract", {}).get("mode", "light")
    fd, tmp = tempfile.mkstemp(suffix=".py", prefix="ts_bench_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
        if mode == "light":
            out = cce.compress_code_light(tmp)
        elif mode == "medium":
            out = cce.compress_code_medium(tmp, fold_threshold=25, keep_head=6)
        elif mode == "raw":
            out = raw
        else:  # signature（舊 v5.0）
            out = cce.extract_context(tmp, recursive=False, include_body=False)
    finally:
        try: os.remove(tmp)
        except Exception: pass
    return out


def _safe_call(prompt: str, max_tokens: int = 500):
    try:
        d = complete("", prompt, max_tokens=max_tokens, temperature=0.1)
        ans = d["choices"][0]["message"]["content"]
        pt = d.get("usage", {}).get("prompt_tokens")
        return ans, pt
    except Exception:
        return None, None


def compare_code_mode(n: int = 3) -> List[Dict]:
    """受控 A/B：同一份 code，兩模式對比——
      (a) 簽名萃取(舊 v5.0，省但丟邏輯)  (b) light 整檔輕量壓縮(v5.1，保邏輯真省)
    證明 v5.1 在品質回復與降幅間取得平衡。"""
    MODES = [("signature_v50", "signature"), ("light_v51", "light")]
    out = []
    for i in range(n):
        raw = gen_code(30)
        instr = TASK_BUILDERS["code"]["instr"]
        base_prompt = build_prompt(instr, raw)
        base_ans, base_pt = _safe_call(base_prompt)
        if base_ans is None:
            print(f"  code#{i+1} baseline 失敗，跳過", flush=True); continue
        base_pt = base_pt or _tk(base_prompt)
        rec = {"sample": i + 1, "baseline_prompt_tokens": base_pt}
        for label, m in MODES:
            opt_text = optimize_code(raw, mode=m)
            opt_prompt = build_prompt(instr, opt_text)
            opt_ans, opt_pt = _safe_call(opt_prompt)
            if opt_ans is None:
                rec[label] = {"prompt_tokens": None, "saving_pct": 0.0, "quality": 0, "reason": "call_fail"}
                continue
            opt_pt = opt_pt or _tk(opt_prompt)
            j = judge_quality(instr, base_ans, opt_ans)
            rec[label] = {"prompt_tokens": opt_pt,
                          "saving_pct": round((base_pt - opt_pt) / base_pt * 100, 1),
                          "quality": j["score"], "reason": j["reason"]}
        out.append(rec)
        print(f"  code#{i+1}: 簽名 品質={rec['signature_v50']['quality']}/{rec['signature_v50']['saving_pct']}% | "
              f"light 品質={rec['light_v51']['quality']}/{rec['light_v51']['saving_pct']}%", flush=True)
        time.sleep(0.5)
    return out

def optimize_system_prompt(raw: str) -> str:
    rep = asp.audit(raw)
    # 實際裁剪：去重複行 + 去 filler
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    seen = set(); kept = []
    for l in lines:
        if l in seen: continue
        if any(f in l for f in asp.FILLER): continue
        seen.add(l); kept.append(l)
    return "\n".join(kept)

def optimize_incremental(raw: List[Dict]) -> List[Dict[str, str]]:
    c = ic.IncrementalCompressor(keep_recent=3, max_state_tokens=200)
    for m in raw:
        c.add_message(m)
    return c.build_context(include_state=True, include_recent=True)


# ===================== 任務定義 =====================
def _fmt_any(x) -> str:
    """tool_output/tool_ranking 通用：list/dict → JSON 字串；str → 原樣（壓縮後已是文字）。"""
    if isinstance(x, (list, dict)):
        return json.dumps(x, ensure_ascii=False)
    return str(x)

def _to_num(v) -> float:
    """安全轉數字（相容 '%' / ',' / 字串）。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace('%', '').replace(',', ''))
        except (ValueError, AttributeError):
            return 0.0
    return 0.0

def gen_facts(raw: List[Dict]) -> Dict:
    """ C：從原始數據精確計算『標準答案事實』（100% 正確），供 judge_facts 核對。
    覆蓋摘要任務與排名任務共同的事實錨點。"""
    rows = sorted(raw, key=lambda x: _to_num(x.get("sales", 0)), reverse=True)
    total = len(raw)
    avg = round(sum(_to_num(r["sales"]) for r in raw) / total, 1) if total else 0.0
    top1 = rows[0] if rows else {}
    vals = sorted(_to_num(r["sales"]) for r in raw)
    med = vals[len(vals) // 2] if vals else 0.0
    # 異常：高於中位數 10 倍（注入的 99999 必中；其餘均勻分佈不誤判）
    anomalies = [r for r in raw if _to_num(r["sales"]) > med * 10 and med > 0]
    return {
        "total_rows": total,
        "avg_sales": avg,
        "top1_product": top1.get("product"),
        "top1_sales": _to_num(top1.get("sales")),
        "top5": [{"product": r["product"], "sales": _to_num(r["sales"])} for r in rows[:5]],
        "anomaly_products": [a["product"] for a in anomalies],
        "anomaly_sales": [_to_num(a["sales"]) for a in anomalies],
    }

def judge_facts(instr: str, cand_ans: str, facts: Dict) -> Dict:
    """ C：事實核對 judge——以『標準答案事實』為 ground truth，核對候選答案
    是否正確包含這些事實。解決舊 judge『candidate vs baseline』兩份模型輸出比一致性
    的噪聲（實測豆包對數值排名任務本身不可靠，致品質天花板 ~48）。"""
    sysj = ("你是一個嚴格的事實核對員。下方給出『標準答案事實』（從原始數據精確計算，100% 正確）。"
            "請核對候選答案是否正確包含了這些事實：筆數(total_rows)、平均銷售額(avg_sales，允許±20%誤差)、"
            "最高產品(top1_product)、Top5 產品與數值、異常產品(anomaly_products)。"
            "只輸出 JSON：{\"score\": 0-100 整數, \"reason\": \"一句中文\", \"miss\": [漏掉或寫錯的事實key]}。")
    fj = "標準答案事實：\n" + json.dumps(facts, ensure_ascii=False, indent=2)
    userj = f"{fj}\n\n【候選答案（壓縮上下文生成）】\n{cand_ans}\n\n請核對並評分（JSON）。"
    for attempt in range(3):
        try:
            d = complete(sysj, userj, max_tokens=300, temperature=0.0)
            txt = d["choices"][0]["message"]["content"]
            s = txt.find("{"); e = txt.rfind("}")
            obj = json.loads(txt[s:e+1])
            return {"score": int(obj.get("score", 0)), "reason": obj.get("reason", ""), "miss": obj.get("miss", [])}
        except Exception as ex:
            if attempt == 2:
                return {"score": 0, "reason": f"parse_fail:{ex}", "miss": []}
            time.sleep(2)
    return {"score": 0, "reason": "unknown", "miss": []}

TASK_BUILDERS = {
    "tool_output": {
        #  C：摘要/統計描述任務（替代對模型一致性極敏感的「列舉 Top5+異常」）
        # 評測改對「標準事實」核對（judge_facts），不再拿 candidate vs baseline 比一致性。
        "gen": lambda: gen_tool_output(200),
        "opt": optimize_tool_output,
        "fmt": _fmt_any,
        "instr": "以下是 MES 系統回傳的銷售明細（JSON 陣列）。請用 3-4 句摘要這份數據：(1) 總共有幾筆；(2) 總銷售額約多少、平均銷售額約多少；(3) 銷售最高的產品是哪個；(4) 數據中是否有明顯異常值，若有請說明其數值。",
        "ctx_name": "sales_data",
    },
    "tool_ranking": {
        #  B：精確排名/異常列舉任務（Top5+異常）——query 含列舉關鍵字 → 路由高通真留全行
        "gen": lambda: gen_tool_output(200),
        "opt": optimize_tool_output,
        "fmt": _fmt_any,
        "instr": "以下是 MES 系統回傳的銷售明細（JSON 陣列）。請列出銷售額 Top 5 產品及其精確數值，並指出明顯異常的產品及其數值。",
        "ctx_name": "sales_data",
    },
    "conversation": {
        "gen": lambda: gen_conversation(40),
        "opt": optimize_conversation,
        "fmt": lambda x: "\n".join(f"{m['role']}: {m['content']}" for m in x),
        "instr": "以下是你與用戶的多輪對話歷史。請總結：(1) 用戶的核心需求；(2) 已完成的任務；(3) 待辦事項。",
        "ctx_name": "history",
    },
    "code": {
        "gen": lambda: gen_code(30),
        "opt": optimize_code,
        "fmt": lambda x: x,
        "instr": "這是一個 Python 業務模組。請只依據代碼回答：(1) 它有幾個公開方法/函數；(2) 列出方法名；(3) 指出一個潛在 bug 或設計風險。",
        "ctx_name": "module",
    },
    "system_prompt": {
        "gen": lambda: gen_system_prompt(),
        "opt": optimize_system_prompt,
        "fmt": lambda x: x,
        "instr": "這是一段系統提示詞。請只依據它回答：(1) 助手被要求扮演什麼角色；(2) 回覆語言是什麼；(3) 匯報必須包含哪三個部分。",
        "ctx_name": "sysprompt",
    },
    "incremental": {
        "gen": lambda: gen_conversation(36),
        "opt": optimize_incremental,
        "fmt": lambda x: "\n".join(f"{m.get('role','?'):>9}: {m['content']}" for m in x),
        "instr": "以下是對話的壓縮狀態與最近幾輪。請回答：(1) 當前任務目標；(2) 已完成項；(3) 待辦項。",
        "ctx_name": "state",
    },
}

def build_prompt(instr: str, ctx_text: str) -> str:
    return f"{instr}\n\n===== 上下文 =====\n{ctx_text}\n===== 結束 ====="

def judge_quality(instr: str, baseline_ans: str, cand_ans: str) -> Dict:
    sysj = "你是一個嚴格的評分員。比較候選答案與基準答案，評估候選在『資訊完整性與正確性』上保留了多少（基準視為 100 分滿分）。只輸出 JSON：{\"score\": 0-100 整數, \"reason\": \"一句中文\"}。"
    userj = f"用戶指令：{instr}\n\n【基準答案（完整上下文）】\n{baseline_ans}\n\n【候選答案（壓縮上下文）】\n{cand_ans}\n\n請評分並給理由（JSON）。"
    for attempt in range(3):
        try:
            d = complete(sysj, userj, max_tokens=300, temperature=0.0)
            txt = d["choices"][0]["message"]["content"]
            # 抽取 JSON
            s = txt.find("{"); e = txt.rfind("}")
            obj = json.loads(txt[s:e+1])
            return {"score": int(obj.get("score", 0)), "reason": obj.get("reason", "")}
        except Exception as ex:
            if attempt == 2:
                return {"score": 0, "reason": f"parse_fail:{ex}"}
            time.sleep(2)
    return {"score": 0, "reason": "unknown"}


def run_benchmark(n_per_type: int = 3, args_out: str = "", type_filter: str = "") -> List[Dict]:
    results = []
    for ttype, spec in TASK_BUILDERS.items():
        if type_filter and ttype != type_filter:
            continue
        for idx in range(n_per_type):
            raw = spec["gen"]()
            instr = spec["instr"]
            #  B：tool_output/tool_ranking 依 query 路由（精確列舉→高通真留全行）
            if ttype in ("tool_output", "tool_ranking"):
                opt, mode = aa.route_tool_output(raw, query=instr, sort_by="sales", calibrated=True)
            else:
                opt = spec["opt"](raw)
                mode = "n/a"
            raw_text = spec["fmt"](raw)
            opt_text = spec["fmt"](opt)
            base_prompt = build_prompt(instr, raw_text)
            opt_prompt = build_prompt(instr, opt_text)
            print(f"[{ttype}#{idx+1}] mode={mode} raw={_tk(raw_text)}tok opt={_tk(opt_text)}tok ...", flush=True)

            # baseline
            try:
                db = complete("", base_prompt, max_tokens=500, temperature=0.1)
                base_ans = db["choices"][0]["message"]["content"]
                base_pt = db.get("usage", {}).get("prompt_tokens", _tk(base_prompt))
            except Exception as e:
                print(f"   !! baseline 失敗: {e}", flush=True)
                continue
            # optimized
            try:
                do = complete("", opt_prompt, max_tokens=500, temperature=0.1)
                opt_ans = do["choices"][0]["message"]["content"]
                opt_pt = do.get("usage", {}).get("prompt_tokens", _tk(opt_prompt))
            except Exception as e:
                print(f"   !! optimized 失敗: {e}", flush=True)
                continue
            # judge： C：tool 類型用「標準事實核對」（去 baseline 一致性噪聲）
            #   同時對 baseline 答案核對 → 才能區分「壓縮損傷」vs「模型本身數值能力天花板」
            if ttype in ("tool_output", "tool_ranking"):
                facts = gen_facts(raw)
                j = judge_facts(instr, opt_ans, facts)
                jb = judge_facts(instr, base_ans, facts)
                baseline_quality = jb["score"]
            else:
                j = judge_quality(instr, base_ans, opt_ans)
                baseline_quality = None
            saving = round((base_pt - opt_pt) / base_pt * 100, 1) if base_pt else 0.0
            # 壓縮品質保留率：優化/原始（事實核對同尺），越接近 100% 表示壓縮不傷事實
            retention = round(j["score"] / baseline_quality * 100, 1) if (baseline_quality and baseline_quality > 0) else None
            rec = {
                "type": ttype, "idx": idx + 1, "mode": mode,
                "raw_tokens_est": _tk(raw_text), "opt_tokens_est": _tk(opt_text),
                "baseline_prompt_tokens": base_pt, "optimized_prompt_tokens": opt_pt,
                "input_saving_pct": saving,
                "quality_score": j["score"], "baseline_quality_score": baseline_quality,
                "quality_retention_pct": retention,
                "quality_reason": j["reason"], "quality_miss": j.get("miss", []),
                "raw_chars": len(raw_text), "opt_chars": len(opt_text),
            }
            results.append(rec)
            # 即時存檔（可續跑，不丟進度）
            json.dump({"model": MODEL, "summary": summarize(results), "results": results},
                      open(args_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"   -> 輸入降幅 {saving}% | 品質 {j['score']}/100 | {j['reason']}", flush=True)
            time.sleep(0.5)
    return results


def summarize(results: List[Dict]) -> Dict:
    if not results:
        return {}
    avg_sav = round(sum(r["input_saving_pct"] for r in results) / len(results), 1)
    avg_q = round(sum(r["quality_score"] for r in results) / len(results), 1)
    bqs = [r["baseline_quality_score"] for r in results if r.get("baseline_quality_score") is not None]
    avg_bq = round(sum(bqs) / len(bqs), 1) if bqs else None
    rts = [r["quality_retention_pct"] for r in results if r.get("quality_retention_pct") is not None]
    avg_rt = round(sum(rts) / len(rts), 1) if rts else None
    by_type = {}
    for t in TASK_BUILDERS:
        rs = [r for r in results if r["type"] == t]
        if rs:
            bqs_t = [r["baseline_quality_score"] for r in rs if r.get("baseline_quality_score") is not None]
            rts_t = [r["quality_retention_pct"] for r in rs if r.get("quality_retention_pct") is not None]
            by_type[t] = {
                "n": len(rs),
                "avg_saving": round(sum(r["input_saving_pct"] for r in rs)/len(rs), 1),
                "avg_quality": round(sum(r["quality_score"] for r in rs)/len(rs), 1),
                "avg_baseline_quality": round(sum(bqs_t)/len(bqs_t), 1) if bqs_t else None,
                "avg_retention": round(sum(rts_t)/len(rts_t), 1) if rts_t else None,
            }
    return {"n": len(results), "avg_input_saving_pct": avg_sav,
            "avg_quality_score": avg_q, "avg_baseline_quality_score": avg_bq,
            "avg_quality_retention_pct": avg_rt, "by_type": by_type}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=3, help="每類任務數（全量 A/B 基準）")
    ap.add_argument("--type", type=str, default="", help="只跑指定類型（tool_output/conversation/code/system_prompt/incremental），空=全跑")
    ap.add_argument("--compare-code", type=int, default=0, help="code 受控對比樣本數（簽名 vs 含正文）")
    ap.add_argument("--out", default=os.path.join(HERE, "benchmark_llm_results_v51.json"))
    args = ap.parse_args()
    if not API_KEY:
        print("ERROR: 設 EX_LLM_KEY 環境變數"); sys.exit(1)
    t0 = time.time()
    if args.compare_code:
        cmp = compare_code_mode(args.compare_code)
        MODES = ["signature_v50", "light_v51"]
        summary = {"samples": len(cmp), "modes": {}}
        for m in MODES:
            qs = [c[m]["quality"] for c in cmp if c.get(m)]
            sv = [c[m]["saving_pct"] for c in cmp if c.get(m)]
            summary["modes"][m] = {"avg_quality": round(sum(qs)/len(qs), 1) if qs else 0,
                                   "avg_saving": round(sum(sv)/len(sv), 1) if sv else 0}
        json.dump({"model": MODEL, "summary": summary, "results": cmp},
                  open(os.path.join(HERE, "benchmark_code_v51.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"\n=== code 受控對比 (v5.0 簽名 vs v5.1 light) ===\n{json.dumps(summary, ensure_ascii=False, indent=2)}")
        print(f"用時 {time.time()-t0:.0f}s | 存 benchmark_code_v51.json")
        return
    results = run_benchmark(args.tasks, args.out, args.type)
    summ = summarize(results)
    out = {"model": MODEL, "generated_at": time.strftime("%Y-%m-%d %H:%M"),
           "summary": summ, "results": results}
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n=== 總結 ===\n{json.dumps(summ, ensure_ascii=False, indent=2)}")
    print(f"用時 {time.time()-t0:.0f}s | 結果存 {args.out}")


if __name__ == "__main__":
    main()
