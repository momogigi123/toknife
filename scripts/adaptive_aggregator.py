# -*- coding: utf-8 -*-
"""
tokknife — 工具回傳自適應聚合
不是靜態的 Top-N 聚合，而是根據 LLM 實際引用情況動態調整聚合粒度。
如果被聚合掉的內容被頻繁追問，自動降低聚合粒度（Top-5 → Top-10）。

用法：
    from adaptive_aggregator import AdaptiveAggregator
    agg = AdaptiveAggregator(initial_top_n=5)
    summary = agg.aggregate(data, columns=["product", "sales", "growth"])
    agg.record_usage(queried_fields=["growth"], queried_rows=["鏡頭膜"])  # LLM 實際查詢了這些
    agg.adapt()  # 根據使用情況調整 top_n
"""
import json
import re
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict


# =====  B：tool_output 路由（精確排名/異常列舉 → 高通真留全行）=====
# 這類任務要求模型精確列舉具體行（Top-N、異常項），過壓（Top-5 聚合）會逼模型
# 對未見行編造 → 實測 96% 降幅/品質 ~48（ 實證）。路由到 json_compressor
# 保留全部精確行（~53% 降幅）才是正解——生產入口 mcp_proxy 本就走這條。
# 關鍵字收緊：只對「強列舉意圖」觸發高通真（Top/排名/列出/前N/異常產品）；
# 摘要類（含「最高產品」「是否有異常」等單一事實詢問）視為非列舉 → 走保真降壓，
# 這樣 benchmark 的 tool_output 任務才能真正測到「壓縮是否保留摘要事實」。
PRECISE_ENUM_KEYWORDS = ["top", "排名", "排行", "榜", "列出", "列舉", "前", "異常產品",
                         "異常項", "異常值產品", "anomal", "exception", "top5", "top 5"]


def is_precise_enum_query(query: str) -> bool:
    """判斷查詢是否為『精確排名/異常列舉』類（需逐行精確值）。
    關鍵字收緊為強列舉意圖（Top/排名/列出/前N/異常產品），避免摘要類
    （含『最高產品』『是否有異常』等單一事實詢問）被誤判為列舉而走高通真。"""
    if not query:
        return False
    q = query.lower()
    return any(k in q for k in PRECISE_ENUM_KEYWORDS)


def route_tool_output(raw: List[Dict], query: str = "", sort_by: Optional[str] = None,
                      columns: Optional[List[str]] = None, calibrated: bool = True,
                      fidelity_guard: bool = True) -> Tuple[str, str]:
    """ B 路由：依查詢類型選壓縮策略。
    回傳 (text, mode)：
      - mode='high_fidelity_csv'：精確列舉類 → json_compressor 留全行（高通真，~53%）
      - mode='adaptive_fidelity'：其餘 → AdaptiveAggregator 保真降壓（head+tail+確定性結論）
    """
    if is_precise_enum_query(query):
        try:
            import json_compressor as jc
            csv_text = jc.compress_json_enhanced(raw)
            return csv_text, "high_fidelity_csv"
        except Exception:
            pass  # 回落 adaptive
    eng = AdaptiveAggregator(initial_top_n=5, tail_n=5, fidelity_guard=fidelity_guard)
    agg = eng.aggregate(raw, sort_by=sort_by or "sales", top_n=5, columns=columns,
                        calibrated=calibrated)
    text = eng.format_for_llm(agg, compact=True, max_cell_len=24)
    text += "\n[指令] 嚴格依上方[確定性 Top5]/[確定性 異常]作答，不得自行計算、不得增刪產品或異常項。"
    return text, "adaptive_fidelity"


