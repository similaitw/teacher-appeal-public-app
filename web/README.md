# 教師申訴評議書公開查詢 Web

這是 Vercel 用的公開查詢版前端。它會在 build 前從專案根目錄的 `data/cases.csv` 與 `data/texts/` 產生靜態 JSON，讓網站不需要資料庫、登入或 server secrets 即可查詢公開案件。

## 本機執行

```bash
cd web
npm install
npm run check:data
npm run build
npm run start
```

## Vercel 部署

建議部署 `web` 目錄。部署前先執行 `npm run check:data`，產生 `web/public/data`；Vercel build 若讀不到上一層 `data/cases.csv`，會使用已產生的靜態資料。這樣不需要把 SQLite、raw HTML、本機快取或私人檔案送到 Vercel。

公開介面：

```txt
/data/manifest.json
/data/cases-index.json
/data/cases/{cid}.json
/
/cases/{cid}
```

目前第一版只提供公開案件搜尋、篩選與閱讀；私人案件、本機上傳、批次 AI 分析與爬蟲更新仍保留在 Streamlit/本機工具。
