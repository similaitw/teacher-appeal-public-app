from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from analysis_runs import ANALYSIS_RUNS_DIR, create_analysis_run, list_analysis_runs
from public_ai_export import export_public_case_bundle
from utils import DATA_DIR
from web_ai_clients import WebAINeedsUserAction, make_web_ai_client


WEB_AI_BATCHES_DIR = DATA_DIR / "ai_exports" / "web_ai_batches"
MAX_PROMPT_CHARS = 180_000
STALE_RUNNING_SECONDS = 10 * 60
STATUS_FIELDNAMES = [
    "cid",
    "status",
    "package_path",
    "run_id",
    "error",
    "started_at",
    "finished_at",
    "updated_at",
    "attempts",
    "manual_note",
]
RETRYABLE_STATUSES = {"pending", "paused", "failed", "stale"}
AUTO_CONTINUE_STATUSES = {"pending", "failed", "stale"}


class WebAIClientProtocol(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def submit(self, text: str) -> None: ...
    def wait_for_response(self) -> None: ...
    def get_response_text(self) -> str: ...
    def pause_for_user(self, message: str) -> None: ...


@dataclass
class PreparedCasePrompt:
    cid: str
    bundle_dir: Path
    prompt_text: str


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def filesystem_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def create_batch_dir(provider: str, output_root: Path = WEB_AI_BATCHES_DIR) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    base = output_root / f"{filesystem_timestamp()}_{provider}"
    path = base
    suffix = 1
    while path.exists():
        suffix += 1
        path = output_root / f"{base.name}_{suffix}"
    path.mkdir(parents=True, exist_ok=False)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


def normalize_cids(cids: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for cid in cids:
        value = str(cid).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def write_batch_manifest(batch_dir: Path, provider: str, model_name: str, cids: list[str], sleep_seconds: float) -> None:
    manifest = {
        "batch_id": batch_dir.name,
        "provider": provider,
        "model_name": model_name,
        "created_at": now_text(),
        "case_count": len(cids),
        "sleep_seconds": sleep_seconds,
        "cids": cids,
    }
    (batch_dir / "batch_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (batch_dir / "selected_cids.txt").write_text("\n".join(cids) + "\n", encoding="utf-8")


def read_cids_from_file(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"找不到 cid 清單檔：{path}")
    if not path.is_file():
        raise ValueError(f"cid 清單路徑不是檔案：{path}")
    return normalize_cids(path.read_text(encoding="utf-8").splitlines())


def load_batch_manifest(batch_dir: Path) -> dict[str, Any]:
    manifest_path = Path(batch_dir) / "batch_manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_selected_cids(batch_dir: Path) -> list[str]:
    batch_dir = Path(batch_dir)
    selected_path = batch_dir / "selected_cids.txt"
    if selected_path.exists():
        return read_cids_from_file(selected_path)
    manifest = load_batch_manifest(batch_dir)
    return normalize_cids([str(cid) for cid in manifest.get("cids", [])])


def normalize_status_row(row: dict[str, str] | None) -> dict[str, str]:
    source = row or {}
    return {field: str(source.get(field, "") or "") for field in STATUS_FIELDNAMES}


def load_status_rows(status_path: Path) -> list[dict[str, str]]:
    if not status_path.exists():
        return []
    with status_path.open("r", newline="", encoding="utf-8-sig") as fh:
        return [normalize_status_row(row) for row in csv.DictReader(fh)]


def write_status_rows(status_path: Path, rows: list[dict[str, str]]) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    with status_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=STATUS_FIELDNAMES)
        writer.writeheader()
        writer.writerows([normalize_status_row(row) for row in rows])


def save_status(status_path: Path, row: dict[str, str]) -> None:
    current_rows = load_status_rows(status_path)
    rows: list[dict[str, str]] = []
    merged = normalize_status_row(row)
    replaced = False
    for existing in current_rows:
        if existing.get("cid") == row.get("cid"):
            combined = normalize_status_row({**existing, **row})
            rows.append(combined)
            merged = combined
            replaced = True
        else:
            rows.append(existing)
    if not replaced:
        rows.append(merged)
    write_status_rows(status_path, rows)


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_valid_run(run_id: str) -> bool:
    if not str(run_id).strip():
        return False
    return (ANALYSIS_RUNS_DIR / Path(run_id).name / "ai_response.md").exists()


def find_analysis_run_for_batch_case(batch_dir: Path, cid: str) -> str:
    batch_name = Path(batch_dir).name
    needle_batch = f"web_ai_batch={batch_name}"
    needle_cid = f"cid={cid}"
    for run in list_analysis_runs(scope="public_bundle"):
        case_ids = [str(value) for value in run.get("case_ids", [])]
        notes = str(run.get("user_notes") or "")
        run_id = str(run.get("run_id") or "")
        if cid in case_ids and needle_batch in notes and needle_cid in notes and is_valid_run(run_id):
            return run_id
    return ""


def refresh_batch_status(batch_dir: Path, stale_seconds: int = STALE_RUNNING_SECONDS) -> tuple[dict[str, int | str], list[dict[str, str]]]:
    batch_dir = Path(batch_dir)
    status_path = batch_dir / "status.csv"
    selected_cids = load_selected_cids(batch_dir)
    manifest = load_batch_manifest(batch_dir)
    now = now_text()
    now_dt = datetime.now()

    rows_by_cid = {row.get("cid", ""): normalize_status_row(row) for row in load_status_rows(status_path) if row.get("cid")}
    for cid in selected_cids:
        row = rows_by_cid.get(cid)
        if row is None:
            row = normalize_status_row({"cid": cid, "status": "pending", "updated_at": now})
            rows_by_cid[cid] = row
        status = row.get("status", "").strip()
        run_id = row.get("run_id", "").strip()
        recovered_run_id = run_id if is_valid_run(run_id) else find_analysis_run_for_batch_case(batch_dir, cid)
        if recovered_run_id:
            row["run_id"] = recovered_run_id
            row["status"] = "done"
            row["error"] = ""
            row["updated_at"] = now
            if not row.get("finished_at"):
                row["finished_at"] = now
            continue
        if status == "done":
            row["status"] = "pending"
            row["error"] = row.get("error") or "done 狀態缺少可讀取的 ai_response.md，已改為 pending"
            row["updated_at"] = now
            continue
        if status == "running":
            reference_time = parse_time(row.get("updated_at", "")) or parse_time(row.get("started_at", ""))
            if reference_time and (now_dt - reference_time).total_seconds() > stale_seconds:
                row["status"] = "stale"
                row["error"] = row.get("error") or f"running 超過 {int(stale_seconds / 60)} 分鐘未更新"
                row["updated_at"] = now
        elif not status:
            row["status"] = "pending"
            row["updated_at"] = now

    ordered_cids = selected_cids + sorted(cid for cid in rows_by_cid if cid not in set(selected_cids))
    rows = [rows_by_cid[cid] for cid in ordered_cids if cid in rows_by_cid]
    write_status_rows(status_path, rows)

    counts: dict[str, int] = {}
    for row in rows:
        status = row.get("status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
    planned_total = int(manifest.get("case_count") or len(selected_cids) or len(rows))
    summary: dict[str, int | str] = {
        "batch_id": batch_dir.name,
        "provider": str(manifest.get("provider") or ""),
        "model_name": str(manifest.get("model_name") or ""),
        "planned_total": planned_total,
        "seen": len(rows),
        "done": counts.get("done", 0),
        "running": counts.get("running", 0),
        "paused": counts.get("paused", 0),
        "failed": counts.get("failed", 0),
        "pending": counts.get("pending", 0),
        "stale": counts.get("stale", 0),
        "remaining": max(planned_total - len(rows), 0),
        "last_refreshed": now,
    }
    return summary, rows


def set_case_status(
    batch_dir: Path,
    cid: str,
    status: str,
    run_id: str = "",
    error: str = "",
    manual_note: str = "",
    package_path: str = "",
) -> dict[str, str]:
    status = status.strip().lower()
    allowed_statuses = {"pending", "running", "done", "paused", "failed", "stale"}
    if status not in allowed_statuses:
        raise ValueError(f"不支援的狀態：{status}")
    status_path = Path(batch_dir) / "status.csv"
    rows_by_cid = {row.get("cid", ""): row for row in load_status_rows(status_path) if row.get("cid")}
    existing = rows_by_cid.get(str(cid), normalize_status_row({"cid": str(cid)}))
    row = normalize_status_row(
        {
            **existing,
            "cid": str(cid),
            "status": status,
            "run_id": run_id or existing.get("run_id", ""),
            "error": error,
            "manual_note": manual_note,
            "package_path": package_path or existing.get("package_path", ""),
            "updated_at": now_text(),
        }
    )
    if status == "done" and not row.get("finished_at"):
        row["finished_at"] = row["updated_at"]
    rows_by_cid[str(cid)] = row
    selected_cids = load_selected_cids(batch_dir)
    ordered_cids = selected_cids + sorted(value for value in rows_by_cid if value not in set(selected_cids))
    write_status_rows(status_path, [rows_by_cid[value] for value in ordered_cids if value in rows_by_cid])
    return row


def select_retry_cids(batch_dir: Path, statuses: set[str] | list[str] | tuple[str, ...] = RETRYABLE_STATUSES) -> list[str]:
    wanted = {str(status).strip().lower() for status in statuses if str(status).strip()}
    _summary, rows = refresh_batch_status(batch_dir)
    return [row["cid"] for row in rows if row.get("status") in wanted]


def row_attempts(row: dict[str, str]) -> int:
    try:
        return int(row.get("attempts") or 0)
    except ValueError:
        return 0


def select_auto_continue_cids(
    batch_dir: Path,
    statuses: set[str] | list[str] | tuple[str, ...] = AUTO_CONTINUE_STATUSES,
    max_attempts: int = 3,
) -> list[str]:
    wanted = {str(status).strip().lower() for status in statuses if str(status).strip()}
    _summary, rows = refresh_batch_status(batch_dir)
    selected: list[str] = []
    for row in rows:
        if row.get("status") not in wanted:
            continue
        if max_attempts > 0 and row_attempts(row) >= max_attempts:
            continue
        selected.append(row["cid"])
    return selected


def mark_retry_exhausted(
    batch_dir: Path,
    statuses: set[str] | list[str] | tuple[str, ...] = AUTO_CONTINUE_STATUSES,
    max_attempts: int = 3,
) -> list[str]:
    wanted = {str(status).strip().lower() for status in statuses if str(status).strip()}
    _summary, rows = refresh_batch_status(batch_dir)
    exhausted: list[str] = []
    for row in rows:
        if row.get("status") in wanted and max_attempts > 0 and row_attempts(row) >= max_attempts:
            note = row.get("manual_note") or ""
            marker = f"已達自動重跑上限 {max_attempts} 次，請人工檢核"
            if marker not in note:
                note = (note + "\n" + marker).strip()
            set_case_status(
                batch_dir,
                row["cid"],
                row.get("status") or "failed",
                run_id=row.get("run_id", ""),
                error=row.get("error", ""),
                manual_note=note,
                package_path=row.get("package_path", ""),
            )
            exhausted.append(row["cid"])
    return exhausted


def continue_batch_until_complete(
    provider: str,
    batch_dir: Path,
    sleep_seconds: float = 3.0,
    model_name: str = "",
    statuses: set[str] | list[str] | tuple[str, ...] = AUTO_CONTINUE_STATUSES,
    max_rounds: int = 5,
    max_attempts: int = 3,
    client: WebAIClientProtocol | None = None,
) -> dict[str, object]:
    manifest = load_batch_manifest(batch_dir)
    provider = (provider or str(manifest.get("provider") or "")).strip().lower()
    if provider not in {"chatgpt", "gemini"}:
        raise ValueError("provider 必須是 chatgpt 或 gemini")
    model_name = model_name or str(manifest.get("model_name") or "")
    rounds: list[dict[str, object]] = []
    max_rounds = max(max_rounds, 1)

    for round_no in range(1, max_rounds + 1):
        cids = select_auto_continue_cids(batch_dir, statuses=statuses, max_attempts=max_attempts)
        rounds.append({"round": round_no, "candidate_count": len(cids), "cids": cids})
        if not cids:
            break
        run_batch(
            provider=provider,
            cids=cids,
            sleep_seconds=sleep_seconds,
            model_name=model_name,
            batch_dir=batch_dir,
            client=client,
            write_manifest=False,
        )
        summary, _rows = refresh_batch_status(batch_dir)
        if int(summary.get("paused", 0) or 0):
            break
        remaining = select_auto_continue_cids(batch_dir, statuses=statuses, max_attempts=max_attempts)
        if not remaining:
            break

    exhausted = mark_retry_exhausted(batch_dir, statuses=statuses, max_attempts=max_attempts)
    summary, _rows = refresh_batch_status(batch_dir)
    return {"batch_dir": str(batch_dir), "rounds": rounds, "exhausted_cids": exhausted, "summary": summary}


def compose_prompt(context_text: str, case_prompt: str, cid: str) -> str:
    return f"""# 批次公開評議書分析

請分析下列單一公開評議書。請只使用本文提供的 D001 來源，不得使用外部資料補充事實。

本案 cid：{cid}

---

{case_prompt.strip()}

---

{context_text.strip()}
"""


def prepare_case_prompt(cid: str, package_root: Path | None = None) -> PreparedCasePrompt:
    output_root = package_root or (WEB_AI_BATCHES_DIR / "single_case_packages")
    result = export_public_case_bundle([cid], mode="single", output_root=output_root)
    bundle_dir = result.bundle_dir
    case_dir = bundle_dir / "cases" / cid
    context_path = case_dir / "case_full_context.md"
    prompt_path = case_dir / "case_prompt.md"
    if not context_path.exists() or not prompt_path.exists():
        raise FileNotFoundError(f"找不到單案分析包內容：{case_dir}")
    prompt_text = compose_prompt(
        context_path.read_text(encoding="utf-8"),
        prompt_path.read_text(encoding="utf-8"),
        cid,
    )
    return PreparedCasePrompt(cid=cid, bundle_dir=bundle_dir, prompt_text=prompt_text)


def run_single_case(
    client: WebAIClientProtocol,
    cid: str,
    provider: str,
    model_name: str,
    batch_dir: Path,
    status_path: Path,
) -> None:
    started_at = now_text()
    existing = next((row for row in load_status_rows(status_path) if row.get("cid") == cid), {})
    attempts = int(existing.get("attempts") or 0) + 1
    row = {
        "cid": cid,
        "status": "running",
        "package_path": existing.get("package_path", ""),
        "run_id": "",
        "error": "",
        "started_at": started_at,
        "finished_at": "",
        "updated_at": started_at,
        "attempts": str(attempts),
        "manual_note": existing.get("manual_note", ""),
    }
    save_status(status_path, row)
    try:
        prepared = prepare_case_prompt(cid, package_root=batch_dir / "packages")
        row["package_path"] = str(prepared.bundle_dir)
        if len(prepared.prompt_text) > MAX_PROMPT_CHARS:
            raise WebAINeedsUserAction(f"本案送出文字約 {len(prepared.prompt_text)} 字，超過第一版限制，請人工處理。")
        client.submit(prepared.prompt_text)
        client.wait_for_response()
        response = client.get_response_text()
        run = create_analysis_run(
            prepared.bundle_dir,
            scope="public_bundle",
            provider=provider,
            model_name=model_name,
            prompt_text=prepared.prompt_text,
            ai_response_text=response,
            notes_text=f"web_ai_batch={batch_dir.name}; cid={cid}",
        )
        finished = now_text()
        row.update({"status": "done", "run_id": run.run_id, "finished_at": finished, "updated_at": finished, "error": ""})
    except WebAINeedsUserAction as exc:
        finished = now_text()
        row.update({"status": "paused", "error": str(exc), "finished_at": finished, "updated_at": finished})
        save_status(status_path, row)
        client.pause_for_user(f"cid={cid} 需要人工處理：{exc}")
        return
    except Exception as exc:
        finished = now_text()
        row.update({"status": "failed", "error": str(exc), "finished_at": finished, "updated_at": finished})
    save_status(status_path, row)


def run_batch(
    provider: str,
    cids: list[str],
    sleep_seconds: float = 3.0,
    model_name: str = "",
    batch_dir: Path | None = None,
    client: WebAIClientProtocol | None = None,
    write_manifest: bool = True,
) -> Path:
    provider = provider.strip().lower()
    if provider not in {"chatgpt", "gemini"}:
        raise ValueError("provider 必須是 chatgpt 或 gemini")
    cids = normalize_cids(cids)
    if not cids:
        raise ValueError("沒有可分析的 cid")
    batch_dir = batch_dir or create_batch_dir(provider)
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "logs").mkdir(parents=True, exist_ok=True)
    if write_manifest or not (batch_dir / "batch_manifest.json").exists():
        write_batch_manifest(batch_dir, provider, model_name, cids, sleep_seconds)
    status_path = batch_dir / "status.csv"

    owns_client = client is None
    client = client or make_web_ai_client(provider)
    if owns_client:
        client.open()
    try:
        for index, cid in enumerate(cids):
            run_single_case(client, cid, provider, model_name, batch_dir, status_path)
            rows = load_status_rows(status_path)
            current = next((row for row in rows if row.get("cid") == cid), {})
            if current.get("status") == "paused":
                break
            if index < len(cids) - 1 and sleep_seconds > 0:
                time.sleep(sleep_seconds)
    finally:
        if owns_client:
            client.close()
    return batch_dir
