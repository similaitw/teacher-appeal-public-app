from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
PRIVATE_DB_PATH = ROOT_DIR / "private_cases.db"
UPLOADED_CASES_DIR = ROOT_DIR / "uploaded_cases"
PRIVATE_EXPORTS_DIR = ROOT_DIR / "exports"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS private_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_uuid TEXT UNIQUE NOT NULL,
    case_number TEXT,
    title TEXT,
    case_type TEXT,
    description TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS private_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    mime_type TEXT,
    sha256 TEXT UNIQUE NOT NULL,
    file_size INTEGER NOT NULL,
    imported_at TEXT,
    parse_status TEXT,
    parse_error TEXT,
    FOREIGN KEY(case_id) REFERENCES private_cases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS private_document_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    unit_type TEXT NOT NULL,
    page_number INTEGER,
    paragraph_number INTEGER,
    line_start INTEGER,
    line_end INTEGER,
    content TEXT,
    normalized_content TEXT,
    FOREIGN KEY(document_id) REFERENCES private_documents(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS private_document_units_fts USING fts5(
    unit_id UNINDEXED,
    document_id UNINDEXED,
    case_uuid UNINDEXED,
    content,
    normalized_content
);
"""


@dataclass
class ParsedUnit:
    unit_type: str
    content: str
    page_number: int | None = None
    paragraph_number: int | None = None
    line_start: int | None = None
    line_end: int | None = None


def utc_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_private_dirs() -> None:
    UPLOADED_CASES_DIR.mkdir(parents=True, exist_ok=True)
    PRIVATE_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def connect(db_path: Path = PRIVATE_DB_PATH) -> sqlite3.Connection:
    ensure_private_dirs()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_private_db(db_path: Path = PRIVATE_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_private_cases_uuid ON private_cases(case_uuid)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_private_documents_case_id ON private_documents(case_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_private_units_document_id ON private_document_units(document_id)")
        conn.commit()


def normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def safe_filename(filename: str) -> str:
    name = Path(filename or "document").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    if not name:
        name = "document"
    stem = Path(name).stem[:80] or "document"
    suffix = Path(name).suffix.lower()
    return f"{stem}{suffix}"


def validate_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支援的檔案格式：{suffix or '(無副檔名)'}")
    return suffix


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_case(
    case_number: str = "",
    title: str = "",
    case_type: str = "",
    description: str = "",
    db_path: Path = PRIVATE_DB_PATH,
) -> dict[str, object]:
    init_private_db(db_path)
    now = utc_now()
    case_uuid = str(uuid.uuid4())
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO private_cases (case_uuid, case_number, title, case_type, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (case_uuid, case_number.strip(), title.strip(), case_type.strip(), description.strip(), now, now),
        )
        conn.commit()
        return get_case_by_id(int(cur.lastrowid), db_path) or {}


def update_case(case_id: int, case_number: str, title: str, case_type: str, description: str, db_path: Path = PRIVATE_DB_PATH) -> None:
    init_private_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE private_cases
            SET case_number = ?, title = ?, case_type = ?, description = ?, updated_at = ?
            WHERE id = ?
            """,
            (case_number.strip(), title.strip(), case_type.strip(), description.strip(), utc_now(), case_id),
        )
        conn.commit()


def delete_case(case_id: int, db_path: Path = PRIVATE_DB_PATH) -> None:
    init_private_db(db_path)
    case = get_case_by_id(case_id, db_path)
    with connect(db_path) as conn:
        doc_ids = [row["id"] for row in conn.execute("SELECT id FROM private_documents WHERE case_id = ?", (case_id,)).fetchall()]
        for doc_id in doc_ids:
            conn.execute("DELETE FROM private_document_units_fts WHERE document_id = ?", (doc_id,))
        conn.execute("DELETE FROM private_cases WHERE id = ?", (case_id,))
        conn.commit()
    if case:
        case_dir = UPLOADED_CASES_DIR / str(case["case_uuid"])
        if case_dir.exists():
            shutil.rmtree(case_dir)


def list_cases(db_path: Path = PRIVATE_DB_PATH) -> list[dict[str, object]]:
    init_private_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(d.id) AS document_count
            FROM private_cases c
            LEFT JOIN private_documents d ON d.case_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_case_by_id(case_id: int, db_path: Path = PRIVATE_DB_PATH) -> dict[str, object] | None:
    init_private_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM private_cases WHERE id = ?", (case_id,)).fetchone()
        return dict(row) if row else None


def get_case_by_uuid(case_uuid: str, db_path: Path = PRIVATE_DB_PATH) -> dict[str, object] | None:
    init_private_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM private_cases WHERE case_uuid = ?", (case_uuid,)).fetchone()
        return dict(row) if row else None


def list_documents(case_id: int | None = None, db_path: Path = PRIVATE_DB_PATH) -> list[dict[str, object]]:
    init_private_db(db_path)
    with connect(db_path) as conn:
        if case_id:
            rows = conn.execute("SELECT * FROM private_documents WHERE case_id = ? ORDER BY imported_at, id", (case_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM private_documents ORDER BY imported_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]


def get_document(document_id: int, db_path: Path = PRIVATE_DB_PATH) -> dict[str, object] | None:
    init_private_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM private_documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row) if row else None


