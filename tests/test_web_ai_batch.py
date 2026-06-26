from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import web_ai_batch  # noqa: E402
from web_ai_batch import (  # noqa: E402
    WebAINeedsUserAction,
    load_status_rows,
    prepare_case_prompt,
    refresh_batch_status,
    continue_batch_until_complete,
    run_batch,
    save_status,
    select_retry_cids,
    select_auto_continue_cids,
    set_case_status,
    write_batch_manifest,
)
from web_ai_batch import read_cids_from_file  # noqa: E402


@dataclass
class FakeBundleResult:
    bundle_dir: Path


@dataclass
class FakeRunResult:
    run_id: str


class FakeClient:
    def __init__(self, response: str = "AI 完成回覆", pause_on_submit: bool = False) -> None:
        self.response = response
        self.pause_on_submit = pause_on_submit
        self.submitted: list[str] = []
        self.paused: list[str] = []

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def submit(self, text: str) -> None:
        if self.pause_on_submit:
            raise WebAINeedsUserAction("需要登入")
        self.submitted.append(text)

    def wait_for_response(self) -> None:
        pass

    def get_response_text(self) -> str:
        return self.response

    def pause_for_user(self, message: str) -> None:
        self.paused.append(message)


def fake_export_factory(tmp_path: Path):
    def fake_export(cids, mode="single", output_root=None):
        cid = cids[0]
        bundle_dir = Path(output_root) / f"bundle_{cid}"
        case_dir = bundle_dir / "cases" / cid
        case_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "bundle_manifest.json").write_text(
            json.dumps({"mode": mode, "case_count": 1, "cids": [cid]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (bundle_dir / "selected_cases.csv").write_text("cid\n" + cid + "\n", encoding="utf-8-sig")
        (bundle_dir / "multi_case_prompt.md").write_text("多案 prompt", encoding="utf-8")
        (case_dir / "case_manifest.json").write_text(json.dumps({"cid": cid, "title": "測試案"}, ensure_ascii=False), encoding="utf-8")
        (case_dir / "case_full_context.md").write_text(f"[來源：D001，第1段]\n\n{cid} 內容", encoding="utf-8")
        (case_dir / "source_index.csv").write_text("source_id,cid,paragraph_no\nD001," + cid + ",1\n", encoding="utf-8-sig")
        (case_dir / "case_prompt.md").write_text("請每項重要事實都標示 [來源：D001，第N段]", encoding="utf-8")
        return FakeBundleResult(bundle_dir=bundle_dir)

    return fake_export


def fake_create_analysis_run_factory():
    counter = {"value": 0}

    def fake_create_analysis_run(*args, **kwargs):
        counter["value"] += 1
        return FakeRunResult(run_id=f"run{counter['value']}")

    return fake_create_analysis_run


def test_save_status_upserts_rows(tmp_path):
    status_path = tmp_path / "status.csv"
    save_status(status_path, {"cid": "A", "status": "running"})
    save_status(status_path, {"cid": "A", "status": "done", "run_id": "run1"})
    rows = load_status_rows(status_path)
    assert len(rows) == 1
    assert rows[0]["cid"] == "A"
    assert rows[0]["status"] == "done"
    assert rows[0]["run_id"] == "run1"
    assert "updated_at" in rows[0]
    assert "attempts" in rows[0]


def test_read_cids_from_file_missing_file_has_clear_error(tmp_path):
    missing = tmp_path / "missing_cids.txt"
    try:
        read_cids_from_file(missing)
    except FileNotFoundError as exc:
        assert "找不到 cid 清單檔" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError")


def test_prepare_case_prompt_contains_d001_and_context(tmp_path, monkeypatch):
    monkeypatch.setattr(web_ai_batch, "export_public_case_bundle", fake_export_factory(tmp_path))
    prepared = prepare_case_prompt("CID001", package_root=tmp_path / "packages")
    assert prepared.cid == "CID001"
    assert prepared.bundle_dir.exists()
    assert "CID001 內容" in prepared.prompt_text
    assert "D001" in prepared.prompt_text


def test_run_batch_success_creates_analysis_runs_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(web_ai_batch, "export_public_case_bundle", fake_export_factory(tmp_path))
    monkeypatch.setattr(web_ai_batch, "create_analysis_run", fake_create_analysis_run_factory())
    batch_dir = tmp_path / "batch"
    client = FakeClient(response="AI 回覆")
    result_dir = run_batch("chatgpt", ["CID001", "CID002"], sleep_seconds=0, model_name="GPT Test", batch_dir=batch_dir, client=client)
    assert result_dir == batch_dir
    rows = load_status_rows(batch_dir / "status.csv")
    assert [row["status"] for row in rows] == ["done", "done"]
    assert all(row["run_id"] for row in rows)
    assert len(set(row["run_id"] for row in rows)) == 2
    assert len(client.submitted) == 2


def test_run_batch_pauses_on_login_or_captcha(tmp_path, monkeypatch):
    monkeypatch.setattr(web_ai_batch, "export_public_case_bundle", fake_export_factory(tmp_path))
    monkeypatch.setattr(web_ai_batch, "create_analysis_run", fake_create_analysis_run_factory())
    batch_dir = tmp_path / "batch"
    client = FakeClient(pause_on_submit=True)
    run_batch("gemini", ["CID001", "CID002"], sleep_seconds=0, model_name="Gemini", batch_dir=batch_dir, client=client)
    rows = load_status_rows(batch_dir / "status.csv")
    assert len(rows) == 1
    assert rows[0]["status"] == "paused"
    assert "需要登入" in rows[0]["error"]
    assert client.paused


def test_batch_manifest_and_selected_cids_created(tmp_path, monkeypatch):
    monkeypatch.setattr(web_ai_batch, "export_public_case_bundle", fake_export_factory(tmp_path))
    monkeypatch.setattr(web_ai_batch, "create_analysis_run", fake_create_analysis_run_factory())
    batch_dir = tmp_path / "batch"
    run_batch("chatgpt", ["CID001"], sleep_seconds=0, model_name="GPT", batch_dir=batch_dir, client=FakeClient())
    manifest = json.loads((batch_dir / "batch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["provider"] == "chatgpt"
    assert manifest["model_name"] == "GPT"
    assert manifest["cids"] == ["CID001"]
    with (batch_dir / "status.csv").open("r", encoding="utf-8-sig", newline="") as fh:
        assert list(csv.DictReader(fh))[0]["cid"] == "CID001"


def test_refresh_batch_status_adds_pending_rows(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    write_batch_manifest(batch_dir, "chatgpt", "GPT", ["CID001", "CID002", "CID003"], 0)
    save_status(batch_dir / "status.csv", {"cid": "CID001", "status": "done", "run_id": "missing"})

    summary, rows = refresh_batch_status(batch_dir)

    assert summary["planned_total"] == 3
    assert [row["cid"] for row in rows] == ["CID001", "CID002", "CID003"]
    assert [row["status"] for row in rows] == ["pending", "pending", "pending"]


def test_refresh_batch_status_marks_done_when_run_file_exists(tmp_path, monkeypatch):
    analysis_root = tmp_path / "analysis_runs"
    run_dir = analysis_root / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "ai_response.md").write_text("AI 回覆", encoding="utf-8")
    monkeypatch.setattr(web_ai_batch, "ANALYSIS_RUNS_DIR", analysis_root)
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    write_batch_manifest(batch_dir, "chatgpt", "GPT", ["CID001"], 0)
    save_status(batch_dir / "status.csv", {"cid": "CID001", "status": "failed", "run_id": "run1", "error": "old"})

    summary, rows = refresh_batch_status(batch_dir)

    assert summary["done"] == 1
    assert rows[0]["status"] == "done"
    assert rows[0]["error"] == ""


def test_refresh_batch_status_marks_stale_running(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    write_batch_manifest(batch_dir, "chatgpt", "GPT", ["CID001"], 0)
    old_time = (datetime.now() - timedelta(minutes=20)).isoformat(timespec="seconds")
    save_status(batch_dir / "status.csv", {"cid": "CID001", "status": "running", "started_at": old_time, "updated_at": old_time})

    summary, rows = refresh_batch_status(batch_dir, stale_seconds=60)

    assert summary["stale"] == 1
    assert rows[0]["status"] == "stale"


def test_set_case_status_updates_single_case_note(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    write_batch_manifest(batch_dir, "chatgpt", "GPT", ["CID001"], 0)

    row = set_case_status(batch_dir, "CID001", "paused", error="人工暫停", manual_note="先等帳號")

    assert row["status"] == "paused"
    assert row["manual_note"] == "先等帳號"
    rows = load_status_rows(batch_dir / "status.csv")
    assert rows[0]["error"] == "人工暫停"


def test_select_retry_cids_skips_done(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    write_batch_manifest(batch_dir, "chatgpt", "GPT", ["CID001", "CID002", "CID003"], 0)
    save_status(batch_dir / "status.csv", {"cid": "CID001", "status": "done", "run_id": "missing"})
    save_status(batch_dir / "status.csv", {"cid": "CID002", "status": "failed"})

    retry_cids = select_retry_cids(batch_dir, ["pending", "failed"])

    assert retry_cids == ["CID001", "CID002", "CID003"]


def test_old_status_csv_is_read_with_new_columns(tmp_path):
    status_path = tmp_path / "status.csv"
    status_path.write_text("cid,status,package_path,run_id,error,started_at,finished_at\nCID001,failed,,,,,\n", encoding="utf-8-sig")

    rows = load_status_rows(status_path)

    assert rows[0]["cid"] == "CID001"
    assert rows[0]["attempts"] == ""
    assert rows[0]["manual_note"] == ""


def test_select_auto_continue_respects_max_attempts(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    write_batch_manifest(batch_dir, "chatgpt", "GPT", ["CID001", "CID002", "CID003"], 0)
    save_status(batch_dir / "status.csv", {"cid": "CID001", "status": "failed", "attempts": "1"})
    save_status(batch_dir / "status.csv", {"cid": "CID002", "status": "failed", "attempts": "3"})
    save_status(batch_dir / "status.csv", {"cid": "CID003", "status": "paused", "attempts": "1"})

    retry_cids = select_auto_continue_cids(batch_dir, ["pending", "failed", "stale"], max_attempts=3)

    assert retry_cids == ["CID001"]


def test_continue_batch_until_complete_marks_exhausted(tmp_path, monkeypatch):
    monkeypatch.setattr(web_ai_batch, "export_public_case_bundle", fake_export_factory(tmp_path))

    def always_fail(*args, **kwargs):
        raise RuntimeError("analysis failed")

    monkeypatch.setattr(web_ai_batch, "create_analysis_run", always_fail)
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    write_batch_manifest(batch_dir, "chatgpt", "GPT", ["CID001"], 0)
    client = FakeClient(response="AI 回覆")

    result = continue_batch_until_complete(
        "chatgpt",
        batch_dir,
        sleep_seconds=0,
        max_rounds=3,
        max_attempts=2,
        client=client,
    )

    rows = load_status_rows(batch_dir / "status.csv")
    assert rows[0]["status"] == "failed"
    assert rows[0]["attempts"] == "2"
    assert "自動重跑上限" in rows[0]["manual_note"]
    assert result["exhausted_cids"] == ["CID001"]
