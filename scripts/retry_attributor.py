# -*- coding: utf-8 -*-
"""
tokknife — 失敗重試 Token 歸因分析
分析每次重試的根本原因，統計有多少 token 是因為壓縮過度導致的重試浪費。
如果壓縮節省 < 重試增加，自動建議關閉該策略。

用法：
    from retry_attributor import RetryAttributor
    attr = RetryAttributor()
    attr.record_attempt(success=False, tokens_used=500, error_type="format_error", compressed=True)
    attr.record_attempt(success=True, tokens_used=800, compressed=False)
    report = attr.analyze()
"""
import json
import re
from typing import Dict, List, Any, Optional
from collections import defaultdict


# 錯誤類型分類
ERROR_CATEGORIES = {
    "format_error": {
        "name": "輸出格式錯誤",
        "description": "JSON 解析失敗、缺少必要字段、格式不符合要求",
        "likely_caused_by_compression": True,
    },
    "missing_info": {
        "name": "信息缺失",
        "description": "LLM 因為上下文被壓縮而缺少必要信息",
        "likely_caused_by_compression": True,
    },
    "tool_error": {
        "name": "工具調用錯誤",
        "description": "工具參數錯誤、工具調用失敗",
        "likely_caused_by_compression": True,
    },
    "hallucination": {
        "name": "幻覺",
        "description": "LLM 編造了不存在的信息",
        "likely_caused_by_compression": True,
    },
    "rate_limit": {
        "name": "速率限制",
        "description": "API 限流",
        "likely_caused_by_compression": False,
    },
    "network_error": {
        "name": "網絡錯誤",
        "description": "連接超時、網絡中斷",
        "likely_caused_by_compression": False,
    },
    "model_error": {
        "name": "模型錯誤",
        "description": "模型內部錯誤、500 錯誤",
        "likely_caused_by_compression": False,
    },
    "other": {
        "name": "其他",
        "description": "未知錯誤",
        "likely_caused_by_compression": False,
    },
}


