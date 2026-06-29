# 教師申訴評議書本機查詢系統

這是一個本機端可執行的教育部教師申訴評議書／申評會審議書查詢系統。它可以下載公開案件 HTML、保存純文字與索引，建立 SQLite + FTS5 全文檢索資料庫，並提供命令列與 Streamlit 查詢介面。目前介面以公開搜尋、私人案件整理、ChatGPT / Gemini 批次分析與本機歸檔為主。

## 安裝方式

### Windows PowerShell

```bash
cd teacher-appeal-local-ai
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### macOS / Linux

```bash
cd teacher-appeal-local-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 抓資料

下載單一 cid：

```bash
python scripts/crawl_appeal.py --cid 114070228
```

使用 cid 清單：

```bash
python scripts/crawl_appeal.py --cid-file cids.txt --sleep 1.5
```

若你手上是一批網址或混雜文字，可先整理成 cid 清單：

```bash
Get-Content raw-links.txt | python scripts/prepare_cids.py --output cids.txt
python scripts/crawl_appeal.py --cid-file cids.txt --sleep 1.5
python scripts/build_db.py
```

使用單一關鍵字或關鍵字檔：

```bash
python scripts/crawl_appeal.py --keyword 擔任導師 --sleep 1.5
python scripts/crawl_appeal.py --keywords-file keywords.txt --sleep 1.5
```

抓取公開查詢系統目前可公開取得的全部評議書：

```bash
python scripts/crawl_appeal.py --all --sleep 1.5
```

中斷後續抓：

```bash
python scripts/crawl_appeal.py --resume --sleep 1.5
```

只重試前次下載失敗的 cid：

```bash
python scripts/crawl_appeal.py --retry-failed --sleep 2
```

小量測試：

```bash
python scripts/crawl_appeal.py --all --limit 3 --sleep 1.5
```

`--all` 不猜測 cid，也不暴力列舉。它會先 GET 查詢頁取得 ASP.NET 的 `__VIEWSTATE`、`__EVENTVALIDATION` 等欄位，再以合法日期條件 `0010101` 到目前民國年的年底送出查詢，依結果頁的 `下一頁` WebForms postback 遍歷分頁，從公開列表連結收集 `appraise_view.aspx?cid=...`。站台會在結果頁顯示類似 `第 1 / 17 頁`、`共 324 筆` 的分頁與總筆數資訊。每頁目前約 20 筆。

爬蟲會保存狀態檔：

```txt
data/discovered_cids.txt
data/downloaded_cids.txt
data/failed_cids.txt
data/crawl_state.json
```

已存在於 `data/cases.csv`、`data/texts/`、`data/raw_html/` 或 `data/downloaded_cids.txt` 的成功 cid 會自動略過，不會重複下載。遇到 429、500、502、503、504 會指數退避重試。若教育部網站調整表單或搜尋 POST 失敗，仍可使用 `--cid` 或 `--cid-file` 直接下載案件頁。錯誤會寫入 `data/crawl_errors.log`。

目前測試時，該站憑證在 Python/OpenSSL 可能出現 `Missing Subject Key Identifier` 驗證錯誤；爬蟲預設會記錄後自動改用 `verify=False` 重試，以確保本機備份流程可用。如需強制憑證驗證，可加上：

```bash
python scripts/crawl_appeal.py --cid 114070228 --verify-ssl
```

## 建資料庫

```bash
python scripts/build_db.py
```

會建立：

```txt
data/appeal_cases.db
```

## 更新公開資料

若教育部網站後續新增公開評議書，可使用更新管線自動比對本機資料，只下載新增案件，並重建公開 SQLite/FTS。此流程只更新公開資料，不會自動送 ChatGPT/Gemini 分析。

檢查並更新：

```bash
python scripts/update_public_cases.py --sleep 1.5
```

小量測試：

```bash
python scripts/update_public_cases.py --limit 5 --sleep 1.5
```

重試前次失敗案件：

```bash
python scripts/update_public_cases.py --retry-failed --sleep 2
```

只下載與產生紀錄，不重建資料庫：

```bash
python scripts/update_public_cases.py --no-build-db --sleep 1.5
```

每次更新會建立：

