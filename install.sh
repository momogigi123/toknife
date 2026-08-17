#!/bin/bash
# toknife v5.1.1 — 一鍵安裝腳本（安裝 = 常駐）
# 用法: bash install.sh
# 做三件事: ①驗證環境 ②準備常駐片段（複製即用）③提示進階代理（授權版）
set -e
echo "=== toknife v5.1.1 安裝 ==="

# ① 驗證 Python
PY=""
for cand in "$HOME/.workbuddy/binaries/python/versions/"*/python.exe python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then echo "❌ 找不到 Python（需 3.7+）"; exit 1; fi
echo "✅ Python: $("$PY" --version 2>&1)"

# ② 跑確定性驗證（零 API，確認腳本能用）
echo "--- 驗證安裝 ---"
(cd scripts && "$PY" verify_code_v51.py) 2>&1 | tail -1 || echo "⚠️ verify 可稍後手動跑: python scripts/verify_code_v51.py"

# ③ 常駐片段（安裝即常駐的關鍵一步）
echo ""
echo "=== 常駐設定（最後一步，一次貼上永久生效）==="
echo "1) 打開你的 AI 平台 → 設定 → 自訂指令 / Custom Instructions"
echo "2) 貼上以下片段："
echo ""
cat <<'SNIPPET'
【toknife 常駐規範 v5.1.1】所有任務一律套用：
優先級：領域規則＞用戶明確要求＞完整模式＞決策樹（領域豁免不客套）
默認原則：無明確要求一律精簡（默認短、顯式加長）
完整模式觸發：
- 明確句式：「詳細講一下/請解釋/完整列出/要 N 個」
- 任務動詞：「怎麼做/怎麼修/怎麼談/推薦/教我/看看/審閱/檢查」＋對象含技巧/判斷/安全/知識
- 診斷：「為什麼＋故障/當機/報錯」→ 排查路徑
- 不觸發：「為什麼」一句能講完→短；對象瑣碎→短（瑣碎優先）；「完整嗎」→不觸發
- 複雜度：步驟≥3且含技巧/判斷/安全→完整；不確定→短兜底
- 資訊不足（修/推薦缺參數）→ 先反問再完整
字數軟約束：完整豁免字數但先結論；數字絕不砍優先於 ≤50 字
領域規則：法律/醫療/財務（含合約審閱）→完整＋免責；情緒支持→傾聽式
決策樹（其餘）：事實≤50字；分析≤300字先結論；清單≤5項（用戶要更多以用戶為準）；程式碼=代碼+一句；創作放寬；一律不客套不開場白
工具回傳 >50 行：先壓縮再入上下文
短回傳不壓（防淨成本）；結論/數字/任務要求細節絕不砍
SNIPPET
echo ""
echo "3) 完成——從此每輪自動常駐省 token。"

# ④ 進階提示（代理，授權版）
echo ""
echo "=== 進階：系統級自動壓縮（代理端點）==="
echo "想要『每次回傳都自動壓縮』（不靠常駐規範）？代理端點隨 v6.8 授權版提供。"
echo "取得授權版並放好 ts_proxy_server.py 後: python ts_proxy_server.py 8121 → 應用 base_url 改為 http://127.0.0.1:8121/v1"
echo "（該腳本隨 v6.8+ 授權版提供，本開源倉庫 v5.1.1 不含，請勿直接從此目錄執行）"
echo ""
echo "✅ toknife v5.1.1 安裝完成——已常駐準備就緒"
