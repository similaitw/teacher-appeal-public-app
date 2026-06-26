from __future__ import annotations

import argparse

from public_ai_export import PUBLIC_AI_EXPORT_DIR, export_public_cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="將公開評議書匯出成可上傳 ChatGPT/Gemini 的單案分析包")
    parser.add_argument("--all", action="store_true", help="匯出 data/cases.csv 中所有公開案件")
    parser.add_argument("--cid", action="append", default=[], help="匯出指定 cid，可重複指定")
    parser.add_argument("--limit", type=int, default=0, help="限制匯出筆數，常用於小量測試")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.all and not args.cid:
        raise SystemExit("請指定 --all 或至少一個 --cid")
    outputs = export_public_cases(cids=args.cid or None, limit=args.limit, output_root=PUBLIC_AI_EXPORT_DIR)
    print(f"已匯出 {len(outputs)} 個公開案件 AI 分析包")
    print(f"輸出根目錄：{PUBLIC_AI_EXPORT_DIR}")
    for path in outputs[:20]:
        print(path)
    if len(outputs) > 20:
        print(f"...其餘 {len(outputs) - 20} 個略")


if __name__ == "__main__":
    main()