```txt
data/update_runs/<timestamp>/
  update_manifest.json
  discovered_cids.txt
  new_cids.txt
  downloaded_cids.txt
  failed_cids.txt
  ai_pending_cids.txt
  stdout.log
  stderr.log
```

`ai_pending_cids.txt` 只包含本次新增且下載成功的 cid，供你確認後再手動建立 ChatGPT/Gemini 批次分析。Streamlit「公開資料更新」頁籤可一鍵啟動更新、查看最近紀錄、下載 cid 清單，並建立待分析批次清單。

Windows 工作排程範例，每日凌晨 3 點更新公開資料：

```powershell
schtasks /Create /TN "TeacherAppealPublicUpdate" /SC DAILY /ST 03:00 /TR "H:\AI_Project\teacher-appeal-local-ai\.venv\Scripts\python.exe H:\AI_Project\teacher-appeal-local-ai\scripts\update_public_cases.py --sleep 1.5"
```

## 命令列查詢

```bash
python scripts/search_db.py 擔任導師
python scripts/search_db.py 寒暑假 生活輔導
python scripts/search_db.py --cid 114070228
python scripts/search_db.py --query 導師 --limit 20
```

## 匯出 Markdown

匯出單一案件全文：

```bash
python scripts/export_case.py --cid 114070228
```

匯出搜尋結果摘要與 AI 來源片段：

```bash
python scripts/export_case.py --query 導師 --limit 10 --with-evidence
```

## 公開評議書 AI 分析預處理

已抓取的公開評議書可整理成「一案一包」，供手動上傳 ChatGPT、Gemini 或其他 AI 工具。此流程只處理公開案件資料，不使用 `private_cases.db` 或私人案件檔案。

輸出位置：

```txt
data/ai_exports/public_cases/<cid>/
  case_manifest.json
  case_full_context.md
  source_index.csv
  case_prompt.md
```

單案匯出：

```bash
python scripts/export_public_ai_cases.py --cid 114070228
```

小量測試：

```bash
python scripts/export_public_ai_cases.py --all --limit 10
```

全部公開案件：

```bash
python scripts/export_public_ai_cases.py --all
```

`case_full_context.md` 會移除網站導覽、頁尾、轉存連結等固定文字，保留評議書核心內容，並以段落編號標示來源：

```txt
[來源：D001，第12段]
```

`source_index.csv` 會記錄 `source_id`、`cid`、`section`、`paragraph_no`、`heading`、`char_start`、`char_end`，方便後續引用核對。Streamlit 的「公開 AI 分析包」頁籤可用表格勾選案件，並產生 ChatGPT / Gemini 手動上傳用 ZIP；程式不呼叫外部 API，也不會自動上傳全文。

介面流程：

1. 依關鍵字、年度、結果或爭點分類篩選公開案件。
2. 勾選一件或多件案件。
3. 選擇「單案分析包」或「多案比較包」。
4. 按「產生 AI 上傳包」並下載 ZIP。
5. 開啟 ChatGPT 或 Gemini，上傳 ZIP 或其中的 `case_full_context.md`，再貼上 `multi_case_prompt.md`。

多案輸出位置：

```txt
data/ai_exports/bundles/<timestamp>_<mode>_<count>_cases/
  bundle_manifest.json
  selected_cases.csv
  multi_case_prompt.md
  cases/
    <cid>/
      case_manifest.json
      case_full_context.md
      source_index.csv
      case_prompt.md
```

`multi_case_prompt.md` 會要求 AI 逐案保留 cid 與 `[來源：D001，第N段]`，並禁止把 A 案事實、人物、日期或結論套用到 B 案。

### ChatGPT / Gemini 網頁批次自動分析

可在 Streamlit「公開 AI 分析包」頁籤勾選案件後，啟動「網頁批次自動分析」。系統會一案一案產生單案來源包，開啟本機瀏覽器，將 `case_full_context.md` 與 `case_prompt.md` 合併貼到 ChatGPT 或 Gemini，等待回覆後自動保存到「AI 分析紀錄」。

此功能不使用 API、不保存帳密、不繞過登入、驗證碼、付費牆或額度限制。第一次使用前請先安裝 Playwright 瀏覽器：

```bash
pip install -r requirements.txt
playwright install chromium
```

