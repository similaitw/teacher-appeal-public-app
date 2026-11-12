# 專案狀態

更新時間：2026-11-12

## 一眼看懂

| 項目 | 狀態 |
| --- | --- |
| 公開資料集 | 324 筆（CSV、SQLite/FTS5、HTML、TXT、downloaded CID 一致） |
| 最後成功資料更新 | 2026-06-26（最新評議書發文日：中華民國 115 年 5 月 22 日） |
| 自動更新排程 | **已停用**（2026-11-12）；GitHub 雲端主機連不到教育部站台，改由本機手動更新 |
| 測試 | `pytest` 全數通過（含雲端公開模式 smoke 與發布檔案政策測試） |
| 私人主庫 | [teacher-appeal-local-ai](https://github.com/similaitw/teacher-appeal-local-ai)（唯一開發來源） |
| 公開部署庫 | [teacher-appeal-public-app](https://github.com/similaitw/teacher-appeal-public-app)（Streamlit，鏡像私人主庫 main） |
| Vercel 前端 | <https://teacher-appeal-public-app.vercel.app>（Next.js，`web/`；CLI 部署，未連 GitHub；最後部署 2026-07-02，324 筆） |

## 功能

- Streamlit 工作台：公開評議書搜尋與閱讀、公開 AI 分析包、ChatGPT / Gemini 網頁批次分析與監控、AI 分析紀錄與引用覆核、私人去識別化案件管理。
- 雲端公開模式 `APP_MODE=cloud_public`：停用私人案件、瀏覽器自動化、資料下載與資料庫重建。
- Next.js 公開前端：靜態 JSON，不需資料庫或 server secrets；只匯出 `scope=public_bundle` 且為公開 cid 的 AI 分析。

## 安全防線

- `scripts/publish_policy.py`：公開發布**允許清單 + 禁止清單**。所有被 git 追蹤的檔案都必須在允許清單內，且不得命中禁止清單（`.env*`、`secrets.toml`、`private_cases.db`、帳號權限檔、`uploaded_cases/`、`exports/`、`ai_exports/`、瀏覽器 profile 等，不論位於哪一層目錄）。
- CI 與 `scripts/sync_repos.py` 都會執行 `scripts/check_publish_files.py`；新增檔案類型若未列入允許清單，同步會被擋下。
- `tests/test_cloud_public_smoke.py`：在雲端公開模式且關閉登入（最壞情況）下逐頁執行 Streamlit，確認不會建立 `private_cases.db`、`uploaded_cases/`、`exports/`。

## 驗收指令

```bash
python -m pytest -q
python -m py_compile scripts/*.py app/streamlit_app.py
python scripts/check_publish_files.py
python scripts/health_check.py --skip-ai
cd web && npm ci && npm run check:data && npm run build
```

## 已知限制

- 教育部站台（appeal.moe.gov.tw）從 GitHub Actions 等海外雲端連線會得到 `Network is unreachable`；資料更新只能在臺灣可連線的本機執行。
- `data/crawl_state.json` 的 `total_records` 為 0，係舊版狀態欄位，不代表資料筆數；以 `cases.csv` 與 SQLite 為準。
- `health_check.py --skip-ai` 會略過 Ollama；雲端公開模式不依賴本機 Ollama。

## 下一步

見 `docs/MAINTENANCE.md`「待完成事項」。
