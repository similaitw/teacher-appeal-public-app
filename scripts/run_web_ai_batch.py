from __future__ import annotations

import argparse
from pathlib import Path

from web_ai_batch import (
    AUTO_CONTINUE_STATUSES,
    continue_batch_until_complete,
    create_batch_dir,
    load_batch_manifest,
    read_cids_from_file,
    refresh_batch_status,
    run_batch,
    select_retry_cids,
    set_case_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="逐案開啟 ChatGPT/Gemini 網頁批次分析公開評議書並自動歸檔")
    parser.add_argument("--provider", choices=["chatgpt", "gemini"], help="目標服務")
    parser.add_argument("--cid", action="append", default=[], help="要分析的 cid，可重複指定")
    parser.add_argument("--cid-file", type=Path, help="cid 清單檔，每行一個")
    parser.add_argument("--sleep", type=float, default=3.0, help="每案完成後等待秒數")
    parser.add_argument("--model-name", default="", help="記錄用模型名稱")
    parser.add_argument("--batch-dir", type=Path, help="指定批次輸出目錄；未指定則自動建立")
    parser.add_argument("--refresh-status", action="store_true", help="重算並同步指定批次的 status.csv")
    parser.add_argument("--resume-batch", type=Path, help="重跑指定批次中符合 --statuses 的案件")
    parser.add_argument("--continue-batch", type=Path, help="多輪接續跑指定批次，直到沒有 pending/failed/stale 或達到上限")
    parser.add_argument("--statuses", default="pending,paused,failed,stale", help="重跑狀態清單，以逗號分隔")
    parser.add_argument("--max-rounds", type=int, default=5, help="--continue-batch 最多執行輪數")
    parser.add_argument("--max-attempts", type=int, default=3, help="--continue-batch 每案最多自動嘗試次數，0 表示不限")
    parser.add_argument("--set-status", choices=["pending", "running", "done", "paused", "failed", "stale"], help="手動設定單一 cid 狀態")
    parser.add_argument("--note", default="", help="手動狀態備註")
    parser.add_argument("--run-id", default="", help="手動狀態要補入的分析紀錄 run_id")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.refresh_status:
        if not args.batch_dir:
            raise SystemExit("--refresh-status 需要搭配 --batch-dir")
        summary, _rows = refresh_batch_status(args.batch_dir)
        print(
            "狀態已同步："
            f"done={summary['done']} running={summary['running']} pending={summary['pending']} "
            f"paused={summary['paused']} failed={summary['failed']} stale={summary['stale']}"
        )
        return

    if args.set_status:
        if not args.batch_dir or len(args.cid) != 1:
            raise SystemExit("--set-status 需要搭配 --batch-dir 與單一 --cid")
        row = set_case_status(args.batch_dir, args.cid[0], args.set_status, run_id=args.run_id, manual_note=args.note)
        print(f"已更新 cid={row['cid']} status={row['status']}")
        return

    if args.continue_batch:
        manifest = load_batch_manifest(args.continue_batch)
        provider = args.provider or str(manifest.get("provider") or "")
        if provider not in {"chatgpt", "gemini"}:
            raise SystemExit("找不到批次 provider，請補 --provider chatgpt 或 --provider gemini")
        raw_statuses = [status.strip() for status in args.statuses.split(",") if status.strip()]
        statuses = raw_statuses if raw_statuses != ["pending", "paused", "failed", "stale"] else sorted(AUTO_CONTINUE_STATUSES)
        result = continue_batch_until_complete(
            provider=provider,
            batch_dir=args.continue_batch,
            sleep_seconds=args.sleep,
            model_name=args.model_name or str(manifest.get("model_name") or ""),
            statuses=statuses,
            max_rounds=args.max_rounds,
            max_attempts=args.max_attempts,
        )
        summary = result["summary"]
        print(
            f"接續完成：done={summary['done']} running={summary['running']} pending={summary['pending']} "
            f"paused={summary['paused']} failed={summary['failed']} stale={summary['stale']} "
            f"exhausted={len(result['exhausted_cids'])}"
        )
        return

    if args.resume_batch:
        manifest = load_batch_manifest(args.resume_batch)
        provider = args.provider or str(manifest.get("provider") or "")
        if provider not in {"chatgpt", "gemini"}:
            raise SystemExit("找不到批次 provider，請補 --provider chatgpt 或 --provider gemini")
        statuses = [status.strip() for status in args.statuses.split(",") if status.strip()]
        retry_cids = select_retry_cids(args.resume_batch, statuses)
        if args.cid:
            requested = set(args.cid)
            retry_cids = [cid for cid in retry_cids if cid in requested]
        if not retry_cids:
            print("沒有符合條件的案件需要重跑")
            return
        result_dir = run_batch(
            provider=provider,
            cids=retry_cids,
            sleep_seconds=args.sleep,
            model_name=args.model_name or str(manifest.get("model_name") or ""),
            batch_dir=args.resume_batch,
            write_manifest=False,
        )
        print(f"批次完成或暫停：{result_dir}")
        return

    cids = list(args.cid)
    try:
        if args.cid_file:
            cids.extend(read_cids_from_file(args.cid_file))
        if not cids:
            raise ValueError("請指定 --cid 或 --cid-file")
        if not args.provider:
            raise ValueError("請指定 --provider chatgpt 或 --provider gemini")
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    batch_dir = args.batch_dir or create_batch_dir(args.provider)
    result_dir = run_batch(
        provider=args.provider,
        cids=cids,
        sleep_seconds=args.sleep,
        model_name=args.model_name,
        batch_dir=batch_dir,
    )
    print(f"批次完成或暫停：{result_dir}")


if __name__ == "__main__":
    main()
