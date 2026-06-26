from __future__ import annotations

import argparse

from private_db import export_analysis_package, get_case_by_uuid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="產生 Codex 分析用 Markdown 來源包")
    parser.add_argument("--case-uuid", required=True)
    parser.add_argument("--query", default="", help="只匯出搜尋相關片段")
    parser.add_argument("--full", action="store_true", help="匯出全文")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    case = get_case_by_uuid(args.case_uuid)
    if not case:
        raise SystemExit(f"找不到 case_uuid={args.case_uuid}")
    out_dir = export_analysis_package(int(case["id"]), query=args.query, full_context=args.full or not args.query)
    print(f"已輸出：{out_dir}")


if __name__ == "__main__":
    main()
