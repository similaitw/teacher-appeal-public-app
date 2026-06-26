# 開發回報

更新時間：2026-05-27

## 今日完成

- 將 Streamlit 從單頁查詢改成完整工作台。
- 新增總覽、搜尋、案件閱讀、AI 問答、資料管理、資安檢查 6 個區塊。
- 新增 `scripts/prepare_cids.py`，可從網址或文字整理 cid 清單。
- 新增 `scripts/export_case.py`，可匯出單案或搜尋結果 Markdown。
- 新增 `scripts/health_check.py`，可檢查資料庫、CSV、原始檔、Ollama 與爬蟲紀錄。
- Streamlit 可讀取本機 Ollama 模型清單，優先選已安裝模型。
- AI 回答若未明確標示來源 cid，會追加人工覆核提示。

## 驗收

已通過：

```powershell
python -m py_compile scripts\utils.py scripts\crawl_appeal.py scripts\build_db.py scripts\search_db.py scripts\llm.py scripts\ask_ollama.py scripts\prepare_cids.py scripts\export_case.py scripts\health_check.py app\streamlit_app.py
python scripts\search_db.py 導師 --limit 5
python scripts\ask_ollama.py --check --model gemma2:2b
python scripts\health_check.py --model gemma2:2b
python scripts\export_case.py --query 導師 --limit 3 --with-evidence --output data\exports\search_results_full_workbench.md
```

Streamlit 元件測試結果：

```txt
exceptions= 0
title= ['教師申訴評議書本機查詢系統']
tabs= ['總覽', '搜尋', '案件閱讀', 'AI 問答', '資料管理', '資安檢查']
metrics= 4
```

Streamlit 本機服務：

```txt
http://localhost:8501
```

已回應 HTTP 200。

## 目前限制

- 目前資料庫只有 1 筆測試案件，正式分析前需要批次擴充 cid。
- 教育部站台憑證在 Python/OpenSSL 可能觸發驗證問題，爬蟲會記錄後改用寬鬆模式重試。
- 關鍵字搜尋 POST 仍可能因官方 ASP.NET 表單變動而抓不到 cid，最穩流程是先整理 cid 清單。
- AI 回答是草稿整理，正式引用仍須依 cid 原文覆核。

## 下一步

1. 批次整理更多教師申訴案件 cid。
2. 使用資料管理頁下載案件並重建資料庫。
3. 增加固定主題摘要模板，例如導師職務、考核、懲處、解聘停聘不續聘。
4. 加入案件標籤修正與人工註記欄位。
