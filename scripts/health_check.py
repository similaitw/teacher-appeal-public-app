from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from llm import OllamaConfig, check_ollama, list_ollama_models
from utils import CASES_CSV, DB_PATH, ERROR_LOG, RAW_HTML_DIR, TEXTS_DIR, read_cases_csv


def count_rows() -> int:
    if not DB_PATH.exists():
        return 0
    conn = sqlite3.connect(DB_PATH)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0])
    finally:
        conn.close()


def run_health_check(model: str = "qwen2.5:7b", base_url: str = "http://localhost:11434", check_ai: bool = True) -> list[tuple[str, str, str]]:
    checks: list[tuple[str, str, str]] = []

    cases_rows = len(read_cases_csv()) if CASES_CSV.exists() else 0
    db_rows = count_rows()
    checks.append(("資料庫", "PASS" if DB_PATH.exists() and db_rows > 0 else "WARN", f"SQLite 案件數：{db_rows}"))
    checks.append(("CSV", "PASS" if cases_rows > 0 else "WARN", f"cases.csv 案件數：{cases_rows}"))
    checks.append(("原始 HTML", "PASS" if any(RAW_HTML_DIR.glob('*.html')) else "WARN", f"HTML 檔案數：{len(list(RAW_HTML_DIR.glob('*.html')))}"))
    checks.append(("純文字", "PASS" if any(TEXTS_DIR.glob('*.txt')) else "WARN", f"文字檔案數：{len(list(TEXTS_DIR.glob('*.txt')))}"))

    if cases_rows != db_rows:
        checks.append(("同步狀態", "WARN", "CSV 與 SQLite 筆數不同，建議重新執行 python scripts/build_db.py"))
    else:
        checks.append(("同步狀態", "PASS", "CSV 與 SQLite 筆數一致"))

    if ERROR_LOG.exists() and ERROR_LOG.stat().st_size > 0:
        last_lines = ERROR_LOG.read_text(encoding="utf-8").splitlines()[-3:]
        checks.append(("爬蟲紀錄", "WARN", "最近紀錄：" + " | ".join(last_lines)))
    else:
        checks.append(("爬蟲紀錄", "PASS", "沒有錯誤紀錄"))

    if not check_ai:
        checks.append(("Ollama", "WARN", "已暫時停用，未執行連線檢查"))
    else:
        models_ok, models_text = list_ollama_models(base_url)
        if models_ok:
            config = OllamaConfig(model=model, base_url=base_url)
            ok, message = check_ollama(config)
            checks.append(("Ollama", "PASS" if ok else "WARN", message if ok else f"{message}；可用模型：{models_text.replace(chr(10), '、')}"))
        else:
            checks.append(("Ollama", "WARN", models_text))

    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="檢查教師申訴本機查詢系統狀態")
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--skip-ai", action="store_true", help="不檢查 Ollama")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for name, status, detail in run_health_check(model=args.model, base_url=args.base_url, check_ai=not args.skip_ai):
        print(f"[{status}] {name}: {detail}")


if __name__ == "__main__":
    main()
