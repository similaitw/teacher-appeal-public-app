from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from typing import Iterable

import requests
from dotenv import load_dotenv

from utils import ROOT_DIR, get_case_by_cid, load_keywords, make_snippet, search_fts


INSUFFICIENT_ANSWER = "目前資料庫中找不到足夠原文支持此結論。"
SOURCE_WARNING = "\n\n注意：本回答未明確標示來源 cid，請回到下方來源片段人工覆核後再引用。"

QA_FORMAT = """一、簡要結論
二、相關案件
三、申評會判斷理由
四、可引用重點
五、仍需注意事項
六、來源 cid"""

SUMMARY_FORMAT = """一、案件爭點
二、教師主張
三、學校主張
四、申評會判斷
五、可引用重點"""

SYSTEM_RULES = """你是教育部教師申訴評議書本機查詢助手。
你只能根據下方「可用原文片段」回答，不可使用片段外的常識補完事實。
每一個判斷都要盡量標示 cid，並引用短原文片段。
如果可用原文片段不足以支持結論，只能回答：目前資料庫中找不到足夠原文支持此結論。
請使用繁體中文，語氣精確、保守、可供教育行政人員檢核。"""


@dataclass
class OllamaConfig:
    model: str = "qwen2.5:7b"
    base_url: str = "http://localhost:11434"
    timeout: int = 180

    @classmethod
    def from_env(cls, model: str = "", base_url: str = "") -> "OllamaConfig":
        load_dotenv()
        return cls(
            model=model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            base_url=base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )


def check_ollama(config: OllamaConfig) -> tuple[bool, str]:
    ok, models_or_message = list_ollama_models(config.base_url)
    if not ok:
        return False, models_or_message
    models = models_or_message.splitlines() if models_or_message else []
    if config.model not in models:
        available = "、".join(models) if models else "無"
        return False, f"找不到模型 {config.model}。目前模型：{available}"
    return True, f"Ollama 可用：{config.model}"


def list_ollama_models(base_url: str = "http://localhost:11434", timeout: int = 4) -> tuple[bool, str]:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        response.raise_for_status()
        models = [item.get("name", "") for item in response.json().get("models", [])]
    except requests.RequestException as exc:
        return False, f"Ollama 連線失敗：{exc}"
    return True, "\n".join(model for model in models if model)


def choose_model(preferred: str, available: list[str]) -> str:
    if preferred in available:
        return preferred
    for candidate in ("qwen2.5:7b", "gemma2:2b", "gemma2:9b", "phi3:mini"):
        if candidate in available:
            return candidate
    return available[0] if available else preferred


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _query_terms(query: str) -> list[str]:
    terms = [term for term in re.split(r"\s+", query.strip()) if len(term.strip()) >= 2]
    if terms:
        return terms
    return [query.strip()] if query.strip() else []


def expand_query(question: str) -> str:
    hits = []
    for keyword in load_keywords(ROOT_DIR / "keywords.txt"):
        if keyword in question:
            hits.append(keyword)
    for keyword in ["教師法", "申訴", "學校", "教師", "導師", "寒暑假", "早自習", "職務", "工作分配"]:
        if keyword in question and keyword not in hits:
            hits.append(keyword)
    return " ".join(hits) if hits else question


def split_relevant_segments(text: str, query: str, max_segments: int = 2, segment_chars: int = 600) -> list[str]:
    flat = _normalize_text(text)
    if not flat:
        return []
    terms = _query_terms(query)
    starts: list[int] = []
    for term in terms:
        start = flat.find(term)
        if start >= 0:
            starts.append(max(start - 220, 0))
    if not starts:
        starts = [0]

    segments: list[str] = []
    for start in sorted(set(starts))[:max_segments]:
        segment = flat[start : start + segment_chars]
        if start:
            segment = "..." + segment
        if start + segment_chars < len(flat):
            segment += "..."
        segments.append(segment)
    return segments


def retrieve_cases(question: str, cid: str = "", limit: int = 8) -> list[dict[str, str]]:
    if cid:
        row = get_case_by_cid(cid)
        return [row] if row else []
    rows = search_fts(question, limit=limit)
    if rows:
        return rows
    expanded = expand_query(question)
    if expanded != question:
        return search_fts(expanded, limit=limit)
    return []


def build_evidence(rows: Iterable[dict[str, str]], query: str, max_chars: int = 5000) -> tuple[str, list[dict[str, str]]]:
    blocks = []
    sources = []
    used = 0
    for row in rows:
        cid = row.get("cid", "")
        url = row.get("url", "")
        segments = split_relevant_segments(row.get("full_text", ""), query)
        if not segments:
            continue
        sources.append(
            {
                "cid": cid,
                "url": url,
                "title": row.get("title", ""),
                "date_text": row.get("date_text", ""),
                "result": row.get("result", ""),
                "snippet": make_snippet(row.get("full_text", ""), query, length=180),
            }
        )
        for index, segment in enumerate(segments, start=1):
            block = (
                f"[來源 {len(sources)}.{index}]\n"
                f"cid: {cid}\n"
                f"url: {url}\n"
                f"title: {row.get('title', '')}\n"
                f"date: {row.get('date_text', '')}\n"
                f"result: {row.get('result', '')}\n"
                f"原文片段: {segment}\n"
            )
            if used + len(block) > max_chars:
                return "\n".join(blocks), sources
            blocks.append(block)
            used += len(block)
    return "\n".join(blocks), sources


def build_prompt(question: str, evidence: str, mode: str = "qa") -> str:
    answer_format = SUMMARY_FORMAT if mode == "summary" else QA_FORMAT
    task = "請整理指定案件。" if mode == "summary" else "請回答使用者問題。"
    return f"""{SYSTEM_RULES}

任務：
{task}

固定輸出格式：
{answer_format}

使用者問題：
{question}

可用原文片段：
{evidence}
"""


def generate_with_ollama(prompt: str, config: OllamaConfig) -> str:
    response = requests.post(
        f"{config.base_url.rstrip('/')}/api/generate",
        json={
            "model": config.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
            },
        },
        stream=True,
        timeout=(10, config.timeout),
    )
    response.raise_for_status()
    chunks = []
    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if data.get("response"):
            chunks.append(data["response"])
        if data.get("done"):
            break
    return "".join(chunks).strip()


def answer_question(
    question: str,
    rows: list[dict[str, str]],
    config: OllamaConfig,
    mode: str = "qa",
) -> tuple[str, list[dict[str, str]], str]:
    evidence_query = expand_query(question)
    evidence, sources = build_evidence(rows, evidence_query)
    if not evidence.strip() or not sources:
        return INSUFFICIENT_ANSWER, [], ""
    prompt = build_prompt(question, evidence, mode=mode)
    answer = generate_with_ollama(prompt, config)
    if not answer:
        answer = INSUFFICIENT_ANSWER
    elif sources and not any(source.get("cid", "") and source.get("cid", "") in answer for source in sources):
        answer += SOURCE_WARNING
    return answer, sources, evidence


def summarize_case(cid: str, config: OllamaConfig) -> tuple[str, list[dict[str, str]], str]:
    rows = retrieve_cases("", cid=cid, limit=1)
    question = f"幫我整理 cid={cid} 的爭點、雙方主張、申評會判斷與可引用重點。"
    return answer_question(question, rows, config, mode="summary")
