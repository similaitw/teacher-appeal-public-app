from __future__ import annotations

import argparse
from pathlib import Path

from llm import build_evidence, retrieve_cases
from utils import EXPORTS_DIR, get_case_by_cid, make_snippet, search_fts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="將案件或搜尋結果匯出成 Markdown")
    parser.add_argument("--cid", default="", help="匯出指定 cid 全文")
    parser.add_argument("--query", default="", help="匯出搜尋結果摘要")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", default="", help="輸出路徑，預設 data/exports/*.md")
    parser.add_argument("--with-evidence", action="store_true", help="搜尋匯出時附上送給 AI 的來源片段")
    return parser.parse_args()


def case_markdown(row: dict[str, str]) -> str:
    return f"""# {row.get("title", "")}

- cid: {row.get("cid", "")}
- 日期: {row.get("date_text", "")}
- 案件類型: {row.get("case_type", "")}
- 爭點分類: {row.get("issue_type", "")}
- 結果: {row.get("result", "")}
- 原始網址: {row.get("url", "")}

## 全文

{row.get("full_text", "")}
"""


def search_markdown(query: str, rows: list[dict[str, str]], with_evidence: bool) -> str:
    lines = [f"# 搜尋結果：{query}", ""]
    for index, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"## {index}. {row.get('title', '')}",
                "",
                f"- cid: {row.get('cid', '')}",
                f"- 日期: {row.get('date_text', '')}",
                f"- 結果: {row.get('result', '')}",
                f"- 原始網址: {row.get('url', '')}",
                "",
                make_snippet(row.get("full_text", ""), query, length=260),
                "",
            ]
        )
    if with_evidence:
        evidence, _ = build_evidence(rows, query)
        lines.extend(["## AI 來源片段", "", evidence])
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.cid:
        row = get_case_by_cid(args.cid)
        if not row:
            raise SystemExit(f"找不到 cid={args.cid}")
        content = case_markdown(row)
        default_name = f"case_{args.cid}.md"
    else:
        if not args.query:
            raise SystemExit("請指定 --cid 或 --query")
        rows = retrieve_cases(args.query, limit=args.limit)
        if not rows:
            rows = search_fts(args.query, limit=args.limit)
        content = search_markdown(args.query, rows, args.with_evidence)
        default_name = "search_results.md"

    output = Path(args.output) if args.output else EXPORTS_DIR / default_name
    output.write_text(content, encoding="utf-8")
    print(f"已匯出：{output}")


if __name__ == "__main__":
    main()