也可用 CLI 執行：

```bash
python scripts/run_web_ai_batch.py --provider chatgpt --cid 114070228 --sleep 3 --model-name GPT-4.1
python scripts/run_web_ai_batch.py --provider gemini --cid-file cids.txt --sleep 3 --model-name "Gemini 2.5 Pro"
```

若批次中有 `failed` 或 `stale`，可只重跑這些案件：

```bash
python scripts/run_web_ai_batch.py --resume-batch data/ai_exports/web_ai_batches/<batch_id> --statuses failed,stale --sleep 3
```

若要讓系統自動接續跑到沒有可自動重跑的案件，可使用多輪接續模式。此模式預設處理 `pending`、`failed`、`stale`，不自動處理 `paused`；每案達到重跑上限後會保留人工檢核備註：

```bash
python scripts/run_web_ai_batch.py --continue-batch data/ai_exports/web_ai_batches/<batch_id> --statuses pending,failed,stale --max-rounds 5 --max-attempts 3 --sleep 3
```

批次狀態會輸出到：

```txt
data/ai_exports/web_ai_batches/<batch_id>/
  batch_manifest.json
  selected_cids.txt
  status.csv
  logs/
```

登入狀態保存在本機瀏覽器 profile：

```txt
browser_profiles/chatgpt/
browser_profiles/gemini/
```

這些資料已加入 `.gitignore`，不要提交到版本控制。若遇到登入、CAPTCHA、額度限制、網頁 UI 改版或單案文字太長，批次會標示為 `paused`，請人工處理後再繼續或重跑未完成案件。

## 保存 AI 分析結果

ChatGPT、Gemini 或 Codex 的分析結果可能因模型版本、提示語或隨機性而不同。建議每次分析都保存為獨立版本，不覆蓋舊結果。

Streamlit「AI 分析紀錄」頁籤可保存公開案件上傳包與私人 Codex 分析包的分析結果。程式只在本機存檔，不呼叫外部 API，不儲存任何服務金鑰。

輸出位置：

```txt
data/ai_exports/analysis_runs/<timestamp>_<provider>_<scope>/
  input_manifest.json
  prompt_used.md
  ai_response.md
  citation_review.md
  notes.md
```

建議流程：

1. 先在「公開 AI 分析包」或「Codex 分析資料」產生來源包。
2. 手動到 ChatGPT、Gemini 或 Codex 分析。
3. 回到「AI 分析紀錄」頁籤選擇來源包。
4. 填入 AI 工具、模型名稱，確認或修改實際 prompt。
5. 貼上 AI 原始回覆與人工備註，按「保存 AI 分析紀錄」。

`input_manifest.json` 會記錄來源包路徑、案件 cid 或私人案件 UUID、來源檔案 SHA-256、prompt SHA-256、AI 回覆 SHA-256、模型名稱與分析時間。`citation_review.md` 是人工引用覆核範本，用來檢查 AI 是否引用不存在段落、是否把不同案件事實混用、是否把單方主張寫成認定事實。

## 可能誤判風險稽核

已下載公開案件與已保存 AI 分析結果可進行本機規則式稽核，輸出人工覆核用 HTML / CSV / JSON 報表。此功能只標示「可能誤判風險」與「需人工覆核」事項，不作成最終認定、懲處建議或正式法律結論。

```bash
python scripts/misjudgment_audit.py --all --html
python scripts/misjudgment_audit.py --cid 114070228
python scripts/misjudgment_audit.py --analysis-runs
```

預設輸出位置：

```txt
data/audit_reports/misjudgment/<timestamp>/
  misjudgment_audit.html
  misjudgment_audit.csv
  misjudgment_audit.json
```

Streamlit「誤判風險稽核」頁籤可選擇全部案件、指定 cid、只掃 AI 分析結果，或依最近報表重掃高風險 cid，並提供報表下載與單項風險詳情。

## 健康檢查

```bash
python scripts/health_check.py --model gemma2:2b
```

會檢查 SQLite、CSV、原始 HTML、純文字、爬蟲錯誤紀錄與資料庫同步狀態。

## 啟動 Streamlit

```bash
streamlit run app/streamlit_app.py
```

開啟：

