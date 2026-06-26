from __future__ import annotations

import sqlite3

from utils import CASES_CSV, CASE_FIELDS, DB_PATH, ensure_dirs, read_cases_csv


CREATE_CASES_SQL = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cid TEXT UNIQUE,
    url TEXT,
    matched_keywords TEXT,
    title TEXT,
    case_type TEXT,
    issue_type TEXT,
    result TEXT,
    year TEXT,
    date_text TEXT,
    doc_no TEXT,
    text_path TEXT,
    html_path TEXT,
    full_text TEXT,
    created_at TEXT,
    updated_at TEXT
);
"""

CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS cases_fts USING fts5(
    cid,
    title,
    case_type,
    issue_type,
    result,
    matched_keywords,
    full_text
);
"""


def main() -> None:
    ensure_dirs()
    rows = read_cases_csv()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DROP TABLE IF EXISTS cases_fts")
        conn.execute(CREATE_CASES_SQL)
        conn.execute("DELETE FROM cases")
        conn.execute(CREATE_FTS_SQL)

        placeholders = ", ".join("?" for _ in CASE_FIELDS)
        columns = ", ".join(CASE_FIELDS)
        for row in rows:
            values = [row.get(field, "") for field in CASE_FIELDS]
            conn.execute(f"INSERT OR REPLACE INTO cases ({columns}) VALUES ({placeholders})", values)
            conn.execute(
                """
                INSERT INTO cases_fts (cid, title, case_type, issue_type, result, matched_keywords, full_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("cid", ""),
                    row.get("title", ""),
                    row.get("case_type", ""),
                    row.get("issue_type", ""),
                    row.get("result", ""),
                    row.get("matched_keywords", ""),
                    row.get("full_text", ""),
                ),
            )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_cid ON cases(cid)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_year ON cases(year)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_result ON cases(result)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_issue_type ON cases(issue_type)")
        conn.commit()
    finally:
        conn.close()
    print(f"已建立資料庫：{DB_PATH}")
    print(f"匯入案件數：{len(rows)}")


if __name__ == "__main__":
    main()
