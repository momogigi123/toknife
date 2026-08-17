# -*- coding: utf-8 -*-
"""
tokknife — 質量-成本帕累托優化器
在給定質量閾值下，找到 token 成本最小的優化策略組合。
不是盲目壓縮，而是在可接受的質量損失下最小化成本。

用法：
    from pareto_optimizer import ParetoOptimizer
    opt = ParetoOptimizer()
    result = opt.optimize(quality_threshold=0.9, task_type="data_analysis")
    # result = {"strategies": [...], "expected_cost": 0.6, "expected_quality": 0.92, "pareto_front": [...]}
"""
import json
import itertools
from typing import Dict, List, Any, Optional, Tuple


# 策略的成本和質量影響（經驗值，非精確）
# cost_saving: 節省的成本比例（0-1）
# quality_impact: 質量影響比例（0=無影響，1=完全毀掉）
STRATEGY_PROFILES = {
    "english_system_prompt": {"cost_saving": 0.08, "quality_impact": 0.0, "name": "英文 System Prompt"},
    "dynamic_max_tokens": {"cost_saving": 0.12, "quality_impact": 0.02, "name": "動態 max_tokens"},
    "output_json_mode": {"cost_saving": 0.15, "quality_impact": 0.03, "name": "JSON Mode"},
    "tokenizer_optimization": {"cost_saving": 0.30, "quality_impact": 0.0, "name": "Tokenizer 優化"},
    "tool_output_aggregation": {"cost_saving": 0.40, "quality_impact": 0.08, "name": "工具回傳聚合"},
    "history_compression": {"cost_saving": 0.25, "quality_impact": 0.06, "name": "歷史壓縮"},
    "rag_rerank": {"cost_saving": 0.20, "quality_impact": 0.04, "name": "RAG 重排序"},
    "lazy_tool_loading": {"cost_saving": 0.15, "quality_impact": 0.02, "name": "工具懶載入"},
    "semantic_cache": {"cost_saving": 0.50, "quality_impact": 0.10, "name": "語義快取"},
    "plan_execute_separation": {"cost_saving": 0.35, "quality_impact": 0.07, "name": "規劃執行分離"},
    "code_context_extraction": {"cost_saving": 0.45, "quality_impact": 0.09, "name": "代碼上下文提取"},
    "aggressive_compression": {"cost_saving": 0.60, "quality_impact": 0.20, "name": "極限壓縮（不推薦）"},
}

#  校準版：用 benchmark_llm_results.json（15 任務 × 豆包 seed-2.0-pro 實跑）回填
# quality_impact 從實測品質分數推得：impact = 1 - quality_score/100（品質 100 = 無損失）
# 數據點（n=3/類）：
#   tool_output  省 94.6%  品質 50.0 → impact 0.50（經驗值 0.08 嚴重低估！）
#   conversation 省 73.0%  品質 80.0 → impact 0.20
#   code         省 86.9%  品質  8.3 → impact 0.92（經驗值 0.09 嚴重低估！簽名級壓縮幾乎毀掉 code 品質）
#   system_prompt省 32.8%  品質 83.3 → impact 0.17
#   incremental  省 72.8%  品質 58.3 → impact 0.42
# 未校準策略（無對應實測）保留經驗值，並在 result 標註哪些已校準。
CALIBRATED_PROFILES = {
    "tool_output_aggregation": {"cost_saving": 0.95, "quality_impact": 0.50, "name": "工具回傳聚合",
                                "calibrated_from": "tool_output (n=3, 品質50/100)"},
    "history_compression": {"cost_saving": 0.73, "quality_impact": 0.20, "name": "歷史壓縮",
                            "calibrated_from": "conversation (n=3, 品質80/100)"},
    "code_context_extraction": {"cost_saving": 0.87, "quality_impact": 0.92, "name": "代碼上下文提取",
                                "calibrated_from": "code (n=3, 品質8.3/100 ⚠️ 簽名級幾乎毀品質)"},
    "english_system_prompt": {"cost_saving": 0.33, "quality_impact": 0.17, "name": "英文 System Prompt",
                              "calibrated_from": "system_prompt (n=3, 品質83.3/100)"},
    # incremental（72.8% 省 / 品質58.3）與 conversation（73.0% / 80）皆屬「長上下文壓縮」，
    # 取品質較差的 incremental 保守估計 → impact 0.42
    "history_compression": {"cost_saving": 0.73, "quality_impact": 0.42, "name": "歷史/增量壓縮",
                            "calibrated_from": "incremental+conversation (n=6, 品質58.3~80/100)"},
}