```txt
http://localhost:8501
```

### 遠端操作與帳號權限

Streamlit 工作台支援帳號與角色權限。首次啟動會建立 `admin`、`public`、`private` 三個帳號；預設密碼可用 `DEFAULT_APP_PASSWORD` 覆寫，若未設定則使用 `APP_PASSWORD`，最後才使用 `simisimi520`。正式遠端開放後，請先用 `admin` 登入右上角「帳號與權限」，到「帳號管理」重設密碼。

角色權限：

- `public`：公開搜尋、公開案件閱讀、公開 AI 上傳包。
- `private`：私人案件、文件匯入、Codex 分析包、AI 分析結果、ChatGPT/Gemini 網頁批次、公開資料更新、誤判風險稽核與資安檢查。
- `admin`：包含所有私人功能，並可管理帳號。

PowerShell 範例：

```powershell
$env:DEFAULT_APP_PASSWORD="請改成強密碼"
python -m streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

帳號資料會以 PBKDF2 雜湊保存在 `data/auth_users.json`。遠端開放前請確認 `data/auth_users.json`、`private_cases.db`、`uploaded_cases/`、`exports/`、`data/ai_exports/` 與 `browser_profiles/` 不會提交到公開 repo；目前 `.gitignore` 已排除這些私人資料。

介面支援關鍵字、cid、年度、案件類型與結果篩選，並可顯示全文、匯出 Excel、產生 AI 分析包、監控批次分析與查看歸檔結果。

目前 Streamlit 工作台包含：

- 總覽：案件數、年度數、結果類別與爭點統計。
- 搜尋：關鍵字、年度、案件類型與結果篩選，支援 Excel / Markdown 下載。
- 案件閱讀：依 cid 顯示全文、下載單案 Markdown。
- 資料管理：貼上 cid 或案件網址，整理 `cids.txt`，可直接下載案件並重建 SQLite。
- 公開 AI 分析包：篩選並勾選公開案件，產生 ChatGPT / Gemini 手動上傳 ZIP。
- 網頁批次自動分析：逐案開啟 ChatGPT / Gemini 網頁分析並自動歸檔。
- AI 分析紀錄：保存 ChatGPT / Gemini / Codex 原始回覆、prompt、來源檔 SHA-256 與引用覆核筆記。
- 資安檢查：檢查資料庫、CSV、HTML、純文字與爬蟲紀錄。

## 雲端公開版部署

第一階段建議採「公開評議書上雲、私人案件留本機」：

- Streamlit Community Cloud 執行公開搜尋與公開 AI 上傳包。
- GitHub 保存程式與公開資料，例如 `data/cases.csv`、`data/texts/`、`data/raw_html/`、`data/appeal_cases.db`。
- GitHub Actions 定期執行 `scripts/update_public_cases.py`，只更新公開資料並重建 SQLite/FTS。
- 私人案件、上傳原檔、`private_cases.db`、`uploaded_cases/`、`exports/`、ChatGPT/Gemini Playwright 自動化與 browser profile 不上雲。

本機測試雲端公開模式：

```powershell
$env:APP_MODE="cloud_public"
python -m streamlit run app/streamlit_app.py
```

雲端模式會停用私人案件頁面與瀏覽器自動批次，保留公開評議書搜尋、案件閱讀、公開 AI 分析包與 AI 分析紀錄。詳細部署步驟請見 `CLOUD_DEPLOYMENT.md`。

已新增雲端部署檔：

```txt
.streamlit/config.toml
packages.txt
requirements-cloud.txt
.github/workflows/update-public-cases.yml
CLOUD_DEPLOYMENT.md
```

Streamlit Community Cloud 預設會讀取 `requirements.txt`。若要降低免費空間冷啟動與記憶體壓力，可在專門的雲端部署分支使用 `requirements-cloud.txt` 內容作為 `requirements.txt`；本機完整功能仍使用原本的 `requirements.txt`。

## 同步 private 主 repo 與 public 部署 repo

本機 Git 有兩個 remote：

```txt
origin         # private 主 repo：similaitw/teacher-appeal-local-ai
public-deploy # public 部署 repo：similaitw/teacher-appeal-public-app
```

改完程式並 commit 後，先做 dry-run 檢查：

```bash
python scripts/sync_repos.py
```

確認通過後同步推送兩邊：

```bash
python scripts/sync_repos.py --push
```

同步腳本會檢查工作樹是否乾淨、兩個遠端是否存在、遠端是否有本機沒有的 commit、是否誤追蹤私人檔案，並執行語法檢查、pytest、健康檢查與公開資料一致性檢查。Streamlit Cloud 追蹤 public repo，因此推送 `public-deploy` 後線上站會自動重新部署。

## 匯入已去識別化真實評議書

本版本新增私人案件資料庫，與公開評議書資料庫完全分開：

```txt
data/appeal_cases.db   # 公開評議書
private_cases.db       # 私人已去識別化案件
uploaded_cases/        # 私人案件原始檔
exports/<case_uuid>/   # Codex 分析資料包
```

支援 PDF、DOCX、TXT，可一次匯入多份文件到同一案件。匯入時會保留原始檔名、計算 SHA-256 避免重複匯入，並建立 SQLite FTS5 全文索引。PDF 以頁為單位保存頁碼；DOCX 以段落為單位保存段落編號；TXT 以行區塊保存行號。若 PDF 沒有文字層，系統會標示需要 OCR，不會假裝解析成功。

命令列建立案件並匯入：

```bash
python scripts/import_private_case.py report.pdf evidence.docx notes.txt --case-number A-001 --title 已去識別化案件
```

匯入到既有案件：

```bash
python scripts/import_private_case.py another.pdf --case-uuid <case_uuid>
```

Streamlit 介面提供：

- 私人案件管理：建立、編輯、列表、二次確認刪除。
- 匯入案件文件：多檔上傳 PDF / DOCX / TXT，顯示成功、失敗、無文字層與 OCR 提醒。
- 案件文件閱讀：依文件、頁碼、段落或行號瀏覽全文，可搜尋單一案件或全部已去識別化私人案件。
- Codex 分析資料：產生 Markdown 來源包，不摘要、不改寫原文。

## Codex 分析資料包

在 Streamlit「Codex 分析資料」頁籤選擇案件後，可輸出：

```txt
exports/<case_uuid>/
  case_manifest.json
  case_full_context.md
  source_index.csv
