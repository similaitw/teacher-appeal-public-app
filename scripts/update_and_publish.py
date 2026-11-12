"""一鍵更新公開資料並發布。

在可連線教育部站台的電腦（臺灣）上執行：

    python scripts/update_and_publish.py

流程：
1. 確認在 main、工作樹乾淨，並從 origin 取得最新版本。
2. 執行爬蟲更新公開評議書（scripts/update_public_cases.py）。
3. 匯出公開 AI 分析（web 的 npm run publish:analysis；沒有 npm 或沒有分析紀錄時略過）。
4. 沒有任何變更就結束；有變更則跑測試、健康檢查、資料一致性與公開檔案清單檢查。
5. 顯示變更摘要，確認後提交，並用 scripts/sync_repos.py --push 同步到兩個 repo。
   公開庫更新後，Vercel 網站會自動部署。

任何一步失敗都會停下來，不會提交或推送。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync_repos  # noqa: E402
from publish_policy import find_violations  # noqa: E402

# 這支腳本只會提交這些公開資料路徑，其他檔案一律不碰。
PUBLISH_PATHS = [
    "data/cases.csv",
    "data/discovered_cids.txt",
    "data/downloaded_cids.txt",
    "data/failed_cids.txt",
    "data/crawl_state.json",
    "data/raw_html",
    "data/texts",
    "data/appeal_cases.db",
    "data/public_analysis",
]
DOWNLOADED_CIDS = ROOT_DIR / "data" / "downloaded_cids.txt"
PUBLIC_ANALYSIS_RUNS = ROOT_DIR / "data" / "public_analysis" / "runs"
LOCAL_ANALYSIS_RUNS = ROOT_DIR / "data" / "ai_exports" / "analysis_runs"
WEB_DIR = ROOT_DIR / "web"


class Stop(Exception):
    """預期內的中止：印出訊息後以非零狀態結束。"""


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT_DIR, text=True, encoding="utf-8", capture_output=True, check=check)


def run_streaming(command: list[str], cwd: Path = ROOT_DIR) -> int:
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command, cwd=cwd).returncode


def is_publish_path(path: str) -> bool:
    path = path.rstrip("/")
    return any(path == item or path.startswith(item + "/") or item.startswith(path + "/") for item in PUBLISH_PATHS)


def read_cids() -> set[str]:
    if not DOWNLOADED_CIDS.exists():
        return set()
    return {line.strip() for line in DOWNLOADED_CIDS.read_text(encoding="utf-8").splitlines() if line.strip()}


def count_analysis_runs() -> int:
    return len(list(PUBLIC_ANALYSIS_RUNS.glob("*.json"))) if PUBLIC_ANALYSIS_RUNS.exists() else 0


def committed_cids() -> set[str]:
    """已提交版本（HEAD）的案件清單，作為「更新前」的基準。"""
    result = git("show", "HEAD:data/downloaded_cids.txt", check=False)
    return {line.strip() for line in result.stdout.splitlines() if line.strip()} if result.returncode == 0 else set()


def committed_analysis_runs() -> int:
    result = git("ls-tree", "--name-only", "HEAD", "data/public_analysis/runs/", check=False)
    return len([line for line in result.stdout.splitlines() if line.endswith(".json")])


def preflight(pull: bool) -> None:
    step("1. 檢查 repo 狀態")
    branch = git("branch", "--show-current").stdout.strip()
    if branch != sync_repos.BRANCH:
        raise Stop(f"目前分支是 {branch!r}，請先切回 {sync_repos.BRANCH}。")
    remotes = set(git("remote").stdout.split())
    missing = [name for name in (sync_repos.PRIVATE_REMOTE, sync_repos.PUBLIC_REMOTE) if name not in remotes]
    if missing:
        raise Stop(
            f"缺少 git remote：{', '.join(missing)}。\n"
            "公開庫請用：git remote add public-deploy https://github.com/similaitw/teacher-appeal-public-app"
        )
    # 上次執行留下、尚未發布的公開資料變更可以接續處理；其他變更必須先處理。
    dirty = [
        line
        for line in git("status", "--porcelain").stdout.splitlines()
        if line.strip() and not is_publish_path(line[3:].strip().strip('"').split(" -> ")[-1])
    ]
    if dirty:
        raise Stop("工作樹有公開資料以外的未提交變更，請先處理後再執行：\n" + "\n".join(dirty))
    if pull:
        result = git("pull", "--ff-only", sync_repos.PRIVATE_REMOTE, sync_repos.BRANCH, check=False)
        if result.returncode != 0:
            raise Stop("無法從 origin 取得最新版本：\n" + (result.stdout + result.stderr).strip())
        print((result.stdout or "").strip() or "已是最新版本。")
    print("repo 狀態正常。")


def crawl(sleep: float, limit: int) -> None:
    step("2. 更新公開評議書")
    command = [sys.executable, "scripts/update_public_cases.py", "--sleep", str(sleep)]
    if limit:
        command += ["--limit", str(limit)]
    if run_streaming(command) != 0:
        git("checkout", "--", *[path for path in PUBLISH_PATHS if (ROOT_DIR / path).exists()], check=False)
        raise Stop(
            "爬蟲更新失敗，已還原資料檔，沒有提交任何東西。\n"
            "常見原因：這台電腦連不到 appeal.moe.gov.tw（需要臺灣的網路）。\n"
            "若只想發布 AI 分析，可加上 --skip-crawl。"
        )


def publish_analysis() -> None:
    step("3. 匯出公開 AI 分析")
    if not LOCAL_ANALYSIS_RUNS.exists():
        print("這台電腦沒有 data/ai_exports/analysis_runs，略過。")
        return
    npm = shutil.which("npm")
    if not npm:
        print("找不到 npm（需要安裝 Node.js），略過 AI 分析匯出。")
        return
    if not (WEB_DIR / "node_modules" / "csv-parse").exists():
        if run_streaming([npm, "ci", "--no-audit", "--no-fund"], cwd=WEB_DIR) != 0:
            raise Stop("npm ci 失敗，請檢查網路或 Node.js 安裝。")
    if run_streaming([npm, "run", "--silent", "publish:analysis"], cwd=WEB_DIR) != 0:
        raise Stop("AI 分析匯出失敗，沒有提交任何東西。")


def stage_changes() -> list[str]:
    existing = [path for path in PUBLISH_PATHS if (ROOT_DIR / path).exists()]
    git("add", "--", *existing)
    return [line for line in git("diff", "--cached", "--name-only").stdout.splitlines() if line.strip()]


def unstage() -> None:
    git("reset", "-q", check=False)


def verify(skip_tests: bool) -> None:
    step("4. 檢查")
    violations = find_violations(git("ls-files").stdout.splitlines())
    if violations["forbidden"] or violations["not_allowed"]:
        raise Stop(
            "公開檔案清單檢查失敗：\n"
            + "\n".join(violations["forbidden"] + violations["not_allowed"])
        )
    print("公開檔案清單檢查通過")
    try:
        sync_repos.quality_checks(skip_tests=skip_tests)
    except subprocess.CalledProcessError as exc:
        raise Stop("檢查未通過：\n" + (exc.stdout or "").strip()) from exc
    except SystemExit as exc:
        raise Stop(str(exc)) from exc


def summarize(staged: list[str], cids_before: set[str], runs_before: int) -> str:
    cids_after = read_cids()
    new_cids = sorted(cids_after - cids_before)
    removed_cids = sorted(cids_before - cids_after)
    runs_after = count_analysis_runs()
    analysis_files = [path for path in staged if path.startswith("data/public_analysis/")]
    lines = [
        f"公開案件：{len(cids_before)} → {len(cids_after)} 筆（新增 {len(new_cids)}）",
        f"公開 AI 分析：{runs_before} → {runs_after} 筆（變更檔案 {len(analysis_files)} 個）",
        f"變更檔案總數：{len(staged)}",
    ]
    if new_cids:
        shown = "、".join(new_cids[:10]) + ("…" if len(new_cids) > 10 else "")
        lines.append(f"新增 cid：{shown}")
    if removed_cids:
        lines.append(f"注意：有 {len(removed_cids)} 個 cid 從清單消失：{'、'.join(removed_cids[:10])}")
    print("\n".join(lines))
    parts = []
    if new_cids:
        parts.append(f"{len(new_cids)} new cases")
    if analysis_files:
        parts.append(f"{len(analysis_files)} analysis files")
    return ", ".join(parts) or "data refresh"


def confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="一鍵更新公開資料並發布到兩個 repo（Vercel 會自動部署）")
    parser.add_argument("--skip-crawl", action="store_true", help="不跑爬蟲，只發布 AI 分析")
    parser.add_argument("--skip-analysis", action="store_true", help="不匯出 AI 分析")
    parser.add_argument("--skip-tests", action="store_true", help="略過 pytest（仍會做健康檢查與資料一致性檢查）")
    parser.add_argument("--no-pull", action="store_true", help="不先從 origin 取得最新版本")
    parser.add_argument("--no-push", action="store_true", help="只更新與檢查，不提交也不推送（變更會留在工作樹）")
    parser.add_argument("--yes", action="store_true", help="不詢問，檢查通過就直接提交並推送")
    parser.add_argument("--sleep", type=float, default=1.5, help="爬蟲每次請求間隔秒數")
    parser.add_argument("--limit", type=int, default=0, help="限制爬蟲本次下載數量，小量測試用")
    args = parser.parse_args()

    try:
        preflight(pull=not args.no_pull)
        cids_before = committed_cids()
        runs_before = committed_analysis_runs()

        if args.skip_crawl:
            step("2. 更新公開評議書")
            print("已略過（--skip-crawl）。")
        else:
            crawl(args.sleep, args.limit)

        if args.skip_analysis:
            step("3. 匯出公開 AI 分析")
            print("已略過（--skip-analysis）。")
        else:
            publish_analysis()

        staged = stage_changes()
        if not staged:
            print("\n沒有新資料，不需要發布。")
            return 0

        try:
            verify(args.skip_tests)
        except Stop:
            unstage()
            print("\n變更仍保留在工作樹，尚未提交。修正後可重新執行；要放棄變更請用 git checkout -- data")
            raise

        step("5. 發布")
        label = summarize(staged, cids_before, runs_before)
        if args.no_push:
            unstage()
            print("\n已略過提交與推送（--no-push）。變更保留在工作樹，下次執行會接續發布。")
            return 0
        if not args.yes and not confirm("要提交並同步到兩個 repo（網站會自動部署）嗎？"):
            unstage()
            print("已取消。變更保留在工作樹，下次執行會接續發布；要放棄請用 git checkout -- data 並刪除新增的檔案。")
            return 0

        message = f"Update public data ({label}) {datetime.now():%Y-%m-%d}"
        result = git("commit", "-m", message, check=False)
        if result.returncode != 0:
            raise Stop("git commit 失敗：\n" + (result.stdout + result.stderr).strip())
        print(f"已提交：{message}")

        # 測試剛剛已跑過；sync_repos 會再做一次健康檢查、資料一致性與兩個 remote 的檢查後才推送。
        if run_streaming([sys.executable, "scripts/sync_repos.py", "--push", "--skip-tests"]) != 0:
            raise Stop(
                "同步失敗。變更已在本機提交但尚未完整推送。\n"
                "排除問題後執行：python scripts/sync_repos.py --push"
            )
        print("\n完成。公開庫已更新，Vercel 會在一兩分鐘內自動部署：")
        print("https://teacher-appeal-public-app.vercel.app")
        return 0
    except Stop as exc:
        print(f"\n[中止] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
