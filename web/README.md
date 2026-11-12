# 教師申訴評議書公開查詢 Web

正式網址：<https://teacher-appeal-public-app.vercel.app>

這是唯一的公開網站（Next.js，部署在 Vercel）。建置前會從專案根目錄的 `data/cases.csv`、`data/texts/` 與 `data/public_analysis/` 產生靜態 JSON，不需要資料庫、登入或 server secrets。

## 頁面

| 路徑 | 功能 |
| --- | --- |
| `/` | 公開評議書搜尋與篩選 |
| `/cases/{cid}` | 評議書全文閱讀、相關 AI 分析 |
| `/analysis` | 公開 AI 分析結果與引用核對 |
| `/package` | AI 分析包：勾選案件，在瀏覽器內打包 ZIP（不呼叫任何 AI 服務） |

本站沒有登入功能。私人案件、文件匯入、批次 AI 分析與爬蟲更新都留在本機 Streamlit 工作台。

## 本機執行

```bash
cd web
npm ci
npm run check:data   # 產生 web/public/data 並檢查筆數
npm run build
npm run start
```

## AI 分析包與 Python 版一致

`lib/ai-package.ts` 是 `scripts/public_ai_export.py` 的移植版，兩邊產出的檔案內容必須逐字相同。`tests/test_web_ai_package_parity.py` 會用全部公開案件比對（需要 Node.js 22.18 以上與 `npm ci`，否則略過）。修改提示詞或格式時兩邊一起改，再跑：

```bash
python -m pytest -q tests/test_web_ai_package_parity.py
```

## 公開 AI 分析的來源

AI 分析的原始紀錄在本機 `data/ai_exports/analysis_runs/`，不進 repo。要讓網站顯示，先在存有這些紀錄的電腦上匯出公開版本：

```bash
cd web
npm run publish:analysis
```

它只會匯出 `scope=public_bundle` 且案件全為公開 cid 的分析，寫到 `data/public_analysis/runs/`。檢查後提交這個資料夾。建置時會再檢查一次，不合格的檔案會被略過。

## 部署

Vercel 專案 `teacher-appeal-public-app`，Root Directory 設為 `web`，並保留「Include files outside the Root Directory」（建置要讀上一層的 `data/`）。

- 連接 GitHub 後：公開庫 `teacher-appeal-public-app` 的 `main` 一更新就自動部署。若 repo 內沒有任何公開分析，建置會失敗並提示先執行 `npm run publish:analysis`，避免把分析結果頁清空。
- 手動部署（備用）：`cd web && npx vercel --prod`。

首頁右上角的「資料更新」是案件資料最後成功更新的日期，不是網站建置時間。