# 不同任務類型的策略適用性
TASK_APPLICABILITY = {
    "data_analysis": ["english_system_prompt", "dynamic_max_tokens", "output_json_mode", "tokenizer_optimization",
                      "tool_output_aggregation", "history_compression", "rag_rerank", "semantic_cache", "plan_execute_separation"],
    "code_debug": ["english_system_prompt", "dynamic_max_tokens", "tokenizer_optimization", "lazy_tool_loading"],
    "code_generation": ["english_system_prompt", "dynamic_max_tokens", "tokenizer_optimization", "code_context_extraction", "lazy_tool_loading"],
    "creative_writing": ["english_system_prompt", "tokenizer_optimization"],
    "simple_qa": ["english_system_prompt", "dynamic_max_tokens", "output_json_mode", "tokenizer_optimization", "semantic_cache"],
    "agent_multi_step": ["english_system_prompt", "dynamic_max_tokens", "tokenizer_optimization", "tool_output_aggregation",
                         "history_compression", "lazy_tool_loading", "plan_execute_separation", "semantic_cache"],
    "long_conversation": ["english_system_prompt", "dynamic_max_tokens", "tokenizer_optimization", "history_compression"],
    "summary_extraction": ["english_system_prompt", "dynamic_max_tokens", "output_json_mode", "tokenizer_optimization",
                           "tool_output_aggregation", "rag_rerank", "semantic_cache"],
}


