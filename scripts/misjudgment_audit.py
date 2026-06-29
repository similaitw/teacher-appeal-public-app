from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from analysis_runs import ANALYSIS_RUNS_DIR, list_analysis_runs
from utils import DATA_DIR, ROOT_DIR, get_case_by_cid, read_cases_csv


AUDIT_REPORTS_DIR = DATA_DIR / "audit_reports" / "misjudgment"
SOURCE_REF_RE = re.compile(r"\[來源：(?P<source>D\d{3})，第(?P<unit>\d+)(?P<label>段|頁|行)?\]")
LEGAL_CITATION_RE = re.compile(r"[\u4e00-\u9fffA-Za-z（）()、]{2,30}(?:法|準則|辦法|要點|注意事項|條例)第\d+條")
CID_RE = re.compile(r"(?:cid\s*[=：:]\s*|案件\s*)([A-Za-z0-9_-]{6,})")


SENSITIVE_KEYWORDS = [
    "懲處",
    "申誡",
    "記過",
    "成績考核",
    "考核",
    "解聘",
    "停聘",
    "不續聘",
    "霸凌",
    "性平",
    "校事會議",
    "升等",
    "導師職務",
    "管教",
    "體罰",
]

UNCERTAINTY_KEYWORDS = ["尚待確認", "資料不足", "未查明", "無法確認", "無從確認", "待查", "陳述不一", "說法不一"]
PROCEDURE_KEYWORDS = ["不受理", "逾期", "管轄", "申訴適格", "不適格", "再申訴論", "救濟範圍", "程序"]
EVIDENCE_CONFLICT_KEYWORDS = ["雙方說法", "陳述不一", "互有出入", "互不相符", "尚無客觀資料", "無其他證據"]
EVIDENCE_REASONING_KEYWORDS = ["採信", "不採", "證據", "調查報告", "卷附", "紀錄"]
OVERSTATEMENT_KEYWORDS = ["顯然", "毫無疑問", "違法確定", "已構成", "應懲處", "應撤銷", "惡意", "說謊"]
PARTY_CLAIM_PREFIXES = ["申訴人主張", "再申訴人主張", "申請人主張", "相對人表示", "校方說明", "學校表示", "證人陳述"]
FACT_ASSERTION_TERMS = ["足認", "認定", "確定", "已證明", "確有", "構成", "違法", "不當"]


@dataclass
class AuditFinding:
    risk_level: str
    risk_score: int
    risk_type: str
    cid: str
    title: str
    result: str
    issue_type: str
    date_text: str
    triggered_rules: list[str]
    source_refs: list[str]
    excerpt: str
    review_note: str
    judgment_result: str = ""
    judgment_basis: str = ""
    status: str = "待覆核"
    run_id: str = ""
    provider: str = ""
    model_name: str = ""


@dataclass
class AuditReport:
    report_id: str
    report_dir: Path
    findings: list[AuditFinding]
    summary: dict[str, Any]
    json_path: Path
    csv_path: Path
    html_path: Path


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def filesystem_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def relative_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT_DIR.resolve()))
    except ValueError:
        return str(resolved)