class RetryAttributor:
    """失敗重試 Token 歸因分析器。"""

    def __init__(self):
        self.attempts: List[Dict] = []
        self.task_groups: Dict[str, List[Dict]] = defaultdict(list)

    def record_attempt(self, task_id: str = "default", success: bool = False,
                       tokens_used: int = 0, error_type: str = "other",
                       error_message: str = "", compressed: bool = False,
                       compression_strategies: Optional[List[str]] = None,
                       timestamp: Optional[str] = None):
        """
        記錄一次嘗試。

        參數：
            task_id: 任務標識，用於歸組同一任務的多次嘗試
            success: 是否成功
            tokens_used: 本次嘗試使用的 token 數
            error_type: 錯誤類型（見 ERROR_CATEGORIES）
            error_message: 錯誤詳情
            compressed: 本次是否使用了壓縮
            compression_strategies: 使用的壓縮策略列表
            timestamp: 時間戳（可選）
        """
        attempt = {
            "task_id": task_id,
            "success": success,
            "tokens_used": tokens_used,
            "error_type": error_type if error_type in ERROR_CATEGORIES else "other",
            "error_message": error_message[:200],
            "compressed": compressed,
            "compression_strategies": compression_strategies or [],
            "timestamp": timestamp,
        }
        self.attempts.append(attempt)
        self.task_groups[task_id].append(attempt)
        return attempt

    def classify_error(self, error_message: str) -> str:
        """
        從錯誤消息自動分類錯誤類型。
        簡單的關鍵詞匹配，生產環境可用更複雜的分類器。
        """
        msg = error_message.lower()

        if any(kw in msg for kw in ["json", "parse", "format", "schema", "validation"]):
            return "format_error"
        if any(kw in msg for kw in ["missing", "not found", "no such", "undefined", "null"]):
            return "missing_info"
        if any(kw in msg for kw in ["tool", "function", "argument", "parameter"]):
            return "tool_error"
        if any(kw in msg for kw in ["hallucinat", "fabricat", "made up"]):
            return "hallucination"
        if any(kw in msg for kw in ["rate limit", "429", "too many"]):
            return "rate_limit"
        if any(kw in msg for kw in ["timeout", "connection", "network", "502", "503", "504"]):
            return "network_error"
        if any(kw in msg for kw in ["500", "internal", "server error"]):
            return "model_error"
        return "other"

    def analyze(self) -> Dict[str, Any]:
        """
        分析重試數據，返回歸因報告。
        """
        if not self.attempts:
            return {"error": "無記錄"}

        total_attempts = len(self.attempts)
        successful = sum(1 for a in self.attempts if a["success"])
        failed = total_attempts - successful
        total_tokens = sum(a["tokens_used"] for a in self.attempts)

        # 按錯誤類型統計
        error_stats = defaultdict(lambda: {"count": 0, "tokens": 0, "compressed_count": 0})
        for a in self.attempts:
            if not a["success"]:
                cat = a["error_type"]
                error_stats[cat]["count"] += 1
                error_stats[cat]["tokens"] += a["tokens_used"]
                if a["compressed"]:
                    error_stats[cat]["compressed_count"] += 1

        # 壓縮相關的重試
        compression_related_retries = 0
        compression_related_tokens = 0
        for cat, stats in error_stats.items():
            if ERROR_CATEGORIES.get(cat, {}).get("likely_caused_by_compression", False):
                compression_related_retries += stats["compressed_count"]
                compression_related_tokens += stats["tokens"]

        # 按任務組分析重試次數
        retry_counts = {}
        for task_id, attempts in self.task_groups.items():
            failures = sum(1 for a in attempts if not a["success"])
            successes = sum(1 for a in attempts if a["success"])
            retry_counts[task_id] = {
                "total_attempts": len(attempts),
                "failures": failures,
                "successes": successes,
                "retries": max(0, failures),  # 失敗次數即重試次數
                "total_tokens": sum(a["tokens_used"] for a in attempts),
            }

        # 計算浪費的 token（失敗嘗試的 token）
        wasted_tokens = sum(a["tokens_used"] for a in self.attempts if not a["success"])
        wasted_percent = (wasted_tokens / total_tokens * 100) if total_tokens > 0 else 0

        # 壓縮策略效果分析
        strategy_impact = defaultdict(lambda: {"with_compression": [], "without_compression": []})
        for a in self.attempts:
            if a["compressed"] and a["compression_strategies"]:
                for s in a["compression_strategies"]:
                    strategy_impact[s]["with_compression"].append(a)
            elif not a["compressed"]:
                for s in strategy_impact:
                    strategy_impact[s]["without_compression"].append(a)

        strategy_recommendations = []
        for strategy, data in strategy_impact.items():
            with_c = data["with_compression"]
            without_c = data["without_compression"]
            if with_c and without_c:
                with_fail_rate = sum(1 for a in with_c if not a["success"]) / len(with_c)
                without_fail_rate = sum(1 for a in without_c if not a["success"]) / len(without_c)
                if with_fail_rate > without_fail_rate + 0.1:  # 失敗率高 10% 以上
                    strategy_recommendations.append({
                        "strategy": strategy,
                        "with_compression_fail_rate": round(with_fail_rate, 3),
                        "without_compression_fail_rate": round(without_fail_rate, 3),
                        "recommendation": "建議關閉或降低此策略的壓縮力度",
                    })

        return {
            "summary": {
                "total_attempts": total_attempts,
                "successful": successful,
                "failed": failed,
                "success_rate": round(successful / total_attempts, 3),
                "total_tokens": total_tokens,
                "wasted_tokens": wasted_tokens,
                "wasted_percent": f"{wasted_percent:.1f}%",
            },
            "error_breakdown": {
                cat: {
                    "name": ERROR_CATEGORIES[cat]["name"],
                    "count": stats["count"],
                    "tokens_wasted": stats["tokens"],
                    "compressed_count": stats["compressed_count"],
                    "likely_caused_by_compression": ERROR_CATEGORIES[cat]["likely_caused_by_compression"],
                }
                for cat, stats in error_stats.items()
            },
            "compression_impact": {
                "compression_related_retries": compression_related_retries,
                "compression_related_wasted_tokens": compression_related_tokens,
                "compression_related_percent": f"{(compression_related_tokens/wasted_tokens*100):.1f}%" if wasted_tokens > 0 else "0%",
            },
            "task_retry_counts": retry_counts,
            "strategy_recommendations": strategy_recommendations,
            "disclaimer": "歸因分析基於錯誤類型關鍵詞匹配，可能存在誤判，建議人工複核",
        }

    def print_report(self, report: Dict):
        """打印可讀的分析報告。"""
        print("=" * 60)
        print("失敗重試 Token 歸因分析報告")
        print("=" * 60)

        s = report["summary"]
        print(f"\n--- 總覽 ---")
        print(f"  總嘗試次數: {s['total_attempts']}")
        print(f"  成功: {s['successful']}")
        print(f"  失敗: {s['failed']}")
        print(f"  成功率: {s['success_rate']*100:.1f}%")
        print(f"  總 Token: {s['total_tokens']}")
        print(f"  浪費 Token（失敗嘗試）: {s['wasted_tokens']}（{s['wasted_percent']}）")

        print(f"\n--- 錯誤分類 ---")
        for cat, data in report["error_breakdown"].items():
            compression_flag = " ⚠️ 可能與壓縮有關" if data["likely_caused_by_compression"] else ""
            print(f"  {data['name']}: {data['count']} 次，浪費 {data['tokens_wasted']} token{compression_flag}")

        ci = report["compression_impact"]
        print(f"\n--- 壓縮影響 ---")
        print(f"  壓縮相關重試: {ci['compression_related_retries']} 次")
        print(f"  壓縮相關浪費 Token: {ci['compression_related_wasted_tokens']}（{ci['compression_related_percent']}）")

        if report["strategy_recommendations"]:
            print(f"\n--- 策略建議 ---")
            for rec in report["strategy_recommendations"]:
                print(f"  ⚠️  {rec['strategy']}: 壓縮時失敗率 {rec['with_compression_fail_rate']*100:.1f}%，"
                      f"無壓縮時 {rec['without_compression_fail_rate']*100:.1f}%")
                print(f"     {rec['recommendation']}")

        print(f"\n⚠️  {report['disclaimer']}")
        print("=" * 60)


