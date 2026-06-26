from __future__ import annotations

import argparse
import csv
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PRIVATE_REMOTE = "origin"
PUBLIC_REMOTE = "public-deploy"
BRANCH = "main"
FORBIDDEN_TRACKED_PATTERNS = (
    ".env",
    "secrets.toml",
    "private_cases.db",
    "uploaded_cases/",
    "browser_profiles/",
    "data/ai_exports/",
    "data/exports/",
    ".venv/",
    "__pycache__/",
)


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command))
    return subprocess.run(command, cwd=ROOT_DIR, text=True, check=check, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def print_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout.rstrip())


def ensure_clean_worktree() -> None:
    result = run(["git", "status", "--porcelain"])
    if result.stdout.strip():
        print(result.stdout, file=sys.stderr)
        raise SystemExit("工作樹尚有未提交變更，請先 commit 後再同步。")


def ensure_remotes() -> None:
    result = run(["git", "remote"])
    remotes = set(result.stdout.split())
    missing = [remote for remote in (PRIVATE_REMOTE, PUBLIC_REMOTE) if remote not in remotes]
    if missing:
        raise SystemExit(f"缺少 remote：{', '.join(missing)}")


def ensure_branch() -> None:
    result = run(["git", "branch", "--show-current"])
    branch = result.stdout.strip()
    if branch != BRANCH:
        raise SystemExit(f"目前分支是 {branch!r}，請切回 {BRANCH!r} 後再同步。")


def ensure_no_forbidden_tracked_files() -> None:
    result = run(["git", "ls-files"])
    files = result.stdout.splitlines()
    forbidden = [
        path
        for path in files
        if any(path == pattern or path.startswith(pattern) or f"/{pattern}" in path for pattern in FORBIDDEN_TRACKED_PATTERNS)
    ]
    if forbidden:
        raise SystemExit("追蹤清單含不得上傳檔案：\n" + "\n".join(forbidden))


def ensure_public_data_consistency() -> None:
    cases_csv = ROOT_DIR / "data" / "cases.csv"
    with cases_csv.open("r", newline="", encoding="utf-8-sig") as fh:
        case_cids = {row["cid"].strip() for row in csv.DictReader(fh) if row.get("cid", "").strip()}
    text_cids = {path.stem for path in (ROOT_DIR / "data" / "texts").glob("*.txt")}
    html_cids = {path.stem for path in (ROOT_DIR / "data" / "raw_html").glob("*.html")}
    downloaded = {
        line.strip()
        for line in (ROOT_DIR / "data" / "downloaded_cids.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    with sqlite3.connect(ROOT_DIR / "data" / "appeal_cases.db") as conn:
        db_count = conn.execute("select count(*) from cases").fetchone()[0]
        fts_count = conn.execute("select count(*) from cases_fts").fetchone()[0]
    if not (case_cids == text_cids == html_cids == downloaded and db_count == fts_count == len(case_cids)):
        raise SystemExit(
            "公開資料不一致："
            f" cases={len(case_cids)} texts={len(text_cids)} html={len(html_cids)} "
            f"downloaded={len(downloaded)} db={db_count} fts={fts_count}"
        )
    print(f"公開資料一致：{len(case_cids)} 筆")


def ensure_remote_not_ahead(remote: str) -> None:
    run(["git", "fetch", remote, BRANCH])
    result = run(["git", "rev-list", "--left-right", "--count", f"HEAD...{remote}/{BRANCH}"])
    left, right = [int(part) for part in result.stdout.split()]
    if right:
        raise SystemExit(f"{remote}/{BRANCH} 有 {right} 個本機沒有的 commit，請先檢查後再同步。")
    print(f"{remote}/{BRANCH} divergence: local_ahead={left}, remote_ahead={right}")


def quality_checks(skip_tests: bool = False) -> None:
    run([sys.executable, "-m", "py_compile", *[str(path.relative_to(ROOT_DIR)) for path in (ROOT_DIR / "scripts").glob("*.py")], "app/streamlit_app.py"])
    if not skip_tests:
        print_output(run([sys.executable, "-m", "pytest", "-q"]))
    print_output(run([sys.executable, "scripts/health_check.py", "--skip-ai"]))
    ensure_public_data_consistency()


def push_remote(remote: str) -> None:
    print_output(run(["git", "push", remote, f"{BRANCH}:{BRANCH}"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 private 主 repo 與 public Streamlit 部署 repo")
    parser.add_argument("--push", action="store_true", help="實際推送到 origin 與 public-deploy；預設只檢查")
    parser.add_argument("--skip-tests", action="store_true", help="略過 pytest，仍會做語法與資料一致性檢查")
    args = parser.parse_args()

    ensure_branch()
    ensure_remotes()
    ensure_clean_worktree()
    ensure_no_forbidden_tracked_files()
    ensure_remote_not_ahead(PRIVATE_REMOTE)
    ensure_remote_not_ahead(PUBLIC_REMOTE)
    quality_checks(skip_tests=args.skip_tests)

    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    print(f"準備同步 commit：{head}")
    if not args.push:
        print("dry-run 完成；若要推送，請執行：python scripts/sync_repos.py --push")
        return

    push_remote(PRIVATE_REMOTE)
    push_remote(PUBLIC_REMOTE)
    print("同步完成。")


if __name__ == "__main__":
    main()
