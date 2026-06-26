from __future__ import annotations

import csv
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RAW_HTML_DIR = DATA_DIR / "raw_html"
TEXTS_DIR = DATA_DIR / "texts"
EXPORTS_DIR = DATA_DIR / "exports"
CASES_CSV = DATA_DIR / "cases.csv"
DB_PATH = DATA_DIR / "appeal_cases.db"
ERROR_LOG = DATA_DIR / "crawl_errors.log"
BASE_URL = "https://appeal.moe.gov.tw/"
SEARCH_URL = urljoin(BASE_URL, "appraise_search.aspx")
VIEW_URL_TEMPLATE = urljoin(BASE_URL, "appraise_view.aspx?cid={cid}")

CASE_FIELDS = [
    "cid",
    "url",
    "matched_keywords",
    "title",
    "case_type",
    "issue_type",
    "result",
    "year",
    "date_text",
    "doc_no",
    "text_path",
    "html_path",
    "full_text",
    "created_at",
    "updated_at",
]


def ensure_dirs() -> None:
    for path in (RAW_HTML_DIR, TEXTS_DIR, EXPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    if not CASES_CSV.exists():
        with CASES_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=CASE_FIELDS)
            writer.writeheader()


def clean_text(html_or_text: str) -> str:
    if not html_or_text:
        return ""
    soup = BeautifulSoup(html_or_text, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n") if soup.find() else html_or_text
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_cid_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    query_cid = parse_qs(parsed.query).get("cid", [None])[0]
    if query_cid:
        return re.sub(r"\D", "", query_cid) or query_cid
    match = re.search(r"cid=([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def _first_match(patterns: Iterable[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            return match.group(1).strip(" ：:\t")
    return ""


def infer_result(text: str) -> str:
    candidates = [
        "申訴有理由",
        "申訴無理由",
        "原措施撤銷",
        "撤銷原措施",
        "不受理",
        "駁回",
    ]
    for item in candidates:
        if item in text:
            return item
    return ""


def infer_issue_type(text: str) -> str:
    categories = [
        ("導師職務", ["導師", "生活輔導"]),
        ("成績考核", ["成績考核", "考核"]),
        ("懲處", ["懲處", "申誡", "記過"]),
        ("解聘停聘不續聘", ["解聘", "停聘", "不續聘"]),
        ("寒暑假／課後輔導", ["寒暑假", "課後輔導", "早自習"]),
        ("工作分配", ["工作分配", "職務分配"]),
    ]
    hits = [name for name, words in categories if any(word in text for word in words)]
    return "、".join(hits)


def parse_case_metadata(html: str, cid: str, matched_keywords: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    text = clean_text(html)
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    title = re.sub(r"-?教育部教師申訴案件查詢系統", "", title).strip()
    if not title or title in {"教育部訴願案件查詢系統", "教育部教師申訴案件查詢系統"}:
        title = _first_match([r"(\d{8,12}\s*評議書)", r"(教師申訴評議書)"], text)

    date_text = _first_match(
        [
            r"(?:日期|評議日期|決定日期|公告日期)\s*[：:]\s*([^\n]+)",
            r"(\d{2,3}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
        ],
        text,
    )
    year = _first_match([r"(\d{2,3})\s*年"], date_text or text)
    doc_no = _first_match(
        [
            r"(?:文號|案號|評議書字號|決定書字號)\s*[：:]\s*([^\n]+)",
            r"([臺台]教[^\n]{3,35}字第\s*\d+\s*號)",
        ],
        text,
    )
    case_type = _first_match(
        [r"(?:案件類型|申訴類型|類別)\s*[：:]\s*([^\n]+)", r"(教師申訴評議書)"],
        text,
    )
    if not case_type and "評議書" in title:
        case_type = "教師申訴評議書"

    return {
        "cid": cid,
        "url": VIEW_URL_TEMPLATE.format(cid=cid),
        "matched_keywords": matched_keywords,
        "title": title or f"cid={cid}",
        "case_type": case_type,
        "issue_type": infer_issue_type(text),
        "result": infer_result(text),
        "year": year,
        "date_text": date_text,
        "doc_no": doc_no,
        "text_path": str((TEXTS_DIR / f"{cid}.txt").relative_to(ROOT_DIR)),
        "html_path": str((RAW_HTML_DIR / f"{cid}.html").relative_to(ROOT_DIR)),
        "full_text": text,
    }


def save_text(cid: str, html: str) -> str:
    path = TEXTS_DIR / f"{cid}.txt"
    path.write_text(clean_text(html), encoding="utf-8")
    return str(path)


def load_keywords(path: str | Path) -> list[str]:
    keyword_path = Path(path)
    if not keyword_path.is_absolute():
        keyword_path = ROOT_DIR / keyword_path
    if not keyword_path.exists():
        return []
    return [line.strip() for line in keyword_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_log(message: str) -> None:
    ensure_dirs()
    timestamp = datetime.now().isoformat(timespec="seconds")
    with ERROR_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"[{timestamp}] {message}\n")


def read_cases_csv() -> list[dict[str, str]]:
    ensure_dirs()
    with CASES_CSV.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def upsert_cases_csv(new_rows: list[dict[str, str]]) -> None:
    ensure_dirs()
    existing = {row.get("cid", ""): row for row in read_cases_csv() if row.get("cid")}
    now = datetime.now().isoformat(timespec="seconds")
    for row in new_rows:
        cid = row["cid"]
        previous = existing.get(cid, {})
        merged = {field: row.get(field, previous.get(field, "")) for field in CASE_FIELDS}
        merged["created_at"] = previous.get("created_at") or now
        merged["updated_at"] = now
        existing[cid] = merged
    with CASES_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CASE_FIELDS)
        writer.writeheader()
        writer.writerows(existing.values())


def _fts_query(query: str) -> str:
    terms = [term for term in re.split(r"\s+", query.strip()) if term]
    return " OR ".join(f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms)


def make_snippet(text: str, query: str, length: int = 140) -> str:
    flat = re.sub(r"\s+", " ", text or "")
    terms = [term for term in re.split(r"\s+", query.strip()) if term]
    positions = [flat.find(term) for term in terms if term in flat]
    start = max(min(positions) - 45, 0) if positions else 0
    snippet = flat[start : start + length]
    return ("..." if start else "") + snippet + ("..." if start + length < len(flat) else "")


def search_fts(
    query: str = "",
    db_path: str | Path = DB_PATH,
    limit: int = 20,
    year: str = "",
    case_type: str = "",
    result: str = "",
) -> list[dict[str, str]]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    params: list[str | int] = []
    filters = []
    if year:
        filters.append("c.year = ?")
        params.append(year)
    if case_type:
        filters.append("c.case_type = ?")
        params.append(case_type)
    if result:
        filters.append("c.result = ?")
        params.append(result)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    def like_search() -> list[sqlite3.Row]:
        like_filters = filters[:]
        like_params: list[str | int] = params[:]
        if query.strip():
            for term in re.split(r"\s+", query.strip()):
                like_filters.append("(c.title LIKE ? OR c.full_text LIKE ? OR c.matched_keywords LIKE ?)")
                like_params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
        like_where = ("WHERE " + " AND ".join(like_filters)) if like_filters else ""
        return conn.execute(f"SELECT c.*, substr(c.full_text, 1, 180) AS snippet FROM cases c {like_where} LIMIT ?", [*like_params, limit]).fetchall()

    try:
        if query.strip():
            match_query = _fts_query(query)
            sql = f"""
                SELECT c.*, snippet(cases_fts, 6, '...', '...', '...', 18) AS snippet,
                       bm25(cases_fts) AS rank_score
                FROM cases_fts
                JOIN cases c ON c.cid = cases_fts.cid
                {"WHERE cases_fts MATCH ? AND " + " AND ".join(filters) if filters else "WHERE cases_fts MATCH ?"}
                ORDER BY rank_score
                LIMIT ?
            """
            rows = conn.execute(sql, [match_query, *params, limit]).fetchall()
            if not rows:
                rows = like_search()
        else:
            rows = conn.execute(f"SELECT c.*, substr(c.full_text, 1, 180) AS snippet FROM cases c {where} ORDER BY c.updated_at DESC LIMIT ?", [*params, limit]).fetchall()
    except sqlite3.Error:
        rows = like_search()
    finally:
        conn.close()

    results = []
    for row in rows:
        item = dict(row)
        terms = [term for term in re.split(r"\s+", query.strip()) if term]
        if not item.get("snippet") or (terms and not any(term in item.get("snippet", "") for term in terms)):
            item["snippet"] = make_snippet(item.get("full_text", ""), query)
        results.append(item)
    return results


def get_case_by_cid(cid: str, db_path: str | Path = DB_PATH) -> dict[str, str] | None:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM cases WHERE cid = ?", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None
