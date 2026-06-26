from __future__ import annotations

import argparse

from utils import get_case_by_cid, make_snippet, search_fts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="搜尋本機教師申訴評議書資料庫")
    parser.add_argument("terms", nargs="*", help="搜尋關鍵字")
    parser.add_argument("--query", default="", help="搜尋語句")
    parser.add_argument("--cid", default="", help="直接查指定 cid")
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def print_case(index: int, row: dict[str, str], query: str = "") -> None:
    snippet = row.get("snippet") or make_snippet(row.get("full_text", ""), query)
    print(f"[{index}] cid={row.get('cid', '')}")
    print(f"標題：{row.get('title', '')}")
    print(f"案件類型：{row.get('case_type', '')}")
    print(f"判斷結果：{row.get('result', '')}")
    print(f"日期：{row.get('date_text', '')}")
    print(f"網址：{row.get('url', '')}")
    print(f"片段：{snippet}")
    print()


def main() -> None:
    args = parse_args()
    if args.cid:
        row = get_case_by_cid(args.cid)
        if not row:
            print(f"找不到 cid={args.cid}")
            return
        print("找到 1 筆結果\n")
        print_case(1, row)
        return

    query = args.query or " ".join(args.terms)
    if not query:
        print("請輸入查詢關鍵字，或使用 --cid。")
        return
    rows = search_fts(query=query, limit=args.limit)
    print(f"找到 {len(rows)} 筆結果\n")
    for index, row in enumerate(rows, start=1):
        print_case(index, row, query)


if __name__ == "__main__":
    main()
