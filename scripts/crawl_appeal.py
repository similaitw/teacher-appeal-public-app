from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.exceptions import SSLError

from utils import (
    DATA_DIR,
    RAW_HTML_DIR,
    SEARCH_URL,
    TEXTS_DIR,
    VIEW_URL_TEMPLATE,
    ensure_dirs,
    extract_cid_from_url,
    load_keywords,
    parse_case_metadata,
    read_cases_csv,
    save_text,
    upsert_cases_csv,
    write_log,
)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/125.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DISCOVERED_CIDS_PATH = DATA_DIR / "discovered_cids.txt"
DOWNLOADED_CIDS_PATH = DATA_DIR / "downloaded_cids.txt"
FAILED_CIDS_PATH = DATA_DIR / "failed_cids.txt"
CRAWL_STATE_PATH = DATA_DIR / "crawl_state.json"
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    verify_ssl: bool = True,
    allow_ssl_fallback: bool = True,
    **kwargs,
) -> requests.Response:
    last_error: Exception | None = None
    verify = verify_ssl
    for attempt in range(5):
        try:
            response = session.request(method, url, timeout=60, headers=HEADERS, verify=verify, **kwargs)
            if response.status_code in TRANSIENT_STATUS_CODES:
                delay = min(60, 2**attempt)
                write_log(f"{method} {url} transient status={response.status_code}; retrying in {delay}s")
                time.sleep(delay)
                continue
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            return response
        except SSLError as exc:
            last_error = exc
            if verify and allow_ssl_fallback:
                write_log(f"{method} {url} SSL verification failed; retrying with verify=False: {exc}")
                verify = False
                continue
            write_log(f"{method} {url} failed attempt={attempt + 1}: {exc}")
            time.sleep(min(60, 2**attempt))
        except Exception as exc:  # requests exposes several transient exception classes.
            last_error = exc
            write_log(f"{method} {url} failed attempt={attempt + 1}: {exc}")
            time.sleep(min(60, 2**attempt))
    raise RuntimeError(f"request failed after retries: {url}") from last_error


