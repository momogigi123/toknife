#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""benchmark_cross_model.py —  跨模型基準（多 API 提供商對比）

在 benchmark_llm 的 15 任務基礎上，支援多個模型提供商對比：
- OpenAI（gpt-4o, gpt-3.5-turbo）
- Anthropic（claude-3-5-sonnet）
- DeepSeek（deepseek-chat）
- 豆包/Ark（doubao-seed-2-0-pro）

用法:
  python benchmark_cross_model.py --models openai:gpt-4o anthropic:claude-3-5-sonnet
  python benchmark_cross_model.py --models deepseek:deepseek-chat --tasks 5
  python benchmark_cross_model.py --list-providers

環境變數:
  OPENAI_API_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, ARK_API_KEY
  可選：OPENAI_BASE_URL, ANTHROPIC_BASE_URL, DEEPSEEK_BASE_URL, ARK_BASE_URL
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_proxy import est_tokens


# ===== 提供商配置 =====

PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "chat_path": "/chat/completions",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-3-5-sonnet-20240620",
        "chat_path": "/v1/messages",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "chat_path": "/chat/completions",
    },
    "ark": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "env_key": "ARK_API_KEY",
        "default_model": "doubao-seed-2-0-pro-260215",
        "chat_path": "/chat/completions",
    },
}


def chat_completion(provider, model, messages, api_key=None, timeout=60):
    """統一聊天接口，返回 (content, usage_dict, error)。"""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        return None, {}, f"未知提供商: {provider}"

    if not api_key:
        api_key = os.environ.get(cfg["env_key"], "")
    if not api_key:
        return None, {}, f"缺少 API Key: 設置環境變數 {cfg['env_key']}"

    base_url = os.environ.get(f"{provider.upper()}_BASE_URL", cfg["base_url"])
    url = base_url + cfg["chat_path"]

    if provider == "anthropic":
        # Anthropic API 格式不同
        payload = {
            "model": model,
            "max_tokens": 2048,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"],
        }
        sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        if sys_msg:
            payload["system"] = sys_msg
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    else:
        # OpenAI 兼容格式
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        return None, {}, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, {}, f"{type(e).__name__}: {e}"

    if provider == "anthropic":
        content = "".join(b.get("text", "") for b in data.get("content", []))
        usage = data.get("usage", {})
        usage = {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        }
    else:
        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = data.get("usage", {})

    return content, usage, None


# ===== 15 個基準任務 =====

BENCHMARK_TASKS = [
    {"id": "tool_output_1", "type": "tool_output", "prompt": "從以下工具輸出中找出價格最高的5個產品和異常值：\n{data}"},
    {"id": "tool_output_2", "type": "tool_output", "prompt": "統計以下數據的均值、中位數和分佈：\n{data}"},
    {"id": "tool_output_3", "type": "tool_output", "prompt": "找出以下數據中的重複項和缺失值：\n{data}"},
    {"id": "conversation_1", "type": "conversation", "prompt": "總結以下對話的要點：\n{data}"},
    {"id": "conversation_2", "type": "conversation", "prompt": "提取以下對話中的行動項：\n{data}"},
    {"id": "conversation_3", "type": "conversation", "prompt": "判斷以下對話的情緒傾向：\n{data}"},
    {"id": "code_1", "type": "code", "prompt": "審查以下代碼的潛在 bug：\n```python\n{data}\n```"},
    {"id": "code_2", "type": "code", "prompt": "重構以下代碼提高可讀性：\n```python\n{data}\n```"},
    {"id": "code_3", "type": "code", "prompt": "為以下代碼寫單元測試：\n```python\n{data}\n```"},
    {"id": "system_prompt_1", "type": "system_prompt", "prompt": "優化以下系統提示詞：\n{data}"},
    {"id": "system_prompt_2", "type": "system_prompt", "prompt": "為以下角色設定補充安全規範：\n{data}"},
    {"id": "incremental_1", "type": "incremental", "prompt": "根據以下狀態快照繼續執行：\n{data}"},
    {"id": "incremental_2", "type": "incremental", "prompt": "合併以下增量更新：\n{data}"},
    {"id": "qa_1", "type": "qa", "prompt": "回答以下問題：\n{data}"},
    {"id": "creative_1", "type": "creative", "prompt": "根據以下素材創作：\n{data}"},
]


