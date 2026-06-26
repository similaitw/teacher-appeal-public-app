from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


CID_RE = re.compile(r"(?:cid=)?([0-9]{6,12})", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="從貼上的網址或文字整理 cid 清單")
    parser.add_argument("--input", default="", help="來源文字檔；未指定時讀取 stdin")
    parser.add_argument("--output", default="cids.txt", help="輸出 cid 清單，預設 cids.txt")
    parser.add_argument("--append", action="store_true", help="保留輸出檔既有 cid 並追加去重")
    return parser.parse_args()


def extract_cids(text: str) -> list[str]:
    seen: set[str] = set()
    cids: list[str] = []
    for match in CID_RE.finditer(text):
        cid = match.group(1).strip()
        if cid and cid not in seen:
            seen.add(cid)
            cids.append(cid)
    return cids


def main() -> None:
    args = parse_args()
    source = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    cids = extract_cids(source)
    output = Path(args.output)

    if args.append and output.exists():
        existing = extract_cids(output.read_text(encoding="utf-8"))
        cids = existing + [cid for cid in cids if cid not in set(existing)]

    output.write_text("\n".join(cids) + ("\n" if cids else ""), encoding="utf-8")
    print(f"已輸出 {len(cids)} 個 cid 到 {output}")


if __name__ == "__main__":
    main()
