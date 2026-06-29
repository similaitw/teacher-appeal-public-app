from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from misjudgment_audit import AUDIT_REPORTS_DIR, list_audit_reports, read_audit_report
from public_ai_export import clean_public_text, split_public_paragraphs
from utils import DATA_DIR, ROOT_DIR, read_cases_csv


DEEP_REVIEW_DIR = DATA_DIR / "audit_reports" / "deep_review"
UNCERTAINTY_KEYWORDS = ["尚待確認", "資料不足", "未查明", "無法確認", "無從確認", "待查", "陳述不一", "說法不一", "無其他客觀資料"]
CLAIM_KEYWORDS = ["申訴人主張", "再申訴人主張", "申請人主張", "相對人表示", "校方說明", "學校表示", "證人陳述"]
EVIDENCE_KEYWORDS = ["調查報告", "會議紀錄", "卷附", "函", "紀錄", "資料", "訪談", "陳述", "審查意見", "考核會", "校事會議"]
DETERMINATION_KEYWORDS = ["認定", "足認", "尚難謂", "核屬有據", "並無違誤", "應予維持", "無理由", "不受理", "駁回"]
CONCLUSION_KEYWORDS = ["主文", "申訴駁回", "再申訴駁回", "申訴不受理", "本件申訴為無理由", "本件再申訴為無理由"]


@dataclass
class ParagraphView:
    no: int
    section: str
    heading: str
    content: str
    tags: list[str]
    is_flagged: bool


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def latest_audit_report_dir() -> Path:
    reports = list_audit_reports(AUDIT_REPORTS_DIR)
    if not reports:
        raise FileNotFoundError("找不到可能誤判風險稽核報表，請先執行 scripts/misjudgment_audit.py --all --html")
    return reports[0]


def unique_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    base = root / now_stamp()
    path = base
    suffix = 1
    while path.exists():
        suffix += 1
        path = root / f"{base.name}_{suffix}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def load_target_findings(audit_dir: Path, judgment: str = "需深入人工覆核") -> list[dict[str, Any]]:
    payload = read_audit_report(audit_dir)
    return [row for row in payload.get("findings", []) if row.get("judgment_result") == judgment]


def rows_by_cid() -> dict[str, dict[str, str]]:
    return {row.get("cid", ""): row for row in read_cases_csv() if row.get("cid")}


