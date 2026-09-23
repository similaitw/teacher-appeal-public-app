# 教師申訴評議書專案維護手冊

更新：2026-09-23

## 儲存庫與發布責任

| 儲存庫 | 用途 | 修改原則 |
| --- | --- | --- |
| [teacher-appeal-local-ai](https://github.com/similaitw/teacher-appeal-local-ai)（私人） | 原始碼、測試、本機工作台與公開資料建置 | 唯一開發來源；私人案件資料只存本機，絕不提交 |
| [teacher-appeal-public-app](https://github.com/similaitw/teacher-appeal-public-app)（公開） | Streamlit 公開部署 | 只發布通過驗證的公開程式與資料，不直接開發 |
| `web/` | Next.js/Vercel 公開前端 | 與 Streamlit 為不同入口，正式網址及部署連結待確認 |

截至 2026-09-23，兩庫 main 同為 `a3218eef8aa5e811a1f2160cb1cd519757c6a399`，程式及公開資料仍是鏡像。公開資料集文件記載 324 筆；新資料更新尚未恢復。

## 已知故障與處置

兩庫的 `.github/workflows/update-public-cases.yml` 均排程執行爬蟲。私人庫 2026-09-22 的執行在連線 `https://appeal.moe.gov.tw/appraise_search.aspx` 時得到 `Network is unreachable`；公開庫最近可見的失敗亦在相同步驟。這是更新環境的連線故障，不能用重新建置資料庫掩蓋，也不能把失敗日標成資料更新日。

1. 從可連線的環境確認教育部站台與查詢流程，再以少量 CID 測試更新。
2. 更新結果通過 CSV、HTML、TXT、downloaded CID、SQLite 與 FTS 一致性檢查後才提交。
3. 確立單一排程：只在可連線的環境執行爬蟲；公開庫停止獨立抓取，僅接收已驗證資料。
4. 在解決連線前，保留現有資料並在公開介面標示最後成功更新時間；不宣稱每日更新。
5. 不繞過網站存取限制，不把 SSL 驗證關閉當成網路不通的解法。

## 發布流程

1. 在私人主庫修改，確認 `AGENTS.md`、測試與公開資料用途。
2. 執行 `python -m pytest -q`、`python -m py_compile scripts/*.py app/streamlit_app.py`、`python scripts/health_check.py --skip-ai`。
3. 執行 `python scripts/sync_repos.py` 檢查兩個 remote 與資料一致性。同步前逐項檢查 `git ls-files`，確保 `.env`、secrets、私人案件、上傳原檔、瀏覽器 profile、AI 分析輸出均未被追蹤。
4. 提交主庫；測試通過且公開檔案清單核對完成後，執行 `python scripts/sync_repos.py --push`。此腳本目前要求兩邊 main 沒有額外提交；若任何一邊領先，先人工檢查差異，勿強推。
5. 確認公開 Streamlit 顯示新增版本、搜尋及案件閱讀可用。若 Vercel 前端已連接，另執行 `cd web && npm ci && npm run check:data && npm run build`，檢查正式網址與資料筆數。

## 維護週期

| 時機 | 檢查項目 | 失敗時 |
| --- | --- | --- |
| 每週 | 更新執行紀錄、最近成功日期、資料筆數、公開站可用性 | 保留上一版，記錄錯誤及環境，修復後重試 |
| 每次程式更新 | 測試、公開資料一致性、禁傳檔案、兩庫提交 | 不同步、不部署 |
| 每月 | 兩庫 main、公開權限與祕密設定、Streamlit/Vercel 正式入口 | 修正差異與文件，再發布 |

## 待完成事項

- [ ] 確認可連線教育部站台的更新環境與最後成功更新日。
- [ ] 改為單一排程，停用另一庫的重複爬蟲。
- [ ] 驗證公開版不會讀取私人資料；建立發布檔案允許清單。
- [ ] 更新過時的 `STATUS.md` 與部署說明。
- [ ] 確認 Vercel 專案、正式網址、GitHub 來源、root directory 與部署狀態。
- [ ] 完成 Streamlit 與 Vercel 的公開功能及資料筆數 smoke test。
