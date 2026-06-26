from __future__ import annotations

import csv
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from public_ai_export import clean_public_text, export_public_case_bundle, split_public_paragraphs, write_case_package


def sample_row(text_path: Path, cid: str = "TEST001", title: str = "測試評議書") -> dict[str, str]:
    return {
        "cid": cid,
        "url": f"https://example.test/appraise_view.aspx?cid={cid}",
        "title": title,
        "case_type": "教師申訴評議書",
        "issue_type": "導師職務",
        "result": "申訴駁回",
        "date_text": "中華民國 115 年 01 月 01 日",
        "doc_no": "測字第001號",
        "text_path": str(text_path),
    }


def sample_text() -> str:
    return """測試評議書-教育部教師申訴案件查詢系統
跳到主要內容區塊
教育部訴願案件查詢系統
:::
網站導覽
評議書查詢
轉存PDF檔
發文日期：中華民國 115 年 01 月 01 日
發文字號：測字第001號
教育部中央教師申訴評議委員會申訴評議書
申訴人：ＯＯＯ
原措施學校：ＯＯＯ
申訴人因導師職務事件，提起申訴，本會決定如下：
主　文
申訴駁回。
事 實
一、申訴人主張其導師職務遭調整。
(一)申訴人稱調整程序有疑義。
理　由
二、學校說明係依校務需求辦理。
1. 會議紀錄記載已通知相關人員。
歡迎蒞臨教育部 法制處 網站 地址：臺北市中正區徐州路五號11樓
電話：(02)7736-5792、6805
資通安全及隱私政策
"""


def test_clean_public_text_removes_site_boilerplate():
    cleaned = clean_public_text(sample_text())
    assert "跳到主要內容區塊" not in cleaned
    assert "轉存PDF檔" not in cleaned
    assert "歡迎蒞臨教育部" not in cleaned
    assert "發文日期：中華民國 115 年 01 月 01 日" in cleaned
    assert "申訴駁回。" in cleaned


def test_split_public_paragraphs_recognizes_sections_and_numbered_items():
    paragraphs = split_public_paragraphs(clean_public_text(sample_text()))
    sections = [paragraph.section for paragraph in paragraphs]
    headings = [paragraph.heading for paragraph in paragraphs]
    assert "主文" in sections
    assert "事實" in sections
    assert "理由" in sections
    assert any(heading.startswith("一、申訴人主張") for heading in headings)
    assert any(heading.startswith("(一)申訴人稱") for heading in headings)
    assert any(heading.startswith("1. 會議紀錄") for heading in headings)


def test_single_case_export_outputs_four_files_and_source_labels(tmp_path):
    text_path = tmp_path / "TEST001.txt"
    text_path.write_text(sample_text(), encoding="utf-8")
    out_dir = write_case_package(sample_row(text_path), output_root=tmp_path / "ai_exports")
    assert sorted(path.name for path in out_dir.iterdir()) == [
        "case_full_context.md",
        "case_manifest.json",
        "case_prompt.md",
        "source_index.csv",
    ]
    manifest = json.loads((out_dir / "case_manifest.json").read_text(encoding="utf-8"))
    assert manifest["cid"] == "TEST001"
    assert manifest["title"] == "測試評議書"
    assert manifest["paragraph_count"] > 0
    context = (out_dir / "case_full_context.md").read_text(encoding="utf-8")
    assert "# 案件基本資料" in context
    assert "# 文件內容" in context
    assert "[來源：D001，第1段]" in context
    assert "跳到主要內容區塊" not in context
    assert "申訴人主張其導師職務遭調整。" in context


