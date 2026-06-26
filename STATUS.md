# 專案狀態

更新時間：2026-06-26

## 目前完成

- 公開教師申訴評議書已建立本機資料集：
  - `data/cases.csv`：324 筆。
  - `data/appeal_cases.db`：SQLite + FTS5，324 筆。
  - `data/raw_html/`：324 個 HTML。
  - `data/texts/`：324 個純文字檔。
  - `data/downloaded_cids.txt`：324 筆。
- 已修正「已下載但未進入 CSV/SQLite」的快取修補流程。
  - `scripts/crawl_appeal.py` 會在略過已下載 cid 時，將缺少 CSV 列的 cached HTML/TXT 補回。
  - `scripts/update_public_cases.py` 會在公開更新時產生 `repaired_cids.txt` 並重建資料庫。
- Streamlit 工作台已支援：
  - 公開評議書搜尋與閱讀。
  - 公開 AI 分析包與 ZIP 匯出。
  - ChatGPT / Gemini 網頁批次分析與批次狀態監控。
  - AI 分析紀錄保存與引用覆核筆記。
  - 私人去識別化案件匯入、搜尋與 Codex 分析資料包。
  - 雲端公開模式 `APP_MODE=cloud_public`，停用私人案件與本機瀏覽器自動化。
- 雲端部署檔已建立：
  - `.streamlit/config.toml`
  - `requirements-cloud.txt`
  - `packages.txt`
  - `.github/workflows/update-public-cases.yml`
  - `.github/workflows/ci.yml`
  - `CLOUD_DEPLOYMENT.md`

## 驗收結果

已通過：

```powershell
.venv\Scripts\python.exe -m pytest -q
# 48 passed

.venv\Scripts\python.exe -m py_compile scripts\*.py app\streamlit_app.py

.venv\Scripts\python.exe scripts\build_db.py
# 匯入案件數：324

.venv\Scripts\python.exe scripts\health_check.py --skip-ai
# SQLite / CSV / HTML / TXT / 同步狀態皆 PASS
```

資料一致性：

```txt
cases 324
db 324
fts 324
texts 324
html 324
downloaded 324
all_sets_equal True
```

雲端公開模式 smoke：

```powershell
$env:APP_MODE="cloud_public"
.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py --server.port 8502
```

Windows 端 HTTP 檢查回應 `STATUS=200`。Playwright DOM smoke 已確認頁面渲染出 Streamlit app。

## 目前限制

- 本目錄原本不是 Git repository；實際上線需要先推到 GitHub，再接 Streamlit Community Cloud。
- GitHub / Streamlit Cloud 上線後，私人案件資料、`private_cases.db`、`uploaded_cases/`、`exports/`、`browser_profiles/` 與 `data/ai_exports/` 不應上雲。
- `health_check.py --skip-ai` 會略過 Ollama；雲端公開模式不依賴本機 Ollama。
- `data/crawl_errors.log` 仍保留教育部網站 SSL fallback 紀錄，屬已知站台憑證相容性紀錄；爬蟲會自動 fallback。

## 下一步

1. 初始化 Git repository 並提交目前可上線版本。
2. 推送至 GitHub repo。
3. 在 Streamlit Community Cloud 建立 app：
   - Main file path：`app/streamlit_app.py`
   - 環境變數或 secrets：`APP_MODE = "cloud_public"`
4. 等 GitHub Actions `CI` 通過。
5. 啟用 `Update public appeal cases` workflow 作為定期公開資料更新。
