# -*- coding: utf-8 -*-
"""
toknife — 規劃-執行分離最小可運行示例
展示 Planner（便宜模型）+ Executor（強模型）的架構，
相比傳統 ReAct 模式可省 40-60% token。

核心思想：
1. Planner 只需看任務描述 + 工具列表，生成 JSON 格式的執行計劃
2. Executor 每步只接收當前步驟的上下文，不需要看完整歷史和所有工具
3. 確定性步驟（數據處理、格式轉換）直接用代碼，不調用 LLM
"""
import json
from typing import List, Dict, Any, Optional, Callable


# ===== 模擬 LLM 調用（生產環境替換為真實 API）=====

def mock_llm_call(model: str, messages: List[Dict], max_tokens: int = 500) -> str:
 """模擬 LLM 調用，返回固定格式的結果。實際使用時替換為 OpenAI/Anthropic API。"""
 # 這裡用規則模擬，實際環境調用真實 API
 if model == "planner":
 # Planner 生成執行計劃
 return json.dumps({
 "plan": [
 {"step": 1, "action": "search", "args": {"query": "Q2銷售數據"}, "description": "搜索Q2銷售數據"},
 {"step": 2, "action": "analyze", "args": {"data_ref": "step1"}, "description": "分析下滑產品線"},
 {"step": 3, "action": "generate", "args": {"topic": "改進建議"}, "description": "生成改進建議"},
 ]
 }, ensure_ascii=False)
 elif model == "executor":
 # Executor 執行單步
 return json.dumps({"result": "步驟執行完成", "output": "..."}, ensure_ascii=False)
 return "{}"


# ===== 工具定義（精簡版，只給 Planner 看名稱和描述）=====

TOOLS_FOR_PLANNER = [
 {"name": "search", "description": "搜索數據庫，返回相關記錄"},
 {"name": "analyze", "description": "分析數據，返回統計摘要和異常"},
 {"name": "generate", "description": "生成文本報告或建議"},
 {"name": "write_file", "description": "將結果寫入文件"},
]

# ===== Planner（便宜模型，如 Qwen3-8B / DeepSeek-Flash / GPT-4o-mini）=====

class Planner:
 """規劃器：用便宜模型生成執行計劃，單次調用，token 消耗少。"""

 def __init__(self, model: str = "gpt-4o-mini"):
 self.model = model

 def plan(self, task: str, tools: List[Dict]) -> List[Dict]:
 """
 生成執行計劃。

 輸入：任務描述 + 工具列表（精簡版）
 輸出：步驟列表 [{"step": 1, "action": "...", "args": {...}, "description": "..."}]
 """
 system_prompt = """你是一個任務規劃器。將用戶任務分解為可執行的步驟。
輸出 JSON 格式：{"plan": [{"step": 1, "action": "工具名", "args": {...}, "description": "一句話描述"}]}
只返回 JSON，不要解釋。"""

 user_prompt = f"任務：{task}\n\n可用工具：\n{json.dumps(tools, ensure_ascii=False)}"

 messages = [
 {"role": "system", "content": system_prompt},
 {"role": "user", "content": user_prompt},
 ]

 response = mock_llm_call("planner", messages, max_tokens=300)
 plan_data = json.loads(response)
 return plan_data.get("plan", [])


# ===== Executor（強模型，如 GPT-4o / Claude Sonnet）=====

class Executor:
 """執行器：用強模型執行單個步驟，每步只接收當前上下文。"""

 def __init__(self, model: str = "gpt-4o"):
 self.model = model
 self.results: Dict[int, Any] = {} # 步驟結果存儲

 def execute_step(self, step: Dict, context: Optional[str] = None) -> Any:
 """
 執行單個步驟。

 關鍵：每步只發送當前步驟的信息 + 必要的上下文摘要，
 不發送完整歷史和所有工具定義。
 """
 step_num = step["step"]
 action = step["action"]
 args = step.get("args", {})
 description = step.get("description", "")

 # 構建精簡的上下文（只包含前一步的結果摘要，不是完整歷史）
 context_summary = ""
 if context:
 context_summary = f"前一步結果摘要：{context[:200]}\n\n"

 system_prompt = f"""你是一個執行器。執行當前任務步驟。
當前步驟：{step_num}. {description}
工具：{action}
參數：{json.dumps(args, ensure_ascii=False)}
{context_summary}
輸出 JSON 格式的執行結果。"""

 messages = [
 {"role": "system", "content": system_prompt},
 {"role": "user", "content": f"執行步驟 {step_num}"},
 ]

 response = mock_llm_call("executor", messages, max_tokens=500)
 result = json.loads(response)
 self.results[step_num] = result
 return result


# ===== 規劃-執行分離 Agent =====

