from __future__ import annotations

import argparse
from pathlib import Path

from private_db import create_case, get_case_by_uuid, init_private_db, list_cases
from private_documents import import_document_from_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="匯入已去識別化真實評議書到私人案件資料庫")
    parser.add_argument("files", nargs="+", help="PDF、DOCX 或 TXT 檔案")
    parser.add_argument("--case-uuid", default="", help="匯入到既有案件 UUID")
    parser.add_argument("--case-number", default="", help="新案件案號")
    parser.add_argument("--title", default="", help="新案件標題")
    parser.add_argument("--case-type", default="", help="新案件類型")
    parser.add_argument("--description", default="", help="新案件說明")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_private_db()
    if args.case_uuid:
        case = get_case_by_uuid(args.case_uuid)
        if not case:
            raise SystemExit(f"找不到 case_uuid={args.case_uuid}")
    else:
        title = args.title or Path(args.files[0]).stem
        case = create_case(args.case_number, title, args.case_type, args.description)
        print(f"已建立案件：{case['case_uuid']}")

    for item in args.files:
        result = import_document_from_path(int(case["id"]), Path(item))
        duplicate = "（重複，未新增內容）" if result.get("duplicate") else ""
        print(f"{result.get('original_filename')}：{result.get('parse_status')}，units={result.get('unit_count')}{duplicate}")
    print(f"目前私人案件數：{len(list_cases())}")


if __name__ == "__main__":
    main()
