# -*- coding: utf-8 -*-
"""
Token Saver v3.1 — 多輪對話 Token 預算分配
任務開始時預估總 token 預算，按步驟分配，超預算時自動觸發壓縮建議。
類似操作系統的內存管理，避免前面步驟用太多導致後面上下文不足。

用法：
    from token_budget import TokenBudget
    budget = TokenBudget(total_budget=10000, task_type="agent_multi_step")
    budget.start_phase("planning")
    budget.record_usage(500)
    budget.start_phase("execution")
    budget.record_usage(3000)
    status = budget.check_status()  # 檢查是否超預算
"""
import json
from typing import Dict, List, Any, Optional


# 不同任務類型的預算分配比例
TASK_BUDGET_PROFILES = {
    "agent_multi_step": {
        "name": "Agent 多步任務",
        "phases": {
            "planning": 0.10,      # 規劃階段 10%
            "execution": 0.70,     # 執行階段 70%
            "summarization": 0.20, # 總結階段 20%
        },
    },
    "data_analysis": {
        "name": "數據分析",
        "phases": {
            "data_loading": 0.15,
            "exploration": 0.35,
            "analysis": 0.35,
            "report": 0.15,
        },
    },
    "code_debug": {
        "name": "代碼調試",
        "phases": {
            "understanding": 0.20,
            "reproduction": 0.25,
            "fixing": 0.40,
            "verification": 0.15,
        },
    },
    "long_conversation": {
        "name": "長對話",
        "phases": {
            "early": 0.30,
            "middle": 0.40,
            "late": 0.30,
        },
    },
    "default": {
        "name": "默認",
        "phases": {
            "input": 0.40,
            "processing": 0.40,
            "output": 0.20,
        },
    },
}