def test_source_index_matches_markdown_source_labels(tmp_path):
    text_path = tmp_path / "TEST001.txt"
    text_path.write_text(sample_text(), encoding="utf-8")
    out_dir = write_case_package(sample_row(text_path), output_root=tmp_path / "ai_exports")
    context = (out_dir / "case_full_context.md").read_text(encoding="utf-8")
    with (out_dir / "source_index.csv").open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    for row in rows:
        assert row["source_id"] == "D001"
        assert row["cid"] == "TEST001"
        assert row["paragraph_no"]
        assert row["section"]
        assert row["char_start"]
        assert row["char_end"]
        assert f"[來源：D001，第{row['paragraph_no']}段]" in context


def test_single_selection_bundle_contains_case_package_and_zip(tmp_path):
    text_path = tmp_path / "TEST001.txt"
    text_path.write_text(sample_text(), encoding="utf-8")
    result = export_public_case_bundle(
        ["TEST001"],
        mode="single",
        output_root=tmp_path / "bundles",
        case_rows=[sample_row(text_path)],
        canonical_output_root=tmp_path / "public_cases",
    )
    assert result.bundle_dir.exists()
    assert result.zip_path.exists()
    assert (result.bundle_dir / "bundle_manifest.json").exists()
    assert (result.bundle_dir / "selected_cases.csv").exists()
    assert (result.bundle_dir / "multi_case_prompt.md").exists()
    case_dir = result.bundle_dir / "cases" / "TEST001"
    assert sorted(path.name for path in case_dir.iterdir()) == [
        "case_full_context.md",
        "case_manifest.json",
        "case_prompt.md",
        "source_index.csv",
    ]
    with zipfile.ZipFile(result.zip_path) as zf:
        names = set(zf.namelist())
    assert "bundle_manifest.json" in names
    assert "selected_cases.csv" in names
    assert "multi_case_prompt.md" in names
    assert "cases/TEST001/case_full_context.md" in names
    assert "cases/TEST001/source_index.csv" in names


def test_multi_case_bundle_manifest_selected_csv_and_prompt(tmp_path):
    text1 = tmp_path / "TEST001.txt"
    text2 = tmp_path / "TEST002.txt"
    text1.write_text(sample_text(), encoding="utf-8")
    text2.write_text(sample_text().replace("導師職務", "成績考核"), encoding="utf-8")
    rows = [
        sample_row(text1, cid="TEST001", title="第一案"),
        sample_row(text2, cid="TEST002", title="第二案"),
    ]
    result = export_public_case_bundle(
        ["TEST002", "TEST001"],
        mode="compare",
        output_root=tmp_path / "bundles",
        case_rows=rows,
        canonical_output_root=tmp_path / "public_cases",
    )
    manifest = json.loads((result.bundle_dir / "bundle_manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "compare"
    assert manifest["case_count"] == 2
    assert manifest["cids"] == ["TEST002", "TEST001"]
    prompt = (result.bundle_dir / "multi_case_prompt.md").read_text(encoding="utf-8")
    assert "不得把任一案件" in prompt
    assert "cid=TEST001" in prompt
    assert "cid=TEST002" in prompt
    selected = (result.bundle_dir / "selected_cases.csv").read_text(encoding="utf-8-sig")
    assert "TEST001" in selected
    assert "TEST002" in selected


def test_bundle_case_context_uses_only_d001_source_labels(tmp_path):
    text1 = tmp_path / "TEST001.txt"
    text2 = tmp_path / "TEST002.txt"
    text1.write_text(sample_text(), encoding="utf-8")
    text2.write_text(sample_text(), encoding="utf-8")
    rows = [
        sample_row(text1, cid="TEST001", title="第一案"),
        sample_row(text2, cid="TEST002", title="第二案"),
    ]
    result = export_public_case_bundle(
        ["TEST001", "TEST002"],
        mode="single",
        output_root=tmp_path / "bundles",
        case_rows=rows,
        canonical_output_root=tmp_path / "public_cases",
    )
    for cid in ["TEST001", "TEST002"]:
        context = (result.bundle_dir / "cases" / cid / "case_full_context.md").read_text(encoding="utf-8")
        assert "[來源：D001，第1段]" in context
        assert "來源：D002" not in context