```

可選擇三種輸出範圍：

- 全部文件全文。
- 勾選文件。
- 單案搜尋結果。

`case_full_context.md` 只整理來源，不重新編寫或摘要原文，並保留來源標記：

```txt
[來源：D001，第1頁]
[來源：D002，第15段]
[來源：D003，第20至30行]
```

若 PDF 某頁沒有文字層，該頁會保留頁碼並標示：

```txt
[本頁無法擷取文字]
```

`case_manifest.json` 會記錄案件 UUID、案號、標題、案件類型、匯出時間、文件數、單元數與來源檔案清單。`source_index.csv` 會列出 `source_id`、`document_id`、`filename`、`unit_type`、`page_number`、`paragraph_number`、`line_start`、`line_end`，供後續引用核對。

如需分析，請先產生 Markdown 分析包或公開 AI 上傳包，再交由 ChatGPT、Gemini 或 Codex 分析並回存「AI 分析紀錄」。

## 常見錯誤排除

- `data/appeal_cases.db` 不存在：先執行 `python scripts/build_db.py`。
- 搜尋不到資料：先確認 `data/cases.csv` 是否已有案件，可先跑 `python scripts/crawl_appeal.py --cid 114070228`。
- 教育部網站 timeout：稍後重試，或先手動整理 cid 清單後使用 `--cid-file`。本工具不暴力掃描 cid。
- 關鍵字 POST 沒有結果：可能是 ASP.NET 表單欄位或驗證規則異動，請改用 `--cid` / `--cid-file`。
- AI 回答沒有標示 cid：系統會提示需人工覆核，正式引用前請回到來源片段或案件全文確認。

## 專案結構

```txt
data/
  raw_html/
  texts/
  exports/
  cases.csv
  appeal_cases.db
scripts/
  crawl_appeal.py
  build_db.py
  search_db.py
  llm.py
  utils.py
app/
  streamlit_app.py
keywords.txt
requirements.txt
.env.example
README.md
STATUS.md
```