class PlanExecuteAgent:
 """
 規劃-執行分離 Agent。

 相比傳統 ReAct：
 - Planner 只調用 1 次（便宜模型）
 - Executor 每步上下文精簡（強模型但輸入少）
 - 總 token 消耗降 40-60%
 """

 def __init__(self, planner_model: str = "gpt-4o-mini", executor_model: str = "gpt-4o"):
 self.planner = Planner(model=planner_model)
 self.executor = Executor(model=executor_model)

 def run(self, task: str) -> Dict[str, Any]:
 """執行完整任務。"""
 print(f"[任務] {task}\n")

 # 階段 1：規劃（便宜模型，1 次調用）
 print("[階段1] Planner 生成執行計劃...")
 plan = self.planner.plan(task, TOOLS_FOR_PLANNER)
 for step in plan:
 print(f" 步驟 {step['step']}: {step['description']} ({step['action']})")
 print

 # 階段 2：執行（強模型，每步獨立調用）
 print("[階段2] Executor 逐步執行...")
 last_result_summary = None
 for step in plan:
 print(f" 執行步驟 {step['step']}: {step['description']}...")
 result = self.executor.execute_step(step, context=last_result_summary)
 # 只把結果摘要傳給下一步，不是完整結果
 last_result_summary = str(result.get("output", ""))[:200]
 print(f" 完成: {result.get('result', '未知')}")
 print

 return {
 "plan": plan,
 "results": self.executor.results,
 "total_steps": len(plan),
 }


# ===== 對比：傳統 ReAct 模式 =====

class ReActAgent:
 """傳統 ReAct 模式：每輪都發送完整歷史 + 所有工具定義。"""

 def __init__(self, model: str = "gpt-4o"):
 self.model = model
 self.history: List[Dict] = []

 def run(self, task: str, max_steps: int = 3) -> Dict[str, Any]:
 """傳統 ReAct：每輪重複發送完整上下文。"""
 print(f"[ReAct 模式] {task}\n")

 system_prompt = f"""你是一個 ReAct Agent。可用工具：
{json.dumps(TOOLS_FOR_PLANNER, ensure_ascii=False)}
每次思考後選擇一個工具執行，觀察結果，繼續思考直到任務完成。"""

 self.history.append({"role": "system", "content": system_prompt})
 self.history.append({"role": "user", "content": task})

 for i in range(max_steps):
 print(f" 輪次 {i+1}: 思考 + 行動（發送完整歷史，{len(self.history)} 條訊息）")
 # 模擬：每輪都把完整歷史送進模型
 response = mock_llm_call("executor", self.history, max_tokens=500)
 self.history.append({"role": "assistant", "content": response})
 self.history.append({"role": "user", "content": "觀察：工具執行結果..."})

 return {"steps": max_steps, "history_length": len(self.history)}


# ===== Token 消耗對比 =====

def compare_token_usage:
 """對比兩種模式的 token 消耗（估算）。"""
 print("=" * 60)
 print("Token 消耗對比（3 步任務，估算）")
 print("=" * 60)

 # Plan-Execute 模式
 planner_input = 200 # system + task + tools
 planner_output = 150 # plan JSON
 executor_per_step_input = 300 # 每步精簡上下文
 executor_per_step_output = 200
 pe_total = (planner_input + planner_output +
 3 * (executor_per_step_input + executor_per_step_output))

 # ReAct 模式
 react_system = 200
 react_per_round_input_growth = 400 # 每輪歷史增長
 react_total = react_system + sum(react_per_round_input_growth * (i+1) + 300 for i in range(3))

 print(f"\nPlan-Execute 模式:")
 print(f" Planner: {planner_input}+{planner_output} = {planner_input+planner_output} tokens")
 print(f" Executor x3: {executor_per_step_input}+{executor_per_step_output} x3 = {3*(executor_per_step_input+executor_per_step_output)} tokens")
 print(f" 總計: {pe_total} tokens")

 print(f"\nReAct 模式:")
 print(f" 每輪歷史遞增，3 輪總計: ~{react_total} tokens")

 print(f"\n節省: {(1 - pe_total/react_total)*100:.1f}%")
 print("=" * 60)


# ===== 演示 =====

if __name__ == "__main__":
 # 演示 Plan-Execute 模式
 agent = PlanExecuteAgent
 result = agent.run("分析 Q2 銷售數據，找出下滑最嚴重的產品線並給出改進建議")

 print(f"\n[完成] 共 {result['total_steps']} 步\n")

 # 對比 token 消耗
 compare_token_usage

 print("\n生產環境實現要點：")
 print(" 1. Planner 用便宜模型（Qwen3-8B/DeepSeek-Flash/GPT-4o-mini）")
 print(" 2. Executor 用強模型（GPT-4o/Claude Sonnet）")
 print(" 3. 步驟間只傳遞結果摘要，不傳完整數據")
 print(" 4. 確定性步驟（數據過濾、格式轉換）用代碼實現，不調 LLM")
 print(" 5. Planner 生成的計劃可由用戶確認後再執行")
