from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from html import escape
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from health_check import run_health_check  # noqa: E402
from prepare_cids import extract_cids  # noqa: E402
from utils import CASES_CSV, DB_PATH, ERROR_LOG, EXPORTS_DIR, get_case_by_cid, make_snippet, search_fts  # noqa: E402
from private_db import (  # noqa: E402
    PRIVATE_DB_PATH,
    create_case,
    delete_case,
    export_analysis_package,
    get_case_by_id as get_private_case_by_id,
    init_private_db,
    list_cases as list_private_cases,
    list_documents as list_private_documents,
    list_units as list_private_units,
    search_units as search_private_units,
    update_case,
)
from private_documents import import_document  # noqa: E402
from public_ai_export import PUBLIC_AI_BUNDLE_DIR, PUBLIC_AI_EXPORT_DIR, export_public_case_bundle  # noqa: E402
from analysis_runs import (  # noqa: E402
    ANALYSIS_RUNS_DIR,
    create_analysis_run,
    list_analysis_runs,
    list_private_export_inputs,
    list_public_bundle_inputs,
)
from web_ai_batch import (  # noqa: E402
    WEB_AI_BATCHES_DIR,
    create_batch_dir,
    refresh_batch_status,
    select_retry_cids,
    set_case_status,
    write_batch_manifest,
)
from update_public_cases import UPDATE_RUNS_DIR  # noqa: E402

BATCH_STATUS_SERVER_PORT = 8765
APP_MODE = os.getenv("APP_MODE", "").strip().lower()
CLOUD_PUBLIC_MODE = APP_MODE == "cloud_public"

st.set_page_config(page_title="教師申訴評議書本機查詢系統", layout="wide")

