from __future__ import annotations

import shutil
from pathlib import Path

from private_db import (
    MAX_UPLOAD_BYTES,
    PRIVATE_DB_PATH,
    ParsedUnit,
    UPLOADED_CASES_DIR,
    get_case_by_id,
    insert_document_with_units,
    safe_filename,
    sha256_bytes,
    validate_extension,
)


def parse_txt(data: bytes) -> tuple[list[ParsedUnit], list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    units: list[ParsedUnit] = []
    warnings: list[str] = []
    chunk_size = 30
    for start in range(0, len(lines), chunk_size):
        chunk = "\n".join(lines[start : start + chunk_size]).strip()
        if chunk:
            units.append(ParsedUnit(unit_type="txt_lines", line_start=start + 1, line_end=min(start + chunk_size, len(lines)), content=chunk))
    if not units:
        warnings.append("TXT 未擷取到文字")
    return units, warnings


def parse_docx(path: Path) -> tuple[list[ParsedUnit], list[str]]:
    from docx import Document

    document = Document(str(path))
    units: list[ParsedUnit] = []
    warnings: list[str] = []
    for index, paragraph in enumerate(document.paragraphs, start=1):
        text = paragraph.text.strip()
        if text:
            units.append(ParsedUnit(unit_type="docx_paragraph", paragraph_number=index, content=text))
    if not units:
        warnings.append("DOCX 未擷取到文字段落")
    return units, warnings


def parse_pdf(path: Path) -> tuple[list[ParsedUnit], list[str]]:
    import fitz

    units: list[ParsedUnit] = []
    warnings: list[str] = []
    with fitz.open(str(path)) as document:
        for page_index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                units.append(ParsedUnit(unit_type="pdf_page", page_number=page_index, content=text))
            else:
                units.append(ParsedUnit(unit_type="pdf_page", page_number=page_index, content=""))
                warnings.append(f"第 {page_index} 頁無文字層，需要 OCR")
    if not units:
        warnings.append("PDF 沒有可擷取文字層，需要 OCR")
    return units, warnings


def parse_file(path: Path, original_filename: str, data: bytes) -> tuple[list[ParsedUnit], list[str]]:
    suffix = validate_extension(original_filename)
    if suffix == ".txt":
        return parse_txt(data)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".pdf":
        return parse_pdf(path)
    raise ValueError("不支援的檔案格式")


def import_document(case_id: int, filename: str, data: bytes, mime_type: str = "", db_path: Path | None = None) -> dict[str, object]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"檔案超過大小限制 {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    validate_extension(filename)
    case = get_case_by_id(case_id, db_path) if db_path else get_case_by_id(case_id)
    if not case:
        raise ValueError("找不到私人案件")
    safe_name = safe_filename(filename)
    file_hash = sha256_bytes(data)
    case_dir = UPLOADED_CASES_DIR / str(case["case_uuid"])
    case_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{file_hash[:16]}_{safe_name}"
    stored_path = case_dir / stored_filename
    stored_path.write_bytes(data)
    try:
        units, warnings = parse_file(stored_path, filename, data)
        if units and warnings:
            status = "parsed_with_warnings"
            error = "；".join(warnings)
        elif units:
            status = "parsed"
            error = ""
        else:
            status = "no_text"
            error = "；".join(warnings) or "無法擷取文字"
    except Exception as exc:
        status = "failed"
        error = str(exc)
        units = []
    doc, duplicate = insert_document_with_units(
        case_id=case_id,
        original_filename=Path(filename).name,
        stored_filename=stored_filename,
        mime_type=mime_type,
        file_sha256=file_hash,
        file_size=len(data),
        parse_status=status,
        parse_error=error,
        units=units,
        db_path=db_path or PRIVATE_DB_PATH,
    )
    if duplicate and stored_path.exists():
        stored_path.unlink()
    result = dict(doc)
    result["duplicate"] = duplicate
    result["unit_count"] = len(units)
    return result


def import_document_from_path(case_id: int, path: Path, db_path: Path | None = None) -> dict[str, object]:
    data = path.read_bytes()
    return import_document(case_id, path.name, data, mime_type="", db_path=db_path)