def load_case_text(row: dict[str, str]) -> str:
    text = row.get("full_text", "")
    if text:
        return text
    text_path = row.get("text_path", "")
    if text_path:
        path = Path(text_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def parse_source_paragraphs(source_refs: list[str]) -> set[int]:
    result: set[int] = set()
    for ref in source_refs:
        for match in re.finditer(r"第(\d+)段", str(ref)):
            result.add(int(match.group(1)))
    return result


def classify_paragraph(content: str) -> list[str]:
    tags: list[str] = []
    if any(keyword in content for keyword in CLAIM_KEYWORDS):
        tags.append("當事人主張")
    if any(keyword in content for keyword in EVIDENCE_KEYWORDS):
        tags.append("客觀資料/證據")
    if any(keyword in content for keyword in DETERMINATION_KEYWORDS):
        tags.append("評議理由/認定")
    if any(keyword in content for keyword in UNCERTAINTY_KEYWORDS):
        tags.append("尚待確認")
    if any(keyword in content for keyword in CONCLUSION_KEYWORDS):
        tags.append("結論/主文")
    return tags or ["一般敘述"]


def build_paragraph_views(text: str, flagged_paragraphs: set[int]) -> list[ParagraphView]:
    cleaned = clean_public_text(text)
    paragraphs = split_public_paragraphs(cleaned)
    return [
        ParagraphView(
            no=paragraph.paragraph_no,
            section=paragraph.section,
            heading=paragraph.heading,
            content=paragraph.content,
            tags=classify_paragraph(paragraph.content),
            is_flagged=paragraph.paragraph_no in flagged_paragraphs,
        )
        for paragraph in paragraphs
    ]


def resolve_flagged_paragraphs(findings: list[dict[str, Any]], paragraphs: list[ParagraphView]) -> set[int]:
    if not paragraphs:
        return set()
    max_no = max(paragraph.no for paragraph in paragraphs)
    resolved: set[int] = set()
    for finding in findings:
        numbers = parse_source_paragraphs(finding.get("source_refs", []))
        excerpt = str(finding.get("excerpt", "") or "")
        local: set[int] = set()
        for number in numbers:
            if 1 <= number <= max_no:
                local.add(number)
            elif number > max_no:
                local.add(max_no)
        if not local and excerpt:
            normalized_excerpt = re.sub(r"\s+", "", excerpt)
            for paragraph in paragraphs:
                normalized_content = re.sub(r"\s+", "", paragraph.content)
                if normalized_content and (normalized_content[:40] in normalized_excerpt or normalized_excerpt[:40] in normalized_content):
                    local.add(paragraph.no)
                    break
        if not local:
            local.add(max_no)
        finding["_resolved_source_numbers"] = sorted(local)
        resolved.update(local)
    return resolved


def nearby_paragraphs(paragraphs: list[ParagraphView], flagged: set[int], radius: int = 2) -> list[ParagraphView]:
    wanted: set[int] = set()
    for number in flagged:
        for candidate in range(max(1, number - radius), number + radius + 1):
            wanted.add(candidate)
    return [paragraph for paragraph in paragraphs if paragraph.no in wanted]


def section_counts(paragraphs: list[ParagraphView]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paragraph in paragraphs:
        counts[paragraph.section] = counts.get(paragraph.section, 0) + 1
    return counts


def tag_counts(paragraphs: list[ParagraphView]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paragraph in paragraphs:
        for tag in paragraph.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def first_numbers(paragraphs: list[ParagraphView], tag: str, limit: int = 8) -> list[int]:
    return [paragraph.no for paragraph in paragraphs if tag in paragraph.tags][:limit]


def paragraph_link(number: int) -> str:
    return f'<a href="#p{number}">第{number}段</a>'


def source_links(numbers: set[int]) -> str:
    return "、".join(paragraph_link(number) for number in sorted(numbers)) or "來源待確認"


def mind_map_html(cid: str, row: dict[str, str], findings: list[dict[str, Any]], paragraphs: list[ParagraphView]) -> str:
    tags = tag_counts(paragraphs)
    flagged = sorted({p.no for p in paragraphs if p.is_flagged})
    risk_types = sorted({str(finding.get("risk_type", "")) for finding in findings})
    issue = row.get("issue_type", "") or "未分類"
    result = row.get("result", "") or "未擷取"
    return f"""
    <div class="mindmap">
      <div class="node root">cid={escape(cid)}<br>{escape(row.get("title", ""))}</div>
      <div class="branch">
        <div class="node">案件類型<br>{escape(issue)}</div>
        <div class="node">主文/結果<br>{escape(result)}</div>
        <div class="node danger">可疑錨點<br>{", ".join("第" + str(n) + "段" for n in flagged) or "來源待確認"}</div>
        <div class="node">風險類型<br>{escape("、".join(risk_types))}</div>
        <div class="node">資料層級<br>主張 {tags.get("當事人主張", 0)}｜證據 {tags.get("客觀資料/證據", 0)}｜認定 {tags.get("評議理由/認定", 0)}｜不確定 {tags.get("尚待確認", 0)}</div>
      </div>
    </div>
    """


def ascii_tree(cid: str, row: dict[str, str], findings: list[dict[str, Any]], paragraphs: list[ParagraphView]) -> str:
    flagged = sorted({p.no for p in paragraphs if p.is_flagged})
    claims = first_numbers(paragraphs, "當事人主張")
    evidence = first_numbers(paragraphs, "客觀資料/證據")
    determinations = first_numbers(paragraphs, "評議理由/認定")
    uncertainties = first_numbers(paragraphs, "尚待確認")
    risk_lines = [f"│  ├─ {finding.get('risk_type', '')}: {finding.get('judgment_result', '')} -> {', '.join(finding.get('source_refs', []))}" for finding in findings]
    return "\n".join(
        [
            f"案件 {cid} {row.get('title', '')}",
            f"├─ 結果：{row.get('result', '') or '未擷取'}",
            f"├─ 申訴/爭點分類：{row.get('issue_type', '') or '未分類'}",
            "├─ 事實與證據鏈",
            f"│  ├─ 當事人主張段落：{', '.join('第'+str(n)+'段' for n in claims) or '未偵測'}",
            f"│  ├─ 證據/客觀資料段落：{', '.join('第'+str(n)+'段' for n in evidence) or '未偵測'}",
            f"│  ├─ 評議理由/認定段落：{', '.join('第'+str(n)+'段' for n in determinations) or '未偵測'}",
            f"│  └─ 尚待確認段落：{', '.join('第'+str(n)+'段' for n in uncertainties) or '未偵測'}",
            "├─ 需覆核錨點",
            *(risk_lines or ["│  └─ 無"]),
            "└─ 卡住/矛盾檢查",
            f"   ├─ 紅字段落是否正是核心爭點：{', '.join('第'+str(n)+'段' for n in flagged) or '來源待確認'}",
            "   ├─ 若不確定語句只是旁支，可能可排除",
            "   └─ 若不確定語句支撐結論，需補證據或重讀理由鏈",
        ]
    )


def contradiction_points(findings: list[dict[str, Any]], paragraphs: list[ParagraphView]) -> list[str]:
    points: list[str] = []
    flagged_numbers = sorted({p.no for p in paragraphs if p.is_flagged})
    for finding in findings:
        risk_type = finding.get("risk_type", "")
        if risk_type == "結論跳躍":
            points.append("結論與不確定語句之間可能存在落差：請確認紅字段落是否為核心爭點，而非旁支說明。")
        elif risk_type == "證據風險":
            points.append("證據比較可能不足：請確認是否已並列支持與反對資料，以及是否說明採信/不採信理由。")
        else:
            points.append(f"{risk_type}：請依來源段落核對。")
    if flagged_numbers:
        points.append("需優先閱讀：" + "、".join(f"第{n}段" for n in flagged_numbers))
    return points


def risk_table_html(findings: list[dict[str, Any]]) -> str:
    rows = []
    for finding in findings:
        nums = {int(number) for number in finding.get("_resolved_source_numbers", [])}
        refs = [source_links(nums)] if nums else []
        if not refs:
            for ref in finding.get("source_refs", []):
                parsed_nums = parse_source_paragraphs([ref])
                refs.append(source_links(parsed_nums) if parsed_nums else escape(str(ref)))
        rows.append(
            f"""
            <tr>
              <td>{escape(str(finding.get("risk_type", "")))}</td>
              <td>{escape(str(finding.get("judgment_result", "")))}</td>
              <td>{escape(str(finding.get("judgment_basis", "")))}</td>
              <td>{"、".join(refs) or "來源待確認"}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def paragraph_html(paragraph: ParagraphView) -> str:
    classes = "paragraph flagged" if paragraph.is_flagged else "paragraph"
    tags = "".join(f'<span class="tag">{escape(tag)}</span>' for tag in paragraph.tags)
    content = escape(paragraph.content)
    if paragraph.is_flagged:
        content = f'<mark class="hit">{content}</mark>'
    return f"""
    <section class="{classes}" id="p{paragraph.no}">
      <div class="p-head"><a href="#top">↑</a> <strong>第{paragraph.no}段</strong>｜{escape(paragraph.section)}｜{tags}</div>
      <p>{content}</p>
    </section>
    """


def case_report_html(cid: str, row: dict[str, str], findings: list[dict[str, Any]], paragraphs: list[ParagraphView], index_filename: str) -> str:
    flagged = {p.no for p in paragraphs if p.is_flagged}
    nearby = nearby_paragraphs(paragraphs, flagged)
    sections = section_counts(paragraphs)
    points = contradiction_points(findings, paragraphs)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(cid)} 深度覆核</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f4ee; color:#1f2933; }}
    main {{ max-width:1320px; margin:0 auto; padding:24px 18px 56px; }}
    a {{ color:#0f766e; }}
    .notice,.card,.paragraph {{ background:#fffdf8; border:1px solid #d8d3c8; border-radius:6px; padding:14px; margin:12px 0; }}
    .notice {{ border-left:5px solid #b42318; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; }}
    .metric {{ background:#fffdf8; border:1px solid #d8d3c8; border-radius:6px; padding:12px; }}
    .metric strong {{ display:block; font-size:1.35rem; }}
    table {{ width:100%; border-collapse:collapse; background:#fffdf8; }}
    th,td {{ border:1px solid #e7e1d6; padding:8px; vertical-align:top; text-align:left; }}
    th {{ background:#18332f; color:#fffdf8; }}
    .tag {{ display:inline-block; background:#e0f2f1; color:#164e49; border-radius:999px; padding:2px 8px; margin:0 3px; font-size:.82rem; }}
    .flagged {{ border-left:5px solid #b42318; }}
    .hit {{ color:#b42318; background:#fee2e2; font-weight:800; padding:2px 4px; border-radius:3px; }}
    .mindmap {{ overflow:auto; padding:12px; background:#fffdf8; border:1px solid #d8d3c8; border-radius:6px; }}
    .mindmap .root {{ margin:auto; max-width:360px; }}
    .branch {{ display:flex; gap:10px; justify-content:center; flex-wrap:wrap; margin-top:16px; }}
    .node {{ border:2px solid #0f766e; border-radius:8px; padding:10px; background:#f8fafc; text-align:center; min-width:150px; }}
    .danger {{ border-color:#b42318; color:#b42318; font-weight:800; }}
    pre {{ white-space:pre-wrap; background:#101820; color:#f8fafc; padding:14px; border-radius:6px; line-height:1.45; }}
    .p-head {{ color:#65727f; }}
  </style>
</head>
<body>
<main id="top">
  <p><a href="{escape(index_filename)}">← 回總索引</a></p>
  <h1>{escape(cid)}｜{escape(row.get("title", ""))}</h1>
  <div class="notice">本頁為內部深度覆核工作稿，只整理來源與風險錨點，不作成最終認定或懲處建議。</div>

  <div class="grid">
    <div class="metric"><strong>{escape(row.get("result", "") or "未擷取")}</strong><span>主文/結果</span></div>
    <div class="metric"><strong>{escape(row.get("issue_type", "") or "未分類")}</strong><span>爭點分類</span></div>
    <div class="metric"><strong>{len(paragraphs)}</strong><span>全文段落數</span></div>
    <div class="metric"><strong>{len(flagged)}</strong><span>紅字錨點段落</span></div>
  </div>

  <h2>覆核導覽</h2>
  <ul>
    <li>紅字錨點：{source_links(flagged)}</li>
    <li>前後文快速閱讀：{"、".join(paragraph_link(p.no) for p in nearby) or "無"}</li>
    <li>章節分布：{escape("｜".join(f"{name}:{count}" for name, count in sections.items()))}</li>
  </ul>

  <h2>心智圖</h2>
  {mind_map_html(cid, row, findings, paragraphs)}

  <h2>ASCII 樹狀圖：理由鏈與卡住點</h2>
  <pre>{escape(ascii_tree(cid, row, findings, paragraphs))}</pre>

  <h2>可能矛盾/卡住點</h2>
  <ol>{"".join(f"<li>{escape(point)}</li>" for point in points)}</ol>

  <h2>風險判斷表</h2>
  <table>
    <thead><tr><th>風險類型</th><th>初步判斷</th><th>判斷依據</th><th>內部連結</th></tr></thead>
    <tbody>{risk_table_html(findings)}</tbody>
  </table>

  <h2>前後文對照</h2>
  {"".join(paragraph_html(p) for p in nearby) or "<p>沒有可顯示的前後文。</p>"}

  <h2>全文段落檢視</h2>
  {"".join(paragraph_html(p) for p in paragraphs)}
</main>
</body>
</html>
"""


def index_html(rows: list[dict[str, Any]], output_dir: Path, index_filename: str) -> str:
    table_rows = []
    for item in rows:
        row = item["row"]
        findings = item["findings"]
        case_file = item["file"].name
        judgment = "；".join(sorted({str(f.get("judgment_result", "")) for f in findings}))
        risks = "；".join(sorted({str(f.get("risk_type", "")) for f in findings}))
        anchors = source_links(item["flagged"])
        table_rows.append(
            f"""
            <tr>
              <td><a href="{escape(case_file)}">{escape(item["cid"])}</a></td>
              <td>{escape(row.get("title", ""))}</td>
              <td>{escape(row.get("result", ""))}</td>
              <td>{escape(risks)}</td>
              <td>{escape(judgment)}</td>
              <td>{anchors}</td>
            </tr>
            """
        )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>深度覆核總索引</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f4ee; color:#1f2933; }}
    main {{ max-width:1280px; margin:0 auto; padding:24px 18px 56px; }}
    table {{ width:100%; border-collapse:collapse; background:#fffdf8; }}
    th,td {{ border:1px solid #e7e1d6; padding:8px; vertical-align:top; text-align:left; }}
    th {{ background:#18332f; color:#fffdf8; }}
    .notice {{ background:#fffdf8; border:1px solid #d8d3c8; border-left:5px solid #b42318; border-radius:6px; padding:14px; margin:12px 0; }}
    a {{ color:#0f766e; }}
  </style>
</head>
<body>
<main>
  <h1>需深入人工覆核案件：深度分析總索引</h1>
  <div class="notice">本報表以既有風險稽核結果篩出「需深入人工覆核」項目，逐案提供全文錨點、心智圖與 ASCII 理由鏈；內容不得視為最終認定。</div>
  <p>輸出目錄：{escape(str(output_dir))}</p>
  <table>
    <thead><tr><th>cid</th><th>案件</th><th>結果</th><th>風險類型</th><th>初步判斷</th><th>紅字錨點</th></tr></thead>
    <tbody>{"".join(table_rows)}</tbody>
  </table>
</main>
</body>
</html>
"""


def generate_deep_review(audit_dir: Path | None = None, output_root: Path = DEEP_REVIEW_DIR) -> Path:
    audit_dir = audit_dir or latest_audit_report_dir()
    findings = load_target_findings(audit_dir)
    if not findings:
        raise ValueError("找不到 judgment_result=需深入人工覆核 的項目")
    cases = rows_by_cid()
    output_dir = unique_dir(output_root)
    index_filename = "index.html"
    grouped: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        grouped.setdefault(str(finding.get("cid", "")), []).append(finding)

    index_rows: list[dict[str, Any]] = []
    for cid, case_findings in sorted(grouped.items()):
        row = cases.get(cid, {"cid": cid, "title": cid, "result": "", "issue_type": ""})
        paragraphs = build_paragraph_views(load_case_text(row), set())
        flagged = resolve_flagged_paragraphs(case_findings, paragraphs)
        paragraphs = build_paragraph_views(load_case_text(row), flagged)
        case_file = output_dir / f"{cid}.html"
        case_file.write_text(case_report_html(cid, row, case_findings, paragraphs, index_filename), encoding="utf-8")
        index_rows.append({"cid": cid, "row": row, "findings": case_findings, "flagged": flagged, "file": case_file})

    (output_dir / index_filename).write_text(index_html(index_rows, output_dir, index_filename), encoding="utf-8")
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_audit_dir": str(audit_dir),
        "case_count": len(grouped),
        "finding_count": len(findings),
        "index": str(output_dir / index_filename),
        "cases": [{"cid": item["cid"], "file": item["file"].name} for item in index_rows],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="針對需深入人工覆核案件產生逐案深度 HTML 報表")
    parser.add_argument("--audit-dir", type=Path, help="指定 misjudgment_audit.json 所在報表目錄；預設使用最新稽核報表")
    parser.add_argument("--output-root", type=Path, default=DEEP_REVIEW_DIR, help="深度覆核報表輸出根目錄")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = generate_deep_review(audit_dir=args.audit_dir, output_root=args.output_root)
    print(f"已產生深度覆核報表：{output_dir}")
    print(f"總索引：{output_dir / 'index.html'}")


if __name__ == "__main__":
    main()
