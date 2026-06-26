from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import update_public_cases  # noqa: E402
from utils import CASE_FIELDS  # noqa: E402


class FakeSession:
    pass


def write_cases_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CASE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def patch_update_paths(monkeypatch, tmp_path: Path) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    cases_csv = data_dir / "cases.csv"
    raw_html = data_dir / "raw_html"
    texts = data_dir / "texts"
    update_runs = data_dir / "update_runs"
    downloaded = data_dir / "downloaded_cids.txt"
    failed = data_dir / "failed_cids.txt"
    raw_html.mkdir(parents=True)
    texts.mkdir(parents=True)
    write_cases_csv(cases_csv, [])

    monkeypatch.setattr(update_public_cases, "UPDATE_RUNS_DIR", update_runs)
    monkeypatch.setattr(update_public_cases, "DOWNLOADED_CIDS_PATH", downloaded)
    monkeypatch.setattr(update_public_cases, "FAILED_CIDS_PATH", failed)

    import crawl_appeal
    import utils

    monkeypatch.setattr(crawl_appeal, "DOWNLOADED_CIDS_PATH", downloaded)
    monkeypatch.setattr(crawl_appeal, "FAILED_CIDS_PATH", failed)
    monkeypatch.setattr(crawl_appeal, "TEXTS_DIR", texts)
    monkeypatch.setattr(crawl_appeal, "RAW_HTML_DIR", raw_html)
    monkeypatch.setattr(utils, "CASES_CSV", cases_csv)
    monkeypatch.setattr(utils, "TEXTS_DIR", texts)
    monkeypatch.setattr(utils, "RAW_HTML_DIR", raw_html)
    monkeypatch.setattr(utils, "DATA_DIR", data_dir)
    monkeypatch.setattr(utils, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(update_public_cases, "ensure_dirs", utils.ensure_dirs)
    monkeypatch.setattr(update_public_cases, "upsert_cases_csv", utils.upsert_cases_csv)
    monkeypatch.setattr(update_public_cases, "write_log", lambda message: None)
    monkeypatch.setattr(update_public_cases, "successful_cids", crawl_appeal.successful_cids)
    monkeypatch.setattr(update_public_cases, "indexed_cids", crawl_appeal.indexed_cids)
    monkeypatch.setattr(update_public_cases, "cached_case_row", crawl_appeal.cached_case_row)
    monkeypatch.setattr(update_public_cases, "read_cid_file", crawl_appeal.read_cid_file)
    monkeypatch.setattr(update_public_cases, "write_cid_file", crawl_appeal.write_cid_file)
    monkeypatch.setattr(update_public_cases, "append_cids", crawl_appeal.append_cids)
    monkeypatch.setattr(crawl_appeal, "read_cases_csv", utils.read_cases_csv)
    return {"cases_csv": cases_csv, "downloaded": downloaded, "failed": failed, "update_runs": update_runs}


def fake_discover(cids: list[str]):
    def _discover(*args, **kwargs):
        return cids

    return _discover


def fake_download_factory(fail: set[str] | None = None):
    fail = fail or set()

    def _download(session, cid, matched_keywords="", verify_ssl=True, allow_ssl_fallback=True):
        if cid in fail:
            raise RuntimeError("download failed")
        return {
            "cid": cid,
            "url": f"https://example.test/?cid={cid}",
            "title": f"{cid}評議書",
            "case_type": "教師申訴評議書",
            "full_text": f"{cid} content",
            "text_path": f"data/texts/{cid}.txt",
            "html_path": f"data/raw_html/{cid}.html",
        }

    return _download


def test_update_skips_existing_and_writes_ai_pending(tmp_path, monkeypatch):
    paths = patch_update_paths(monkeypatch, tmp_path)
    paths["downloaded"].write_text("A\n", encoding="utf-8")
    build_calls = {"count": 0}

    result = update_public_cases.run_public_update(
        sleep_seconds=0,
        output_root=paths["update_runs"],
        session_factory=FakeSession,
        discover_func=fake_discover(["A", "B"]),
        download_func=fake_download_factory(),
        build_db_func=lambda: build_calls.__setitem__("count", build_calls["count"] + 1),
    )

    assert result.manifest["new_count"] == 1
    assert result.manifest["downloaded_count"] == 1
    assert build_calls["count"] == 1
    assert (result.run_dir / "new_cids.txt").read_text(encoding="utf-8").splitlines() == ["B"]
    assert (result.run_dir / "ai_pending_cids.txt").read_text(encoding="utf-8").splitlines() == ["B"]


def test_update_repairs_cached_case_missing_from_csv(tmp_path, monkeypatch):
    paths = patch_update_paths(monkeypatch, tmp_path)
    paths["downloaded"].write_text("A\n", encoding="utf-8")
    raw_html = tmp_path / "data" / "raw_html" / "A.html"
    raw_html.write_text(
        "<html><head><title>1150000001評議書-教育部教師申訴案件查詢系統</title></head>"
        "<body>發文日期：中華民國 115 年 01 月 01 日\n"
        "教育部中央教師申訴評議委員會申訴評議書\n主 文\n申訴駁回。</body></html>",
        encoding="utf-8",
    )
    build_calls = {"count": 0}

    result = update_public_cases.run_public_update(
        sleep_seconds=0,
        output_root=paths["update_runs"],
        session_factory=FakeSession,
        discover_func=fake_discover(["A"]),
        download_func=fake_download_factory(),
        build_db_func=lambda: build_calls.__setitem__("count", build_calls["count"] + 1),
    )

    assert result.manifest["new_count"] == 0
    assert result.manifest["downloaded_count"] == 0
    assert result.manifest["repaired_count"] == 1
    assert build_calls["count"] == 1
    assert (result.run_dir / "repaired_cids.txt").read_text(encoding="utf-8").splitlines() == ["A"]
    with paths["cases_csv"].open("r", newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert [row["cid"] for row in rows] == ["A"]


def test_update_failure_is_recorded_and_does_not_abort(tmp_path, monkeypatch):
    paths = patch_update_paths(monkeypatch, tmp_path)

    result = update_public_cases.run_public_update(
        sleep_seconds=0,
        output_root=paths["update_runs"],
        session_factory=FakeSession,
        discover_func=fake_discover(["A", "B"]),
        download_func=fake_download_factory(fail={"A"}),
        build_db_func=lambda: None,
    )

    assert result.manifest["status"] == "completed_with_errors"
    assert result.manifest["downloaded_count"] == 1
    assert result.manifest["failed_count"] == 1
    assert (result.run_dir / "failed_cids.txt").read_text(encoding="utf-8").splitlines() == ["A"]
    assert "A" in paths["failed"].read_text(encoding="utf-8")


def test_update_no_build_db_skips_rebuild(tmp_path, monkeypatch):
    paths = patch_update_paths(monkeypatch, tmp_path)
    build_calls = {"count": 0}

    result = update_public_cases.run_public_update(
        sleep_seconds=0,
        build_db=False,
        output_root=paths["update_runs"],
        session_factory=FakeSession,
        discover_func=fake_discover(["A"]),
        download_func=fake_download_factory(),
        build_db_func=lambda: build_calls.__setitem__("count", build_calls["count"] + 1),
    )

    assert result.manifest["build_db_status"] == "skipped"
    assert build_calls["count"] == 0


def test_update_limit_restricts_candidates(tmp_path, monkeypatch):
    paths = patch_update_paths(monkeypatch, tmp_path)

    result = update_public_cases.run_public_update(
        sleep_seconds=0,
        limit=1,
        output_root=paths["update_runs"],
        session_factory=FakeSession,
        discover_func=fake_discover(["A", "B", "C"]),
        download_func=fake_download_factory(),
        build_db_func=lambda: None,
    )

    assert result.manifest["candidate_count"] == 1
    assert result.manifest["downloaded_count"] == 1
    manifest = json.loads((result.run_dir / "update_manifest.json").read_text(encoding="utf-8"))
    assert manifest["limit"] == 1


def test_empty_discovery_with_existing_data_is_failed(tmp_path, monkeypatch):
    paths = patch_update_paths(monkeypatch, tmp_path)
    paths["downloaded"].write_text("A\n", encoding="utf-8")

    try:
        update_public_cases.run_public_update(
            sleep_seconds=0,
            output_root=paths["update_runs"],
            session_factory=FakeSession,
            discover_func=fake_discover([]),
            download_func=fake_download_factory(),
            build_db_func=lambda: None,
        )
    except RuntimeError as exc:
        assert "未回傳任何 cid" in str(exc)
    else:
        raise AssertionError("Expected empty discovery to fail when local data exists")

    run_dirs = list(paths["update_runs"].iterdir())
    assert run_dirs
    manifest = json.loads((run_dirs[0] / "update_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