class AdaptiveAggregator:
    """自適應工具回傳聚合器。"""

    def __init__(self, initial_top_n: int = 5, min_top_n: int = 3, max_top_n: int = 20,
                 adapt_threshold: int = 3,
                 fidelity_guard: bool = True, fidelity_ratio: float = 0.12,
                 fidelity_min: int = 12, fidelity_max: int = 30, tail_n: int = 5):
        """
        參數：
            initial_top_n: 初始保留的 Top-N 行數
            min_top_n: 最小保留行數
            max_top_n: 最大保留行數
            adapt_threshold: 超過這個次數的被聚合內容被查詢，就降低聚合粒度
            fidelity_guard:  保真降壓開關。數值表（可排序）下，強制保留不低於
                          保真下限的精確行，避免過壓丟中間值致模型編造（實測 96% 降幅→品質 51）。
            fidelity_ratio: 保真 top_n = ceil(total_rows * ratio)，按規模自適應
            fidelity_min: 保真 top_n 下限（小表也至少留這麼多精確行）
            fidelity_max: 保真 top_n 上限（防大表過度保留吃掉降幅）
            tail_n: 降序排序後補留尾段 N 行（涵蓋極低值異常，與 head 互補）
        """
        self.current_top_n = initial_top_n
        self.min_top_n = min_top_n
        self.max_top_n = max_top_n
        self.adapt_threshold = adapt_threshold
        #  保真降壓
        self.fidelity_guard = fidelity_guard
        self.fidelity_ratio = fidelity_ratio
        self.fidelity_min = fidelity_min
        self.fidelity_max = fidelity_max
        self.tail_n = tail_n

        # 使用統計
        self.field_usage = defaultdict(int)  # 每個字段被引用的次數
        self.row_usage = defaultdict(int)    # 每行被引用的次數
        self.aggregated_but_queried = 0      # 被聚合掉的內容被查詢的次數
        self.total_queries = 0
        self.adaptation_history = []

    def aggregate(self, data: List[Dict], sort_by: Optional[str] = None,
                  columns: Optional[List[str]] = None, top_n: Optional[int] = None,
                  calibrated: bool = False, exclude_anomalies: bool = False) -> Dict:
        """
        聚合數據為摘要 + Top-N + 異常值。

        參數：
            data: 原始數據列表
            sort_by: 排序字段（預設按第一個數值字段降序）
            columns: 要保留的列（預設全部）
            top_n: 覆蓋當前 top_n（可選）
            calibrated:  是否套用校準（剔除空/常數欄位 + 大樣本收緊 Top-N，輸入再降 15-20%）
            exclude_anomalies:  起預設 False（Top-N 包含異常行，排名與原始一致）；
                              True 保留  舊行為（Top-N 排除異常行）

        返回：
            {
                "summary": {...},
                "top_n": [...],
                "anomalies": [...],
                "total_rows": int,
                "aggregated_rows": int,
                "columns": [...],
            }
        """
        if not data:
            return {"summary": {}, "top_n": [], "anomalies": [], "total_rows": 0, "aggregated_rows": 0}

        cal = None
        if calibrated:
            cal = self.calibrate(data, columns)
            if cal["columns"]:
                columns = cal["columns"]
            if top_n is None:
                top_n = cal["top_n"]

        n = top_n if top_n is not None else self.current_top_n
        #  保真降壓：數值表按規模保留精確行下限（防過壓丟中間值致模型編造）
        if self.fidelity_guard and sort_by and self._is_number(data[0].get(sort_by)):
            fid = int(max(self.fidelity_min, len(data) * self.fidelity_ratio))
            fid = min(fid, self.fidelity_max)
            n = max(n, fid)  # 保真下限優先（不允許低於保真下限）
        cols = columns if columns else list(data[0].keys())

        # 統計摘要
        summary = self._compute_summary(data, cols)

        # 排序
        if sort_by and sort_by in data[0]:
            sorted_data = sorted(data, key=lambda x: self._to_number(x.get(sort_by, 0)), reverse=True)
        else:
            # 找第一個數值字段排序
            num_field = self._find_numeric_field(data[0])
            if num_field:
                sorted_data = sorted(data, key=lambda x: self._to_number(x.get(num_field, 0)), reverse=True)
            else:
                sorted_data = data

        # 異常值（超出均值 2 個標準差）
        anomalies = self._find_anomalies(data, cols)
        tail_len = 0  #  保真：tail 行計數（default 0）

        #  V-3a 修正：Top-N 預設包含異常行（exclude_anomalies=False）——
        # 真實 LLM A/B 實測（，96.1% 降幅/33.3 品質）根因： 的「Top-N 排除異常行」
        # 讓壓縮後 Top5 與基準（LLM 看完整 200 行）不一致——99999 的最大銷售被排除，
        # judge 判「Top5 擅自排除異常值」。format 輸出已有 [異常值] 標記可區分，
        # 排除是多餘的過度修正。exclude_anomalies=True 保留舊行為（opt-in）。
        if exclude_anomalies and sort_by:
            anomaly_keys = set()
            for a in anomalies:
                if sort_by in a:
                    anomaly_keys.add((a.get(sort_by), a.get("product")))
            top_rows = [r for r in sorted_data
                        if (r.get(sort_by), r.get("product")) not in anomaly_keys][:n]
        else:
            top_rows = sorted_data[:n]
        #  保真：補 tail（涵蓋極低值異常，與 head 互補；fidelity_guard 關閉或 exclude_anomalies 舊行為不補）
        if self.fidelity_guard and self.tail_n and len(sorted_data) > n + 1 and not exclude_anomalies:
            seen_keys = [tuple(str(r.get(c)) for c in cols) for r in top_rows]
            for r in sorted_data[-self.tail_n:]:
                k = tuple(str(r.get(c)) for c in cols)
                if k not in seen_keys:
                    top_rows.append(r)
                    seen_keys.append(k)
                    tail_len += 1
        top_n_data = [{k: row.get(k) for k in cols} for row in top_rows]

        return {
            "summary": summary,
            "top_n": top_n_data,
            "anomalies": anomalies,
            "total_rows": len(data),
            "aggregated_rows": max(0, len(data) - len(top_rows)),
            "columns": cols,
            "current_top_n": n,
            "tail_len": tail_len,
            "conclusions": self._build_conclusions(data, cols, sort_by, anomalies),
        }

    def _is_number(self, value) -> bool:
        """判斷值是否為數字。"""
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            try:
                float(value.replace('%', '').replace(',', ''))
                return True
            except (ValueError, AttributeError):
                return False
        return False

    def _to_number(self, value) -> float:
        """將值轉換為數字。"""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace('%', '').replace(',', ''))
            except (ValueError, AttributeError):
                return 0.0
        return 0.0

    def calibrate(self, data: List[Dict], columns: Optional[List[str]] = None,
                  max_cell_len: int = 24) -> Dict:
        """ 校準：依數據特徵調聚合參數，輸入再降 15-20%。

        做法：
        1. 剔除全空/全同值的欄位（資訊含量 0，只佔 header）
        2. 資料量 > 50 行 → 收緊 Top-N（大樣本下統計已足夠代表）
        3. 建議長 cell 截斷長度（format_for_llm compact 用）
        """
        if not data:
            return {"columns": columns or [], "top_n": self.current_top_n,
                    "dropped_cols": [], "max_cell_len": max_cell_len}
        cols = columns if columns else list(data[0].keys())
        keep, dropped = [], []
        for c in cols:
            vals = [row.get(c) for row in data if isinstance(row, dict)]
            non_null = [v for v in vals if v is not None and v != ""]
            if not non_null:
                dropped.append(c)          # 全空
                continue
            uniq = {str(v) for v in non_null}
            if len(uniq) == 1:
                dropped.append(c)          # 全同值（資訊在統計即可）
                continue
            keep.append(c)
        top_n = self.current_top_n
        if len(data) > 50:
            top_n = min(top_n, 3)
        elif len(data) > 20:
            top_n = min(top_n, 5)
        return {"columns": keep, "top_n": top_n, "dropped_cols": dropped,
                "max_cell_len": max_cell_len, "total_rows": len(data)}

    def _find_numeric_field(self, row: Dict) -> Optional[str]:
        """找到第一個數值字段。"""
        for k, v in row.items():
            if self._is_number(v):
                return k
        return None

    def _compute_summary(self, data: List[Dict], cols: List[str]) -> Dict:
        """計算數值列的統計摘要。"""
        summary = {"total_rows": len(data)}
        for col in cols:
            values = [self._to_number(row.get(col)) for row in data if self._is_number(row.get(col))]
            if values:
                summary[f"{col}_min"] = min(values)
                summary[f"{col}_max"] = max(values)
                summary[f"{col}_avg"] = round(sum(values) / len(values), 2)
                summary[f"{col}_sum"] = round(sum(values), 2)
        return summary

    def _find_anomalies(self, data: List[Dict], cols: List[str]) -> List[Dict]:
        """異常檢測：IQR + 2σ + 中位數倍數 三引擎（，合併豆包版）。

        三方法取聯集，互補：
        - IQR：對極端值魯棒，但異常佔比 >25% 時 Q3 本身可能是異常（插值計算）
        - 2σ：正態分佈下有效，但小樣本+極端值會被拉高
        - 中位數倍數：值 > 中位數×10 或 < 中位數/10，簡單啟發式兜底（豆包版合併）
        防護：IQR=0（大量重複值）時退回 2σ，避免把正常值全判異常。"""
        anomalies = []
        num_col = self._find_numeric_field(data[0])
        if not num_col:
            return anomalies

        values = [self._to_number(row.get(num_col)) for row in data if self._is_number(row.get(num_col))]
        if len(values) < 3:
            return anomalies

        # 引擎 A：IQR（魯棒，主，插值計算）
        sv = sorted(values)
        n = len(sv)
        def _pct(p):
            k = (n - 1) * p
            f, c = int(k), int(k) + 1
            return sv[f] + (sv[c] - sv[f]) * (k - f)
        q1, q3 = _pct(0.25), _pct(0.75)
        iqr = q3 - q1
        lo_iqr, hi_iqr = q1 - 1.5 * iqr, q3 + 1.5 * iqr

        # 引擎 B：2σ（原邏輯，抓整體偏離）
        avg = sum(values) / len(values)
        variance = sum((v - avg) ** 2 for v in values) / len(values)
        std = variance ** 0.5
        lo_std, hi_std = avg - 2 * std, avg + 2 * std

        # 引擎 C：中位數倍數（豆包版合併，僅抓「異常高」兜底）
        # 實測修正：不抓「異常低」（中位數/10）——均勻分布的自然低端值
        # （如 sales 100-9999 的 171/347）會被誤判為異常；低端異常 IQR/2σ 已覆蓋。
        median = sv[n // 2] if n % 2 else (sv[n // 2 - 1] + sv[n // 2]) / 2
        med_high = median * 10 if median > 0 else float('inf')

        seen = set()
        for row in data:
            val = self._to_number(row.get(num_col))
            if not self._is_number(val):
                continue
            # IQR 判定（IQR=0 時退回 2σ，避免把正常值全判異常）
            if iqr > 0 and (val < lo_iqr or val > hi_iqr):
                pass
            elif val < lo_std or val > hi_std:
                pass
            elif val > med_high:
                pass
            else:
                continue
            key = tuple(str(row.get(c)) for c in cols)
            if key not in seen:
                seen.add(key)
                anomalies.append({k: row.get(k) for k in cols})

        return anomalies[:5]

    def _build_conclusions(self, data: List[Dict], cols: List[str], sort_by: Optional[str],
                           anomalies: List[Dict]) -> Dict:
        """ 確定性結論預提取：壓縮層直接算出 Top5 與異常（不依賴模型推導），
        解決『模型從壓縮表推導排名/異常→編造錯數值』的根因（實測 96% 過壓→品質 40）。"""
        concl = {}
        if not sort_by or sort_by not in data[0]:
            return concl
        key_col = cols[0] if cols else None
        if not key_col:
            return concl
        sorted_all = sorted(data, key=lambda x: self._to_number(x.get(sort_by, 0)), reverse=True)
        top5 = sorted_all[:5]
        concl["top5"] = [{key_col: r.get(key_col), sort_by: self._to_number(r.get(sort_by))}
                         for r in top5]
        if anomalies:
            concl["anomalies"] = [{key_col: a.get(key_col), sort_by: self._to_number(a.get(sort_by))}
                                  for a in anomalies[:5]]
        return concl

    def record_usage(self, queried_fields: Optional[List[str]] = None,
                     queried_rows: Optional[List[str]] = None,
                     llm_response: Optional[str] = None):
        """
        記錄 LLM 實際使用了哪些內容。
        可以顯式傳入，也可以從 LLM 響應中自動提取。

        參數：
            queried_fields: LLM 引用的字段名
            queried_rows: LLM 引用的行標識（如產品名）
            llm_response: LLM 的響應文本，用於自動提取引用
        """
        self.total_queries += 1

        if queried_fields:
            for f in queried_fields:
                self.field_usage[f] += 1

        if queried_rows:
            for r in queried_rows:
                self.row_usage[r] += 1

        # 從響應中自動提取
        if llm_response:
            self._extract_usage_from_response(llm_response)

    def _extract_usage_from_response(self, response: str):
        """從 LLM 響應中簡單提取引用的字段和行。"""
        # 這裡用簡單的關鍵詞匹配，生產環境可以用更複雜的方法
        # 提取數字（可能是引用了某行的數據）
        numbers = re.findall(r'\d+(?:\.\d+)?%?', response)
        for n in numbers:
            self.field_usage["numeric_values"] += 1

    def check_if_aggregated_was_needed(self, query: str, aggregated_data: Dict) -> bool:
        """
        檢查用戶/LLM 的查詢是否需要被聚合掉的內容。
        返回 True 表示需要，應該降低聚合粒度。
        v4.1 修復：改「實體精確比對」，取代原子串匹配（「產品1」誤匹配「產品10」）
        與長度猜測（len>10 即視為需要）兩處缺陷。
        """
        import re
        top_rows = aggregated_data.get("top_n", [])
        top_keys = set()
        for row in top_rows:
            for v in row.values():
                if isinstance(v, str):
                    top_keys.add(v.lower())
        q = query.lower()
        # 1) 字首+數字 型實體（如 產品1/訂單2026）：比對 query 中同前綴實體是否超出 Top-N
        prefixed = {}
        for k in top_keys:
            m = re.match(r'^(.+?)(\d+)$', k)
            if m:
                prefixed.setdefault(m.group(1), set()).add(m.group(2))
        for prefix, nums in prefixed.items():
            for ent in re.findall(prefix + r'\d+', q):
                if ent[len(prefix):] not in nums:
                    self.aggregated_but_queried += 1
                    return True
        # 2) 無數字後綴型：查詢若完整包含任一 top 值則在 Top-N 中；否則無法可靠判定，保守 False
        return False

    def adapt(self) -> Dict:
        """
        根據使用統計自適應調整聚合粒度。
        返回調整結果。
        """
        old_top_n = self.current_top_n
        reason = ""

        # 如果被聚合掉的內容被頻繁查詢，降低聚合粒度（增加 top_n）
        if self.aggregated_but_queried >= self.adapt_threshold:
            self.current_top_n = min(self.current_top_n + 2, self.max_top_n)
            reason = f"被聚合內容被查詢 {self.aggregated_but_queried} 次，增加 Top-N"
            self.aggregated_but_queried = 0  # 重置計數

        # 如果 Top-N 中的行很少被引用，提高聚合粒度（減少 top_n）
        elif self.total_queries >= self.adapt_threshold * 2:
            top_row_hits = sum(1 for r in self.row_usage if self.row_usage[r] > 0)
            if top_row_hits < self.current_top_n * 0.3:
                self.current_top_n = max(self.current_top_n - 1, self.min_top_n)
                reason = f"Top-N 中僅 {top_row_hits} 行被引用，減少 Top-N"

        result = {
            "old_top_n": old_top_n,
            "new_top_n": self.current_top_n,
            "changed": old_top_n != self.current_top_n,
            "reason": reason or "無需調整",
            "total_queries": self.total_queries,
            "aggregated_but_queried": self.aggregated_but_queried,
            "field_usage": dict(self.field_usage),
            "row_usage_top": sorted(self.row_usage.items(), key=lambda x: x[1], reverse=True)[:5],
        }

        if result["changed"]:
            self.adaptation_history.append(result)

        return result

    def format_for_llm(self, aggregated: Dict, compact: bool = False, max_cell_len: int = 24) -> str:
        """將聚合結果格式化為適合 LLM 閱讀的緊湊文本。
         新增 compact=True：去重複欄位名（header 一次）＋統計濃縮一行，
        輸入 token 比完整模式再降 ~30-40%（對標報告 P0-2：adaptive 曾比 v4.1 多 44%）。
         校準：compact 下長 cell 截斷（max_cell_len，預設 24 字元）＋剔除空/常數欄位，
        輸入再降 15-20%（配合 aggregate(calibrated=True) 使用）。
        """
        def _cell(v, trunc):
            s = str(v) if v is not None else ""
            if trunc and len(s) > trunc:
                return s[:trunc] + "…"
            return s

        if not compact:
            lines = []
            lines.append(f"[數據摘要] 共 {aggregated['total_rows']} 行，顯示 Top-{aggregated['current_top_n']}")

            if aggregated["summary"]:
                summary_parts = []
                for k, v in aggregated["summary"].items():
                    if k != "total_rows":
                        summary_parts.append(f"{k}={v}")
                lines.append("統計: " + ", ".join(summary_parts[:8]))

            lines.append(f"\n[Top-{aggregated['current_top_n']}]")
            for i, row in enumerate(aggregated["top_n"], 1):
                row_str = ", ".join(f"{k}={_cell(v, max_cell_len)}" for k, v in row.items())
                lines.append(f"  {i}. {row_str}")

            if aggregated["anomalies"]:
                lines.append(f"\n[異常值] {len(aggregated['anomalies'])} 條")
                for row in aggregated["anomalies"]:
                    row_str = ", ".join(f"{k}={_cell(v, max_cell_len)}" for k, v in row.items())
                    lines.append(f"  ! {row_str}")

            if aggregated["aggregated_rows"] > 0:
                lines.append(f"\n[註] 另有 {aggregated['aggregated_rows']} 行已聚合，如需詳細數據請查詢")

            return "\n".join(lines)

        # ===== compact 模式 =====
        top_n = aggregated.get("current_top_n", len(aggregated.get("top_n", [])))
        lines = [f"[數據] {aggregated['total_rows']}行 Top-{top_n}"]
        cols = aggregated.get("columns", [])

        #  確定性結論（置頂，模型直接轉述，避免從表推導編造）
        concl = aggregated.get("conclusions")
        if concl and concl.get("top5"):
            ckeys = list(concl["top5"][0].keys())
            kc, vc = ckeys[0], ckeys[1]
            top_str = " > ".join(f"{r[kc]}={r[vc]:.0f}" for r in concl["top5"])
            lines.append(f"[確定性 Top5 {vc}降序] {top_str}")
            if concl.get("anomalies"):
                anom_str = "; ".join(f"{r[kc]}={r[vc]:.0f}" for r in concl["anomalies"])
                lines.append(f"[確定性 異常] {anom_str}")

        # 統計濃縮一行（找 *_avg 配 *_min/*_max）
        summ = aggregated.get("summary", {})
        if summ:
            stat_parts = []
            for k, v in summ.items():
                if k.endswith("_avg"):
                    col = k[:-4]
                    mn, mx = summ.get(f"{col}_min"), summ.get(f"{col}_max")
                    stat_parts.append(f"{col}:μ{v}[{mn}~{mx}]")
            if stat_parts:
                lines.append(" ".join(stat_parts))

        if aggregated.get("top_n") and cols:
            tn = aggregated.get("current_top_n", 0)
            tl = aggregated.get("tail_len", 0)
            head_rows = aggregated["top_n"][:tn]
            tail_rows = aggregated["top_n"][tn:tn + tl] if tl else []
            # head 段：最高值（降序 Top-N，任務要的排名源，清晰標註避免模型讀錯方向）
            lines.append(f"[Top-{tn} 精確值·降序]")
            for i, row in enumerate(head_rows, 1):
                lines.append(f"{i}. " + " ".join(f"{c}={_cell(row.get(c, ''), max_cell_len)}" for c in cols))
            # tail 段：最低值（升序，極小異常候選，與 head 互補）
            if tail_rows:
                lines.append(f"[最低 {tl} 精確值·升序·異常候選]")
                for i, row in enumerate(tail_rows, 1):
                    lines.append(f"{i}. " + " ".join(f"{c}={_cell(row.get(c, ''), max_cell_len)}" for c in cols))

        if aggregated.get("anomalies"):
            for row in aggregated["anomalies"][:3]:
                present = [c for c in cols if c in row]
                if present:
                    lines.append("! " + "|".join(_cell(row.get(c, ""), max_cell_len) for c in present))

        if aggregated.get("aggregated_rows", 0) > 0:
            tr = aggregated.get("total_rows", 0)
            lines.append(f"+{aggregated['aggregated_rows']}行已聚合 [read_more:原始{tr}行精確資料可回溯]")

        return "\n".join(lines)


# ===== 演示 =====
if __name__ == "__main__":
    print("=== 自適應聚合演示 ===\n")

    # 模擬銷售數據
    data = [
        {"product": f"產品{i}", "sales": 1000 - i * 50, "growth": round(10 - i * 1.5, 1)}
        for i in range(1, 21)
    ]

    agg = AdaptiveAggregator(initial_top_n=5, adapt_threshold=2)

    # 第一次聚合
    result1 = agg.aggregate(data, sort_by="sales")
    print("--- 初始聚合（Top-5）---")
    print(agg.format_for_llm(result1))
    print()

    # 模擬 LLM 多次查詢被聚合掉的內容
    print("--- 模擬 LLM 查詢被聚合的內容 ---")
    for i in range(3):
        query = f"產品{10 + i}的銷售額是多少？"
        needed = agg.check_if_aggregated_was_needed(query, result1)
        print(f"  查詢: {query} → 需要被聚合內容: {needed}")
        if needed:
            agg.record_usage(queried_rows=[f"產品{10 + i}"])

    # 自適應調整
    print("\n--- 自適應調整 ---")
    adapt_result = agg.adapt()
    print(f"  舊 Top-N: {adapt_result['old_top_n']}")
    print(f"  新 Top-N: {adapt_result['new_top_n']}")
    print(f"  原因: {adapt_result['reason']}")

    # 重新聚合
    if adapt_result["changed"]:
        result2 = agg.aggregate(data, sort_by="sales")
        print(f"\n--- 調整後聚合（Top-{adapt_result['new_top_n']}）---")
        print(agg.format_for_llm(result2))

    print("\n說明：這是規則驅動的自適應，生產環境可結合 LLM 判斷查詢意圖。")