def risk_level(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_source_units(text: str) -> list[tuple[int, str]]:
    units: list[tuple[int, str]] = []
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            units.append((len(units) + 1, clean))
    return units


def source_ref_for_text(text: str, needle: str) -> str:
    if not text or not needle:
        return ""
    for paragraph_no, line in split_source_units(text):
        if needle in line:
            return f"[來源：D001，第{paragraph_no}段]"
    return "[來源待確認]"


def excerpt_around(text: str, keyword: str, length: int = 220) -> str:
    flat = normalize_text(text)
    if not flat:
        return ""
    idx = flat.find(keyword) if keyword else -1
    start = max(idx - 70, 0) if idx >= 0 else 0
    return flat[start : start + length]


def has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def sensitive_weight(row: dict[str, str], text: str) -> int:
    haystack = " ".join([row.get("issue_type", ""), row.get("title", ""), text[:3000]])
    return 10 if has_any(haystack, SENSITIVE_KEYWORDS) else 0


def preliminary_judgment(
    risk_type: str,
    risk_score: int,
    triggered_rules: list[str],
    source_refs: list[str],
    excerpt: str,
) -> tuple[str, str]:
    joined_rules = "；".join(triggered_rules)
    joined_refs = "；".join(source_refs)
    if risk_type == "AI 引用風險" and ("不存在" in joined_rules or "來源待確認" in joined_refs or "未偵測到任何來源標記" in joined_rules):
        return (
            "高度疑似 AI 引用錯誤",
            "來源標記缺漏或無法對應 source_index.csv，正式引用前不可直接採用該 AI 段落。",
        )
    if risk_type == "AI 誤讀" and ("多案混用" in joined_rules or "cid=" in excerpt):
        return (
            "高度疑似 AI 混用案件",
            "AI 回覆出現非本案 cid 或跨案線索，需排除張冠李戴後才可使用。",
        )
    if risk_type == "AI 誤讀":
        return (
            "需改寫或人工確認 AI 用語",
            "AI 文字可能含強烈認定、處置建議或將主張推進為認定，需回來源逐句核對。",
        )
    if risk_type == "資料不足":
        return (
            "資料缺漏，暫不得判斷實體",
            "目前缺少可核對來源，應先補齊全文或索引，不得推論案件本身有錯。",
        )
    if risk_type in {"證據風險", "結論跳躍"} and risk_score >= 75:
        return (
            "需深入人工覆核",
            "紅字涉及證據不足、不確定事項或結論連結，可能影響核心爭點，需回原文檢查證據取捨與理由。",
        )
    if risk_type == "程序風險" and risk_score >= 75:
        return (
            "需深入人工覆核程序理由",
            "程序性結論需逐項對照管轄、期限、申訴適格或救濟範圍；若原文缺少要件說明，可能有風險。",
        )
    if risk_type == "法規風險":
        return (
            "需人工核對法規版本",
            "本項通常不是直接錯誤，而是提醒確認事件發生時有效法規與程序類型是否一致。",
        )
    if risk_score < 60:
        return (
            "目前僅屬提醒",
            "規則命中強度較低，若原文前後已有說明，通常可排除；仍建議正式引用前核對。",
        )
    return (
        "需人工覆核",
        "規則已命中可能影響事實、證據、程序或引用的訊號，需回到來源段落判斷是否可排除。",
    )


def finding(
    row: dict[str, str],
    risk_type: str,
    base_score: int,
    triggered_rules: list[str],
    source_refs: list[str],
    excerpt: str,
    review_note: str,
    run_id: str = "",
    provider: str = "",
    model_name: str = "",
) -> AuditFinding:
    text = row.get("full_text", "")
    score = min(100, max(1, base_score + sensitive_weight(row, text)))
    judgment_result, judgment_basis = preliminary_judgment(risk_type, score, triggered_rules, source_refs, excerpt)
    return AuditFinding(
        risk_level=risk_level(score),
        risk_score=score,
        risk_type=risk_type,
        cid=str(row.get("cid", "")),
        title=str(row.get("title", "")),
        result=str(row.get("result", "")),
        issue_type=str(row.get("issue_type", "")),
        date_text=str(row.get("date_text", "")),
        triggered_rules=triggered_rules,
        source_refs=[ref for ref in source_refs if ref],
        excerpt=excerpt[:600],
        review_note=review_note,
        judgment_result=judgment_result,
        judgment_basis=judgment_basis,
        run_id=run_id,
        provider=provider,
        model_name=model_name,
    )


def audit_case_row(row: dict[str, str]) -> list[AuditFinding]:
    text = str(row.get("full_text") or "")
    if not text:
        text_path = row.get("text_path", "")
        path = Path(text_path)
        if text_path and not path.is_absolute():
            path = ROOT_DIR / path
        if path.exists():
            text = path.read_text(encoding="utf-8")
            row = {**row, "full_text": text}
    findings: list[AuditFinding] = []
    if not text.strip():
        findings.append(
            finding(
                row,
                "資料不足",
                80,
                ["找不到案件全文，無法執行來源核對"],
                ["[來源待確認]"],
                "",
                "請先確認 data/texts、data/cases.csv 或 SQLite 是否完整。",
            )
        )
        return findings

    result_text = " ".join([row.get("result", ""), text[:1200]])
    if has_any(result_text, PROCEDURE_KEYWORDS):
        reason_window = text[text.find("理") :] if "理" in text else text
        has_procedure_basis = has_any(reason_window, PROCEDURE_KEYWORDS) and bool(LEGAL_CITATION_RE.search(reason_window))
        if not has_procedure_basis:
            keyword = next((word for word in PROCEDURE_KEYWORDS if word in result_text), "程序")
            findings.append(
                finding(
                    row,
                    "程序風險",
                    72,
                    ["主文或摘要出現程序性結論，但理由中未明確偵測到法規依據或程序要件連結"],
                    [source_ref_for_text(text, keyword)],
                    excerpt_around(text, keyword),
                    "請人工確認不受理、管轄、逾期、申訴適格或再申訴論等程序判斷是否逐項說明。",
                )
            )

    if has_any(text, EVIDENCE_CONFLICT_KEYWORDS):
        conflict_keyword = next((word for word in EVIDENCE_CONFLICT_KEYWORDS if word in text), "")
        conflict_pos = text.find(conflict_keyword)
        nearby = text[max(conflict_pos - 400, 0) : conflict_pos + 800] if conflict_pos >= 0 else text
        if not has_any(nearby, EVIDENCE_REASONING_KEYWORDS):
            findings.append(
                finding(
                    row,
                    "證據風險",
                    70,
                    ["評議書出現陳述不一或證據不足語句，但附近未偵測到證據取捨理由"],
                    [source_ref_for_text(text, conflict_keyword)],
                    excerpt_around(text, conflict_keyword),
                    "請人工確認是否並列有利與不利資料，並說明採信或不採信理由。",
                )
            )

    if has_any(result_text, ["駁回", "不受理", "無理由"]) and has_any(text, UNCERTAINTY_KEYWORDS):
        keyword = next((word for word in UNCERTAINTY_KEYWORDS if word in text), "")
        findings.append(
            finding(
                row,
                "結論跳躍",
                78,
                ["案件結論為駁回、不受理或無理由，但內文出現資料不足或尚待確認語句"],
                [source_ref_for_text(text, keyword)],
                excerpt_around(text, keyword),
                "請人工確認不確定事項是否已被正確限定，且未被直接用作不利結論。",
            )
        )

    legal_hits = LEGAL_CITATION_RE.findall(text)
    if len(set(legal_hits)) >= 6 and not has_any(text, ["行為時", "事件發生時", "當時有效", "修正發布", "適用"]):
        first_hit = legal_hits[0]
        findings.append(
            finding(
                row,
                "法規風險",
                52,
                ["法規引用密集，但未偵測到行為時或事件發生時法規版本說明"],
                [source_ref_for_text(text, first_hit)],
                excerpt_around(text, first_hit),
                "請人工確認引用條文是否為事件發生時有效版本，且程序類型未混用。",
            )
        )

    claim_positions = [text.find(prefix) for prefix in PARTY_CLAIM_PREFIXES if prefix in text]
    for pos in [pos for pos in claim_positions if pos >= 0][:2]:
        nearby = text[pos : pos + 180]
        if has_any(nearby, FACT_ASSERTION_TERMS) and not any(marker in nearby for marker in PARTY_CLAIM_PREFIXES):
            findings.append(
                finding(
                    row,
                    "證據風險",
                    62,
                    ["單方主張附近出現認定性語句，需確認是否誤將主張寫成客觀事實"],
                    [source_ref_for_text(text, nearby[:18])],
                    nearby,
                    "請人工區分當事人主張、客觀資料顯示、調查認定與尚待確認事項。",
                )
            )
            break

    return findings


def read_source_index_units(run_manifest: dict[str, Any]) -> dict[str, set[int]]:
    units: dict[str, set[int]] = {}
    for item in run_manifest.get("source_files", []):
        if item.get("role") != "source_index":
            continue
        path = Path(str(item.get("path") or ""))
        if not path.is_absolute():
            path = ROOT_DIR / path
        if not path.exists():
            continue
        with path.open("r", newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                source_id = str(row.get("source_id") or "").strip()
                number = row.get("paragraph_no") or row.get("page_number") or row.get("line_start")
                try:
                    unit_no = int(str(number).strip())
                except (TypeError, ValueError):
                    continue
                units.setdefault(source_id, set()).add(unit_no)
    return units


def read_source_context(run_manifest: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in run_manifest.get("source_files", []):
        if item.get("role") != "source_context":
            continue
        path = Path(str(item.get("path") or ""))
        if not path.is_absolute():
            path = ROOT_DIR / path
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def source_context_mentions(context: str) -> set[str]:
    return {match.group(0) for match in LEGAL_CITATION_RE.finditer(context)}


def audit_ai_run(run: dict[str, Any]) -> list[AuditFinding]:
    run_id = str(run.get("run_id") or "")
    run_dir = ANALYSIS_RUNS_DIR / Path(run_id).name
    response_path = run_dir / "ai_response.md"
    if not run_id or not response_path.exists():
        return []
    response = response_path.read_text(encoding="utf-8")
    case_ids = [str(value) for value in run.get("case_ids", []) if str(value).strip()]
    cid = case_ids[0] if case_ids else ""
    case_row = get_case_by_cid(cid) or {"cid": cid}
    row = {
        **case_row,
        "cid": cid,
        "title": case_row.get("title", "") if case_row else "",
        "result": case_row.get("result", "") if case_row else "",
        "issue_type": case_row.get("issue_type", "") if case_row else "",
        "date_text": case_row.get("date_text", "") if case_row else "",
    }
    provider = str(run.get("provider") or "")
    model_name = str(run.get("model_name") or "")
    findings: list[AuditFinding] = []
    citations = list(SOURCE_REF_RE.finditer(response))
    if response.strip() and not citations:
        findings.append(
            finding(
                row,
                "AI 引用風險",
                90,
                ["AI 回覆未偵測到任何來源標記"],
                ["[來源待確認]"],
                normalize_text(response)[:320],
                "正式使用前需逐項回到原文補齊來源，避免無來源摘要被誤用。",
                run_id=run_id,
                provider=provider,
                model_name=model_name,
            )
        )

    units = read_source_index_units(run)
    invalid_refs: list[str] = []
    for match in citations:
        source_id = match.group("source")
        unit_no = int(match.group("unit"))
        if source_id not in units or unit_no not in units.get(source_id, set()):
            invalid_refs.append(match.group(0))
    if invalid_refs:
        findings.append(
            finding(
                row,
                "AI 引用風險",
                95,
                ["AI 回覆引用不存在於 source_index.csv 的來源段落"],
                sorted(set(invalid_refs))[:10],
                "；".join(sorted(set(invalid_refs))[:8]),
                "請人工核對 AI 是否引用不存在段落、頁碼或行號。",
                run_id=run_id,
                provider=provider,
                model_name=model_name,
            )
        )

    response_cids = {match.group(1) for match in CID_RE.finditer(response)}
    expected_cids = set(case_ids)
    unexpected = sorted(response_cids - expected_cids)
    if unexpected and expected_cids:
        findings.append(
            finding(
                row,
                "AI 誤讀",
                88,
                ["AI 回覆出現非本次分析來源案件的 cid，可能有多案混用"],
                ["[來源待確認]"],
                "、".join(unexpected[:12]),
                "請人工確認 AI 是否把其他案件人物、日期、理由或結論套入本案。",
                run_id=run_id,
                provider=provider,
                model_name=model_name,
            )
        )

    for keyword in OVERSTATEMENT_KEYWORDS:
        if keyword in response:
            findings.append(
                finding(
                    row,
                    "AI 誤讀",
                    70,
                    ["AI 回覆出現強烈認定或處置性文字"],
                    [source_ref_for_text(response, keyword) or "[來源待確認]"],
                    excerpt_around(response, keyword),
                    "請人工確認是否超出來源整理範圍；報表不得直接作成最終認定或懲處建議。",
                    run_id=run_id,
                    provider=provider,
                    model_name=model_name,
                )
            )
            break

    for prefix in PARTY_CLAIM_PREFIXES:
        if prefix in response:
            pos = response.find(prefix)
            nearby = response[pos : pos + 220]
            if has_any(nearby, FACT_ASSERTION_TERMS) and "主張" not in nearby[max(0, nearby.find(prefix)) : nearby.find(prefix) + len(prefix) + 30]:
                findings.append(
                    finding(
                        row,
                        "AI 誤讀",
                        72,
                        ["AI 回覆可能將單方主張推進為認定性事實"],
                        [source_ref_for_text(response, prefix) or "[來源待確認]"],
                        nearby,
                        "請人工確認 AI 是否清楚區分主張、客觀資料、調查認定及尚待確認。",
                        run_id=run_id,
                        provider=provider,
                        model_name=model_name,
                    )
                )
                break

    context = read_source_context(run)
    context_laws = source_context_mentions(context)
    response_laws = source_context_mentions(response)
    extra_laws = sorted(response_laws - context_laws)
    if extra_laws:
        findings.append(
            finding(
                row,
                "AI 引用風險",
                82,
                ["AI 回覆出現來源包未偵測到的法規條號"],
                ["[來源待確認]"],
                "、".join(extra_laws[:8]),
                "請人工確認 AI 是否自行補充外部法規或錯引條號。",
                run_id=run_id,
                provider=provider,
                model_name=model_name,
            )
        )

    return findings


def select_case_rows(cids: list[str] | None = None) -> list[dict[str, str]]:
    rows = [row for row in read_cases_csv() if row.get("cid")]
    if not cids:
        return rows
    wanted = {str(cid).strip() for cid in cids if str(cid).strip()}
    return [row for row in rows if row.get("cid") in wanted]


def audit_cases(cids: list[str] | None = None) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for row in select_case_rows(cids):
        findings.extend(audit_case_row(row))
    return findings


def audit_analysis_runs(cids: list[str] | None = None) -> list[AuditFinding]:
    wanted = {str(cid).strip() for cid in cids or [] if str(cid).strip()}
    findings: list[AuditFinding] = []
    for run in list_analysis_runs():
        case_ids = [str(value) for value in run.get("case_ids", [])]
        if wanted and not wanted.intersection(case_ids):
            continue
        findings.extend(audit_ai_run(run))
    return findings


def flatten_finding(finding_row: AuditFinding) -> dict[str, Any]:
    data = asdict(finding_row)
    data["triggered_rules"] = "；".join(finding_row.triggered_rules)
    data["source_refs"] = "；".join(finding_row.source_refs)
    return data


def summarize_findings(findings: list[AuditFinding], scanned_cases: int, scanned_analysis_runs: int) -> dict[str, Any]:
    level_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    type_counts: dict[str, int] = {}
    judgment_counts: dict[str, int] = {}
    for item in findings:
        level_counts[item.risk_level] = level_counts.get(item.risk_level, 0) + 1
        type_counts[item.risk_type] = type_counts.get(item.risk_type, 0) + 1
        judgment_counts[item.judgment_result] = judgment_counts.get(item.judgment_result, 0) + 1
    return {
        "generated_at": now_text(),
        "scanned_cases": scanned_cases,
        "scanned_analysis_runs": scanned_analysis_runs,
        "finding_count": len(findings),
        "level_counts": level_counts,
        "type_counts": type_counts,
        "judgment_counts": judgment_counts,
        "disclaimer": "本報表僅供可能誤判風險與 AI 引用風險之人工覆核，不作成最終認定或懲處建議。",
    }


def write_json(path: Path, summary: dict[str, Any], findings: list[AuditFinding]) -> None:
    payload = {"summary": summary, "findings": [asdict(item) for item in findings]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, findings: list[AuditFinding]) -> None:
    fieldnames = [
        "risk_level",
        "risk_score",
        "risk_type",
        "cid",
        "title",
        "result",
        "issue_type",
        "date_text",
        "triggered_rules",
        "source_refs",
        "excerpt",
        "review_note",
        "judgment_result",
        "judgment_basis",
        "status",
        "run_id",
        "provider",
        "model_name",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for item in findings:
            writer.writerow(flatten_finding(item))


def html_badge(level: str) -> str:
    labels = {"high": "高風險", "medium": "中風險", "low": "低風險"}
    return f'<span class="badge badge-{escape(level)}">{labels.get(level, level)}</span>'


def audit_interpretation_steps(risk_type: str) -> list[str]:
    guides = {
        "程序風險": [
            "先看紅字是否是主文或理由中的程序結論，例如不受理、逾期、管轄或申訴適格。",
            "再回到來源段落確認評議書是否逐項說明法規依據、要件與本案事實如何對應。",
            "若後文其實已有完整說明，這通常只是提醒；若找不到依據或只用一句話帶過，才列為需深入覆核。",
        ],
        "證據風險": [
            "先看紅字是否表示雙方說法不一、無客觀資料、資料不足或只是一方主張。",
            "再找同一段前後是否有證據取捨，例如採信何項資料、不採何項資料及理由。",
            "若只有主張沒有證據比較，或把單方說法寫成確定事實，才可能是實質風險。",
        ],
        "結論跳躍": [
            "先看紅字的不確定語句，例如資料不足、尚待確認、未查明。",
            "再對照主文或結論是否仍直接駁回、不受理或作成不利判斷。",
            "若不確定事項與結論無關，可能不是錯誤；若正是核心爭點，應人工覆核。",
        ],
        "法規風險": [
            "先看紅字法規條號，確認是否為案件發生時有效的版本。",
            "再確認程序類型是否一致，例如教師申訴、再申訴、性平、霸凌或校事會議不可混用。",
            "若評議書未交代行為時法規或條文版本，應回原文與法規資料人工核對。",
        ],
        "AI 引用風險": [
            "先看紅字來源標記，確認該段落、頁碼或行號是否真的存在於 source_index.csv。",
            "再打開 AI 回覆與 case_full_context.md 對照，確認 AI 沒有自行補事實、補法條或引用不存在段落。",
            "若來源標記不存在、引用內容對不上，該 AI 文字不可直接採用。",
        ],
        "AI 誤讀": [
            "先看紅字是否出現其他 cid、強烈結論、處置建議或把主張寫成認定。",
            "再確認 AI 回覆是否把 A 案人物、日期、事實、理由或結論套到 B 案。",
            "若只是模型用語過強，應改寫；若事實來源不在本案，應排除該段分析。",
        ],
        "資料不足": [
            "先確認案件全文、來源索引或 AI 分析檔是否存在。",
            "若檔案缺漏，先補資料再判斷；不得用缺資料直接推論案件有錯。",
        ],
    }
    return guides.get(
        risk_type,
        [
            "先看紅字標示的句子或來源。",
            "再回到原文確認該句是否有來源、是否符合上下文、是否被過度推論。",
            "只有在來源、程序或證據對照後仍無法支持時，才列為可能錯誤。",
        ],
    )


def highlight_terms_for_finding(item: AuditFinding) -> list[str]:
    terms = [item.risk_type]
    terms.extend(item.source_refs)
    if item.risk_type == "程序風險":
        terms.extend(PROCEDURE_KEYWORDS)
    elif item.risk_type == "證據風險":
        terms.extend(EVIDENCE_CONFLICT_KEYWORDS + PARTY_CLAIM_PREFIXES + ["客觀資料", "佐證"])
    elif item.risk_type == "結論跳躍":
        terms.extend(UNCERTAINTY_KEYWORDS + ["駁回", "不受理", "無理由"])
    elif item.risk_type == "法規風險":
        terms.extend(LEGAL_CITATION_RE.findall(item.excerpt))
    elif item.risk_type == "AI 引用風險":
        terms.extend(SOURCE_REF_RE.findall(item.excerpt))
        terms.extend(re.findall(r"\[來源：D\d{3}，第\d+(?:段|頁|行)?\]", item.excerpt))
        terms.extend(LEGAL_CITATION_RE.findall(item.excerpt))
    elif item.risk_type == "AI 誤讀":
        terms.extend(OVERSTATEMENT_KEYWORDS + ["cid=", "應撤銷", "應懲處"])
    clean_terms: list[str] = []
    for term in terms:
        if isinstance(term, tuple):
            continue
        value = str(term).strip()
        if value and value not in clean_terms:
            clean_terms.append(value)
    return sorted(clean_terms, key=len, reverse=True)


def highlighted_excerpt_html(item: AuditFinding) -> str:
    text = escape(item.excerpt or "（無摘錄，請回來源核對）")
    for term in highlight_terms_for_finding(item):
        escaped = escape(term)
        if escaped and escaped in text:
            text = text.replace(escaped, f'<mark class="risk-hit">{escaped}</mark>')
    return text


def interpretation_html(item: AuditFinding) -> str:
    steps = audit_interpretation_steps(item.risk_type)
    return "<ol>" + "".join(f"<li>{escape(step)}</li>" for step in steps) + "</ol>"


def write_html(path: Path, summary: dict[str, Any], findings: list[AuditFinding]) -> None:
    sorted_findings = sorted(findings, key=lambda item: item.risk_score, reverse=True)
    high_rows = "\n".join(
        f"""
        <tr>
          <td>{html_badge(item.risk_level)}</td>
          <td>{item.risk_score}</td>
          <td>{escape(item.risk_type)}</td>
          <td>{escape(item.cid)}</td>
          <td>{escape(item.title)}</td>
          <td>{escape(item.result)}</td>
          <td>{escape(item.judgment_result)}</td>
          <td>{escape('；'.join(item.source_refs))}</td>
          <td>{escape(item.review_note)}</td>
        </tr>
        """
        for item in sorted_findings[:80]
    )
    type_cards = "\n".join(
        f"<div class=\"metric\"><strong>{count}</strong><span>{escape(name)}</span></div>"
        for name, count in sorted(summary.get("type_counts", {}).items(), key=lambda pair: pair[1], reverse=True)
    )
    judgment_cards = "\n".join(
        f"<div class=\"metric\"><strong>{count}</strong><span>{escape(name)}</span></div>"
        for name, count in sorted(summary.get("judgment_counts", {}).items(), key=lambda pair: pair[1], reverse=True)
    )
    details = "\n".join(
        f"""
        <section class="finding">
          <div class="finding-head">
            <div>{html_badge(item.risk_level)} <strong>{item.risk_score}</strong>｜{escape(item.risk_type)}｜cid={escape(item.cid)}</div>
            <div class="muted">{escape(item.date_text)}｜{escape(item.issue_type)}｜{escape(item.result)}</div>
          </div>
          <h3>{escape(item.title or item.cid)}</h3>
          <p><strong>觸發規則：</strong>{escape('；'.join(item.triggered_rules))}</p>
          <p><strong>來源核對：</strong>{escape('；'.join(item.source_refs) or '來源待確認')}</p>
          <p><strong>待確認事項：</strong>{escape(item.review_note)}</p>
          <p><strong>初步覆核判斷：</strong><span class="judgment">{escape(item.judgment_result)}</span></p>
          <p><strong>判斷依據：</strong>{escape(item.judgment_basis)}</p>
          <div class="compare">
            <div>
              <h4>系統紅字標示</h4>
              <blockquote>{highlighted_excerpt_html(item)}</blockquote>
            </div>
            <div>
              <h4>人工判讀方式</h4>
              {interpretation_html(item)}
            </div>
          </div>
          <p class="muted">狀態：{escape(item.status)}{('｜run_id=' + escape(item.run_id)) if item.run_id else ''}</p>
        </section>
        """
        for item in sorted_findings
    )
    payload = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>可能誤判風險稽核報表</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f4ee; color: #1f2933; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 28px 22px 56px; }}
    h1 {{ margin: 0 0 8px; font-size: 2rem; }}
    h2 {{ margin-top: 30px; border-bottom: 1px solid #d8d3c8; padding-bottom: 8px; }}
    .notice {{ background: #fff7ed; border: 1px solid #fed7aa; border-left: 5px solid #b45309; padding: 12px 14px; border-radius: 6px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 18px 0; }}
    .metric {{ background: #fffdf8; border: 1px solid #d8d3c8; border-radius: 6px; padding: 12px; }}
    .metric strong {{ display: block; font-size: 1.6rem; }}
    .metric span, .muted {{ color: #65727f; }}
    table {{ width: 100%; border-collapse: collapse; background: #fffdf8; border: 1px solid #d8d3c8; }}
    th, td {{ border-bottom: 1px solid #e7e1d6; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #18332f; color: #fffdf8; }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 3px 9px; font-weight: 700; font-size: .84rem; }}
    .badge-high {{ color: #fff; background: #b42318; }}
    .badge-medium {{ color: #fff; background: #b45309; }}
    .badge-low {{ color: #18332f; background: #c7e6df; }}
    .finding {{ margin: 14px 0; padding: 16px; background: #fffdf8; border: 1px solid #d8d3c8; border-radius: 6px; }}
    .finding-head {{ display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
    blockquote {{ margin: 10px 0 0; padding: 10px 12px; background: #f8fafc; border-left: 4px solid #0f766e; }}
    .guide {{ background: #fffdf8; border: 1px solid #d8d3c8; border-left: 5px solid #b42318; border-radius: 6px; padding: 14px 16px; margin: 18px 0; }}
    .compare {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, .9fr); gap: 14px; align-items: start; margin-top: 10px; }}
    .compare h4 {{ margin: 0 0 6px; }}
    .risk-hit {{ color: #b42318; background: #fee2e2; font-weight: 800; padding: 0 3px; border-radius: 3px; }}
    .judgment {{ color: #b42318; font-weight: 800; }}
    @media (max-width: 760px) {{ .compare {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <h1>可能誤判風險稽核報表</h1>
  <p class="muted">產生時間：{escape(str(summary.get("generated_at", "")))}</p>
  <div class="notice">{escape(str(summary.get("disclaimer", "")))}</div>
  <div class="guide">
    <strong>怎麼看紅字是否真的有錯：</strong>
    <ol>
      <li>紅字只是「需要人工核對」的訊號，不等於案件已誤判。</li>
      <li>先看紅字句子屬於主張、客觀資料、調查認定，還是尚待確認。</li>
      <li>再用旁邊的來源段落回原文核對：是否有證據、程序要件、法規版本與理由說明。</li>
      <li>如果後文已有完整說明，通常只是低階提醒；如果找不到來源或理由，才列為可能錯誤。</li>
    </ol>
  </div>
  <div class="metrics">
    <div class="metric"><strong>{summary.get("scanned_cases", 0)}</strong><span>掃描案件</span></div>
    <div class="metric"><strong>{summary.get("scanned_analysis_runs", 0)}</strong><span>AI 分析紀錄</span></div>
    <div class="metric"><strong>{summary.get("finding_count", 0)}</strong><span>風險項目</span></div>
    <div class="metric"><strong>{summary.get("level_counts", {}).get("high", 0)}</strong><span>高風險</span></div>
    <div class="metric"><strong>{summary.get("level_counts", {}).get("medium", 0)}</strong><span>中風險</span></div>
    <div class="metric"><strong>{summary.get("level_counts", {}).get("low", 0)}</strong><span>低風險</span></div>
  </div>
  <h2>分類統計</h2>
  <div class="metrics">{type_cards or '<div class="metric"><strong>0</strong><span>無風險項目</span></div>'}</div>
  <h2>初步覆核判斷統計</h2>
  <div class="metrics">{judgment_cards or '<div class="metric"><strong>0</strong><span>無判斷項目</span></div>'}</div>
  <h2>高風險清單</h2>
  <table>
    <thead><tr><th>等級</th><th>分數</th><th>類型</th><th>cid</th><th>案件</th><th>結果</th><th>初步判斷</th><th>來源</th><th>待確認</th></tr></thead>
    <tbody>{high_rows or '<tr><td colspan="9">未偵測到風險項目。</td></tr>'}</tbody>
  </table>
  <h2>單案詳情與引用核對</h2>
  {details or '<p>未偵測到風險項目。</p>'}
</main>
</body>
</html>
"""
    path.write_text(payload, encoding="utf-8")


def unique_report_dir(output_root: Path = AUDIT_REPORTS_DIR) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    base = output_root / filesystem_timestamp()
    path = base
    suffix = 1
    while path.exists():
        suffix += 1
        path = output_root / f"{base.name}_{suffix}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def create_audit_report(
    cids: list[str] | None = None,
    include_cases: bool = True,
    include_analysis_runs: bool = True,
    output_root: Path = AUDIT_REPORTS_DIR,
) -> AuditReport:
    findings: list[AuditFinding] = []
    case_rows = select_case_rows(cids) if include_cases else []
    runs = list_analysis_runs()
    if cids:
        wanted = set(cids)
        runs = [run for run in runs if wanted.intersection({str(value) for value in run.get("case_ids", [])})]
    if include_cases:
        for row in case_rows:
            findings.extend(audit_case_row(row))
    if include_analysis_runs:
        for run in runs:
            findings.extend(audit_ai_run(run))
    summary = summarize_findings(findings, scanned_cases=len(case_rows), scanned_analysis_runs=len(runs) if include_analysis_runs else 0)
    report_dir = unique_report_dir(output_root)
    report_id = report_dir.name
    json_path = report_dir / "misjudgment_audit.json"
    csv_path = report_dir / "misjudgment_audit.csv"
    html_path = report_dir / "misjudgment_audit.html"
    write_json(json_path, summary, findings)
    write_csv(csv_path, findings)
    write_html(html_path, summary, findings)
    return AuditReport(report_id, report_dir, findings, summary, json_path, csv_path, html_path)


def list_audit_reports(output_root: Path = AUDIT_REPORTS_DIR) -> list[Path]:
    if not output_root.exists():
        return []
    return sorted([path for path in output_root.iterdir() if path.is_dir()], key=lambda path: path.stat().st_mtime, reverse=True)


def read_audit_report(report_dir: Path) -> dict[str, Any]:
    path = Path(report_dir) / "misjudgment_audit.json"
    if not path.exists():
        raise FileNotFoundError(f"找不到稽核報表 JSON：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="產生公開案件與 AI 分析結果的可能誤判風險稽核報表")
    parser.add_argument("--all", action="store_true", help="掃描全部已下載公開案件")
    parser.add_argument("--cid", action="append", default=[], help="指定 cid，可重複指定")
    parser.add_argument("--analysis-runs", action="store_true", help="掃描已保存 AI 分析結果")
    parser.add_argument("--cases-only", action="store_true", help="只掃描公開案件原文")
    parser.add_argument("--html", action="store_true", help="保留相容參數；報表一律輸出 HTML")
    parser.add_argument("--output-root", type=Path, default=AUDIT_REPORTS_DIR, help="報表輸出根目錄")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.all and not args.cid and not args.analysis_runs:
        raise SystemExit("請指定 --all、--cid 或 --analysis-runs")
    include_cases = bool(args.all or args.cid) and not args.analysis_runs or bool(args.all or args.cid)
    include_analysis = bool(args.analysis_runs or (args.all and not args.cases_only))
    if args.cases_only:
        include_analysis = False
    result = create_audit_report(
        cids=args.cid or None,
        include_cases=include_cases,
        include_analysis_runs=include_analysis,
        output_root=args.output_root,
    )
    print(f"已產生可能誤判風險稽核報表：{result.report_dir}")
    print(f"掃描案件：{result.summary['scanned_cases']}；AI 分析紀錄：{result.summary['scanned_analysis_runs']}；風險項目：{result.summary['finding_count']}")
    print(f"HTML：{result.html_path}")
    print(f"CSV：{result.csv_path}")
    print(f"JSON：{result.json_path}")


if __name__ == "__main__":
    main()
