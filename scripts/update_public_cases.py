from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

from build_db import main as build_public_db
from crawl_appeal import (
    DOWNLOADED_CIDS_PATH,
    FAILED_CIDS_PATH,
    append_cids,
    cached_case_row,
    download_case,
    indexed_cids,
    read_cid_file,
    search_all_public_cids,
    successful_cids,
    write_cid_file,
)
from utils import DATA_DIR, ensure_dirs, upsert_cases_csv, write_log


UPDATE_RUNS_DIR = DATA_DIR / "update_runs"


@dataclass
class UpdateResult:
    run_dir: Path
    manifest: dict[str, object]


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def filesystem_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def write_lines(path: Path, values: list[str] | set[str]) -> None:
    unique = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(unique) + ("\n" if unique else ""), encoding="utf-8")


def create_update_run_dir(output_root: Path = UPDATE_RUNS_DIR) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    base = output_root / filesystem_timestamp()
    run_dir = base
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = output_root / f"{base.name}_{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def update_log(run_dir: Path, message: str) -> None:
    line = f"[{now_text()}] {message}"
    print(line)
    with (run_dir / "stdout.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def update_error(run_dir: Path, message: str) -> None:
    line = f"[{now_text()}] {message}"
    print(line, file=sys.stderr)
    with (run_dir / "stderr.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def select_update_candidates(
    discovered_cids: list[str],
    existing_successful: set[str],
    retry_failed: bool = False,
    limit: int = 0,
) -> tuple[list[str], list[str]]:
    failed_cids = read_cid_file(FAILED_CIDS_PATH) if retry_failed else []
    new_cids = [cid for cid in discovered_cids if cid not in existing_successful]
    candidates = list(dict.fromkeys([*new_cids, *failed_cids]))
    if limit:
        candidates = candidates[:limit]
    return new_cids, candidates


def run_public_update(
    sleep_seconds: float = 1.5,
    limit: int = 0,
    retry_failed: bool = False,
    build_db: bool = True,
    force_verify_ssl: bool = False,
    output_root: Path = UPDATE_RUNS_DIR,
    session_factory: Callable[[], requests.Session] = requests.Session,
    discover_func: Callable[..., list[str]] = search_all_public_cids,
    download_func: Callable[..., dict[str, str]] = download_case,
    build_db_func: Callable[[], None] = build_public_db,
) -> UpdateResult:
    ensure_dirs()
    run_dir = create_update_run_dir(output_root)
    start_time = now_text()
    manifest: dict[str, object] = {
        "run_id": run_dir.name,
        "started_at": start_time,
        "finished_at": "",
        "status": "running",
        "sleep_seconds": sleep_seconds,
        "limit": limit,
        "retry_failed": retry_failed,
        "build_db": build_db,
        "discovered_count": 0,
        "existing_count": 0,
        "new_count": 0,
        "candidate_count": 0,
        "downloaded_count": 0,
        "failed_count": 0,
        "ai_pending_count": 0,
        "repaired_count": 0,
        "build_db_status": "skipped",
    }
    (run_dir / "update_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    session = session_factory()
    downloaded_rows: list[dict[str, str]] = []
    downloaded_cids: list[str] = []
    failed_this_run: list[str] = []
    ai_pending_cids: list[str] = []
    repaired_cids: list[str] = []
    allow_ssl_fallback = not force_verify_ssl

    try:
        update_log(run_dir, "開始檢查教育部公開評議書列表")
        discovered_cids = discover_func(
            session,
            sleep_seconds,
            limit=0,
            verify_ssl=True,
            allow_ssl_fallback=allow_ssl_fallback,
        )
        discovered_cids = list(dict.fromkeys(str(cid).strip() for cid in discovered_cids if str(cid).strip()))
        write_lines(run_dir / "discovered_cids.txt", discovered_cids)

        existing = successful_cids()
        if not discovered_cids and existing:
            raise RuntimeError("公開查詢頁未回傳任何 cid，但本機已有資料；可能是網站表單、查詢條件或連線異常，已停止更新。")
        new_cids, candidates = select_update_candidates(discovered_cids, existing, retry_failed=retry_failed, limit=limit)
        indexed = indexed_cids()
        for cid in discovered_cids:
            if cid in existing and cid not in indexed:
                row = cached_case_row(cid)
                if row:
                    downloaded_rows.append(row)
                    repaired_cids.append(cid)
                    indexed.add(cid)
        write_lines(run_dir / "new_cids.txt", new_cids)
        update_log(
            run_dir,
            f"發現 {len(discovered_cids)} 筆；本機已有 {len(existing)} 筆；新增 {len(new_cids)} 筆；"
            f"本次候選 {len(candidates)} 筆；修補索引 {len(repaired_cids)} 筆",
        )

        failed_global = set(read_cid_file(FAILED_CIDS_PATH))
        for index, cid in enumerate(candidates, start=1):
            try:
                update_log(run_dir, f"[{index}/{len(candidates)}] 下載 cid={cid}")
                row = download_func(session, cid, "", verify_ssl=True, allow_ssl_fallback=allow_ssl_fallback)
                downloaded_rows.append(row)
                downloaded_cids.append(cid)
                append_cids(DOWNLOADED_CIDS_PATH, [cid])
                failed_global.discard(cid)
                if cid in new_cids:
                    ai_pending_cids.append(cid)
            except Exception as exc:
                failed_this_run.append(cid)
                failed_global.add(cid)
                write_log(f"update cid={cid} download failed: {exc}")
                update_error(run_dir, f"cid={cid} 下載失敗：{exc}")
            write_cid_file(FAILED_CIDS_PATH, sorted(failed_global))
            if sleep_seconds > 0 and index < len(candidates):
                time.sleep(sleep_seconds)

        if downloaded_rows:
            upsert_cases_csv(downloaded_rows)
        write_lines(run_dir / "downloaded_cids.txt", downloaded_cids)
        write_lines(run_dir / "failed_cids.txt", failed_this_run)
        write_lines(run_dir / "ai_pending_cids.txt", ai_pending_cids)
        write_lines(run_dir / "repaired_cids.txt", repaired_cids)

        if build_db and downloaded_rows:
            update_log(run_dir, "重建公開 SQLite FTS 資料庫")
            build_db_func()
            manifest["build_db_status"] = "ok"
        elif build_db:
            manifest["build_db_status"] = "skipped_no_changes"

        manifest.update(
            {
                "status": "completed" if not failed_this_run else "completed_with_errors",
                "finished_at": now_text(),
                "discovered_count": len(discovered_cids),
                "existing_count": len(existing),
                "new_count": len(new_cids),
                "candidate_count": len(candidates),
                "downloaded_count": len(downloaded_cids),
                "failed_count": len(failed_this_run),
                "ai_pending_count": len(ai_pending_cids),
                "repaired_count": len(repaired_cids),
            }
        )
        update_log(run_dir, f"更新完成：下載 {len(downloaded_cids)} 筆；失敗 {len(failed_this_run)} 筆；AI pending {len(ai_pending_cids)} 筆")
    except Exception as exc:
        manifest.update({"status": "failed", "finished_at": now_text(), "error": str(exc)})
        update_error(run_dir, f"更新流程失敗：{exc}")
        raise
    finally:
        (run_dir / "update_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return UpdateResult(run_dir=run_dir, manifest=manifest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="檢查教育部公開評議書新增案件，更新本機搜尋資料庫並產生 AI 待分析清單")
    parser.add_argument("--sleep", type=float, default=1.5, help="每次請求間隔秒數")
    parser.add_argument("--limit", type=int, default=0, help="限制本次下載候選數，方便小量測試")
    parser.add_argument("--retry-failed", action="store_true", help="除新增案件外，也重試全域 failed_cids.txt")
    parser.add_argument("--no-build-db", action="store_true", help="下載後不重建 SQLite/FTS")
    parser.add_argument("--verify-ssl", action="store_true", help="強制 SSL 憑證驗證，不啟用自動 fallback")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_public_update(
        sleep_seconds=args.sleep,
        limit=args.limit,
        retry_failed=args.retry_failed,
        build_db=not args.no_build_db,
        force_verify_ssl=args.verify_ssl,
    )
    print(f"更新紀錄：{result.run_dir}")


if __name__ == "__main__":
    main()
