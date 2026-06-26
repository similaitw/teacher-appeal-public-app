from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analysis_runs import (  # noqa: E402
    create_analysis_run,
    list_private_export_inputs,
    list_public_bundle_inputs,
    sha256_text,
)
from public_ai_export import export_public_case_bundle  # noqa: E402


def sample_public_row(text_path: Path) -> dict[str, str]:
    return {
        "cid": "TEST001",
        "url": "https://example.test/appraise_view.aspx?cid=TEST001",
        "title": "測試公開案",
        "case_type": "教師申訴評議書",
        "issue_type": "導師職務",
        "result": "申訴駁回",
        "date_text": "中華民國 115 年 01 月 01 日",
        "doc_no": "測字第001號",
        "text_path": str(text_path),
    }


def sample_public_text() -> str:
    return """發文日期：中華民國 115 年 01 月 01 日
發文字號：測字第001號
主　文
申訴駁回。
事 實
一、申訴人主張其導師職務遭調整。
理　由
二、學校說明係依校務需求辦理。
"""


def make_public_bundle(tmp_path: Path) -> Path:
    text_path = tmp_path / "TEST001.txt"
    text_path.write_text(sample_public_text(), encoding="utf-8")
    result = export_public_case_bundle(
        ["TEST001"],
        mode="single",
        output_root=tmp_path / "bundles",
        case_rows=[sample_public_row(text_path)],
        canonical_output_root=tmp_path / "public_cases",
    )
    return result.bundle_dir


def make_private_export(tmp_path: Path) -> Path:
    export_dir = tmp_path / "exports" / "case-uuid-001"
    export_dir.mkdir(parents=True)
    manifest = {
        "case_uuid": "case-uuid-001",
        "case_number": "P-001",
        "title": "私人測試案",
        "case_type": "教師申訴",
        "export_time": "2026-06-16T10:00:00",
        "document_count": 1,
        "unit_count": 1,
        "source_files": [{"source_id": "D001", "filename": "report.txt"}],
    }
    (export_dir / "case_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (export_dir / "case_full_context.md").write_text("# 文件內容\n\n[來源：D001，第1段]\n\n測試內容", encoding="utf-8")
    (export_dir / "source_index.csv").write_text("source_id,document_id,filename\nD001,1,report.txt\n", encoding="utf-8-sig")
    return export_dir


def test_public_bundle_analysis_run_outputs_five_files(tmp_path):
    bundle_dir = make_public_bundle(tmp_path)
    result = create_analysis_run(
        bundle_dir,
        scope="public_bundle",
        provider="chatgpt",
        model_name="GPT Test",
        prompt_text="請分析",
        ai_response_text="AI 回覆內容",
        notes_text="人工備註",
        output_root=tmp_path / "analysis_runs",
    )
    assert sorted(path.name for path in result.run_dir.iterdir()) == [
        "ai_response.md",
        "citation_review.md",
        "input_manifest.json",
        "notes.md",
        "prompt_used.md",
    ]
    manifest = json.loads((result.run_dir / "input_manifest.json").read_text(encoding="utf-8"))
    assert manifest["scope"] == "public_bundle"
    assert manifest["provider"] == "chatgpt"
    assert manifest["case_ids"] == ["TEST001"]
    assert manifest["prompt_sha256"] == sha256_text("請分析")
    assert manifest["ai_response_sha256"] == sha256_text("AI 回覆內容")


def test_private_export_analysis_run_manifest_and_hashes(tmp_path):
    export_dir = make_private_export(tmp_path)
    source_info = list_private_export_inputs(export_dir)
    assert source_info["case_ids"] == ["case-uuid-001"]
    assert len(source_info["source_files"]) == 3
    result = create_analysis_run(
        export_dir,
        scope="private_case",
        provider="codex",
        model_name="Codex",
        prompt_text=source_info["default_prompt"],
        ai_response_text="私人案分析",
        notes_text="已人工覆核",
        output_root=tmp_path / "analysis_runs",
    )
    manifest = json.loads((result.run_dir / "input_manifest.json").read_text(encoding="utf-8"))
    assert manifest["scope"] == "private_case"
    assert manifest["case_ids"] == ["case-uuid-001"]
    assert all(row["sha256"] for row in manifest["source_files"])
    assert manifest["notes_sha256"] == sha256_text("已人工覆核")


def test_repeated_analysis_runs_do_not_overwrite(tmp_path):
    export_dir = make_private_export(tmp_path)
    output_root = tmp_path / "analysis_runs"
    first = create_analysis_run(export_dir, "private_case", "gemini", "Gemini", "prompt", "response 1", output_root=output_root)
    second = create_analysis_run(export_dir, "private_case", "gemini", "Gemini", "prompt", "response 2", output_root=output_root)
    assert first.run_id != second.run_id
    assert (first.run_dir / "ai_response.md").read_text(encoding="utf-8") == "response 1"
    assert (second.run_dir / "ai_response.md").read_text(encoding="utf-8") == "response 2"


def test_citation_review_template_contains_checklist(tmp_path):
    bundle_dir = make_public_bundle(tmp_path)
    result = create_analysis_run(
        bundle_dir,
        scope="public_bundle",
        provider="other",
        model_name="Manual",
        prompt_text="prompt",
        ai_response_text="response",
        output_root=tmp_path / "analysis_runs",
    )
    review = (result.run_dir / "citation_review.md").read_text(encoding="utf-8")
    assert "引用核對表" in review
    assert "AI 回覆中的重要事實都有來源標記" in review
    assert "AI 沒有把 A 案事實套用到 B 案" in review


def test_public_bundle_input_listing_includes_prompt_and_source_context(tmp_path):
    bundle_dir = make_public_bundle(tmp_path)
    source_info = list_public_bundle_inputs(bundle_dir)
    roles = {row["role"] for row in source_info["source_files"]}
    assert "prompt" in roles
    assert "source_context" in roles
    assert source_info["default_prompt"]