st.markdown(
    """
    <style>
    :root {
        --desk-bg: #f6f4ee;
        --paper: #fffdf8;
        --ink: #1f2933;
        --muted: #65727f;
        --line: #d8d3c8;
        --accent: #0f766e;
        --accent-2: #b45309;
        --danger: #b42318;
    }
    .stApp {
        background:
            linear-gradient(180deg, rgba(246,244,238,.94), rgba(250,249,245,.98)),
            repeating-linear-gradient(90deg, rgba(31,41,51,.025) 0, rgba(31,41,51,.025) 1px, transparent 1px, transparent 18px);
        color: var(--ink);
    }
    [data-testid="stHeader"] {
        background: rgba(246,244,238,.82);
        backdrop-filter: blur(10px);
        border-bottom: 1px solid rgba(216,211,200,.72);
    }
    .block-container {
        max-width: 1480px;
        padding-top: .95rem;
        padding-bottom: 4rem;
    }
    h1 {
        font-size: clamp(1.55rem, 2.5vw, 2.55rem) !important;
        letter-spacing: 0 !important;
        color: #18232d;
        border-bottom: 2px solid var(--ink);
        padding-bottom: .55rem;
        margin-bottom: .25rem !important;
    }
    h2, h3 {
        color: #26323d;
        letter-spacing: 0 !important;
    }
    div[data-testid="stCaptionContainer"], .stCaption {
        color: var(--muted) !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        position: sticky;
        top: 3.05rem;
        z-index: 998;
        gap: .35rem;
        overflow-x: auto;
        padding: .45rem .15rem .5rem;
        border-bottom: 1px solid var(--line);
        background: rgba(246,244,238,.96);
        backdrop-filter: blur(12px);
        box-shadow: 0 8px 18px rgba(31,41,51,.06);
    }
    .stTabs [data-baseweb="tab"] {
        background: rgba(255,253,248,.72);
        border: 1px solid var(--line);
        border-radius: 6px;
        min-height: 38px;
        padding: .45rem .8rem;
        white-space: nowrap;
    }
    .stTabs [aria-selected="true"] {
        background: #18332f !important;
        color: #fffdf8 !important;
        border-color: #18332f !important;
    }
    div[data-testid="stMetric"] {
        background: var(--paper);
        border: 1px solid var(--line);
        border-left: 4px solid var(--accent);
        border-radius: 6px;
        padding: .8rem .9rem;
        box-shadow: 0 1px 0 rgba(31,41,51,.05);
    }
    div[data-testid="stMetricLabel"] {
        color: var(--muted);
    }
    div[data-testid="stMetricValue"] {
        color: var(--ink);
        font-size: clamp(1.1rem, 2vw, 1.75rem);
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--line);
        border-radius: 6px;
        overflow: hidden;
        background: var(--paper);
    }
    .stButton > button, .stDownloadButton > button, div[data-testid="stLinkButton"] a {
        border-radius: 6px !important;
        border: 1px solid #21443f !important;
        background: #18332f !important;
        color: #fffdf8 !important;
        font-weight: 650 !important;
    }
    .stButton > button:hover, .stDownloadButton > button:hover, div[data-testid="stLinkButton"] a:hover {
        background: #0f766e !important;
        border-color: #0f766e !important;
    }
    input, textarea, [data-baseweb="select"] > div {
        border-radius: 6px !important;
    }
    div[data-testid="stAlert"] {
        border-radius: 6px;
        border: 1px solid rgba(216,211,200,.9);
    }
    .workflow-strip {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: .75rem;
        margin: 1rem 0 1.25rem;
    }
    .workflow-card {
        background: var(--paper);
        border: 1px solid var(--line);
        border-top: 3px solid var(--accent-2);
        border-radius: 6px;
        padding: .9rem 1rem;
        min-height: 96px;
    }
    .workflow-card strong {
        display: block;
        color: #17212b;
        margin-bottom: .35rem;
    }
    .workflow-card span {
        color: var(--muted);
        font-size: .92rem;
        line-height: 1.45;
    }
    .layout-kicker {
        margin: .85rem 0 .35rem;
        color: var(--muted);
        font-size: .78rem;
        font-weight: 800;
        letter-spacing: .04em;
        text-transform: uppercase;
    }
    .action-bar-note {
        display: flex;
        align-items: center;
        gap: .5rem;
        margin: .15rem 0 .55rem;
        color: #18332f;
        font-weight: 750;
    }
    .content-panel-note {
        margin: 1rem 0 .45rem;
        color: #26323d;
        font-weight: 750;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: rgba(216,211,200,.95) !important;
        border-radius: 8px !important;
        background: rgba(255,253,248,.74);
        box-shadow: 0 1px 0 rgba(31,41,51,.04);
    }
    .stTabs [data-baseweb="tab-panel"] {
        padding-top: .75rem;
    }
    .batch-dashboard {
        background: #18232d;
        color: #fffdf8;
        border: 1px solid #101820;
        border-radius: 8px;
        padding: 1rem;
        margin: .85rem 0 1rem;
        box-shadow: 0 18px 42px rgba(24,35,45,.16);
    }
    .batch-dashboard__top {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        align-items: flex-start;
        flex-wrap: wrap;
        margin-bottom: .9rem;
    }
    .batch-dashboard__title {
        font-size: clamp(1.05rem, 2vw, 1.45rem);
        font-weight: 750;
    }
    .batch-dashboard__meta {
        color: rgba(255,253,248,.72);
        font-size: .9rem;
        margin-top: .2rem;
    }
    .batch-dashboard__badge {
        border: 1px solid rgba(255,253,248,.25);
        border-radius: 999px;
        padding: .32rem .7rem;
        color: #fffdf8;
        background: rgba(255,253,248,.08);
        font-size: .86rem;
        white-space: nowrap;
    }
    .batch-dashboard__bar {
        height: 18px;
        border-radius: 999px;
        overflow: hidden;
        display: flex;
        background: rgba(255,253,248,.12);
        border: 1px solid rgba(255,253,248,.18);
    }
    .batch-dashboard__seg {
        min-width: 0;
        height: 100%;
    }
    .batch-dashboard__legend {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: .5rem;
        margin-top: .75rem;
    }
    .batch-dashboard__legend-item {
        background: rgba(255,253,248,.08);
        border: 1px solid rgba(255,253,248,.12);
        border-radius: 7px;
        padding: .58rem .65rem;
        min-height: 72px;
    }
    .batch-dashboard__legend-item strong {
        display: block;
        font-size: 1.2rem;
        color: #fffdf8;
    }
    .batch-dashboard__legend-item span {
        color: rgba(255,253,248,.72);
        font-size: .84rem;
    }
    .batch-pulse {
        display: inline-block;
        width: .6rem;
        height: .6rem;
        border-radius: 50%;
        background: #22c55e;
        box-shadow: 0 0 0 rgba(34,197,94,.45);
        animation: batchPulse 1.7s infinite;
        margin-right: .35rem;
    }
    @keyframes batchPulse {
        0% { box-shadow: 0 0 0 0 rgba(34,197,94,.45); }
        70% { box-shadow: 0 0 0 9px rgba(34,197,94,0); }
        100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
    }
    .batch-step-list {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: .7rem;
        margin: .8rem 0;
    }
    .batch-step {
        background: var(--paper);
        border: 1px solid var(--line);
        border-radius: 7px;
        padding: .8rem;
    }
    .batch-step small {
        color: var(--muted);
        display: block;
        margin-bottom: .25rem;
    }
    .batch-step strong {
        color: var(--ink);
        word-break: break-word;
    }
    div[data-testid="stButton"] button[kind="secondary"] {
        text-align: left;
        justify-content: flex-start;
        white-space: normal;
        line-height: 1.25;
    }
    @media (max-width: 900px) {
        .block-container {
            padding-left: .85rem;
            padding-right: .85rem;
            padding-top: .9rem;
        }
        .workflow-strip {
            grid-template-columns: 1fr;
        }
        .batch-dashboard__legend,
        .batch-step-list {
            grid-template-columns: 1fr;
        }
        .stTabs [data-baseweb="tab"] {
            padding: .4rem .62rem;
            font-size: .88rem;
        }
        .stTabs [data-baseweb="tab-list"] {
            top: 2.65rem;
        }
        div[data-testid="column"] {
            min-width: 100% !important;
            width: 100% !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def run_command(args: list[str], timeout: int = 600) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:
        return False, str(exc)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part.strip())
    return completed.returncode == 0, output


def start_background_command(args: list[str], stdout_path: Path, stderr_path: Path) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_fh = stdout_path.open("w", encoding="utf-8")
    stderr_fh = stderr_path.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            args,
            cwd=ROOT_DIR,
            stdout=stdout_fh,
            stderr=stderr_fh,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        stdout_fh.close()
        stderr_fh.close()
    return int(proc.pid)


def is_local_port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def ensure_batch_status_server(port: int = BATCH_STATUS_SERVER_PORT) -> tuple[bool, str]:
    url = f"http://127.0.0.1:{port}"
    if is_local_port_open(port):
        return True, url
    stdout_path = ROOT_DIR / "data" / "ai_exports" / "batch_status_server_stdout.log"
    stderr_path = ROOT_DIR / "data" / "ai_exports" / "batch_status_server_stderr.log"
    args = [
        sys.executable,
        "scripts/batch_status_server.py",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    try:
        start_background_command(args, stdout_path, stderr_path)
        time.sleep(1.0)
    except Exception as exc:
        return False, f"啟動狀態伺服器失敗：{exc}"
    if is_local_port_open(port):
        return True, url
    detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-1200:] if stderr_path.exists() else ""
    return False, detail or "狀態伺服器沒有回應"


def query_df(sql: str, params: tuple[str, ...] = ()) -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def db_stats() -> dict[str, int | str]:
    if not DB_PATH.exists():
        return {"cases": 0, "years": 0, "results": 0, "updated": "尚未建立"}
    row = query_df(
        """
        SELECT COUNT(*) AS cases,
               COUNT(DISTINCT year) AS years,
               COUNT(DISTINCT result) AS results,
               MAX(updated_at) AS updated
        FROM cases
        """
    ).iloc[0]
    return {
        "cases": int(row["cases"] or 0),
        "years": int(row["years"] or 0),
        "results": int(row["results"] or 0),
        "updated": row["updated"] or "未知",
    }


def distinct_values(column: str) -> list[str]:
    allowed = {"year", "case_type", "result", "issue_type"}
    if column not in allowed or not DB_PATH.exists():
        return []
    rows = query_df(f"SELECT DISTINCT {column} FROM cases WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}")
    return rows[column].dropna().astype(str).tolist() if not rows.empty else []


def case_markdown(case: dict[str, str]) -> str:
    return f"""# {case.get("title", "")}

- cid: {case.get("cid", "")}
- 日期: {case.get("date_text", "")}
- 案件類型: {case.get("case_type", "")}
- 爭點分類: {case.get("issue_type", "")}
- 結果: {case.get("result", "")}
- 原始網址: {case.get("url", "")}

## 全文

{case.get("full_text", "")}
"""


def highlight_terms(text: str, query: str) -> str:
    value = text or ""
    for term in [part for part in query.strip().split() if part]:
        value = value.replace(term, f"【{term}】")
    return value


def render_sources(sources: list[dict[str, str]]) -> None:
    if not sources:
        return
    st.markdown("**來源**")
    for source in sources:
        with st.expander(f"cid={source.get('cid', '')}｜{source.get('title', '')}", expanded=False):
            st.write(f"網址：{source.get('url', '')}")
            st.write(f"日期：{source.get('date_text', '')}")
            st.write(f"結果：{source.get('result', '')}")
            st.write(f"片段：{source.get('snippet', '')}")


def get_ai_config() -> SimpleNamespace:
    return SimpleNamespace(model="", base_url="")


def private_case_options() -> list[dict[str, object]]:
    init_private_db()
    return list_private_cases()


def private_case_label(case: dict[str, object]) -> str:
    title = case.get("title") or "未命名案件"
    number = case.get("case_number") or str(case.get("case_uuid", ""))[:8]
    return f"{case.get('id')}｜{number}｜{title}"


def selected_private_case(label: str, cases: list[dict[str, object]]) -> dict[str, object] | None:
    if not label:
        return None
    case_id = int(label.split("｜", 1)[0])
    return next((case for case in cases if int(case["id"]) == case_id), None)


def public_bundle_options() -> list[Path]:
    if not PUBLIC_AI_BUNDLE_DIR.exists():
        return []
    return sorted(
        [path for path in PUBLIC_AI_BUNDLE_DIR.iterdir() if path.is_dir() and (path / "bundle_manifest.json").exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def private_export_options() -> list[Path]:
    root = ROOT_DIR / "exports"
    if not root.exists():
        return []
    return sorted(
        [path for path in root.iterdir() if path.is_dir() and (path / "case_manifest.json").exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def path_label(path: Path) -> str:
    return f"{path.name}｜{path}"


def web_ai_batch_options() -> list[Path]:
    if not WEB_AI_BATCHES_DIR.exists():
        return []
    return sorted([path for path in WEB_AI_BATCHES_DIR.iterdir() if path.is_dir()], key=lambda path: path.stat().st_mtime, reverse=True)


def update_run_options() -> list[Path]:
    if not UPDATE_RUNS_DIR.exists():
        return []
    return sorted(
        [path for path in UPDATE_RUNS_DIR.iterdir() if path.is_dir() and (path / "update_manifest.json").exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def file_url(path: Path) -> str:
    try:
        return path.resolve().as_uri() if path.exists() else ""
    except Exception:
        return ""


def web_ai_batch_status(batch_dir: Path, refresh: bool = True) -> tuple[dict[str, int | str], pd.DataFrame]:
    if refresh:
        summary, rows = refresh_batch_status(batch_dir)
        df = pd.DataFrame(rows)
    else:
        manifest = read_json_file(batch_dir / "batch_manifest.json")
        status_path = batch_dir / "status.csv"
        if status_path.exists():
            df = pd.read_csv(status_path, dtype=str).fillna("")
        else:
            df = pd.DataFrame()
        counts = df["status"].value_counts().to_dict() if not df.empty and "status" in df.columns else {}
        planned_total = int(manifest.get("case_count") or len(df))
        summary = {
            "batch_id": batch_dir.name,
            "provider": str(manifest.get("provider") or ""),
            "model_name": str(manifest.get("model_name") or ""),
            "planned_total": planned_total,
            "done": int(counts.get("done", 0)),
            "running": int(counts.get("running", 0)),
            "paused": int(counts.get("paused", 0)),
            "failed": int(counts.get("failed", 0)),
            "pending": int(counts.get("pending", 0)),
            "stale": int(counts.get("stale", 0)),
            "remaining": max(planned_total - len(df), 0),
            "seen": len(df),
            "last_refreshed": "",
        }
    for column in ["cid", "status", "package_path", "run_id", "error", "started_at", "finished_at", "updated_at", "attempts", "manual_note"]:
        if column not in df.columns:
            df[column] = ""
    if not df.empty:
        df["analysis_dir"] = df["run_id"].apply(lambda run_id: str(ANALYSIS_RUNS_DIR / str(run_id)) if str(run_id).strip() else "")
        df["ai_response_url"] = df["run_id"].apply(lambda run_id: file_url(ANALYSIS_RUNS_DIR / str(run_id) / "ai_response.md") if str(run_id).strip() else "")
        df["citation_review_url"] = df["run_id"].apply(lambda run_id: file_url(ANALYSIS_RUNS_DIR / str(run_id) / "citation_review.md") if str(run_id).strip() else "")
    return summary, df


def process_badge(batch_dir: Path, summary: dict[str, int | str]) -> str:
    process_info = read_json_file(batch_dir / "process.json")
    pid = process_info.get("pid")
    running = int(summary.get("running", 0) or 0)
    if running:
        return f'<span class="batch-pulse"></span>執行中{f"｜PID {pid}" if pid else ""}'
    if int(summary.get("paused", 0) or 0):
        return "需要人工處理"
    if int(summary.get("failed", 0) or 0) or int(summary.get("stale", 0) or 0):
        return "需要重跑或覆核"
    if int(summary.get("pending", 0) or 0):
        return "等待續跑"
    return "全部完成"


def render_batch_dashboard(batch_dir: Path, summary: dict[str, int | str], status_df: pd.DataFrame) -> None:
    total = max(int(summary.get("planned_total", 0) or 0), 1)
    status_colors = {
        "done": "#22c55e",
        "running": "#38bdf8",
        "pending": "#f59e0b",
        "paused": "#fb7185",
        "failed": "#ef4444",
        "stale": "#a855f7",
    }
    status_labels = {
        "done": "完成",
        "running": "執行中",
        "pending": "待跑",
        "paused": "暫停",
        "failed": "失敗",
        "stale": "停滯",
    }
    segments = []
    legend = []
    for status in ["done", "running", "pending", "paused", "failed", "stale"]:
        count = int(summary.get(status, 0) or 0)
        width = max((count / total) * 100, 0)
        color = status_colors[status]
        if count:
            segments.append(f'<div class="batch-dashboard__seg" style="width:{width:.4f}%; background:{color};"></div>')
        legend.append(
            f"""
            <div class="batch-dashboard__legend-item">
                <span style="color:{color};">{status_labels[status]}</span>
                <strong>{count}</strong>
                <span>{(count / total) * 100:.1f}%</span>
            </div>
            """
        )
    done = int(summary.get("done", 0) or 0)
    html = f"""
    <div class="batch-dashboard">
        <div class="batch-dashboard__top">
            <div>
                <div class="batch-dashboard__title">批次 AI 分析儀表板</div>
                <div class="batch-dashboard__meta">{escape(batch_dir.name)}｜{escape(str(summary.get("provider") or ""))}｜{escape(str(summary.get("model_name") or ""))}</div>
            </div>
            <div class="batch-dashboard__badge">{process_badge(batch_dir, summary)}</div>
        </div>
        <div class="batch-dashboard__bar">{''.join(segments) or '<div class="batch-dashboard__seg" style="width:100%; background:rgba(255,253,248,.18);"></div>'}</div>
        <div class="batch-dashboard__meta" style="margin-top:.55rem;">完成 {done} / {total}，完成率 {(done / total) * 100:.1f}%｜最後同步：{escape(str(summary.get("last_refreshed") or ""))}</div>
        <div class="batch-dashboard__legend">{''.join(legend)}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

    if status_df.empty:
        st.info("此批次目前沒有 status.csv 內容。")
        return

    done_rows = status_df[status_df["status"].astype(str) == "done"]
    running_rows = status_df[status_df["status"].astype(str) == "running"]
    pending_rows = status_df[status_df["status"].astype(str) == "pending"]
    attention_rows = status_df[status_df["status"].astype(str).isin(["paused", "failed", "stale"])]
    last_done = done_rows.iloc[-1].to_dict() if not done_rows.empty else {}
    current = running_rows.iloc[0].to_dict() if not running_rows.empty else {}
    next_pending = pending_rows.iloc[0].to_dict() if not pending_rows.empty else {}
    st.markdown(
        f"""
        <div class="batch-step-list">
            <div class="batch-step"><small>目前處理</small><strong>{escape(str(current.get("cid") or "無執行中案件"))}</strong><br><small>{escape(str(current.get("started_at") or ""))}</small></div>
            <div class="batch-step"><small>最後完成</small><strong>{escape(str(last_done.get("cid") or "尚無完成"))}</strong><br><small>{escape(str(last_done.get("finished_at") or ""))}</small></div>
            <div class="batch-step"><small>下一筆待跑</small><strong>{escape(str(next_pending.get("cid") or "無待跑案件"))}</strong><br><small>{escape(str(next_pending.get("started_at") or ""))}</small></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not attention_rows.empty:
        st.warning(f"有 {len(attention_rows)} 筆需要注意：暫停、失敗或停滯。")


def analysis_result_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for run in list_analysis_runs():
        run_id = str(run.get("run_id") or "")
        if not run_id:
            continue
        run_dir = ANALYSIS_RUNS_DIR / run_id
        ai_response_path = run_dir / "ai_response.md"
        citation_path = run_dir / "citation_review.md"
        case_ids = [str(cid) for cid in run.get("case_ids", [])]
        first_case = get_case_by_cid(case_ids[0]) if case_ids else None
        title = first_case.get("title", "") if first_case else ""
        preview = ""
        if ai_response_path.exists():
            try:
                preview = " ".join(ai_response_path.read_text(encoding="utf-8").split())[:240]
            except Exception:
                preview = ""
        rows.append(
            {
                "cid": "、".join(case_ids),
                "title": title,
                "provider": run.get("provider", ""),
                "model_name": run.get("model_name", ""),
                "analysis_time": run.get("analysis_time", ""),
                "run_id": run_id,
                "ai_response_url": file_url(ai_response_path),
                "citation_review_url": file_url(citation_path),
                "run_dir_url": file_url(run_dir),
                "preview": preview,
            }
        )
    return rows


st.title("教師申訴評議書本機查詢工作台")
if CLOUD_PUBLIC_MODE:
    st.caption("雲端公開版：提供公開評議書搜尋、閱讀與 AI 上傳包；私人案件與瀏覽器自動化批次已停用。")
else:
    st.caption("公開評議書搜尋、私人案件整理、ChatGPT / Gemini 批次分析與本機歸檔；正式引用前請回到來源全文覆核。")

llm_config = get_ai_config()

stats = db_stats()
m1, m2, m3, m4 = st.columns(4)
m1.metric("案件數", stats["cases"])
m2.metric("年度數", stats["years"])
m3.metric("結果類別", stats["results"])
m4.metric("最後更新", str(stats["updated"])[:16])

if not DB_PATH.exists():
    st.warning("尚未建立 data/appeal_cases.db。請先到「資料管理」重建資料庫。")

tabs = st.tabs([
    "總覽",
    "公開評議書搜尋",
    "公開案件閱讀",
    "資料管理",
    "公開 AI 分析包",
    "資安檢查",
    "私人案件管理",
    "匯入案件文件",
    "案件文件閱讀",
    "Codex 分析資料",
    "AI 分析結果",
    "批次儀表板",
    "公開資料更新",
])

with tabs[0]:
    st.subheader("目前資料概況")
    c1, c2 = st.columns(2)
    with c1:
        by_issue = query_df("SELECT issue_type AS 爭點, COUNT(*) AS 件數 FROM cases GROUP BY issue_type ORDER BY 件數 DESC LIMIT 12")
        if not by_issue.empty:
            st.dataframe(by_issue, width="stretch", hide_index=True)
        else:
            st.info("尚無可統計資料。")
    with c2:
        by_result = query_df("SELECT result AS 結果, COUNT(*) AS 件數 FROM cases GROUP BY result ORDER BY 件數 DESC")
        if not by_result.empty:
            st.bar_chart(by_result.set_index("結果"))
        else:
            st.info("尚無結果統計。")
    st.markdown("**建議工作順序**")
    st.markdown(
        """
        <div class="workflow-strip">
          <div class="workflow-card"><strong>1. 找資料</strong><span>用公開搜尋或案件閱讀確認 cid、爭點與全文。</span></div>
          <div class="workflow-card"><strong>2. 產分析包</strong><span>勾選案件，產生 ChatGPT / Gemini 可分析的來源包。</span></div>
          <div class="workflow-card"><strong>3. 監控與覆核</strong><span>批次分析完成後，從分析紀錄開啟回覆與引用核對表。</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with tabs[1]:
    st.subheader("公開評議書搜尋")
    st.caption("搜尋、篩選、預覽、下載與加入分析批次都在同一頁完成。")
    st.markdown('<div class="layout-kicker">ACTION BAR</div><div class="action-bar-note">搜尋條件與篩選</div>', unsafe_allow_html=True)
    with st.container(border=True):
        f1, f2 = st.columns([3, 1])
        query = f1.text_input("關鍵字", value="", placeholder="例如：導師 職務分配、職場霸凌、成績考核")
        limit = f2.slider("筆數", min_value=10, max_value=300, value=50, step=10)
        with st.expander("進階篩選", expanded=False):
            ff1, ff2, ff3 = st.columns(3)
            year = ff1.selectbox("年度", [""] + distinct_values("year"))
            case_type = ff2.selectbox("案件類型", [""] + distinct_values("case_type"))
            result = ff3.selectbox("結果", [""] + distinct_values("result"))
    rows = search_fts(query=query, limit=int(limit), year=year, case_type=case_type, result=result)
    df = pd.DataFrame(rows)
    st.markdown('<div class="content-panel-note">內容區：結果清單與案件閱讀</div>', unsafe_allow_html=True)
    if df.empty:
        st.info("目前沒有符合條件的案件。可以放寬關鍵字，或清除進階篩選。")
    else:
        with st.container(border=True):
            if "selected_search_cid" not in st.session_state or st.session_state.selected_search_cid not in set(df["cid"].astype(str)):
                st.session_state.selected_search_cid = str(df.iloc[0]["cid"])
            st.caption(f"搜尋結果：{len(rows)} 筆。點左側案件即可在同頁閱讀全文。")
            left, right = st.columns([1.05, 1.45])
            with left:
                st.markdown("**結果清單**")
                for index, row in enumerate(rows, start=1):
                    cid = str(row.get("cid", ""))
                    title = row.get("title", "")
                    date_text = row.get("date_text", "")
                    result_text = row.get("result", "")
                    issue = row.get("issue_type", "")
                    snippet = highlight_terms(str(row.get("snippet", "")), query)
                    label = f"{index}. {cid}｜{title}"
                    if st.button(label, key=f"search_pick_{cid}", width="stretch"):
                        st.session_state.selected_search_cid = cid
                    if cid == st.session_state.selected_search_cid:
                        st.markdown(f"**目前選取**｜{date_text}｜{result_text}｜{issue}")
                    st.caption(snippet[:260])
                    st.divider()
            with right:
                case = get_case_by_cid(str(st.session_state.selected_search_cid))
                if not case:
                    st.warning("找不到選取案件。")
                else:
                    st.markdown(f"### {case.get('title', '')}")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("cid", case.get("cid", ""))
                    c2.metric("日期", case.get("date_text", "")[:18])
                    c3.metric("結果", case.get("result", ""))
                    c4.metric("爭點", case.get("issue_type", "")[:12])
                    st.caption(f"原始網址：{case.get('url', '')}")
                    a1, a2 = st.columns(2)
                    a1.download_button(
                        "下載本案 Markdown",
                        data=case_markdown(case).encode("utf-8"),
                        file_name=f"case_{case.get('cid', '')}.md",
                        mime="text/markdown",
                        width="stretch",
                    )
                    a2.link_button("開啟原始網址", case.get("url", "") or "https://appeal.moe.gov.tw/", width="stretch")
                    view_mode = st.radio("閱讀模式", ["命中片段", "全文"], horizontal=True)
                    if view_mode == "命中片段":
                        st.text_area("片段", value=highlight_terms(str(case.get("snippet") or make_snippet(case.get("full_text", ""), query)), query), height=260)
                    else:
                        st.text_area("全文", value=highlight_terms(case.get("full_text", ""), query), height=560)
            st.markdown("**匯出目前搜尋結果**")
            export_df = df.drop(columns=["full_text"], errors="ignore")
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                export_df.to_excel(writer, index=False, sheet_name="results")
            e1, e2, e3 = st.columns(3)
            e1.download_button(
                "下載 Excel",
                data=excel_buffer.getvalue(),
                file_name="appeal_search_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            md = "\n\n".join(
                f"## {row.get('title', '')}\n- cid: {row.get('cid', '')}\n- 結果: {row.get('result', '')}\n- 網址: {row.get('url', '')}\n\n{row.get('snippet', '')}"
                for row in rows
            )
            e2.download_button("下載 Markdown", data=md.encode("utf-8"), file_name="appeal_search_results.md", mime="text/markdown", width="stretch")
            cids_text = "\n".join(str(row.get("cid", "")) for row in rows if row.get("cid")) + "\n"
            e3.download_button("下載 cid 清單", data=cids_text.encode("utf-8"), file_name="search_cids.txt", mime="text/plain", width="stretch")

with tabs[2]:
    st.subheader("案件閱讀")
    cid_input = st.text_input("輸入 cid", value="")
    if not cid_input:
        recent = query_df("SELECT cid, title, date_text, result FROM cases ORDER BY updated_at DESC LIMIT 50")
        if not recent.empty:
            selected = st.selectbox("或從最近案件選擇", [""] + [f"{r.cid}｜{r.title}" for r in recent.itertuples()])
            cid_input = selected.split("｜", 1)[0] if selected else ""
    if cid_input:
        case = get_case_by_cid(cid_input.strip())
        if case:
            st.markdown(f"### {case.get('title', '')}")
            c1, c2, c3, c4 = st.columns(4)
            c1.write(f"cid：{case.get('cid', '')}")
            c2.write(f"日期：{case.get('date_text', '')}")
            c3.write(f"結果：{case.get('result', '')}")
            c4.write(f"爭點：{case.get('issue_type', '')}")
            st.write(f"原始網址：{case.get('url', '')}")
            st.download_button("下載本案 Markdown", data=case_markdown(case).encode("utf-8"), file_name=f"case_{cid_input}.md", mime="text/markdown")
            st.text_area("全文", value=case.get("full_text", ""), height=520)
        else:
            st.warning("找不到這個 cid。")

with tabs[3]:
    st.subheader("資料管理")
    pasted = st.text_area("貼上 cid、案件網址或混雜文字", height=160, placeholder="https://appeal.moe.gov.tw/appraise_view.aspx?cid=114070228")
    cids = extract_cids(pasted)
    st.caption(f"已解析 cid：{len(cids)} 個")
    if cids:
        st.code("\n".join(cids))
        st.download_button("下載 cids.txt", data=("\n".join(cids) + "\n").encode("utf-8"), file_name="cids.txt", mime="text/plain")
    d1, d2 = st.columns(2)
    with d1:
        sleep_seconds = st.number_input("下載間隔秒數", min_value=0.0, max_value=10.0, value=1.5, step=0.5)
        if st.button("下載上方 cid 並更新 CSV", disabled=not cids):
            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            temp_cids = EXPORTS_DIR / "streamlit_cids.txt"
            temp_cids.write_text("\n".join(cids) + "\n", encoding="utf-8")
            ok, output = run_command([sys.executable, "scripts/crawl_appeal.py", "--cid-file", str(temp_cids), "--sleep", str(sleep_seconds)], timeout=1800)
            st.success(output) if ok else st.error(output)
    with d2:
        if st.button("重建 SQLite 資料庫"):
            ok, output = run_command([sys.executable, "scripts/build_db.py"])
            st.success(output) if ok else st.error(output)
    st.markdown("**目前資料檔**")
    files = [
        ("cases.csv", CASES_CSV),
        ("appeal_cases.db", DB_PATH),
        ("private_cases.db", PRIVATE_DB_PATH),
        ("crawl_errors.log", ERROR_LOG),
    ]
    st.dataframe(pd.DataFrame([{"檔案": name, "存在": path.exists(), "大小": path.stat().st_size if path.exists() else 0} for name, path in files]), hide_index=True)

with tabs[4]:
    st.subheader("公開評議書 AI 分析包")
    st.info("勾選公開案件後產生可下載的 ChatGPT / Gemini 上傳包；本頁不呼叫外部 API，也不會自動上傳全文。")
    if not CASES_CSV.exists():
        st.warning("找不到 data/cases.csv，請先完成公開資料抓取。")
    else:
        public_rows = query_df("SELECT cid, title, date_text, year, result, issue_type FROM cases ORDER BY updated_at DESC")
        if public_rows.empty:
            st.warning("公開資料庫沒有案件。請先執行 python scripts/build_db.py。")
        else:
            st.markdown('<div class="layout-kicker">ACTION BAR</div><div class="action-bar-note">篩選、勾選與產生上傳包</div>', unsafe_allow_html=True)
            with st.container(border=True):
                f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
                keyword = f1.text_input("篩選關鍵字", placeholder="搜尋 cid、標題、日期、結果或爭點", key="public_ai_keyword")
                year_filter = f2.selectbox("年度", [""] + sorted(public_rows["year"].dropna().astype(str).unique().tolist()), key="public_ai_year")
                result_filter = f3.selectbox("結果", [""] + sorted(public_rows["result"].dropna().astype(str).unique().tolist()), key="public_ai_result")
                issue_filter = f4.selectbox("爭點分類", [""] + sorted(public_rows["issue_type"].dropna().astype(str).unique().tolist()), key="public_ai_issue")

            filtered = public_rows.copy()
            if keyword.strip():
                needle = keyword.strip()
                search_cols = ["cid", "title", "date_text", "result", "issue_type"]
                mask = filtered[search_cols].fillna("").astype(str).apply(lambda col: col.str.contains(needle, case=False, regex=False)).any(axis=1)
                filtered = filtered[mask]
            if year_filter:
                filtered = filtered[filtered["year"].astype(str) == year_filter]
            if result_filter:
                filtered = filtered[filtered["result"].fillna("").astype(str) == result_filter]
            if issue_filter:
                filtered = filtered[filtered["issue_type"].fillna("").astype(str) == issue_filter]

            st.markdown('<div class="content-panel-note">內容區：案件選取與輸出</div>', unsafe_allow_html=True)
            st.caption(f"篩選結果：{len(filtered)} / {len(public_rows)} 筆")
            select_all = st.checkbox("全選目前篩選結果", value=False, key="public_ai_select_all")
            editor_df = filtered[["cid", "title", "date_text", "year", "result", "issue_type"]].copy()
            editor_df.insert(0, "選取", select_all)
            edited = st.data_editor(
                editor_df,
                hide_index=True,
                width="stretch",
                disabled=["cid", "title", "date_text", "year", "result", "issue_type"],
                column_config={"選取": st.column_config.CheckboxColumn("選取")},
                key="public_ai_case_selector",
            )
            selected_cids = edited.loc[edited["選取"], "cid"].astype(str).tolist() if not edited.empty else []
            package_label = st.radio("工作包模式", ["單案分析包", "多案比較包"], horizontal=True)
            package_mode = "compare" if package_label == "多案比較包" else "single"

            selected_df = filtered[filtered["cid"].astype(str).isin(selected_cids)]
            estimated_chars = 0
            for cid in selected_cids:
                text_path = ROOT_DIR / "data" / "texts" / f"{cid}.txt"
                if text_path.exists():
                    estimated_chars += text_path.stat().st_size
            m1, m2, m3 = st.columns(3)
            m1.metric("已選案件", len(selected_cids))
            m2.metric("預估文字大小", f"{estimated_chars / 1024:.1f} KB")
            m3.metric("輸出模式", package_label)
            if len(selected_cids) > 20:
                st.warning("已選案件超過 20 件，建議分批產生，避免 ChatGPT / Gemini 上傳或上下文限制。")
            if package_mode == "compare" and len(selected_cids) < 2:
                st.warning("多案比較建議至少選 2 件；只選 1 件時仍可產生，但比較內容會有限。")
            if not selected_df.empty:
                st.markdown("**已選清單**")
                st.dataframe(selected_df[["cid", "title", "date_text", "result", "issue_type"]], width="stretch", hide_index=True)

            st.caption(f"單案輸出根目錄：{PUBLIC_AI_EXPORT_DIR}")
            st.caption(f"上傳包輸出根目錄：{PUBLIC_AI_BUNDLE_DIR}")
            if st.button("產生 AI 上傳包", type="primary", disabled=not selected_cids):
                try:
                    result = export_public_case_bundle(selected_cids, mode=package_mode)
                    st.success(f"已產生 {result.manifest['case_count']} 件案件上傳包。")
                    st.code(str(result.bundle_dir))
                    st.download_button(
                        "下載 ZIP 上傳包",
                        data=result.zip_path.read_bytes(),
                        file_name=result.zip_path.name,
                        mime="application/zip",
                    )
                    st.markdown("**建議操作文字**")
                    st.code(
                        "請先上傳這個 ZIP，或上傳其中各案的 case_full_context.md；"
                        "再貼上 multi_case_prompt.md。請只根據資料包內來源分析，並逐項引用 cid 與 D001 段落。"
                    )
                    st.info("完成 ChatGPT/Gemini 分析後，請到「AI 分析紀錄」頁籤貼上 AI 原始回覆存檔。")
                    c1, c2 = st.columns(2)
                    c1.link_button("開啟 ChatGPT", "https://chatgpt.com/")
                    c2.link_button("開啟 Gemini", "https://gemini.google.com/")
                except Exception as exc:
                    st.error(f"匯出失敗：{exc}")

            if CLOUD_PUBLIC_MODE:
                web_sleep = 3.0
                st.info("雲端公開版不啟動 ChatGPT/Gemini 瀏覽器自動化。請下載 AI 上傳包後，手動到 ChatGPT/Gemini 分析並回到「AI 分析結果」保存。")
                recent_batches = []
            else:
                st.markdown('<div class="layout-kicker">ACTION BAR</div><div class="action-bar-note">網頁批次自動分析</div>', unsafe_allow_html=True)
                with st.container(border=True):
                    st.warning("此功能會開啟本機瀏覽器控制 ChatGPT/Gemini 網頁。請先登入帳號；遇到驗證、額度或 UI 異常時會暫停，不會繞過限制。")
                    b1, b2, b3 = st.columns([1, 1, 1])
                    web_provider = b1.selectbox("服務", ["chatgpt", "gemini"], key="web_ai_provider")
                    web_model_name = b2.text_input("模型名稱", value="", placeholder="例如 GPT-4.1 / Gemini 2.5 Pro", key="web_ai_model")
                    web_sleep = b3.number_input("每案間隔秒數", min_value=0.0, max_value=60.0, value=3.0, step=1.0, key="web_ai_sleep")
                    max_cases = st.number_input("最多送出案件數", min_value=1, max_value=100, value=min(max(len(selected_cids), 1), 10), step=1)
                    batch_cids = selected_cids[: int(max_cases)]
                    st.caption(f"將送出 {len(batch_cids)} 件。第一版採貼文字方式；若單案文字過長會暫停並要求人工處理。")
                    start_web_batch = st.button("啟動網頁批次自動分析", disabled=not batch_cids)
                if start_web_batch:
                    try:
                        batch_dir = create_batch_dir(web_provider)
                        cid_file = batch_dir / "selected_cids.txt"
                        cid_file.write_text("\n".join(batch_cids) + "\n", encoding="utf-8")
                        stdout_path = batch_dir / "logs" / "stdout.log"
                        stderr_path = batch_dir / "logs" / "stderr.log"
                        args = [
                            sys.executable,
                            "scripts/run_web_ai_batch.py",
                            "--provider",
                            web_provider,
                            "--cid-file",
                            str(cid_file),
                            "--sleep",
                            str(float(web_sleep)),
                            "--model-name",
                            web_model_name,
                            "--batch-dir",
                            str(batch_dir),
                        ]
                        pid = start_background_command(args, stdout_path, stderr_path)
                        (batch_dir / "process.json").write_text(
                            json.dumps({"pid": pid, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "args": args}, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        st.success(f"已啟動背景批次，PID={pid}")
                        st.code(" ".join(args))
                        st.code(str(batch_dir))
                        st.info("若瀏覽器停在登入、驗證或額度畫面，請在開啟的瀏覽器中人工處理，再回到命令列/背景程序提示繼續。")
                    except Exception as exc:
                        st.error(f"啟動失敗：{exc}")
                st.markdown('<div class="content-panel-note">內容區：最近網頁批次狀態</div>', unsafe_allow_html=True)
                recent_batches = web_ai_batch_options()[:5]
            if recent_batches:
                st.markdown("**最近網頁批次狀態**")
                selected_batch_label = st.selectbox("選擇批次", [path_label(path) for path in recent_batches], key="web_ai_batch_status")
                selected_batch = recent_batches[[path_label(path) for path in recent_batches].index(selected_batch_label)]
                m1, m2, m3 = st.columns([1, 1, 2])
                auto_refresh = m1.checkbox("自動刷新", value=False, key="web_ai_auto_refresh")
                refresh_seconds = m2.number_input("刷新秒數", min_value=5, max_value=120, value=10, step=5, key="web_ai_refresh_seconds")
                if m3.button("手動同步全部狀態", width="stretch"):
                    refresh_batch_status(selected_batch)
                    st.success("已重新同步 status.csv。")
                    st.rerun()
                summary, status_df = web_ai_batch_status(selected_batch)
                s1, s2, s3, s4, s5, s6, s7, s8 = st.columns(8)
                s1.metric("總數", summary["planned_total"])
                s2.metric("完成", summary["done"])
                s3.metric("執行中", summary["running"])
                s4.metric("暫停", summary["paused"])
                s5.metric("失敗", summary["failed"])
                s6.metric("待跑", summary.get("pending", 0))
                s7.metric("停滯", summary.get("stale", 0))
                s8.metric("剩餘", summary["remaining"])
                total = int(summary["planned_total"] or 0)
                if total:
                    st.progress(min(int(summary["done"]) / total, 1.0), text=f"完成 {summary['done']} / {total}")
                if summary.get("last_refreshed"):
                    st.caption(f"最後同步：{summary['last_refreshed']}")
                with st.expander("狀態更新與重跑", expanded=bool(int(summary.get("paused", 0)) or int(summary.get("failed", 0)) or int(summary.get("stale", 0)))):
                    retry_status_options = ["pending", "paused", "failed", "stale"]
                    retry_statuses = st.multiselect("重跑狀態", retry_status_options, default=["pending", "paused", "failed", "stale"], key="web_ai_retry_statuses")
                    retry_cids = select_retry_cids(selected_batch, retry_statuses) if retry_statuses else []
                    st.caption(f"符合重跑條件：{len(retry_cids)} 件")
                    r1, r2 = st.columns([1, 2])
                    if r1.button("重跑符合條件案件", disabled=not retry_cids, width="stretch"):
                        try:
                            stamp = time.strftime("%Y%m%d_%H%M%S")
                            stdout_path = selected_batch / "logs" / f"resume_{stamp}_stdout.log"
                            stderr_path = selected_batch / "logs" / f"resume_{stamp}_stderr.log"
                            args = [
                                sys.executable,
                                "scripts/run_web_ai_batch.py",
                                "--resume-batch",
                                str(selected_batch),
                                "--statuses",
                                ",".join(retry_statuses),
                                "--sleep",
                                str(float(web_sleep)),
                            ]
                            pid = start_background_command(args, stdout_path, stderr_path)
                            (selected_batch / "process.json").write_text(
                                json.dumps({"pid": pid, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "args": args}, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                            st.success(f"已啟動續跑，PID={pid}")
                            st.code(" ".join(args))
                        except Exception as exc:
                            st.error(f"續跑啟動失敗：{exc}")
                    r2.code(f"python scripts/run_web_ai_batch.py --resume-batch \"{selected_batch}\" --statuses {','.join(retry_statuses or retry_status_options)} --sleep {float(web_sleep)}")

                    if not status_df.empty:
                        st.markdown("**單案覆核**")
                        cid_labels = [
                            f"{row.cid}｜{row.status}｜{row.run_id or 'no-run'}"
                            for row in status_df[["cid", "status", "run_id"]].itertuples(index=False)
                        ]
                        selected_case_label = st.selectbox("選擇 cid", cid_labels, key="web_ai_manual_cid")
                        selected_case_cid = selected_case_label.split("｜", 1)[0]
                        selected_row = status_df[status_df["cid"].astype(str) == selected_case_cid].iloc[0].to_dict()
                        with st.form("web_ai_manual_status_form"):
                            f1, f2 = st.columns(2)
                            status_choices = ["pending", "running", "done", "paused", "failed", "stale"]
                            current_status = str(selected_row.get("status") or "pending")
                            current_status_index = status_choices.index(current_status) if current_status in status_choices else 0
                            manual_status = f1.selectbox(
                                "手動狀態",
                                status_choices,
                                index=current_status_index,
                            )
                            manual_run_id = f2.text_input("run_id", value=str(selected_row.get("run_id") or ""))
                            manual_error = st.text_input("錯誤訊息", value=str(selected_row.get("error") or ""))
                            manual_note = st.text_area("人工備註", value=str(selected_row.get("manual_note") or ""), height=90)
                            c1, c2 = st.columns(2)
                            submitted_manual = c1.form_submit_button("保存單案狀態", width="stretch")
                            submitted_retry_one = c2.form_submit_button("只重跑此案", width="stretch")
                        if submitted_manual:
                            try:
                                set_case_status(
                                    selected_batch,
                                    selected_case_cid,
                                    manual_status,
                                    run_id=manual_run_id,
                                    error=manual_error,
                                    manual_note=manual_note,
                                )
                                st.success(f"已更新 {selected_case_cid}")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"更新失敗：{exc}")
                        if submitted_retry_one:
                            try:
                                set_case_status(selected_batch, selected_case_cid, "pending", manual_note=manual_note)
                                stamp = time.strftime("%Y%m%d_%H%M%S")
                                stdout_path = selected_batch / "logs" / f"resume_{selected_case_cid}_{stamp}_stdout.log"
                                stderr_path = selected_batch / "logs" / f"resume_{selected_case_cid}_{stamp}_stderr.log"
                                args = [
                                    sys.executable,
                                    "scripts/run_web_ai_batch.py",
                                    "--resume-batch",
                                    str(selected_batch),
                                    "--cid",
                                    selected_case_cid,
                                    "--statuses",
                                    "pending,paused,failed,stale",
                                    "--sleep",
                                    str(float(web_sleep)),
                                ]
                                pid = start_background_command(args, stdout_path, stderr_path)
                                st.success(f"已啟動單案重跑，PID={pid}")
                                st.code(" ".join(args))
                            except Exception as exc:
                                st.error(f"單案重跑失敗：{exc}")
                status_path = selected_batch / "status.csv"
                if not status_df.empty:
                    display_df = status_df[
                        [
                            "cid",
                            "status",
                            "run_id",
                            "ai_response_url",
                            "citation_review_url",
                            "error",
                            "started_at",
                            "finished_at",
                            "updated_at",
                            "attempts",
                            "manual_note",
                            "analysis_dir",
                            "package_path",
                        ]
                    ].copy()
                    st.dataframe(
                        display_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "ai_response_url": st.column_config.LinkColumn("AI 回覆", display_text="ai_response.md"),
                            "citation_review_url": st.column_config.LinkColumn("引用覆核", display_text="citation_review.md"),
                        },
                    )
                    completed_rows = status_df[status_df["run_id"].astype(str).str.strip() != ""]
                    if not completed_rows.empty:
                        st.markdown("**快速預覽已歸檔結果**")
                        labels = [f"{row.cid}｜{row.run_id}" for row in completed_rows.itertuples()]
                        selected_run = st.selectbox("選擇分析結果", labels, key="web_ai_analysis_preview")
                        run_id = selected_run.split("｜", 1)[1]
                        response_path = ANALYSIS_RUNS_DIR / run_id / "ai_response.md"
                        c1, c2, c3 = st.columns(3)
                        c1.link_button("開啟 AI 回覆檔", file_url(response_path), disabled=not response_path.exists())
                        c2.link_button("開啟分析資料夾", file_url(ANALYSIS_RUNS_DIR / run_id), disabled=not (ANALYSIS_RUNS_DIR / run_id).exists())
                        c3.link_button("開啟引用覆核表", file_url(ANALYSIS_RUNS_DIR / run_id / "citation_review.md"), disabled=not (ANALYSIS_RUNS_DIR / run_id / "citation_review.md").exists())
                        if response_path.exists():
                            preview = response_path.read_text(encoding="utf-8")
                            st.text_area("AI 回覆預覽", value=preview[:8000], height=360)
                else:
                    st.info("此批次尚未寫入 status.csv。")
                st.caption(f"批次目錄：{selected_batch}")
                if auto_refresh:
                    time.sleep(int(refresh_seconds))
                    st.rerun()

with tabs[5]:
    st.subheader("資安與健康檢查")
    st.write("這裡檢查本機資料、爬蟲錯誤紀錄與資料庫同步狀態。")
    checks = run_health_check(model=llm_config.model, base_url=llm_config.base_url, check_ai=False)
    for name, status, detail in checks:
        if status == "PASS":
            st.success(f"{name}：{detail}")
        else:
            st.warning(f"{name}：{detail}")
    st.markdown("**使用提醒**")
    st.write("- 本工具預設用公開案件資料；若加入非公開資料，請先去識別化。")
    st.write("- 教育部站台憑證異常時爬蟲會採寬鬆模式重試，正式環境可改用 `--verify-ssl`。")
    st.write("- AI 回答只能作整理草稿；正式引用請回到 cid 原文確認。")

with tabs[6]:
    st.subheader("私人案件管理")
    if CLOUD_PUBLIC_MODE:
        st.info("雲端公開版停用私人案件管理。私人文件、private_cases.db、uploaded_cases/ 與 exports/ 請留在本機使用。")
    else:
        init_private_db()
        with st.form("create_private_case"):
            st.markdown("**建立案件**")
            c1, c2 = st.columns(2)
            case_number = c1.text_input("案號")
            title = c2.text_input("標題")
            case_type = c1.text_input("案件類型")
            description = c2.text_area("案件說明", height=90)
            if st.form_submit_button("建立案件", type="primary"):
                created = create_case(case_number, title or "未命名案件", case_type, description)
                st.success(f"已建立案件：{created.get('case_uuid')}")

        cases = private_case_options()
        st.markdown("**案件列表**")
        if cases:
            st.dataframe(pd.DataFrame(cases), width="stretch", hide_index=True)
            selected_label = st.selectbox("選擇案件編輯", [""] + [private_case_label(case) for case in cases], key="private_edit_select")
            case = selected_private_case(selected_label, cases)
            if case:
                with st.form("edit_private_case"):
                    edit_number = st.text_input("案號", value=str(case.get("case_number") or ""))
                    edit_title = st.text_input("標題", value=str(case.get("title") or ""))
                    edit_type = st.text_input("案件類型", value=str(case.get("case_type") or ""))
                    edit_desc = st.text_area("案件說明", value=str(case.get("description") or ""), height=110)
                    if st.form_submit_button("儲存修改"):
                        update_case(int(case["id"]), edit_number, edit_title, edit_type, edit_desc)
                        st.success("已更新案件基本資料。")
                st.markdown("**刪除案件**")
                confirm = st.checkbox(f"我確認要刪除案件 {case.get('case_uuid')} 及其所有文件", key="delete_private_confirm")
                typed = st.text_input("請輸入 DELETE 二次確認", key="delete_private_text")
                if st.button("刪除案件", disabled=not (confirm and typed == "DELETE")):
                    delete_case(int(case["id"]))
                    st.success("已刪除案件。")
        else:
            st.info("尚未建立私人案件。")

with tabs[7]:
    st.subheader("匯入案件文件")
    if CLOUD_PUBLIC_MODE:
        st.info("雲端公開版停用私人文件匯入。請在本機版處理 PDF、DOCX、TXT 與去識別化私人案件。")
    else:
        cases = private_case_options()
        if not cases:
            st.warning("請先到「私人案件管理」建立案件。")
        else:
            selected_label = st.selectbox("選擇案件", [private_case_label(case) for case in cases], key="private_import_case")
            case = selected_private_case(selected_label, cases)
            uploads = st.file_uploader("上傳 PDF、DOCX、TXT，可一次多檔", type=["pdf", "docx", "txt"], accept_multiple_files=True)
            if st.button("開始匯入", type="primary", disabled=not uploads):
                progress = st.progress(0)
                results = []
                for index, uploaded in enumerate(uploads, start=1):
                    try:
                        data = uploaded.getvalue()
                        result = import_document(int(case["id"]), uploaded.name, data, uploaded.type or "")
                        results.append(
                            {
                                "檔名": uploaded.name,
                                "狀態": result.get("parse_status"),
                                "訊息": "重複檔案，未新增內容" if result.get("duplicate") else result.get("parse_error", ""),
                                "擷取單位數": result.get("unit_count", 0),
                            }
                        )
                    except Exception as exc:
                        results.append({"檔名": uploaded.name, "狀態": "failed", "訊息": str(exc), "擷取單位數": 0})
                    progress.progress(index / len(uploads))
                st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)
                for row in results:
                    if row["狀態"] in {"no_text", "parsed_with_warnings"}:
                        st.warning(f"{row['檔名']}：{row['訊息']}")

with tabs[8]:
    st.subheader("案件文件閱讀")
    if CLOUD_PUBLIC_MODE:
        st.info("雲端公開版停用私人案件文件閱讀。私人案件資料不會上傳雲端。")
    else:
        cases = private_case_options()
        if not cases:
            st.info("尚無私人案件。")
        else:
            selected_label = st.selectbox("選擇案件", [private_case_label(case) for case in cases], key="private_read_case")
            case = selected_private_case(selected_label, cases)
            docs = list_private_documents(int(case["id"]))
            st.caption(f"文件數：{len(docs)}")
            if docs:
                doc_label = st.selectbox("文件", [f"{doc['id']}｜{doc['original_filename']}" for doc in docs])
                document_id = int(doc_label.split("｜", 1)[0])
                document = next(doc for doc in docs if int(doc["id"]) == document_id)
                st.write(f"解析狀態：{document.get('parse_status')}｜{document.get('parse_error') or '無'}")
                units = list_private_units(document_id)
                unit_df = pd.DataFrame([{k: row.get(k) for k in ["unit_type", "page_number", "paragraph_number", "line_start", "line_end", "content"]} for row in units])
                if not unit_df.empty:
                    st.dataframe(unit_df.drop(columns=["content"], errors="ignore"), width="stretch", hide_index=True)
                    st.text_area("全文", value="\n\n".join(str(row.get("content") or "") for row in units), height=420)
                else:
                    st.warning("此文件沒有可顯示的文字。若為掃描 PDF，請先 OCR。")
            st.markdown("**私人案件搜尋**")
            q = st.text_input("搜尋關鍵字", key="private_search_query")
            scope = st.radio("搜尋範圍", ["單一案件", "全部已去識別化私人案件"], horizontal=True)
            if st.button("搜尋私人案件") and q.strip():
                rows = search_private_units(q, case_id=int(case["id"]) if scope == "單一案件" else None, limit=100)
                st.caption(f"搜尋結果：{len(rows)} 筆")
                if rows:
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                else:
                    st.info("沒有符合結果。")

with tabs[9]:
    st.subheader("Codex 分析資料")
    if CLOUD_PUBLIC_MODE:
        st.info("雲端公開版停用私人 Codex 分析資料包。請在本機版輸出私人案件 Markdown。")
    else:
        st.info("此功能只整理來源資料並輸出 Markdown，不摘要、不改寫原文，也不從程式內呼叫 Codex IDE。")
        cases = private_case_options()
        if not cases:
            st.warning("尚無私人案件。")
        else:
            selected_label = st.selectbox("選擇案件", [private_case_label(case) for case in cases], key="codex_case")
            case = selected_private_case(selected_label, cases)
            docs = list_private_documents(int(case["id"])) if case else []
            st.markdown("**文件清單**")
            if docs:
                doc_rows = []
                for index, doc in enumerate(docs, start=1):
                    units = list_private_units(int(doc["id"]))
                    doc_rows.append(
                        {
                            "文件代號": f"D{index:03d}",
                            "document_id": doc.get("id"),
                            "原始檔名": doc.get("original_filename"),
                            "類型": Path(str(doc.get("original_filename") or "")).suffix.upper().lstrip("."),
                            "單元數": len(units),
                            "解析狀態": doc.get("parse_status"),
                            "解析訊息": doc.get("parse_error") or "",
                        }
                    )
                st.dataframe(pd.DataFrame(doc_rows), width="stretch", hide_index=True)
            else:
                st.error("此案件尚未匯入任何文件，無法產生 Codex 分析包。")

            mode = st.radio("輸出內容", ["全部文件全文", "勾選文件", "單案搜尋結果"], horizontal=True)
            query = ""
            selected_doc_ids: list[int] | None = None
            if mode == "勾選文件" and docs:
                labels = [f"{doc['id']}｜{doc['original_filename']}" for doc in docs]
                selected_docs = st.multiselect("選擇要匯出的文件", labels, default=labels)
                selected_doc_ids = [int(label.split("｜", 1)[0]) for label in selected_docs]
            if mode == "單案搜尋結果":
                query = st.text_input("片段搜尋關鍵字")
                if query.strip() and case:
                    preview_rows = search_private_units(query, case_id=int(case["id"]), limit=100)
                    st.caption(f"搜尋預覽：{len(preview_rows)} 筆")
                    if preview_rows:
                        st.dataframe(pd.DataFrame(preview_rows), width="stretch", hide_index=True)
            disabled = not docs or (mode == "勾選文件" and not selected_doc_ids) or (mode == "單案搜尋結果" and not query.strip())
            if st.button("產生 Codex 分析包", type="primary", disabled=disabled):
                try:
                    out_dir = export_analysis_package(
                        int(case["id"]),
                        query=query,
                        full_context=(mode != "單案搜尋結果"),
                        document_ids=selected_doc_ids,
                    )
                    st.success(f"已輸出到 {out_dir}")
                    st.code(str(out_dir))
                    st.info("完成 Codex/ChatGPT/Gemini 分析後，請到「AI 分析紀錄」頁籤貼上 AI 原始回覆存檔。")
                except Exception as exc:
                    st.error(f"輸出失敗：{exc}")

with tabs[10]:
    st.subheader("AI 分析結果")
    st.info("這裡直接列出已完成的 ChatGPT / Gemini / Codex 分析結果，可搜尋、開啟回覆、查看引用覆核表。")

    result_rows = analysis_result_rows()
    if result_rows:
        result_df = pd.DataFrame(result_rows)
        st.markdown('<div class="layout-kicker">ACTION BAR</div><div class="action-bar-note">搜尋與結果統計</div>', unsafe_allow_html=True)
        with st.container(border=True):
            q = st.text_input("搜尋已分析結果", placeholder="輸入 cid、標題、run_id 或模型名稱", key="analysis_result_query")
        filtered_results = result_df.copy()
        if q.strip():
            needle = q.strip()
            cols = ["cid", "title", "run_id", "provider", "model_name", "preview"]
            mask = filtered_results[cols].fillna("").astype(str).apply(lambda col: col.str.contains(needle, case=False, regex=False)).any(axis=1)
            filtered_results = filtered_results[mask]
        m1, m2, m3 = st.columns(3)
        m1.metric("已歸檔結果", len(result_df))
        m2.metric("目前顯示", len(filtered_results))
        m3.metric("ChatGPT", int((result_df["provider"] == "chatgpt").sum()) if "provider" in result_df else 0)
        st.markdown('<div class="content-panel-note">內容區：分析清單與回覆對照</div>', unsafe_allow_html=True)
        if filtered_results.empty:
            st.warning("沒有符合搜尋條件的分析結果。")
        else:
            with st.container(border=True):
                if "selected_analysis_run_id" not in st.session_state or st.session_state.selected_analysis_run_id not in set(filtered_results["run_id"].astype(str)):
                    st.session_state.selected_analysis_run_id = str(filtered_results.iloc[0]["run_id"])
                list_col, detail_col = st.columns([0.9, 1.6])
                with list_col:
                    st.markdown("**結果清單**")
                    st.caption("點選左側項目，右側立即切換內容。")
                    for row in filtered_results.itertuples():
                        active = str(row.run_id) == st.session_state.selected_analysis_run_id
                        button_label = f"{row.cid}｜{row.title or row.run_id}"
                        if st.button(button_label, key=f"pick_analysis_{row.run_id}", width="stretch"):
                            st.session_state.selected_analysis_run_id = str(row.run_id)
                        meta = f"{row.analysis_time}｜{row.provider}｜{row.model_name}"
                        st.caption(("目前選取｜" if active else "") + meta)
                        if row.preview:
                            st.caption(str(row.preview)[:180])
                        st.divider()
                with detail_col:
                    selected_row = filtered_results[filtered_results["run_id"].astype(str) == st.session_state.selected_analysis_run_id].iloc[0]
                    selected_run_id = str(selected_row["run_id"])
                    response_path = ANALYSIS_RUNS_DIR / selected_run_id / "ai_response.md"
                    citation_path = ANALYSIS_RUNS_DIR / selected_run_id / "citation_review.md"
                    st.markdown(f"### {selected_row['cid']}｜{selected_row['title'] or '未命名案件'}")
                    d1, d2, d3 = st.columns(3)
                    d1.metric("來源", selected_row["provider"])
                    d2.metric("模型", selected_row["model_name"] or "未填")
                    d3.metric("時間", str(selected_row["analysis_time"])[5:16])
                    c1, c2, c3 = st.columns(3)
                    c1.link_button("開啟 AI 回覆", file_url(response_path), disabled=not response_path.exists(), width="stretch")
                    c2.link_button("開啟引用覆核", file_url(citation_path), disabled=not citation_path.exists(), width="stretch")
                    c3.link_button("開啟資料夾", file_url(ANALYSIS_RUNS_DIR / selected_run_id), disabled=not (ANALYSIS_RUNS_DIR / selected_run_id).exists(), width="stretch")
                    if response_path.exists():
                        response_text = response_path.read_text(encoding="utf-8")
                        st.download_button(
                            "下載本分析 Markdown",
                            data=response_text.encode("utf-8"),
                            file_name=f"{selected_run_id}_ai_response.md",
                            mime="text/markdown",
                            width="stretch",
                        )
                        st.text_area("AI 整理結果", value=response_text, height=680)
                    else:
                        st.warning("找不到 AI 回覆檔。")
            with st.expander("表格總覽與連結", expanded=False):
                st.dataframe(
                    filtered_results[
                        [
                            "cid",
                            "title",
                            "provider",
                            "model_name",
                            "analysis_time",
                            "run_id",
                            "ai_response_url",
                            "citation_review_url",
                            "run_dir_url",
                            "preview",
                        ]
                    ],
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "ai_response_url": st.column_config.LinkColumn("AI 回覆", display_text="開啟"),
                        "citation_review_url": st.column_config.LinkColumn("引用覆核", display_text="開啟"),
                        "run_dir_url": st.column_config.LinkColumn("資料夾", display_text="開啟"),
                    },
                )
    else:
        st.warning("目前尚無已歸檔的 AI 分析結果。批次完成後會自動出現在這裡。")

    st.markdown("---")
    st.subheader("手動補登分析紀錄")
    st.caption("若是手動在 ChatGPT/Gemini/Codex 分析，也可以在這裡把原始回覆貼回來保存。")
    source_options = ["公開 AI 上傳包"] if CLOUD_PUBLIC_MODE else ["公開 AI 上傳包", "私人 Codex 分析包"]
    source_kind = st.radio("紀錄來源", source_options, horizontal=True)
    scope = "public_bundle" if source_kind == "公開 AI 上傳包" else "private_case"
    options = public_bundle_options() if scope == "public_bundle" else private_export_options()
    if not options:
        st.warning("找不到可紀錄的來源包。請先產生公開 AI 上傳包或私人 Codex 分析包。")
    else:
        selected_label = st.selectbox("選擇來源包", [path_label(path) for path in options], key="analysis_run_source")
        source_path = options[[path_label(path) for path in options].index(selected_label)]
        try:
            source_info = list_public_bundle_inputs(source_path) if scope == "public_bundle" else list_private_export_inputs(source_path)
        except Exception as exc:
            source_info = None
            st.error(f"讀取來源包失敗：{exc}")

        if source_info:
            st.markdown("**來源摘要**")
            c1, c2, c3 = st.columns(3)
            c1.metric("案件數", source_info.get("case_count", 0))
            c2.metric("來源檔案", len(source_info.get("source_files", [])))
            c3.metric("來源類型", scope)
            st.caption(f"來源路徑：{source_info.get('source_path', '')}")
            source_df = pd.DataFrame(source_info.get("source_files", []))
            if not source_df.empty:
                show_cols = [col for col in ["role", "filename", "size_bytes", "sha256", "path"] if col in source_df.columns]
                st.dataframe(source_df[show_cols], width="stretch", hide_index=True)

            provider_label = st.selectbox("AI 工具", ["chatgpt", "gemini", "codex", "other"], key="analysis_provider")
            model_name = st.text_input("模型名稱", placeholder="例如：GPT-4.1、Gemini 2.5 Pro、Codex", key="analysis_model")
            prompt_text = st.text_area("實際使用的 prompt", value=str(source_info.get("default_prompt", "")), height=260)
            ai_response_text = st.text_area("AI 原始回覆", height=360, placeholder="將 ChatGPT / Gemini / Codex 的完整回覆貼在這裡")
            notes_text = st.text_area("人工備註 / 覆核筆記", height=140, placeholder="可記錄模型設定、人工校對狀況或待修正事項")
            disabled = not ai_response_text.strip()
            if st.button("保存 AI 分析紀錄", type="primary", disabled=disabled):
                try:
                    result = create_analysis_run(
                        source_path,
                        scope=scope,
                        provider=provider_label,
                        model_name=model_name,
                        prompt_text=prompt_text,
                        ai_response_text=ai_response_text,
                        notes_text=notes_text,
                    )
                    st.success(f"已保存分析紀錄：{result.run_id}")
                    st.code(str(result.run_dir))
                except Exception as exc:
                    st.error(f"保存失敗：{exc}")

    st.markdown("**既有分析紀錄**")
    runs = list_analysis_runs()
    if runs:
        run_df = pd.DataFrame(
            [
                {
                    "run_id": run.get("run_id", ""),
                    "scope": run.get("scope", ""),
                    "provider": run.get("provider", ""),
                    "model_name": run.get("model_name", ""),
                    "analysis_time": run.get("analysis_time", ""),
                    "case_count": run.get("case_count", ""),
                    "run_dir": run.get("run_dir", ""),
                }
                for run in runs
            ]
        )
        st.dataframe(run_df, width="stretch", hide_index=True)
        st.caption(f"分析紀錄根目錄：{ANALYSIS_RUNS_DIR}")
    else:
        st.info("尚無分析紀錄。")

with tabs[11]:
    st.subheader("批次儀表板")
    st.caption("以本機 AJAX 狀態服務動態監控 ChatGPT/Gemini 批次分析；不會整頁刷新停頓。")

    if CLOUD_PUBLIC_MODE:
        st.info("雲端公開版停用 ChatGPT/Gemini 瀏覽器批次與本機 AJAX 儀表板。請在本機版執行批次，或在雲端下載 AI 上傳包後手動分析。")
        batches = []
    else:
        batches = web_ai_batch_options()
    if not batches:
        st.warning("目前沒有網頁 AI 批次。請先到「公開 AI 分析包」啟動批次。")
    else:
        st.markdown('<div class="layout-kicker">ACTION BAR</div><div class="action-bar-note">批次選擇、服務檢查與續跑控制</div>', unsafe_allow_html=True)
        with st.container(border=True):
            top1, top2 = st.columns([2, 1])
            batch_label = top1.selectbox("監控批次", [path_label(path) for path in batches], key="dashboard_batch")
            dashboard_batch = batches[[path_label(path) for path in batches].index(batch_label)]
            server_ok, server_url = ensure_batch_status_server()
            if top2.button("啟動/檢查儀表板服務", width="stretch"):
                server_ok, server_url = ensure_batch_status_server()
                if server_ok:
                    st.success("本機狀態服務已就緒。")
                else:
                    st.error(server_url)

            summary, _status_df = web_ai_batch_status(dashboard_batch, refresh=True)
            retry_targets = select_retry_cids(dashboard_batch, ["pending", "paused", "failed", "stale"])
            failed_stale_targets = select_retry_cids(dashboard_batch, ["failed", "stale"])
            auto_continue_targets = select_retry_cids(dashboard_batch, ["pending", "failed", "stale"])
            actions1, actions2, actions3 = st.columns([1, 1, 2])
            if actions1.button("重跑失敗/停滯", disabled=not failed_stale_targets, width="stretch"):
                try:
                    stamp = time.strftime("%Y%m%d_%H%M%S")
                    stdout_path = dashboard_batch / "logs" / f"dashboard_retry_failed_stale_{stamp}_stdout.log"
                    stderr_path = dashboard_batch / "logs" / f"dashboard_retry_failed_stale_{stamp}_stderr.log"
                    args = [
                        sys.executable,
                        "scripts/run_web_ai_batch.py",
                        "--resume-batch",
                        str(dashboard_batch),
                        "--statuses",
                        "failed,stale",
                        "--sleep",
                        "3",
                    ]
                    pid = start_background_command(args, stdout_path, stderr_path)
                    (dashboard_batch / "process.json").write_text(
                        json.dumps({"pid": pid, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "args": args}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    st.success(f"已啟動續跑，PID={pid}")
                except Exception as exc:
                    st.error(f"續跑啟動失敗：{exc}")
            if actions2.button("接續跑到完成", disabled=not auto_continue_targets, width="stretch"):
                try:
                    stamp = time.strftime("%Y%m%d_%H%M%S")
                    stdout_path = dashboard_batch / "logs" / f"dashboard_continue_{stamp}_stdout.log"
                    stderr_path = dashboard_batch / "logs" / f"dashboard_continue_{stamp}_stderr.log"
                    args = [
                        sys.executable,
                        "scripts/run_web_ai_batch.py",
                        "--continue-batch",
                        str(dashboard_batch),
                        "--statuses",
                        "pending,failed,stale",
                        "--max-rounds",
                        "5",
                        "--max-attempts",
                        "3",
                        "--sleep",
                        "3",
                    ]
                    pid = start_background_command(args, stdout_path, stderr_path)
                    (dashboard_batch / "process.json").write_text(
                        json.dumps({"pid": pid, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "args": args}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    st.success(f"已啟動接續跑，PID={pid}")
                    st.info("此模式不自動處理 paused；達到 3 次仍失敗者會保留給人工檢核。")
                except Exception as exc:
                    st.error(f"接續跑啟動失敗：{exc}")
            actions3.code(f"python scripts/run_web_ai_batch.py --continue-batch \"{dashboard_batch}\" --statuses pending,failed,stale --max-rounds 5 --max-attempts 3 --sleep 3")
        st.markdown('<div class="content-panel-note">內容區：AJAX 動態儀表板</div>', unsafe_allow_html=True)
        if server_ok:
            dashboard_url = f"{server_url}/dashboard?batch={quote(dashboard_batch.name)}"
            st.link_button("在新視窗開啟動態儀表板", dashboard_url, width="stretch")
            components.iframe(dashboard_url, height=980, scrolling=True)
        else:
            st.error(f"本機 AJAX 狀態服務尚未就緒：{server_url}")
            st.info("可按上方「啟動/檢查儀表板服務」重試。")
        st.caption(f"批次目錄：{dashboard_batch}")

with tabs[12]:
    st.subheader("公開資料更新")
    st.caption("檢查教育部公開查詢頁是否有新增評議書，只下載新增案件並更新本機 SQLite/FTS；不會自動送 ChatGPT/Gemini。")

    st.markdown('<div class="layout-kicker">ACTION BAR</div><div class="action-bar-note">更新參數與啟動</div>', unsafe_allow_html=True)
    with st.container(border=True):
        u1, u2, u3, u4 = st.columns([1, 1, 1, 1])
        update_sleep = u1.number_input("請求間隔秒數", min_value=0.5, max_value=10.0, value=1.5, step=0.5, key="public_update_sleep")
        update_limit = u2.number_input("下載上限", min_value=0, max_value=200, value=0, step=1, help="0 表示不限制；測試可填 3 或 5。", key="public_update_limit")
        update_retry_failed = u3.checkbox("重試失敗 cid", value=False, key="public_update_retry_failed")
        update_no_build_db = u4.checkbox("不重建資料庫", value=False, key="public_update_no_build")

        if CLOUD_PUBLIC_MODE:
            st.info("雲端公開版請使用 GitHub Actions 排程更新；Streamlit Cloud runtime 不直接提交資料變更。")
        if st.button("啟動公開資料更新", type="primary", disabled=CLOUD_PUBLIC_MODE):
            try:
                UPDATE_RUNS_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                stdout_path = UPDATE_RUNS_DIR / f"streamlit_update_{stamp}_stdout.log"
                stderr_path = UPDATE_RUNS_DIR / f"streamlit_update_{stamp}_stderr.log"
                args = [
                    sys.executable,
                    "scripts/update_public_cases.py",
                    "--sleep",
                    str(float(update_sleep)),
                ]
                if int(update_limit):
                    args.extend(["--limit", str(int(update_limit))])
                if update_retry_failed:
                    args.append("--retry-failed")
                if update_no_build_db:
                    args.append("--no-build-db")
                pid = start_background_command(args, stdout_path, stderr_path)
                st.success(f"已啟動背景更新，PID={pid}")
                st.code(" ".join(args))
                st.caption(f"背景 stdout：{stdout_path}")
                st.caption(f"背景 stderr：{stderr_path}")
            except Exception as exc:
                st.error(f"啟動更新失敗：{exc}")

        st.markdown("**Windows 工作排程指令**")
        python_exe = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
        if not python_exe.exists():
            python_exe = Path(sys.executable)
        schedule_cmd = (
            f'schtasks /Create /TN "TeacherAppealPublicUpdate" /SC DAILY /ST 03:00 '
            f'/TR "\\"{python_exe}\\" \\"{ROOT_DIR / "scripts" / "update_public_cases.py"}\\" --sleep 1.5"'
        )
        st.code(schedule_cmd, language="powershell")

    st.markdown('<div class="content-panel-note">內容區：更新紀錄與待分析清單</div>', unsafe_allow_html=True)
    runs = update_run_options()
    if not runs:
        st.info("尚無更新紀錄。")
    else:
        latest = runs[0]
        latest_manifest = read_json_file(latest / "update_manifest.json")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("狀態", str(latest_manifest.get("status", "")))
        m2.metric("發現", int(latest_manifest.get("discovered_count", 0) or 0))
        m3.metric("新增", int(latest_manifest.get("new_count", 0) or 0))
        m4.metric("下載", int(latest_manifest.get("downloaded_count", 0) or 0))
        m5.metric("失敗", int(latest_manifest.get("failed_count", 0) or 0))
        m6.metric("AI 待分析", int(latest_manifest.get("ai_pending_count", 0) or 0))

        selected_update_label = st.selectbox("更新紀錄", [path_label(path) for path in runs], key="public_update_run")
        selected_update = runs[[path_label(path) for path in runs].index(selected_update_label)]
        manifest = read_json_file(selected_update / "update_manifest.json")
        st.json(manifest, expanded=False)

        cids_cols = st.columns(4)
        file_map = [
            ("新增 cid", selected_update / "new_cids.txt"),
            ("下載成功", selected_update / "downloaded_cids.txt"),
            ("下載失敗", selected_update / "failed_cids.txt"),
            ("AI 待分析", selected_update / "ai_pending_cids.txt"),
        ]
        for col, (label, path) in zip(cids_cols, file_map):
            values = read_lines(path)
            col.metric(label, len(values))
            if values:
                col.download_button(
                    f"下載 {label}",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime="text/plain",
                    key=f"download_{selected_update.name}_{path.name}",
                )

        pending_cids = read_lines(selected_update / "ai_pending_cids.txt")
        if pending_cids:
            st.markdown("**AI 待分析 cid**")
            st.text_area("本次新增且下載成功，尚待你確認後送 AI 分析", value="\n".join(pending_cids), height=140)
            b1, b2 = st.columns([1, 2])
            if b1.button("建立待分析批次清單", width="stretch"):
                try:
                    batch_dir = create_batch_dir("chatgpt")
                    write_batch_manifest(batch_dir, "chatgpt", "", pending_cids, 3.0)
                    st.success(f"已建立待分析批次清單：{batch_dir}")
                    st.info("這只建立批次清單，不會自動送出到 ChatGPT。確認後可到「批次儀表板」或「公開 AI 分析包」續跑。")
                except Exception as exc:
                    st.error(f"建立批次清單失敗：{exc}")
            b2.code(f"python scripts/run_web_ai_batch.py --provider chatgpt --cid-file \"{selected_update / 'ai_pending_cids.txt'}\" --sleep 3 --model-name GPT")

        stdout_text = (selected_update / "stdout.log").read_text(encoding="utf-8", errors="replace") if (selected_update / "stdout.log").exists() else ""
        stderr_text = (selected_update / "stderr.log").read_text(encoding="utf-8", errors="replace") if (selected_update / "stderr.log").exists() else ""
        with st.expander("更新 log", expanded=False):
            st.text_area("stdout.log", value=stdout_text[-8000:], height=220)
            st.text_area("stderr.log", value=stderr_text[-8000:], height=180)
