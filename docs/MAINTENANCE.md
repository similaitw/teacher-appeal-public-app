# 教師申訴評議書專案維護手冊

更新：2026-11-12

## 儲存庫與發布責任

| 儲存庫 | 用途 | 修改原則 |
| --- | --- | --- |
| [teacher-appeal-local-ai](https://github.com/similaitw/teacher-appeal-local-ai)（私人） | 原始碼、測試、本機工作台與公開資料建置 | 唯一開發來源；私人案件資料只存本機，絕不提交 |
| [teacher-appeal-public-app](https://github.com/similaitw/teacher-appeal-public-app)（公開） | Streamlit 公開部署 | 只發布通過驗證的公開程式與資料，不直接開發 |
| `web/` | Next.js/Vercel 公開前端，正式網址 <https://teacher-appeal-public-app.vercel.app> | Vercel 專案 `teacher-appeal-public-app`（root：`web`），以 CLI 從本機部署、未連 GitHub，因 AI 分析資料只存在本機 `data/ai_exports/` |

截至 2026-11-12，公開庫 main 由私人主庫快轉同步，兩庫仍是鏡像。公開資料集 324 筆，最後成功更新 2026-06-26；新資料更新尚未恢復。

## 已知故障與處置

兩庫的 `.github/workflows/update-public-cases.yml` 均排程執行爬蟲。私人庫 2026-09-22 的執行在連線 `https://appeal.moe.gov.tw/appraise_search.aspx` 時得到 `Network is unreachable`；公開庫最近可見的失敗亦在相同步驟。這是更新環境的連線故障，不能用重新建置資料庫掩蓋，也不能把失敗日標成資料更新日。

1. 從可連線的環境確認教育部站台與查詢流程，再以少量 CID 測試更新。
2. 更新結果通過 CSV、HTML、TXT、downloaded CID、SQLite 與 FTS 一致性檢查後才提交。
3. 確立單一排程：只在可連線的環境執行爬蟲；公開庫停止獨立抓取，僅接收已驗證資料。（2026-11-12：兩庫的 GitHub 排程皆已註解停用，只保留手動 `workflow_dispatch`。）
4. 在解決連線前，保留現有資料並在公開介面標示最後成功更新時間；不宣稱每日更新。
5. 不繞過網站存取限制，不把 SSL 驗證關閉當成網路不通的解法。

## 發布流程

1. 在私人主庫修改，確認 `AGENTS.md`、測試與公開資料用途。
2. 執行 `python -m pytest -q`、`python -m py_compile scripts/*.py app/streamlit_app.py`、`python scripts/health_check.py --skip-ai`。
3. 執行 `python scripts/sync_repos.py` 檢查兩個 remote 與資料一致性。腳本會以 `scripts/publish_policy.py` 的允許清單與禁止清單檢查 `git ls-files`（也可單獨執行 `python scripts/check_publish_files.py`）；新增檔案類型被擋下時，確認可公開後再加入允許清單，不要放寬禁止清單。
4. 提交主庫；測試通過且公開檔案清單核對完成後，執行 `python scripts/sync_repos.py --push`。此腳本目前要求兩邊 main 沒有額外提交；若任何一邊領先，先人工檢查差異，勿強推。
5. 有新的公開 AI 分析時，先執行 `cd web && npm run publish:analysis` 並提交 `data/public_analysis/`。
6. 部署前執行 `cd web && npm ci && npm run check:data && npm run build`；上線後檢查正式網址的案件數、分析數與「資料更新」日期。

## 維護週期

| 時機 | 檢查項目 | 失敗時 |
| --- | --- | --- |
| 每週 | 更新執行紀錄、最近成功日期、資料筆數、公開站可用性 | 保留上一版，記錄錯誤及環境，修復後重試 |
| 每次程式更新 | 測試、公開資料一致性、禁傳檔案、兩庫提交 | 不同步、不部署 |
| 每月 | 兩庫 main、公開權限與祕密設定、Streamlit/Vercel 正式入口 | 修正差異與文件，再發布 |

## 公開網站合併計畫（2026-11-12 決定）

目標：只留 Vercel 網站當公開入口，Streamlit 只在本機當私人工作台；Vercel 連公開庫自動部署。

- [x] 移除 Vercel 網站的假登入（密碼寫死在前端）；Streamlit 雲端公開版未在 Secrets 設定 `DEFAULT_APP_PASSWORD` 時停用登入。
- [x] 把「公開 AI 分析包」搬到網站 `/package`，並以測試確認與 Python 版產出一致。
- [x] 網站顯示資料最後成功更新日；建置不再寫死 324 筆。
- [x] 公開 AI 分析可提交到 `data/public_analysis/runs/`，供自動部署使用。
- [x] 匯出並提交 324 筆公開 AI 分析到 `data/public_analysis/`（與舊站的分析編號及內容指紋一致）。之後有新分析時：`cd web && npm run publish:analysis`，提交後同步。
- [x] Vercel 專案連到公開庫（Root Directory：`web`），2026-11-12 新版上線：324 件案件、324 筆分析。CLI 手動部署須改從專案根目錄執行。
- [ ] 在 Streamlit 公開版放「已搬到新網址」公告，一段時間後刪除 app。
- [ ] 預設密碼曾出現在公開的程式與網站中；若其他地方也用同一組，請更換。

## 待完成事項

- [ ] 在臺灣可連線教育部站台的本機恢復資料更新（README「Windows 工作排程範例」），以少量 CID 測試後再全量更新。
- [x] 改為單一排程，停用另一庫的重複爬蟲。（2026-11-12：兩庫排程皆停用）
- [x] 驗證公開版不會讀取私人資料；建立發布檔案允許清單。（`scripts/publish_policy.py`、`tests/test_cloud_public_smoke.py`）
- [x] 更新過時的 `STATUS.md` 與部署說明。
- [x] 確認 Vercel 專案、正式網址、root directory 與部署狀態。
- [x] 完成 Vercel 公開功能及資料筆數 smoke test。（2026-11-12：首頁 200、manifest 324 筆）
