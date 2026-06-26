from __future__ import annotations

import csv
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from utils import DATA_DIR, ROOT_DIR, TEXTS_DIR, read_cases_csv


PUBLIC_AI_EXPORT_DIR = DATA_DIR / "ai_exports" / "public_cases"
PUBLIC_AI_BUNDLE_DIR = DATA_DIR / "ai_exports" / "bundles"
SOURCE_ID = "D001"

BOILERPLATE_LINES = {
    "跳到主要內容區塊",
    "教育部訴願案件查詢系統",
    ":::",
    "網站導覽",
    "評議書查詢",
    "評議案件進度查詢",
    "回首頁",
    "轉存PDF檔",
    "轉存ODF檔",
    "資通安全及隱私政策",
}

SECTION_HEADINGS = {
    "主文": "主文",
    "主 文": "主文",
    "主　文": "主文",
    "事實": "事實",
    "事 實": "事實",
    "事　實": "事實",
    "理由": "理由",
    "理 由": "理由",
    "理　由": "理由",
}


@dataclass
class PublicParagraph:
    paragraph_no: int
    section: str
    heading: str
    content: str
    char_start: int
    char_end: int


@dataclass
class PublicBundleResult:
    bundle_dir: Path
    zip_path: Path
    case_dirs: list[Path]
    manifest: dict[str, object]


def export_time() -> str:
    return datetime.now().isoformat(timespec="seconds")