# ===== 演示 =====
if __name__ == "__main__":
    print("=== 失敗重試歸因分析演示 ===\n")

    attr = RetryAttributor()

    # 模擬一個任務的多次嘗試
    # 任務1：使用了壓縮，導致格式錯誤
    attr.record_attempt(task_id="task_1", success=False, tokens_used=500,
                        error_type="format_error", error_message="JSON parse error: unexpected token",
                        compressed=True, compression_strategies=["output_json_mode", "tool_output_aggregation"])
    attr.record_attempt(task_id="task_1", success=False, tokens_used=480,
                        error_type="missing_info", error_message="missing required field: product_id",
                        compressed=True, compression_strategies=["tool_output_aggregation"])
    attr.record_attempt(task_id="task_1", success=True, tokens_used=800, compressed=False)

    # 任務2：網絡錯誤（與壓縮無關）
    attr.record_attempt(task_id="task_2", success=False, tokens_used=300,
                        error_type="network_error", error_message="Connection timeout",
                        compressed=False)
    attr.record_attempt(task_id="task_2", success=True, tokens_used=600, compressed=False)

    # 任務3：壓縮正常工作
    attr.record_attempt(task_id="task_3", success=True, tokens_used=400,
                        compressed=True, compression_strategies=["history_compression"])

    report = attr.analyze()
    attr.print_report(report)

    print("\n--- 自動錯誤分類演示 ---")
    test_errors = [
        "Failed to parse JSON response",
        "Connection timed out after 30s",
        "Rate limit exceeded, please retry",
        "Tool call missing required parameter",
    ]
    for err in test_errors:
        print(f"  '{err[:40]}...' → {attr.classify_error(err)}")
