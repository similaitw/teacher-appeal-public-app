# 雲端公開版部署指南

本專案第一階段雲端部署採「公開評議書上雲、私人案件留本機」。

## 部署目標

- Streamlit Community Cloud 執行 `app/streamlit_app.py`
- GitHub 保存程式與公開資料
- GitHub Actions 定期執行公開資料更新
- 私人案件、上傳原檔、瀏覽器 profile、ChatGPT/Gemini 自動化批次不放上雲端

## Streamlit Cloud 設定

在 Streamlit Community Cloud 建立 app：

- Repository：`similaitw/teacher-appeal-public-app`
- Branch：`main`
- Main file path：`app/streamlit_app.py`
- Python version：建議選 `3.11`
- App URL：可自訂，例如 `teacher-appeal-local-ai`

在 App secrets 或環境變數設定：

```toml
APP_MODE = "cloud_public"
```

部署操作：

1. 開啟 `https://share.streamlit.io/` 並以 GitHub 帳號登入。
2. 右上角選擇 `Create app`。
3. 選擇 `Yup, I have an app`。
4. 填入上方 Repository、Branch 與 Main file path。
5. 點 `Advanced settings`，選擇 Python `3.11`，並在 Secrets 欄貼上 `APP_MODE = "cloud_public"`。
6. 儲存後點 `Deploy`。

若要使用較輕量的雲端依賴，可在部署分支將 `requirements-cloud.txt` 內容作為 `requirements.txt` 使用。本機完整功能仍建議保留原 `requirements.txt`。

## 雲端公開版會保留

- 公開評議書搜尋
- 公開案件閱讀
- 公開 AI 分析包下載
- AI 分析結果手動保存
- 公開資料更新紀錄檢視

## 雲端公開版會停用

- 私人案件管理
- 私人文件匯入
- 私人文件閱讀
- 私人 Codex 分析資料包
- ChatGPT/Gemini Playwright 網頁批次
- 本機 AJAX 批次儀表板

## GitHub Actions 更新公開資料

已提供 workflow：

```txt
.github/workflows/update-public-cases.yml
```

它會：

1. 安裝雲端公開版依賴。
2. 執行 `python scripts/update_public_cases.py --sleep 1.5`。
3. 重建 `data/appeal_cases.db`。
4. 若公開資料有變更，自動 commit。

可在 GitHub Actions 頁面手動執行，也會依排程每日執行。

## 不要提交到雲端的資料

以下資料應保留在 `.gitignore`：

```txt
uploaded_cases/
exports/
data/ai_exports/
data/update_runs/
browser_profiles/
private_cases.db
*.db-wal
*.db-shm
```

## 本機測試雲端模式

PowerShell：

```powershell
$env:APP_MODE="cloud_public"
python -m streamlit run app/streamlit_app.py
```

一般回歸測試：

```powershell
python -m pytest
python scripts/search_db.py 導師 --limit 5
```