def filesystem_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def resolve_text_path(row: dict[str, str]) -> Path:
    text_path = row.get("text_path", "")
    if text_path:
        path = Path(text_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        if path.exists():
            return path
    cid = row.get("cid", "")
    return TEXTS_DIR / f"{cid}.txt"


def clean_public_text(raw_text: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in raw_text.splitlines()]
    cleaned: list[str] = []
    in_footer = False
    for line in lines:
        if not line:
            continue
        if line.startswith("歡迎蒞臨教育部"):
            in_footer = True
        if in_footer:
            continue
        if line in BOILERPLATE_LINES:
            continue
        if line.endswith("-教育部教師申訴案件查詢系統"):
            line = line.replace("-教育部教師申訴案件查詢系統", "").strip()
        cleaned.append(line)
    return "\n".join(cleaned)


def section_for_line(line: str, current_section: str) -> str:
    compact = re.sub(r"\s+", "", line)
    if line in SECTION_HEADINGS:
        return SECTION_HEADINGS[line]
    if compact in SECTION_HEADINGS:
        return SECTION_HEADINGS[compact]
    if line.startswith("發文日期") or line.startswith("發文字號") or line.startswith("教育部"):
        return "案件基本資料"
    if line.startswith("申訴人") or line.startswith("原措施"):
        return current_section or "案件基本資料"
    return current_section or "本文"


def heading_for_line(line: str, section: str) -> str:
    compact = re.sub(r"\s+", "", line)
    if line in SECTION_HEADINGS or compact in SECTION_HEADINGS:
        return SECTION_HEADINGS.get(line) or SECTION_HEADINGS.get(compact, line)
    if re.match(r"^[一二三四五六七八九十]+、", line):
        return line.split("。", 1)[0][:60]
    if re.match(r"^\([一二三四五六七八九十]+\)", line):
        return line.split("。", 1)[0][:60]
    if re.match(r"^\d+[.．、]", line):
        return line.split("。", 1)[0][:60]
    return section


def split_public_paragraphs(cleaned_text: str) -> list[PublicParagraph]:
    paragraphs: list[PublicParagraph] = []
    current_section = "案件基本資料"
    cursor = 0
    for line in cleaned_text.splitlines():
        line = line.strip()
        if not line:
            cursor += 1
            continue
        start = cleaned_text.find(line, cursor)
        if start < 0:
            start = cursor
        end = start + len(line)
        current_section = section_for_line(line, current_section)
        paragraphs.append(
            PublicParagraph(
                paragraph_no=len(paragraphs) + 1,
                section=current_section,
                heading=heading_for_line(line, current_section),
                content=line,
                char_start=start,
                char_end=end,
            )
        )
        cursor = end
    return paragraphs


def analysis_prompt(row: dict[str, str]) -> str:
    return f"""# AI 分析指令

請只根據 `case_full_context.md` 的 D001 來源段落分析本案，不得使用外部資料補充事實。

請輸出：

1. 案件基本資料
2. 程序時間軸
3. 申訴人主張
4. 機關／學校說明
5. 申評會理由
6. 爭點
7. 可引用重點
8. 不確定事項
9. 引用核對表

要求：

- 每項重要事實都標示 `[來源：D001，第N段]`。
- 不得摘要成無來源結論。
- 不得引用未提供的法規條號或未出現在來源的事實。
- 單方陳述使用「主張」、「表示」或「稱」。
- 客觀資料使用「依資料顯示」或「評議書記載」。

本案 cid：{row.get("cid", "")}
本案標題：{row.get("title", "")}
"""


def multi_case_prompt(cases: list[dict[str, object]], mode: str) -> str:
    case_lines = "\n".join(
        f"- cid={case.get('cid', '')}｜{case.get('title', '')}｜{case.get('date_text', '')}｜{case.get('result', '')}"
        for case in cases
    )
    mode_note = "多案比較" if mode == "compare" else "多個單案分別分析"
    return f"""# ChatGPT / Gemini 分析指令

本資料包用途：{mode_note}。

請先讀取各案件子資料夾中的 `case_full_context.md`，再依本指令分析。每個案件的事實來源都只有該案件自己的 D001 段落。

## 已選案件

{case_lines}

## 絕對限制

- 不得把任一案件的人物、日期、學校、程序、主張、理由或結論套用到其他案件。
- 引用事實時必須同時標示 cid 與來源段落，例如：`cid=114070228，[來源：D001，第12段]`。
- 不得使用未出現在資料包內的外部資料補充事實。
- 若來源不足，請寫「來源不足，無法判斷」，不要推測。
- 單方陳述使用「主張」、「表示」或「稱」；評議書記載事項使用「依評議書記載」。

## 請輸出

1. 逐案結構化摘要
2. 逐案程序時間軸
3. 逐案申訴人主張
4. 逐案機關／學校說明
5. 逐案申評會理由
6. 共同爭點與差異
7. 相同爭點下的不同見解
8. 可引用段落清單
9. 不確定事項
10. 引用核對表
"""


def manifest_for_case(row: dict[str, str], text_path: Path, paragraph_count: int, exported_at: str) -> dict[str, object]:
    return {
        "cid": row.get("cid", ""),
        "title": row.get("title", ""),
        "date_text": row.get("date_text", ""),
        "doc_no": row.get("doc_no", ""),
        "result": row.get("result", ""),
        "case_type": row.get("case_type", ""),
        "issue_type": row.get("issue_type", ""),
        "url": row.get("url", ""),
        "source_text_path": str(text_path.relative_to(ROOT_DIR)) if text_path.is_relative_to(ROOT_DIR) else str(text_path),
        "paragraph_count": paragraph_count,
        "export_time": exported_at,
    }


def write_case_package(row: dict[str, str], output_root: Path = PUBLIC_AI_EXPORT_DIR) -> Path:
    cid = row.get("cid", "").strip()
    if not cid:
        raise ValueError("案件缺少 cid")
    text_path = resolve_text_path(row)
    if not text_path.exists():
        raise FileNotFoundError(f"找不到文字檔：{text_path}")
    raw_text = text_path.read_text(encoding="utf-8")
    cleaned = clean_public_text(raw_text)
    paragraphs = split_public_paragraphs(cleaned)
    if not paragraphs:
        raise ValueError(f"cid={cid} 沒有可匯出的段落")

    out_dir = output_root / cid
    out_dir.mkdir(parents=True, exist_ok=True)
    exported_at = export_time()
    manifest = manifest_for_case(row, text_path, len(paragraphs), exported_at)
    (out_dir / "case_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    context_lines = [
        "# 案件基本資料",
        "",
        f"- cid：{cid}",
        f"- 標題：{row.get('title', '')}",
        f"- 日期：{row.get('date_text', '')}",
        f"- 文號：{row.get('doc_no', '')}",
        f"- 案件類型：{row.get('case_type', '')}",
        f"- 爭點分類：{row.get('issue_type', '')}",
        f"- 結果：{row.get('result', '')}",
        f"- 原始網址：{row.get('url', '')}",
        f"- 匯出時間：{exported_at}",
        "",
        "# 文件內容",
        "",
        f"## 文件 {SOURCE_ID}：{row.get('title', cid)}",
        "",
    ]
    for paragraph in paragraphs:
        context_lines.extend(
            [
                f"### 第 {paragraph.paragraph_no} 段",
                "",
                f"[來源：{SOURCE_ID}，第{paragraph.paragraph_no}段]",
                "",
                paragraph.content,
                "",
            ]
        )
    (out_dir / "case_full_context.md").write_text("\n".join(context_lines), encoding="utf-8")

    with (out_dir / "source_index.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        fieldnames = ["source_id", "cid", "section", "paragraph_no", "heading", "char_start", "char_end"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for paragraph in paragraphs:
            writer.writerow(
                {
                    "source_id": SOURCE_ID,
                    "cid": cid,
                    "section": paragraph.section,
                    "paragraph_no": paragraph.paragraph_no,
                    "heading": paragraph.heading,
                    "char_start": paragraph.char_start,
                    "char_end": paragraph.char_end,
                }
            )
    (out_dir / "case_prompt.md").write_text(analysis_prompt(row), encoding="utf-8")
    return out_dir


def write_selected_cases_csv(bundle_dir: Path, cases: list[dict[str, object]]) -> None:
    with (bundle_dir / "selected_cases.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        fieldnames = ["cid", "title", "date_text", "doc_no", "result", "case_type", "issue_type", "url", "paragraph_count"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for case in cases:
            writer.writerow({field: case.get(field, "") for field in fieldnames})


def zip_directory(source_dir: Path) -> Path:
    zip_path = source_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir))
    return zip_path


def load_public_cases() -> list[dict[str, str]]:
    return [row for row in read_cases_csv() if row.get("cid")]


def select_rows_by_cid(cids: list[str], case_rows: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    rows = case_rows if case_rows is not None else load_public_cases()
    by_cid = {row.get("cid", ""): row for row in rows if row.get("cid")}
    selected: list[dict[str, str]] = []
    missing: list[str] = []
    seen: set[str] = set()
    for cid in cids:
        clean_cid = str(cid).strip()
        if not clean_cid or clean_cid in seen:
            continue
        seen.add(clean_cid)
        row = by_cid.get(clean_cid)
        if row is None:
            missing.append(clean_cid)
        else:
            selected.append(row)
    if missing:
        raise ValueError(f"找不到 cid：{', '.join(missing)}")
    if not selected:
        raise ValueError("沒有可匯出的案件")
    return selected


def export_public_case_bundle(
    cids: list[str],
    mode: str = "single",
    output_root: Path = PUBLIC_AI_BUNDLE_DIR,
    case_rows: list[dict[str, str]] | None = None,
    canonical_output_root: Path = PUBLIC_AI_EXPORT_DIR,
) -> PublicBundleResult:
    if mode not in {"single", "compare"}:
        raise ValueError("mode 必須是 single 或 compare")
    selected_rows = select_rows_by_cid(cids, case_rows=case_rows)
    base_name = f"{filesystem_timestamp()}_{mode}_{len(selected_rows)}_cases"
    bundle_dir = output_root / base_name
    suffix = 1
    while bundle_dir.exists() or bundle_dir.with_suffix(".zip").exists():
        suffix += 1
        bundle_dir = output_root / f"{base_name}_{suffix}"
    cases_root = bundle_dir / "cases"
    bundle_dir.mkdir(parents=True, exist_ok=False)
    cases_root.mkdir(parents=True, exist_ok=True)

    case_dirs: list[Path] = []
    case_manifests: list[dict[str, object]] = []
    for row in selected_rows:
        # Keep the canonical one-case export path fresh, then copy the same package structure into this upload bundle.
        write_case_package(row, output_root=canonical_output_root)
        case_dir = write_case_package(row, output_root=cases_root)
        case_dirs.append(case_dir)
        manifest = json.loads((case_dir / "case_manifest.json").read_text(encoding="utf-8"))
        case_manifests.append(manifest)

    exported_at = export_time()
    bundle_manifest: dict[str, object] = {
        "export_time": exported_at,
        "mode": mode,
        "case_count": len(case_manifests),
        "cids": [case.get("cid", "") for case in case_manifests],
        "cases": [
            {
                "cid": case.get("cid", ""),
                "title": case.get("title", ""),
                "date_text": case.get("date_text", ""),
                "doc_no": case.get("doc_no", ""),
                "result": case.get("result", ""),
                "case_type": case.get("case_type", ""),
                "issue_type": case.get("issue_type", ""),
                "url": case.get("url", ""),
                "paragraph_count": case.get("paragraph_count", 0),
            }
            for case in case_manifests
        ],
    }
    (bundle_dir / "bundle_manifest.json").write_text(json.dumps(bundle_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_selected_cases_csv(bundle_dir, case_manifests)
    (bundle_dir / "multi_case_prompt.md").write_text(multi_case_prompt(case_manifests, mode), encoding="utf-8")
    zip_path = zip_directory(bundle_dir)
    return PublicBundleResult(bundle_dir=bundle_dir, zip_path=zip_path, case_dirs=case_dirs, manifest=bundle_manifest)


def export_public_cases(cids: list[str] | None = None, limit: int = 0, output_root: Path = PUBLIC_AI_EXPORT_DIR) -> list[Path]:
    rows = load_public_cases()
    if cids:
        wanted = set(cids)
        rows = [row for row in rows if row.get("cid") in wanted]
    if limit:
        rows = rows[:limit]
    outputs = []
    for row in rows:
        outputs.append(write_case_package(row, output_root=output_root))
    return outputs
