from __future__ import annotations

import argparse
import sys

import requests

from llm import (
    INSUFFICIENT_ANSWER,
    OllamaConfig,
    answer_question,
    build_evidence,
    check_ollama,
    retrieve_cases,
    summarize_case,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用本機 Ollama 依案件原文回答問題")
    parser.add_argument("question", nargs="?", default="", help="問題")
    parser.add_argument("--model", default="", help="Ollama 模型，預設讀 .env 或 qwen2.5:7b")
    parser.add_argument("--base-url", default="", help="Ollama API 位址，預設讀 .env 或 http://localhost:11434")
    parser.add_argument("--limit", type=int, default=8, help="檢索案件數")
    parser.add_argument("--cid", default="", help="限定指定 cid")
    parser.add_argument("--timeout", type=int, default=180, help="Ollama 單次讀取逾時秒數")
    parser.add_argument("--summary", action="store_true", help="整理指定 cid 的案件摘要")
    parser.add_argument("--check", action="store_true", help="檢查 Ollama 連線與模型")
    parser.add_argument("--show-context", action="store_true", help="只顯示送給 LLM 的來源片段，不呼叫 Ollama")
    return parser.parse_args()


def print_sources(sources: list[dict[str, str]]) -> None:
    if not sources:
        return
    print("\n---\n來源")
    for source in sources:
        print(f"- cid={source.get('cid')}｜{source.get('url')}")
        snippet = source.get("snippet", "")
        if snippet:
            print(f"  片段：{snippet}")


def main() -> None:
    args = parse_args()
    config = OllamaConfig.from_env(model=args.model, base_url=args.base_url)
    config.timeout = args.timeout

    if args.check:
        ok, message = check_ollama(config)
        print(message)
        sys.exit(0 if ok else 1)

    if args.summary and not args.cid:
        print("使用 --summary 時請同時指定 --cid。", file=sys.stderr)
        sys.exit(2)

    question = args.question.strip()
    if not question and not args.summary:
        print("請輸入問題，或使用 --summary --cid。", file=sys.stderr)
        sys.exit(2)

    rows = retrieve_cases(question, cid=args.cid, limit=args.limit)
    if args.summary:
        rows = retrieve_cases("", cid=args.cid, limit=1)
        question = f"幫我整理 cid={args.cid} 的爭點、雙方主張、申評會判斷與可引用重點。"

    if args.show_context:
        evidence, sources = build_evidence(rows, question)
        print(evidence or INSUFFICIENT_ANSWER)
        print_sources(sources)
        return

    try:
        if args.summary:
            answer, sources, _ = summarize_case(args.cid, config)
        else:
            answer, sources, _ = answer_question(question, rows, config)
        print(answer)
        print_sources(sources)
    except requests.RequestException as exc:
        print(f"Ollama 連線失敗：{exc}", file=sys.stderr)
        print(INSUFFICIENT_ANSWER)


if __name__ == "__main__":
    main()