class TokenBudget:
    """多輪對話 Token 預算管理器。"""

    def __init__(self, total_budget: int = 10000, task_type: str = "default",
                 warning_threshold: float = 0.8, critical_threshold: float = 0.95):
        """
        參數：
            total_budget: 總 token 預算
            task_type: 任務類型，用於確定階段分配
            warning_threshold: 警告閾值（使用比例），預設 80%
            critical_threshold: 危險閾值，預設 95%
        """
        self.total_budget = total_budget
        self.task_type = task_type if task_type in TASK_BUDGET_PROFILES else "default"
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold

        profile = TASK_BUDGET_PROFILES[self.task_type]
        self.phase_budgets = {
            phase: int(total_budget * ratio)
            for phase, ratio in profile["phases"].items()
        }

        self.current_phase: Optional[str] = None
        self.phase_usage: Dict[str, int] = {phase: 0 for phase in self.phase_budgets}
        self.total_used = 0
        self.history: List[Dict] = []
        self.compression_suggested = False

    def start_phase(self, phase: str) -> Dict:
        """
        開始一個新階段。
        返回該階段的預算信息。
        """
        if phase not in self.phase_budgets:
            # 動態添加階段，平均分配剩餘預算
            remaining = self.total_budget - self.total_used
            self.phase_budgets[phase] = max(remaining, 100)
            self.phase_usage[phase] = 0

        self.current_phase = phase
        info = {
            "phase": phase,
            "budget": self.phase_budgets[phase],
            "remaining_total": self.total_budget - self.total_used,
            "remaining_phase": self.phase_budgets[phase] - self.phase_usage[phase],
        }
        return info

    def record_usage(self, tokens: int, phase: Optional[str] = None) -> Dict:
        """
        記錄 token 使用量。

        參數：
            tokens: 使用的 token 數
            phase: 階段（可選，預設當前階段）

        返回：
            使用狀態
        """
        target_phase = phase or self.current_phase
        if target_phase is None:
            target_phase = "default"
            if target_phase not in self.phase_budgets:
                self.phase_budgets[target_phase] = self.total_budget
                self.phase_usage[target_phase] = 0

        self.phase_usage[target_phase] += tokens
        self.total_used += tokens

        record = {
            "phase": target_phase,
            "tokens_used": tokens,
            "total_used": self.total_used,
            "phase_used": self.phase_usage[target_phase],
            "timestamp": None,
        }
        self.history.append(record)

        return self.check_status()

    def check_status(self) -> Dict:
        """
        檢查當前預算使用狀態。
        返回狀態和建議。
        """
        usage_ratio = self.total_used / self.total_budget if self.total_budget > 0 else 0

        status = "normal"
        if usage_ratio >= self.critical_threshold:
            status = "critical"
        elif usage_ratio >= self.warning_threshold:
            status = "warning"

        # 檢查當前階段是否超預算
        phase_over_budget = False
        if self.current_phase:
            phase_used = self.phase_usage[self.current_phase]
            phase_budget = self.phase_budgets[self.current_phase]
            if phase_budget > 0 and phase_used > phase_budget:
                phase_over_budget = True

        # 生成建議
        suggestions = []
        if status == "critical":
            suggestions.append("立即觸發上下文壓縮（歷史壓縮 + 工具回傳聚合）")
            suggestions.append("考慮提前進入總結階段")
            self.compression_suggested = True
        elif status == "warning":
            suggestions.append("準備觸發上下文壓縮")
            suggestions.append("減少工具回傳的詳細程度")
        elif phase_over_budget:
            suggestions.append(f"當前階段 '{self.current_phase}' 已超預算，考慮加快進度")

        # 剩餘階段的預算調整建議
        remaining_phases = [p for p in self.phase_budgets if p != self.current_phase]
        if remaining_phases and self.current_phase:
            remaining_budget = self.total_budget - self.total_used
            per_phase = remaining_budget / len(remaining_phases)
            if per_phase < 500:
                suggestions.append(f"剩餘 {len(remaining_phases)} 個階段，平均每階段僅 {int(per_phase)} token，強烈建議壓縮")

        return {
            "status": status,
            "total_budget": self.total_budget,
            "total_used": self.total_used,
            "usage_ratio": round(usage_ratio, 3),
            "remaining": self.total_budget - self.total_used,
            "current_phase": self.current_phase,
            "phase_used": self.phase_usage.get(self.current_phase, 0) if self.current_phase else 0,
            "phase_budget": self.phase_budgets.get(self.current_phase, 0) if self.current_phase else 0,
            "phase_over_budget": phase_over_budget,
            "suggestions": suggestions,
            "phase_breakdown": self._get_phase_breakdown(),
        }

    def _get_phase_breakdown(self) -> List[Dict]:
        """獲取各階段的預算使用情況。"""
        breakdown = []
        for phase, budget in self.phase_budgets.items():
            used = self.phase_usage.get(phase, 0)
            ratio = used / budget if budget > 0 else 0
            breakdown.append({
                "phase": phase,
                "budget": budget,
                "used": used,
                "remaining": budget - used,
                "usage_ratio": round(ratio, 3),
                "status": "over" if ratio > 1 else ("warning" if ratio > 0.8 else "normal"),
            })
        return breakdown

    def reallocate_budget(self, phase: str, new_budget: int) -> Dict:
        """
        手動重新分配某階段的預算。
        超出部分從後續階段扣除。
        """
        old_budget = self.phase_budgets.get(phase, 0)
        diff = new_budget - old_budget

        if diff > 0:
            # 增加預算，從其他階段扣除
            other_phases = [p for p in self.phase_budgets if p != phase]
            per_phase_cut = diff // len(other_phases) if other_phases else 0
            for p in other_phases:
                self.phase_budgets[p] = max(self.phase_budgets[p] - per_phase_cut, 100)

        self.phase_budgets[phase] = new_budget
        return {
            "phase": phase,
            "old_budget": old_budget,
            "new_budget": new_budget,
            "phase_budgets": self.phase_budgets.copy(),
        }

    def print_status(self, status: Dict):
        """打印可讀的預算狀態。"""
        print("=" * 50)
        print(f"Token 預算狀態 — {TASK_BUDGET_PROFILES.get(self.task_type, {}).get('name', self.task_type)}")
        print("=" * 50)
        print(f"總預算: {status['total_budget']}")
        print(f"已使用: {status['total_used']}（{status['usage_ratio']*100:.1f}%）")
        print(f"剩餘: {status['remaining']}")
        print(f"狀態: {status['status'].upper()}")
        if status["current_phase"]:
            print(f"當前階段: {status['current_phase']}（{status['phase_used']}/{status['phase_budget']}）")

        print(f"\n--- 各階段 ---")
        for p in status["phase_breakdown"]:
            bar = "█" * int(p["usage_ratio"] * 20) + "░" * (20 - int(p["usage_ratio"] * 20))
            status_icon = "⚠️" if p["status"] == "warning" else ("❌" if p["status"] == "over" else "✓")
            print(f"  {status_icon} {p['phase']:<15} {bar} {p['used']}/{p['budget']} ({p['usage_ratio']*100:.0f}%)")

        if status["suggestions"]:
            print(f"\n--- 建議 ---")
            for s in status["suggestions"]:
                print(f"  • {s}")
        print("=" * 50)


# ===== 演示 =====
if __name__ == "__main__":
    print("=== Token 預算分配演示 ===\n")

    budget = TokenBudget(total_budget=10000, task_type="agent_multi_step")

    # 規劃階段
    print("--- 開始規劃階段 ---")
    info = budget.start_phase("planning")
    print(f"  階段預算: {info['budget']}")
    status = budget.record_usage(800)
    budget.print_status(status)

    # 執行階段
    print("\n--- 開始執行階段（大量使用）---")
    budget.start_phase("execution")
    status = budget.record_usage(5000)
    budget.print_status(status)

    print("\n--- 繼續執行（接近危險線）---")
    status = budget.record_usage(3500)
    budget.print_status(status)

    # 總結階段
    print("\n--- 開始總結階段 ---")
    budget.start_phase("summarization")
    status = budget.record_usage(500)
    budget.print_status(status)

    print("\n說明：預算分配為經驗值，實際使用中應根據任務進度動態調整。")
