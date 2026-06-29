from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import misjudgment_audit  # noqa: E402
from misjudgment_audit import (  # noqa: E402
    audit_ai_run,
    audit_case_row,
    create_audit_report,
    write_csv,
    write_html,
    write_json,
)


def sample_case_row(text: str = "") -> dict[str, str]:
    return {
        "cid": "TEST001",
        "title": "測試評議書",
        "case_type": "教師申訴評議書",
        "issue_type": "懲處",
        "result": "申訴駁回",
        "date_text": "中華民國 115 年 01 月 01 日",
        "full_text": text,
    }


def test_case_text_audit_flags_procedure_evidence_and_uncertainty_risks():
    row = sample_case_row(
        """主　文
申訴駁回。
理　由
一、本件涉及懲處事件，申訴人主張原措施不當。
二、雙方說法不一，尚無客觀資料可佐證。
三、部分日期仍尚待確認，惟本件申訴無理由。
"""
    )
    findings = audit_case_row(row)
    risk_types = {finding.risk_type for finding in findings}
    assert "證據風險" in risk_types
    assert "結論跳躍" in risk_types
    assert any(finding.risk_level in {"high", "medium"} for finding in findings)
    assert all(finding.status == "待覆核" for finding in findings)


def make_ai_run(tmp_path: Path, response: str, source_rows: list[dict[str, str]] | None = None) -> dict[str, object]:
    run_id = "RUN001"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "ai_response.md").write_text(response, encoding="utf-8")
    source_index = tmp_path / "source_index.csv"
    with source_index.open("w", newline="", encoding="utf-8-sig") as fh:
        fieldnames = ["source_id", "cid", "paragraph_no"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in source_rows or [{"source_id": "D001", "cid": "TEST001", "paragraph_no": "1"}]:
            writer.writerow(row)
    source_context = tmp_path / "case_full_context.md"
    source_context.write_text("[來源：D001，第1段]\n申訴人主張原措施不當。", encoding="utf-8")
    return {
        "run_id": run_id,
        "case_ids": ["TEST001"],
        "provider": "chatgpt",
        "model_name": "GPT Test",
        "source_files": [
            {"role": "source_index", "path": str(source_index)},
            {"role": "source_context", "path": str(source_context)},
        ],
    }


def test_ai_audit_flags_invalid_source_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(misjudgment_audit, "ANALYSIS_RUNS_DIR", tmp_path)
    run = make_ai_run(tmp_path, "AI 稱本案申訴駁回。[來源：D001，第99段]")
    findings = audit_ai_run(run)
    assert any(finding.risk_type == "AI 引用風險" for finding in findings)
    assert any("第99段" in "；".join(finding.source_refs) for finding in findings)


def test_ai_audit_flags_overstated_party_claim_as_fact(tmp_path, monkeypatch):
    monkeypatch.setattr(misjudgment_audit, "ANALYSIS_RUNS_DIR", tmp_path)
    run = make_ai_run(tmp_path, "申訴人主張原措施不當，因此學校違法確定，應撤銷處分。[來源：D001，第1段]")
    findings = audit_ai_run(run)
    assert any(finding.risk_type == "AI 誤讀" for finding in findings)
    assert any("強烈認定" in "；".join(finding.triggered_rules) for finding in findings)


def test_ai_audit_flags_cross_case_cid_mixing(tmp_path, monkeypatch):
    monkeypatch.setattr(misjudgment_audit, "ANALYSIS_RUNS_DIR", tmp_path)
    run = make_ai_run(tmp_path, "cid=OTHER999 的事實也可參照本案。[來源：D001，第1段]")
    findings = audit_ai_run(run)
    assert any(finding.risk_type == "AI 誤讀" for finding in findings)
    assert any("多案混用" in "；".join(finding.triggered_rules) for finding in findings)


def test_report_outputs_json_csv_and_html_include_core_fields(tmp_path):
    row = sample_case_row(
        """主　文
申訴不受理。
理　由
一、雙方說法不一，資料不足。
"""
    )
    findings = audit_case_row(row)
    summary = misjudgment_audit.summarize_findings(findings, scanned_cases=1, scanned_analysis_runs=0)
    json_path = tmp_path / "misjudgment_audit.json"
    csv_path = tmp_path / "misjudgment_audit.csv"
    html_path = tmp_path / "misjudgment_audit.html"
    write_json(json_path, summary, findings)
    write_csv(csv_path, findings)
    write_html(html_path, summary, findings)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    html_text = html_path.read_text(encoding="utf-8")
    assert payload["findings"][0]["cid"] == "TEST001"
    assert payload["findings"][0]["judgment_result"]
    assert payload["findings"][0]["judgment_basis"]
    assert "risk_level" in csv_text
    assert "source_refs" in csv_text
    assert "judgment_result" in csv_text
    assert "可能誤判風險稽核報表" in html_text
    assert "初步覆核判斷" in html_text
    assert "系統紅字標示" in html_text
    assert "人工判讀方式" in html_text
    assert "risk-hit" in html_text
    assert "TEST001" in html_text


def test_create_audit_report_can_use_injected_sources(tmp_path, monkeypatch):
    row = sample_case_row("主　文\n申訴駁回。\n理　由\n一、資料不足，仍申訴無理由。")
    monkeypatch.setattr(misjudgment_audit, "select_case_rows", lambda cids=None: [row])
    monkeypatch.setattr(misjudgment_audit, "list_analysis_runs", lambda: [])
    report = create_audit_report(cids=None, include_cases=True, include_analysis_runs=True, output_root=tmp_path)
    assert report.json_path.exists()
    assert report.csv_path.exists()
    assert report.html_path.exists()
    assert report.summary["scanned_cases"] == 1
