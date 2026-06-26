from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from utils import DATA_DIR, ROOT_DIR


ANALYSIS_RUNS_DIR = DATA_DIR / "ai_exports" / "analysis_runs"
VALID_SCOPES = {"public_bundle", "private_case"}
VALID_PROVIDERS = {"chatgpt", "gemini", "codex", "other"}


@dataclass
class AnalysisRunResult:
    run_id: str
    run_dir: Path
    manifest: dict[str, Any]


def utc_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def filesystem_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", (value or "").strip().lower()).strip("_")
    return token or "unknown"


def relative_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT_DIR.resolve()))
    except ValueError:
        return str(resolved)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return sha256((text or "").encode("utf-8")).hexdigest()


def file_entry(path: Path, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "path": relative_path(path),
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_public_bundle_inputs(bundle_dir: Path) -> dict[str, Any]:
    bundle_dir = Path(bundle_dir)
    manifest_path = bundle_dir / "bundle_manifest.json"
    prompt_path = bundle_dir / "multi_case_prompt.md"
    if not manifest_path.exists():
        raise FileNotFoundError(f"找不到公開上傳包 manifest：{manifest_path}")
    manifest = read_json(manifest_path)
    files = [file_entry(manifest_path, "bundle_manifest")]
    selected_csv = bundle_dir / "selected_cases.csv"
    if selected_csv.exists():
        files.append(file_entry(selected_csv, "selected_cases"))
    if prompt_path.exists():
        files.append(file_entry(prompt_path, "prompt"))
    for case_dir in sorted((bundle_dir / "cases").glob("*")) if (bundle_dir / "cases").exists() else []:
        if not case_dir.is_dir():
            continue
        for name, role in [
            ("case_manifest.json", "case_manifest"),
            ("case_full_context.md", "source_context"),
            ("source_index.csv", "source_index"),
            ("case_prompt.md", "case_prompt"),
        ]:
            path = case_dir / name
            if path.exists():
                files.append(file_entry(path, role))
    return {
        "scope": "public_bundle",
        "source_path": relative_path(bundle_dir),
        "source_files": files,
        "case_ids": [str(cid) for cid in manifest.get("cids", [])],
        "case_count": manifest.get("case_count", len(manifest.get("cids", []))),
        "source_manifest": manifest,
        "default_prompt": prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "",
    }


def private_default_prompt(manifest: dict[str, Any]) -> str:
    return f"""# Codex / ChatGPT / Gemini 分析指令

請只根據 `case_full_context.md` 與 `source_index.csv` 分析本案，不得使用外部資料補充事實。

要求：

- 每項重要事實都必須引用來源標記。
- 不得摘要成無來源結論。
- 不得把其他案件事實套入本案。
- 單方陳述使用「主張」、「表示」或「稱」。
- 若來源不足，請寫「來源不足，無法判斷」。

案件 UUID：{manifest.get("case_uuid", "")}
案件名稱：{manifest.get("title", "")}
"""


def list_private_export_inputs(export_dir: Path) -> dict[str, Any]:
    export_dir = Path(export_dir)
    manifest_path = export_dir / "case_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"找不到私人分析包 manifest：{manifest_path}")
    manifest = read_json(manifest_path)
    files = [file_entry(manifest_path, "case_manifest")]
    for name, role in [
        ("case_full_context.md", "source_context"),
        ("source_index.csv", "source_index"),
    ]:
        path = export_dir / name
        if path.exists():
            files.append(file_entry(path, role))
    return {
        "scope": "private_case",
        "source_path": relative_path(export_dir),
        "source_files": files,
        "case_ids": [str(manifest.get("case_uuid", ""))],
        "case_count": 1,
        "source_manifest": manifest,
        "default_prompt": private_default_prompt(manifest),
    }


def citation_review_template(scope: str, case_ids: list[str], provider: str, model_name: str) -> str:
    cases = "\n".join(f"- {case_id}" for case_id in case_ids if case_id) or "- （未記錄）"
    return f"""# 引用核對表

- 分析來源：{scope}
- AI 工具：{provider}
- 模型：{model_name}

## 案件

{cases}

## 人工覆核

- [ ] AI 回覆中的重要事實都有來源標記。
- [ ] AI 沒有引用不存在的段落、頁碼或行號。
- [ ] AI 沒有把 A 案事實套用到 B 案。
- [ ] 單方主張沒有被寫成已認定事實。
- [ ] 法規、程序與結論已回到原文覆核。

## 需修正事項

（請在此記錄人工覆核發現的問題）
"""


def unique_run_dir(output_root: Path, base_name: str) -> Path:
    run_dir = output_root / base_name
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = output_root / f"{base_name}_{suffix}"
    return run_dir


def create_analysis_run(
    source_dir: Path,
    scope: str,
    provider: str,
    model_name: str,
    prompt_text: str,
    ai_response_text: str,
    notes_text: str = "",
    output_root: Path = ANALYSIS_RUNS_DIR,
) -> AnalysisRunResult:
    scope = safe_token(scope)
    provider = safe_token(provider)
    if scope not in VALID_SCOPES:
        raise ValueError("scope 必須是 public_bundle 或 private_case")
    if provider not in VALID_PROVIDERS:
        provider = "other"
    if not ai_response_text.strip():
        raise ValueError("AI 原始回覆不可空白")

    source_info = list_public_bundle_inputs(source_dir) if scope == "public_bundle" else list_private_export_inputs(source_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = f"{filesystem_timestamp()}_{provider}_{scope}"
    run_dir = unique_run_dir(output_root, run_id)
    run_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=False)

    analysis_time = utc_now()
    prompt_hash = sha256_text(prompt_text)
    response_hash = sha256_text(ai_response_text)
    notes_hash = sha256_text(notes_text)
    manifest = {
        "run_id": run_id,
        "scope": scope,
        "provider": provider,
        "model_name": model_name.strip(),
        "analysis_time": analysis_time,
        "source_path": source_info["source_path"],
        "case_ids": source_info["case_ids"],
        "case_count": source_info["case_count"],
        "source_files": source_info["source_files"],
        "prompt_sha256": prompt_hash,
        "ai_response_sha256": response_hash,
        "notes_sha256": notes_hash,
        "user_notes": notes_text,
    }
    (run_dir / "input_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "prompt_used.md").write_text(prompt_text, encoding="utf-8")
    (run_dir / "ai_response.md").write_text(ai_response_text, encoding="utf-8")
    (run_dir / "citation_review.md").write_text(
        citation_review_template(scope, source_info["case_ids"], provider, model_name.strip()),
        encoding="utf-8",
    )
    (run_dir / "notes.md").write_text(notes_text, encoding="utf-8")
    return AnalysisRunResult(run_id=run_id, run_dir=run_dir, manifest=manifest)


def list_analysis_runs(scope: str | None = None, output_root: Path = ANALYSIS_RUNS_DIR) -> list[dict[str, Any]]:
    if not output_root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted(output_root.glob("*/input_manifest.json"), reverse=True):
        try:
            manifest = read_json(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        if scope and manifest.get("scope") != scope:
            continue
        manifest["run_dir"] = relative_path(manifest_path.parent)
        rows.append(manifest)
    return rows


def read_analysis_run(run_id: str, output_root: Path = ANALYSIS_RUNS_DIR) -> dict[str, Any]:
    run_dir = output_root / Path(run_id).name
    manifest_path = run_dir / "input_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"找不到分析紀錄：{run_id}")
    return {
        "manifest": read_json(manifest_path),
        "prompt_used": (run_dir / "prompt_used.md").read_text(encoding="utf-8") if (run_dir / "prompt_used.md").exists() else "",
        "ai_response": (run_dir / "ai_response.md").read_text(encoding="utf-8") if (run_dir / "ai_response.md").exists() else "",
        "citation_review": (run_dir / "citation_review.md").read_text(encoding="utf-8") if (run_dir / "citation_review.md").exists() else "",
        "notes": (run_dir / "notes.md").read_text(encoding="utf-8") if (run_dir / "notes.md").exists() else "",
    }