def list_units(document_id: int, db_path: Path = PRIVATE_DB_PATH) -> list[dict[str, object]]:
    init_private_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM private_document_units
            WHERE document_id = ?
            ORDER BY COALESCE(page_number, paragraph_number, line_start, id), id
            """,
            (document_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def insert_document_with_units(
    case_id: int,
    original_filename: str,
    stored_filename: str,
    mime_type: str,
    file_sha256: str,
    file_size: int,
    parse_status: str,
    parse_error: str,
    units: list[ParsedUnit],
    db_path: Path = PRIVATE_DB_PATH,
) -> tuple[dict[str, object], bool]:
    init_private_db(db_path)
    now = utc_now()
    case = get_case_by_id(case_id, db_path)
    if not case:
        raise ValueError("找不到私人案件")
    with connect(db_path) as conn:
        existing = conn.execute("SELECT * FROM private_documents WHERE sha256 = ?", (file_sha256,)).fetchone()
        if existing:
            return dict(existing), True
        cur = conn.execute(
            """
            INSERT INTO private_documents
            (case_id, original_filename, stored_filename, mime_type, sha256, file_size, imported_at, parse_status, parse_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (case_id, original_filename, stored_filename, mime_type, file_sha256, file_size, now, parse_status, parse_error),
        )
        document_id = int(cur.lastrowid)
        for unit in units:
            normalized = normalize_text(unit.content)
            unit_cur = conn.execute(
                """
                INSERT INTO private_document_units
                (document_id, unit_type, page_number, paragraph_number, line_start, line_end, content, normalized_content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    unit.unit_type,
                    unit.page_number,
                    unit.paragraph_number,
                    unit.line_start,
                    unit.line_end,
                    unit.content,
                    normalized,
                ),
            )
            unit_id = int(unit_cur.lastrowid)
            conn.execute(
                """
                INSERT INTO private_document_units_fts (unit_id, document_id, case_uuid, content, normalized_content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (unit_id, document_id, str(case["case_uuid"]), unit.content, normalized),
            )
        conn.execute("UPDATE private_cases SET updated_at = ? WHERE id = ?", (now, case_id))
        conn.commit()
        row = conn.execute("SELECT * FROM private_documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row), False


def fts_query(query: str) -> str:
    terms = [term for term in re.split(r"\s+", query.strip()) if term]
    return " OR ".join(f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms)


def search_units(query: str, case_id: int | None = None, limit: int = 50, db_path: Path = PRIVATE_DB_PATH) -> list[dict[str, object]]:
    init_private_db(db_path)
    with connect(db_path) as conn:
        params: list[object] = []
        case_filter = ""
        if case_id:
            case_filter = "AND c.id = ?"
            params.append(case_id)
        if query.strip():
            match_query = fts_query(query)
            try:
                rows = conn.execute(
                    f"""
                    SELECT u.*, d.original_filename, d.id AS doc_id, c.case_uuid, c.title AS case_title,
                           snippet(private_document_units_fts, 3, '...', '...', '...', 18) AS snippet
                    FROM private_document_units_fts
                    JOIN private_document_units u ON u.id = private_document_units_fts.unit_id
                    JOIN private_documents d ON d.id = u.document_id
                    JOIN private_cases c ON c.id = d.case_id
                    WHERE private_document_units_fts MATCH ? {case_filter}
                    ORDER BY u.id
                    LIMIT ?
                    """,
                    [match_query, *params, limit],
                ).fetchall()
                if rows:
                    return [dict(row) for row in rows]
            except sqlite3.Error:
                pass
        like_params: list[object] = params[:]
        like_filter = ""
        if query.strip():
            like_filter = "AND u.normalized_content LIKE ?"
            like_params.append(f"%{query.strip()}%")
        rows = conn.execute(
            f"""
            SELECT u.*, d.original_filename, d.id AS doc_id, c.case_uuid, c.title AS case_title,
                   substr(u.normalized_content, 1, 220) AS snippet
            FROM private_document_units u
            JOIN private_documents d ON d.id = u.document_id
            JOIN private_cases c ON c.id = d.case_id
            WHERE 1 = 1 {case_filter} {like_filter}
            ORDER BY u.id
            LIMIT ?
            """,
            [*like_params, limit],
        ).fetchall()
        return [dict(row) for row in rows]


def source_label(document_code: str, unit: dict[str, object]) -> str:
    unit_type = unit.get("unit_type")
    if unit_type == "pdf_page":
        return f"來源：{document_code}，第{unit.get('page_number')}頁"
    if unit_type == "docx_paragraph":
        return f"來源：{document_code}，第{unit.get('paragraph_number')}段"
    if unit_type == "txt_lines":
        return f"來源：{document_code}，第{unit.get('line_start')}至{unit.get('line_end')}行"
    return f"來源：{document_code}"


def unit_heading(unit: dict[str, object]) -> str:
    if unit.get("unit_type") == "pdf_page":
        return f"### 第 {unit.get('page_number')} 頁"
    if unit.get("unit_type") == "docx_paragraph":
        return f"### 第 {unit.get('paragraph_number')} 段"
    if unit.get("unit_type") == "txt_lines":
        return f"### 第 {unit.get('line_start')} 至 {unit.get('line_end')} 行"
    return "### 文件單元"


def document_unit_count(document_id: int, db_path: Path = PRIVATE_DB_PATH) -> int:
    return len(list_units(document_id, db_path))


def document_type_label(document: dict[str, object]) -> str:
    filename = str(document.get("original_filename") or "")
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix.upper() if suffix else str(document.get("mime_type") or "")


def export_analysis_package(
    case_id: int,
    query: str = "",
    full_context: bool = True,
    document_ids: list[int] | None = None,
    db_path: Path = PRIVATE_DB_PATH,
) -> Path:
    init_private_db(db_path)
    case = get_case_by_id(case_id, db_path)
    if not case:
        raise ValueError("找不到私人案件")
    export_time = utc_now()
    out_dir = PRIVATE_EXPORTS_DIR / str(case["case_uuid"])
    out_dir.mkdir(parents=True, exist_ok=True)
    all_documents = list_documents(case_id, db_path)
    if not all_documents:
        raise ValueError("此案件尚未匯入任何文件，無法產生 Codex 分析包")

    selected_unit_ids: set[int] | None = None
    allowed_document_ids: set[int] | None = set(document_ids) if document_ids else None
    if not full_context and query.strip():
        selected = search_units(query, case_id=case_id, limit=200, db_path=db_path)
        selected_unit_ids = {int(row["id"]) for row in selected}
        allowed_document_ids = {int(row["document_id"]) for row in selected}
    documents = [doc for doc in all_documents if allowed_document_ids is None or int(doc["id"]) in allowed_document_ids]
    if not documents:
        raise ValueError("沒有符合輸出條件的文件或搜尋結果")

    doc_codes = {int(doc["id"]): f"D{index:03d}" for index, doc in enumerate(sorted(documents, key=lambda item: int(item["id"])), start=1)}
    index_rows: list[dict[str, object]] = []
    content_lines = [
        "# 案件基本資料",
        "",
        f"- 案件編號：{case.get('case_number', '')}",
        f"- 案件名稱：{case.get('title', '')}",
        f"- 案件類型：{case.get('case_type', '')}",
        f"- 匯出時間：{export_time}",
        "",
        "# 文件清單",
        "",
        "| 文件代號 | 原始檔名 | 文件類型 | 頁數或段落數 |",
        "|---|---|---|---|",
    ]
    for doc in sorted(documents, key=lambda item: int(item["id"])):
        doc_id = int(doc["id"])
        content_lines.append(
            f"| {doc_codes[doc_id]} | {doc.get('original_filename', '')} | {document_type_label(doc)} | {document_unit_count(doc_id, db_path)} |"
        )
    content_lines.extend(["", "# 文件內容", ""])

    for doc in sorted(documents, key=lambda item: int(item["id"])):
        doc_id = int(doc["id"])
        code = doc_codes[doc_id]
        content_lines.extend(["", f"## 文件 {code}：{doc.get('original_filename', '')}", ""])
        for unit in list_units(doc_id, db_path):
            if selected_unit_ids is not None and int(unit["id"]) not in selected_unit_ids:
                continue
            label = source_label(code, unit)
            body = str(unit.get("content") or "")
            if unit.get("unit_type") == "pdf_page" and not body.strip():
                body = "[本頁無法擷取文字]"
            content_lines.extend([unit_heading(unit), "", f"[{label}]", "", body, ""])
            index_rows.append(
                {
                    "source_id": code,
                    "document_id": doc_id,
                    "filename": doc.get("original_filename", ""),
                    "unit_type": unit.get("unit_type", ""),
                    "page_number": unit.get("page_number", "") or "",
                    "paragraph_number": unit.get("paragraph_number", "") or "",
                    "line_start": unit.get("line_start", "") or "",
                    "line_end": unit.get("line_end", "") or "",
                }
            )
    manifest = {
        "case_uuid": case.get("case_uuid", ""),
        "case_number": case.get("case_number", ""),
        "title": case.get("title", ""),
        "case_type": case.get("case_type", ""),
        "export_time": export_time,
        "document_count": len(documents),
        "unit_count": len(index_rows),
        "source_files": [
            {
                "source_id": doc_codes[int(doc["id"])],
                "document_id": int(doc["id"]),
                "filename": doc.get("original_filename", ""),
                "mime_type": doc.get("mime_type", ""),
                "parse_status": doc.get("parse_status", ""),
            }
            for doc in sorted(documents, key=lambda item: int(item["id"]))
        ],
    }
    (out_dir / "case_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    full_context_text = "\n".join(content_lines)
    (out_dir / "case_full_context.md").write_text(full_context_text, encoding="utf-8")
    with (out_dir / "source_index.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        fieldnames = ["source_id", "document_id", "filename", "unit_type", "page_number", "paragraph_number", "line_start", "line_end"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(index_rows)
    return out_dir
