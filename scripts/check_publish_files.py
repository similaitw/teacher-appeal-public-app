"""檢查 git 追蹤檔案是否符合公開發布政策（CI 與 sync_repos.py 共用）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish_policy import find_violations  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT_DIR, text=True, check=True, capture_output=True).stdout.splitlines()
    violations = find_violations(files)
    for path in violations["forbidden"]:
        print(f"[FORBIDDEN] {path}")
    for path in violations["not_allowed"]:
        print(f"[NOT ALLOWED] {path}")
    if violations["forbidden"] or violations["not_allowed"]:
        print("公開檔案清單檢查失敗。")
        return 1
    print(f"公開檔案清單檢查通過：{len(files)} 個檔案")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