def form_fields(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    fields = {}
    for node in soup.find_all("input"):
        name = node.get("name")
        input_type = (node.get("type") or "").lower()
        if name and input_type not in {"submit", "button", "image"}:
            fields[name] = node.get("value", "")
    for node in soup.find_all("select"):
        name = node.get("name")
        if not name:
            continue
        selected = node.find("option", selected=True) or node.find("option")
        fields[name] = selected.get("value", "") if selected else ""
    return fields


def hidden_fields(html: str) -> dict[str, str]:
    fields = form_fields(html)
    return {name: fields.get(name, "") for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION") if name in fields}


def collect_cids_from_html(html: str) -> set[str]:
    cids: set[str] = set()
    soup = BeautifulSoup(html, "lxml")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "appraise_view.aspx" in href and "cid=" in href:
            cid = extract_cid_from_url(urljoin(SEARCH_URL, href))
            if cid:
                cids.add(cid)
    for cid in re.findall(r"appraise_view\.aspx\?cid=([A-Za-z0-9_-]+)", html):
        cids.add(cid)
    return cids


def parse_pager(html: str) -> tuple[int, int, int]:
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    page_match = re.search(r"第\s*(\d+)\s*/\s*(\d+)\s*頁", text)
    count_match = re.search(r"共\s*(\d+)\s*筆", text)
    current_page = int(page_match.group(1)) if page_match else 1
    total_pages = int(page_match.group(2)) if page_match else 1
    total_records = int(count_match.group(1)) if count_match else len(collect_cids_from_html(html))
    return current_page, total_pages, total_records


def has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    for link in soup.find_all("a", href=True):
        if "ucPager$butNext" in link["href"]:
            return True
    return False


def read_cid_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    cids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cid = line.strip()
        if cid:
            cids.append(cid)
    return list(dict.fromkeys(cids))


def write_cid_file(path: Path, cids: list[str] | set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    unique = list(dict.fromkeys(str(cid).strip() for cid in cids if str(cid).strip()))
    path.write_text("\n".join(unique) + ("\n" if unique else ""), encoding="utf-8")


def append_cids(path: Path, cids: set[str] | list[str]) -> None:
    existing = read_cid_file(path)
    write_cid_file(path, [*existing, *list(cids)])


def save_crawl_state(**kwargs) -> None:
    state = {}
    if CRAWL_STATE_PATH.exists():
        try:
            state = json.loads(CRAWL_STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    state.update(kwargs)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    CRAWL_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def successful_cids() -> set[str]:
    cids = set(read_cid_file(DOWNLOADED_CIDS_PATH))
    for row in read_cases_csv():
        if row.get("cid"):
            cids.add(row["cid"])
    for path in list(TEXTS_DIR.glob("*.txt")) + list(RAW_HTML_DIR.glob("*.html")):
        if path.stem:
            cids.add(path.stem)
    return cids


def indexed_cids() -> set[str]:
    return {row["cid"] for row in read_cases_csv() if row.get("cid")}


def cached_case_row(cid: str, matched_keywords: str = "") -> dict[str, str] | None:
    html_path = RAW_HTML_DIR / f"{cid}.html"
    text_path = TEXTS_DIR / f"{cid}.txt"
    if html_path.exists():
        return parse_case_metadata(html_path.read_text(encoding="utf-8"), cid, matched_keywords)
    if text_path.exists():
        return parse_case_metadata(text_path.read_text(encoding="utf-8"), cid, matched_keywords)
    return None


def current_roc_year_end() -> str:
    year = datetime.now().year - 1911
    return f"{year:03d}1231"


def search_all_public_cids(
    session: requests.Session,
    sleep_seconds: float,
    limit: int = 0,
    verify_ssl: bool = True,
    allow_ssl_fallback: bool = True,
) -> list[str]:
    response = request_with_retry(session, "GET", SEARCH_URL, verify_ssl=verify_ssl, allow_ssl_fallback=allow_ssl_fallback)
    payload = form_fields(response.text)
    payload.update(
        {
            "ctl00$cphContent$txtSDate": "0010101",
            "ctl00$cphContent$txtEDate": current_roc_year_end(),
            "ctl00$cphContent$ddlReasonID": "",
            "ctl00$cphContent$txtKW1": "",
            "ctl00$cphContent$ddlOper1": "1",
            "ctl00$cphContent$txtKW2": "",
            "ctl00$cphContent$ddlOper2": "1",
            "ctl00$cphContent$txtKW3": "",
            "ctl00$cphContent$butSearch": "查詢",
        }
    )
    time.sleep(sleep_seconds)
    page = request_with_retry(session, "POST", SEARCH_URL, verify_ssl=verify_ssl, allow_ssl_fallback=allow_ssl_fallback, data=payload)
    all_cids: list[str] = []
    page_index = 1
    while True:
        page_cids = sorted(collect_cids_from_html(page.text))
        all_cids = list(dict.fromkeys([*all_cids, *page_cids]))
        current_page, total_pages, total_records = parse_pager(page.text)
        append_cids(DISCOVERED_CIDS_PATH, page_cids)
        save_crawl_state(
            mode="all",
            current_page=current_page,
            total_pages=total_pages,
            total_records=total_records,
            discovered_count=len(all_cids),
            discovery_complete=False,
            date_start="0010101",
            date_end=current_roc_year_end(),
        )
        print(f"discover page {current_page}/{total_pages}: page_cids={len(page_cids)} total_discovered={len(all_cids)} records={total_records}")
        if limit and len(all_cids) >= limit:
            return all_cids[:limit]
        if current_page >= total_pages or not has_next_page(page.text):
            save_crawl_state(discovery_complete=True, discovered_count=len(all_cids))
            return all_cids
        next_payload = form_fields(page.text)
        next_payload["__EVENTTARGET"] = "ctl00$cphContent$ucPager$butNext"
        next_payload["__EVENTARGUMENT"] = ""
        next_payload.pop("ctl00$cphContent$butSearch", None)
        time.sleep(sleep_seconds)
        page = request_with_retry(session, "POST", SEARCH_URL, verify_ssl=verify_ssl, allow_ssl_fallback=allow_ssl_fallback, data=next_payload)
        page_index += 1


def collect_resume_cids(
    session: requests.Session,
    sleep_seconds: float,
    limit: int = 0,
    verify_ssl: bool = True,
    allow_ssl_fallback: bool = True,
) -> list[str]:
    cids = read_cid_file(DISCOVERED_CIDS_PATH)
    state = {}
    if CRAWL_STATE_PATH.exists():
        try:
            state = json.loads(CRAWL_STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    if cids and not state.get("discovery_complete") and not limit:
        print("resume found incomplete discovery state; collecting all pages again before downloading")
        return search_all_public_cids(session, sleep_seconds, limit, verify_ssl, allow_ssl_fallback)
    if cids:
        print(f"resume using saved discovered cid list: {len(cids)}")
        return cids[:limit] if limit else cids
    print("resume found no discovered cid list; collecting with --all first")
    return search_all_public_cids(session, sleep_seconds, limit, verify_ssl, allow_ssl_fallback)


def search_keyword(session: requests.Session, keyword: str, verify_ssl: bool = True, allow_ssl_fallback: bool = True) -> set[str]:
    response = request_with_retry(session, "GET", SEARCH_URL, verify_ssl=verify_ssl, allow_ssl_fallback=allow_ssl_fallback)
    payload = form_fields(response.text)
    payload.update(
        {
            "ctl00$cphContent$txtSDate": "",
            "ctl00$cphContent$txtEDate": "",
            "ctl00$cphContent$ddlReasonID": "",
            "ctl00$cphContent$txtKW1": keyword,
            "ctl00$cphContent$ddlOper1": "1",
            "ctl00$cphContent$txtKW2": "",
            "ctl00$cphContent$ddlOper2": "1",
            "ctl00$cphContent$txtKW3": "",
            "ctl00$cphContent$butSearch": "查詢",
        }
    )
    post = request_with_retry(session, "POST", SEARCH_URL, verify_ssl=verify_ssl, allow_ssl_fallback=allow_ssl_fallback, data=payload)
    cids = collect_cids_from_html(post.text)
    if not cids:
        write_log(f"keyword search returned no cids: {keyword}")
    return cids


def download_case(
    session: requests.Session,
    cid: str,
    matched_keywords: str = "",
    verify_ssl: bool = True,
    allow_ssl_fallback: bool = True,
) -> dict[str, str]:
    url = VIEW_URL_TEMPLATE.format(cid=cid)
    response = request_with_retry(session, "GET", url, verify_ssl=verify_ssl, allow_ssl_fallback=allow_ssl_fallback)
    html = response.text
    html_path = RAW_HTML_DIR / f"{cid}.html"
    html_path.write_text(html, encoding="utf-8")
    save_text(cid, html)
    row = parse_case_metadata(html, cid, matched_keywords)
    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取教育部教師申訴評議書公開案件")
    parser.add_argument("--all", action="store_true", help="依公開查詢頁日期區間遍歷所有分頁，收集全部公開 cid")
    parser.add_argument("--resume", action="store_true", help="使用已保存的 discovered_cids.txt 續抓；若不存在則先執行 --all 收集")
    parser.add_argument("--retry-failed", action="store_true", help="只重試 data/failed_cids.txt 內曾下載失敗的 cid")
    parser.add_argument("--keywords-file", default="", help="關鍵字檔案，預設可用 keywords.txt")
    parser.add_argument("--keyword", action="append", default=[], help="單一關鍵字，可重複指定")
    parser.add_argument("--cid", action="append", default=[], help="直接下載指定 cid，可重複指定")
    parser.add_argument("--cid-file", default="", help="每行一個 cid 的清單")
    parser.add_argument("--limit", type=int, default=0, help="小量測試用，限制發現/下載 cid 數；正式抓取請省略")
    parser.add_argument("--sleep", type=float, default=1.5, help="每次請求間隔秒數")
    parser.add_argument("--verify-ssl", action="store_true", help="強制 SSL 憑證驗證，不啟用自動 fallback")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dirs()
    session = requests.Session()
    cid_keywords: dict[str, set[str]] = {}
    allow_ssl_fallback = not args.verify_ssl

    if args.all:
        all_cids = search_all_public_cids(session, args.sleep, args.limit, verify_ssl=True, allow_ssl_fallback=allow_ssl_fallback)
        for cid in all_cids:
            cid_keywords.setdefault(cid, set())

    if args.resume:
        for cid in collect_resume_cids(session, args.sleep, args.limit, verify_ssl=True, allow_ssl_fallback=allow_ssl_fallback):
            cid_keywords.setdefault(cid, set())

    if args.retry_failed:
        failed_cids = read_cid_file(FAILED_CIDS_PATH)
        if not failed_cids:
            print("沒有 failed_cids.txt 或沒有待重試 cid。")
        for cid in failed_cids[: args.limit or None]:
            cid_keywords.setdefault(cid, set())

    for cid in args.cid:
        cid_keywords.setdefault(cid.strip(), set())

    if args.cid_file:
        cid_path = Path(args.cid_file)
        for line in cid_path.read_text(encoding="utf-8").splitlines():
            cid = line.strip()
            if cid:
                cid_keywords.setdefault(cid, set())

    keywords = list(args.keyword)
    if args.keywords_file:
        keywords.extend(load_keywords(args.keywords_file))

    for keyword in dict.fromkeys(keywords):
        try:
            cids = search_keyword(session, keyword, verify_ssl=True, allow_ssl_fallback=allow_ssl_fallback)
            for cid in cids:
                cid_keywords.setdefault(cid, set()).add(keyword)
            append_cids(DISCOVERED_CIDS_PATH, sorted(cids))
        except Exception as exc:
            write_log(f"keyword={keyword} search failed: {exc}")
        time.sleep(args.sleep)

    if args.limit and not (args.all or args.resume or args.retry_failed):
        limited = list(cid_keywords.items())[: args.limit]
        cid_keywords = dict(limited)

    already_successful = successful_cids()
    if already_successful:
        print(f"已成功下載 cid：{len(already_successful)}，本次將自動略過。")

    rows = []
    indexed = indexed_cids()
    failed = set(read_cid_file(FAILED_CIDS_PATH))
    for index, (cid, matched) in enumerate(cid_keywords.items(), start=1):
        if not cid:
            continue
        if cid in already_successful:
            if cid not in indexed:
                cached_row = cached_case_row(cid, "、".join(sorted(matched)))
                if cached_row:
                    rows.append(cached_row)
                    indexed.add(cid)
                    print(f"[{index}/{len(cid_keywords)}] repair cached cid={cid} into cases.csv")
                else:
                    print(f"[{index}/{len(cid_keywords)}] skip already downloaded cid={cid}")
            else:
                print(f"[{index}/{len(cid_keywords)}] skip already downloaded cid={cid}")
            failed.discard(cid)
            continue
        try:
            print(f"[{index}/{len(cid_keywords)}] download cid={cid}")
            rows.append(download_case(session, cid, "、".join(sorted(matched)), verify_ssl=True, allow_ssl_fallback=allow_ssl_fallback))
            append_cids(DOWNLOADED_CIDS_PATH, [cid])
            failed.discard(cid)
        except Exception as exc:
            failed.add(cid)
            write_log(f"cid={cid} download failed: {exc}")
            print(f"cid={cid} failed: {exc}")
        write_cid_file(FAILED_CIDS_PATH, sorted(failed))
        time.sleep(args.sleep)

    if rows:
        upsert_cases_csv(rows)
    print(f"完成，新增或更新 {len(rows)} 筆。cases.csv 位於 data/cases.csv")
    print(f"已發現 cid：{len(read_cid_file(DISCOVERED_CIDS_PATH))}；已下載 cid：{len(read_cid_file(DOWNLOADED_CIDS_PATH))}；失敗 cid：{len(read_cid_file(FAILED_CIDS_PATH))}")


if __name__ == "__main__":
    main()