class ParetoOptimizer:
    """質量-成本帕累托優化器。"""

    def __init__(self, base_cost: float = 1.0, base_quality: float = 1.0, calibrated: bool = True):
        """
        參數：
            base_cost: 基準成本（預設 1.0，即 100%）
            base_quality: 基準質量（預設 1.0，即 100%）
            calibrated: 用 benchmark_llm 實測數據覆寫經驗值（ 預設開啟）
        """
        self.base_cost = base_cost
        self.base_quality = base_quality
        self.strategies = json.loads(json.dumps(STRATEGY_PROFILES))
        self.calibrated = calibrated
        self.calibrated_keys = []
        if calibrated:
            for sid, prof in CALIBRATED_PROFILES.items():
                if sid in self.strategies:
                    self.strategies[sid] = {**self.strategies[sid], **prof}
                    self.calibrated_keys.append(sid)

    def _evaluate_combination(self, strategy_ids: List[str]) -> Tuple[float, float]:
        """
        評估一個策略組合的成本和質量。
        成本節省不是線性疊加，用 1 - product(1 - saving) 模擬邊際遞減。
        質量影響也不是線性疊加，用 1 - product(1 - impact) 模擬。
        """
        cost_factor = 1.0
        quality_factor = 1.0

        for sid in strategy_ids:
            if sid in self.strategies:
                profile = self.strategies[sid]
                cost_factor *= (1 - profile["cost_saving"])
                quality_factor *= (1 - profile["quality_impact"])

        final_cost = self.base_cost * cost_factor
        final_quality = self.base_quality * quality_factor
        return final_cost, final_quality

    def optimize(self, quality_threshold: float = 0.9, task_type: str = "data_analysis",
                 max_strategies: int = 6) -> Dict[str, Any]:
        """
        在質量閾值下找到成本最小的策略組合。

        參數：
            quality_threshold: 可接受的最低質量（0-1），預設 0.9（90%）
            task_type: 任務類型，用於過濾不適用的策略
            max_strategies: 最多考慮的策略數量（避免組合爆炸）

        返回：
            {
                "optimal_strategies": [...],
                "expected_cost": 0.55,
                "expected_quality": 0.91,
                "cost_saving": "45%",
                "pareto_front": [...],
                "all_valid_combinations": int,
            }
        """
        applicable = TASK_APPLICABILITY.get(task_type, list(self.strategies.keys()))
        applicable = [s for s in applicable if s in self.strategies]

        # 限制策略數量，取 cost_saving 最高的前 max_strategies 個
        applicable.sort(key=lambda s: self.strategies[s]["cost_saving"], reverse=True)
        applicable = applicable[:max_strategies]

        pareto_front = []
        valid_combinations = []
        best_cost = float('inf')
        best_combination = []
        best_quality = 1.0

        # 遍歷所有非空子集
        for r in range(1, len(applicable) + 1):
            for combo in itertools.combinations(applicable, r):
                cost, quality = self._evaluate_combination(list(combo))

                if quality >= quality_threshold:
                    valid_combinations.append({
                        "strategies": list(combo),
                        "cost": round(cost, 4),
                        "quality": round(quality, 4),
                    })

                    if cost < best_cost:
                        best_cost = cost
                        best_combination = list(combo)
                        best_quality = quality

        # 計算帕累托前沿（在所有組合中，沒有其他組合同時成本更低且質量更高）
        all_combos = []
        for r in range(0, len(applicable) + 1):
            for combo in itertools.combinations(applicable, r):
                cost, quality = self._evaluate_combination(list(combo))
                all_combos.append({"strategies": list(combo), "cost": cost, "quality": quality})

        for combo in all_combos:
            dominated = False
            for other in all_combos:
                if other["cost"] <= combo["cost"] and other["quality"] >= combo["quality"]:
                    if other != combo and (other["cost"] < combo["cost"] or other["quality"] > combo["quality"]):
                        dominated = True
                        break
            if not dominated:
                pareto_front.append({
                    "strategies": combo["strategies"],
                    "cost": round(combo["cost"], 4),
                    "quality": round(combo["quality"], 4),
                })

        pareto_front.sort(key=lambda x: x["cost"])

        cost_saving_pct = (1 - best_cost / self.base_cost) * 100 if best_cost < float('inf') else 0

        return {
            "task_type": task_type,
            "quality_threshold": quality_threshold,
            "calibrated": self.calibrated,
            "calibrated_strategies": self.calibrated_keys,
            "optimal_strategies": [
                {
                    "id": sid,
                    "name": self.strategies[sid]["name"],
                    "cost_saving": f"{self.strategies[sid]['cost_saving']*100:.0f}%",
                    "quality_impact": f"{self.strategies[sid]['quality_impact']*100:.0f}%",
                }
                for sid in best_combination
            ],
            "expected_cost": round(best_cost, 4) if best_cost < float('inf') else None,
            "expected_quality": round(best_quality, 4),
            "cost_saving": f"{cost_saving_pct:.1f}%",
            "pareto_front": pareto_front[:10],  # 最多返回 10 個前沿點
            "valid_combinations_count": len(valid_combinations),
            "total_combinations_evaluated": len(all_combos),
            "disclaimer": ("品質影響校準自 benchmark_llm 15 任務實跑（n=3/類）；未校準策略為經驗模擬值，"
                           "實際效果需用 LLM-as-judge 驗證"),
        }

    def compare_thresholds(self, task_type: str = "data_analysis",
                           thresholds: List[float] = None) -> List[Dict]:
        """對比不同質量閾值下的最優解。"""
        if thresholds is None:
            thresholds = [1.0, 0.95, 0.90, 0.85, 0.80]

        results = []
        for t in thresholds:
            opt = self.optimize(quality_threshold=t, task_type=task_type)
            results.append({
                "quality_threshold": t,
                "strategy_count": len(opt["optimal_strategies"]),
                "expected_cost": opt["expected_cost"],
                "expected_quality": opt["expected_quality"],
                "cost_saving": opt["cost_saving"],
                "strategies": [s["name"] for s in opt["optimal_strategies"]],
            })
        return results

    def print_optimization(self, result: Dict):
        """打印可讀的優化結果。"""
        print("=" * 60)
        print(f"帕累托優化結果 — {result['task_type']}")
        print("=" * 60)
        print(f"質量閾值: {result['quality_threshold']}")
        print(f"評估組合數: {result['total_combinations_evaluated']}")
        print(f"有效組合數: {result['valid_combinations_count']}")
        print()

        if result["optimal_strategies"]:
            print(f"--- 最優策略組合（{len(result['optimal_strategies'])} 個）---")
            for s in result["optimal_strategies"]:
                print(f"  ✓ {s['name']}（省 {s['cost_saving']}，質量影響 {s['quality_impact']}）")
            print()
            print(f"預期成本: {result['expected_cost']}（基準 {self.base_cost}）")
            print(f"預期質量: {result['expected_quality']}（基準 {self.base_quality}）")
            print(f"成本節省: {result['cost_saving']}")
        else:
            print("  無滿足質量閾值的組合，請降低閾值")

        print(f"\n--- 帕累托前沿（前 {len(result['pareto_front'])} 點）---")
        for i, point in enumerate(result["pareto_front"]):
            names = [self.strategies[s]["name"] for s in point["strategies"]] if point["strategies"] else ["基準（無優化）"]
            print(f"  {i+1}. 成本={point['cost']:.3f}, 質量={point['quality']:.3f} → {', '.join(names)}")

        print(f"\n⚠️  {result['disclaimer']}")
        print("=" * 60)


# ===== 演示 =====
if __name__ == "__main__":
    opt = ParetoOptimizer()

    print("=== 數據分析任務，質量閾值 90% ===\n")
    result = opt.optimize(quality_threshold=0.9, task_type="data_analysis")
    opt.print_optimization(result)

    print("\n=== 不同質量閾值對比（數據分析）===\n")
    comparisons = opt.compare_thresholds(task_type="data_analysis")
    print(f"{'閾值':<8} {'策略數':<6} {'成本':<8} {'質量':<8} {'節省':<8} 策略")
    print("-" * 70)
    for c in comparisons:
        print(f"{c['quality_threshold']:<8} {c['strategy_count']:<6} {str(c['expected_cost']):<8} "
              f"{c['expected_quality']:<8} {c['cost_saving']:<8} {', '.join(c['strategies'][:3])}")

    print("\n=== 代碼調試任務（高質量要求 95%）===\n")
    result_debug = opt.optimize(quality_threshold=0.95, task_type="code_debug")
    opt.print_optimization(result_debug)
