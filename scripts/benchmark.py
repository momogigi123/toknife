# -*- coding: utf-8 -*-
"""benchmark.py — 標準化基準（補實證樣本，免 API key/GPU）
10 個典型任務 × A/B（不用技能 vs 用 token saver），tiktoken cl100k 真實計數。
輸出：每任務降幅 + 平均 + 中位數 + 場景標註（含反例）。
用法：python benchmark.py [--json]
"""
import statistics

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    count = lambda s: len(_enc.encode(s))
except ImportError:
    count = lambda s: len(s) // 3  # 粗略估算，建議 pip install tiktoken 獲得精確計數

# (任務, A 輸入, A 輸出, B 輸入, B 輸出, 場景標註)
CASES = [
    ("QA 事實問答", "system: 你是知識淵博的助手，請詳細解釋…\nuser: 什麼是光合作用？請從歷史、原理、應用、限制全面說明", "光合作用是植物利用光能將二氧化碳和水轉化為葡萄糖和氧氣的過程。它發生在葉綠體中……（500字詳述）",
     "system: 簡潔回答\nuser: 光合作用？", "光合作用：植物用光能將 CO₂+H₂O→葡萄糖+O₂（葉綠體）。", "構造"),
    ("摘要任務", "system: 你擅長總結，請完整閱讀以下長文並詳盡總結每個段落…\nuser: " + ("產品說明文字。" * 30), "本文介紹了產品的多個特性，包括……（長篇總結）",
     "system: 摘要≤200字\nuser: " + ("產品說明文字。" * 30), "結論：產品主打耐用與便攜。", "構造"),
    ("數據分析", "system: 資深分析師，請逐一分析以下 150 行數據的每一行…\nuser: " + ("2026-07,手機殼,120\n" * 40), "根據數據，手機殼 7 月銷售 120 台，環比……（逐月敘述）",
     "system: 只給結論\nuser: 數據已聚合：手機殼 7 月 4800 台（+3%）", "手機殼穩定成長；無異常。", "構造（聚合）"),
    ("代碼生成", "system: 資深工程師，請生成完整可運行的代碼，包含詳細註釋和錯誤處理，並解釋每一行…\nuser: 寫一個讀 CSV 的函數",
     "def read_csv(path):\n    import pandas as pd\n    # 讀取 CSV\n    return pd.read_csv(path)\n\n# 解釋：pandas 是…（長註釋）",
     "system: 只給最小可用代碼\nuser: read_csv(path) 用 pandas", "import pandas as pd\ndef read_csv(p): return pd.read_csv(p)", "構造"),
    ("創意寫作", "system: 請創作一篇內容豐富、細節生動的短篇小說，不限篇幅…\nuser: 寫一個機器人的故事",
     "機器人阿明在廢棄工廠醒來，記憶碎片……（1000字）",
     "system: 創作，不限篇幅\nuser: 機器人的故事", "機器人阿明醒來，尋找記憶。", "構造（B 僅骨架）"),
    ("翻譯", "system: 請準確翻譯以下文本，保留語氣與文化細節…\nuser: Hello world, this is a test",
     "你好，世界。這是一項測試。",
     "system: 直譯\nuser: hello world test", "你好，世界。", "構造"),
    ("Agent 迴圈", "system: 你是 Agent，逐步分析工具回傳…\nuser: 工具回傳（150行原始）:\n" + ("id,product,qty\n" * 40), "第一步：我看到了 150 行數據，其中……（逐步）",
     "system: 狀態快照制\nuser: 工具已聚合：6 產品 Top3 下滑。", "結論：鏡頭膜 -73% 最嚴重。", "構造（聚合）"),
    ("計畫生成", "system: 請為以下目標制定詳細的分步計劃，每步都說明原因與備選方案…\nuser: 完成一個網站",
     "步驟1：需求分析。原因：……備選：……（長篇）",
     "system: 只給步驟清單\nuser: 網站計劃", "1.需求 2.設計 3.開發 4.測試 5.上線", "構造"),
    ("郵件寫作", "system: 請寫一封語氣得體、結構完整的正式郵件，包含開頭問候、背景、詳細請求、結尾禮貌語…\nuser: 向客戶申請延期",
     "尊敬的客戶您好：非常感謝您一直以來的支持……（300字）",
     "system: 精簡商務郵件\nuser: 申請延期", "主題：延期申請。內文：因供應鏈問題，請求延期一週，抱歉。", "構造"),
    ("重構建議", "system: 請詳細分析以下代碼的問題，並給出完整重構方案，逐行說明…\nuser: def f(a): return a+1",
     "問題：函數名不明確……建議：改為……（詳細）",
     "system: 只列問題+建議\nuser: f(a)=a+1 重構", "問題：命名不明。建議：改名 add_one。", "構造"),
]

def main():
    print("=== Token Saver 標準化基準（tiktoken cl100k，10 任務 × A/B）===")
    print(f"{'任務':<10}{'A總':>7}{'B總':>7}{'降幅':>8}  場景")
    rows = []
    for name, ai, ao, bi, bo, note in CASES:
        a, b = count(ai) + count(ao), count(bi) + count(bo)
        rows.append((name, a, b))
        print(f"{name:<10}{a:>7}{b:>7}{-100*(b-a)/a:>7.1f}%  {note}")
    pcts = [-100 * (b - a) / a for _, a, b in rows]
    print(f"\n平均降幅：{statistics.mean(pcts):.1f}% ｜ 中位數：{statistics.median(pcts):.1f}% ｜ 最大：{max(pcts):.1f}% ｜ 最小：{min(pcts):.1f}%")
    print("⚠️ 場景皆為構造對比（非真實 LLM 測量）；真實雲端測量見 empirical-comparison #4/#5（35–53%）。")

if __name__ == "__main__":
    main()