def _make_sample_data(task_type):
    """生成各類型的測試數據（用固定數據確保對比公平）。"""
    if task_type == "tool_output":
        return json.dumps([{"id": i, "name": f"item{i}", "price": 100 + i * 7, "qty": i % 10} for i in range(100)], ensure_ascii=False)
    if task_type == "conversation":
        return "\n".join([f"User: 問題{i}\nAssistant: 回答{i}" for i in range(20)])
    if task_type == "code":
        return "def process(data):\n    result = []\n    for item in data:\n        if item > 0:\n            result.append(item * 2)\n    return result\n" * 10
    if task_type == "system_prompt":
        return "你是一個有用的助手。" * 50
    if task_type == "incremental":
        return json.dumps({"step": i, "state": f"state_{i}"} for i in range(30))
    return "測試數據" * 100


def run_benchmark(models, num_tasks=15, output_file=None):
    """運行跨模型基準。"""
    results = {}
    tasks = BENCHMARK_TASKS[:num_tasks]

    for model_spec in models:
        if ":" in model_spec:
            provider, model = model_spec.split(":", 1)
        else:
            provider = model_spec
            model = PROVIDERS[provider]["default_model"]

        print(f"\n{'='*60}")
        print(f"模型: {provider}/{model}")
        print(f"{'='*60}")

        model_results = []
        total_orig = 0
        total_comp = 0
        total_output = 0
        errors = 0

        for task in tasks:
            data = _make_sample_data(task["type"])
            prompt = task["prompt"].format(data=data)
            orig_tokens = est_tokens(prompt)

            # 不壓縮
            t0 = time.time()
            content, usage, err = chat_completion(provider, model, [
                {"role": "system", "content": "你是一個簡潔的助手。"},
                {"role": "user", "content": prompt},
            ])
            elapsed = time.time() - t0

            if err:
                print(f"  ❌ {task['id']}: {err}")
                errors += 1
                model_results.append({"id": task["id"], "error": err})
                continue

            output_tokens = usage.get("completion_tokens", est_tokens(content))
            total_orig += orig_tokens
            total_output += output_tokens

            print(f"  ✅ {task['id']}: 輸入{orig_tokens}tok → 輸出{output_tokens}tok ({elapsed:.1f}s)")
            model_results.append({
                "id": task["id"],
                "type": task["type"],
                "input_tokens": orig_tokens,
                "output_tokens": output_tokens,
                "elapsed": round(elapsed, 2),
            })

        results[f"{provider}/{model}"] = {
            "tasks": model_results,
            "total_input": total_orig,
            "total_output": total_output,
            "errors": errors,
            "success_rate": round((len(tasks) - errors) / len(tasks) * 100, 1),
        }

    # 對比報告
    print(f"\n{'='*60}")
    print("【跨模型對比報告】")
    print(f"{'='*60}")
    print(f"{'模型':<35} {'輸入tok':>10} {'輸出tok':>10} {'成功率':>8}")
    print("-" * 65)
    for name, r in results.items():
        print(f"{name:<35} {r['total_input']:>10} {r['total_output']:>10} {r['success_rate']:>7.1f}%")

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n結果已保存: {output_file}")

    return results


def main():
    ap = argparse.ArgumentParser(description="跨模型基準對比（）")
    ap.add_argument("--models", nargs="+", default=["ark:doubao-seed-2-0-pro-260215"],
                    help="模型列表，格式 provider:model（如 openai:gpt-4o）")
    ap.add_argument("--tasks", type=int, default=15, help="任務數量（1-15）")
    ap.add_argument("--output", "-o", help="結果輸出 JSON 文件")
    ap.add_argument("--list-providers", action="store_true", help="列出支援的提供商")
    a = ap.parse_args()

    if a.list_providers:
        print("支援的提供商:")
        for name, cfg in PROVIDERS.items():
            key_set = "✅" if os.environ.get(cfg["env_key"]) else "❌"
            print(f"  {name:<12} 預設模型: {cfg['default_model']:<30} API Key: {key_set} ({cfg['env_key']})")
        return

    run_benchmark(a.models, num_tasks=min(a.tasks, 15), output_file=a.output)


if __name__ == "__main__":
    main()
