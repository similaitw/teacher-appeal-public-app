from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from analysis_runs import ANALYSIS_RUNS_DIR  # noqa: E402
from utils import get_case_by_cid  # noqa: E402
from web_ai_batch import WEB_AI_BATCHES_DIR, refresh_batch_status, select_auto_continue_cids, select_retry_cids  # noqa: E402


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def error_response(handler: BaseHTTPRequestHandler, message: str, status: int = 400) -> None:
    json_response(handler, {"ok": False, "error": message}, status=status)


def batch_dirs() -> list[Path]:
    if not WEB_AI_BATCHES_DIR.exists():
        return []
    return sorted([path for path in WEB_AI_BATCHES_DIR.iterdir() if path.is_dir()], key=lambda path: path.stat().st_mtime, reverse=True)


def safe_batch_dir(batch_name: str | None) -> Path:
    raw_name = unquote(batch_name or "")
    name = Path(raw_name).name
    if raw_name and raw_name != name:
        raise FileNotFoundError(f"不合法的批次名稱：{raw_name}")
    if not name:
        batches = batch_dirs()
        if not batches:
            raise FileNotFoundError("目前沒有批次資料夾")
        return batches[0]
    path = (WEB_AI_BATCHES_DIR / name).resolve()
    root = WEB_AI_BATCHES_DIR.resolve()
    if root not in path.parents or not path.is_dir():
        raise FileNotFoundError(f"找不到批次：{name}")
    return path


def file_url(path: Path) -> str:
    return path.resolve().as_uri() if path.exists() else ""


def status_payload(batch_dir: Path, include_rows: bool = True) -> dict:
    summary, rows = refresh_batch_status(batch_dir)
    enriched_rows: list[dict[str, str]] = []
    for row in rows:
        item = dict(row)
        cid = str(item.get("cid") or "")
        case = get_case_by_cid(cid) if cid else None
        item["title"] = str(case.get("title", "")) if case else ""
        run_id = str(item.get("run_id") or "").strip()
        item["ai_response_url"] = file_url(ANALYSIS_RUNS_DIR / run_id / "ai_response.md") if run_id else ""
        item["citation_review_url"] = file_url(ANALYSIS_RUNS_DIR / run_id / "citation_review.md") if run_id else ""
        item["analysis_dir_url"] = file_url(ANALYSIS_RUNS_DIR / run_id) if run_id else ""
        enriched_rows.append(item)
    retry_cids = select_retry_cids(batch_dir, ["pending", "paused", "failed", "stale"])
    auto_continue_cids = select_auto_continue_cids(batch_dir, ["pending", "failed", "stale"], max_attempts=3)
    manual_review_cids = [
        row["cid"]
        for row in enriched_rows
        if row.get("status") == "paused" or (row.get("status") in {"pending", "failed", "stale"} and int(row.get("attempts") or 0) >= 3)
    ]
    return {
        "ok": True,
        "batch": batch_dir.name,
        "batch_path": str(batch_dir),
        "summary": summary,
        "retry_count": len(retry_cids),
        "auto_continue_count": len(auto_continue_cids),
        "manual_review_count": len(manual_review_cids),
        "rows": enriched_rows if include_rows else [],
    }


def dashboard_html(batch_name: str) -> str:
    batch_query = quote(batch_name)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>批次 AI 分析儀表板</title>
  <style>
    :root {{
      --bg: #f6f4ee;
      --panel: #fffdf8;
      --ink: #1f2933;
      --muted: #66737f;
      --line: #d8d3c8;
      --deep: #18232d;
      --done: #16a34a;
      --running: #0284c7;
      --pending: #d97706;
      --paused: #be123c;
      --failed: #dc2626;
      --stale: #7c3aed;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    .wrap {{ padding: 14px; }}
    .hero {{
      background: var(--deep);
      color: #fffdf8;
      border-radius: 10px;
      padding: 16px;
      box-shadow: 0 14px 32px rgba(24,35,45,.16);
    }}
    .hero-top {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    h1 {{ margin: 0; font-size: clamp(20px, 3vw, 30px); letter-spacing: 0; }}
    .meta {{ color: rgba(255,253,248,.72); font-size: 13px; margin-top: 4px; }}
    .badge {{
      border: 1px solid rgba(255,253,248,.25);
      border-radius: 999px;
      padding: 7px 11px;
      background: rgba(255,253,248,.08);
      white-space: nowrap;
    }}
    .pulse {{
      display: inline-block;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #22c55e;
      box-shadow: 0 0 0 rgba(34,197,94,.45);
      animation: pulse 1.7s infinite;
      margin-right: 6px;
    }}
    @keyframes pulse {{
      0% {{ box-shadow: 0 0 0 0 rgba(34,197,94,.45); }}
      70% {{ box-shadow: 0 0 0 10px rgba(34,197,94,0); }}
      100% {{ box-shadow: 0 0 0 0 rgba(34,197,94,0); }}
    }}
    .bar {{
      height: 20px;
      border-radius: 999px;
      overflow: hidden;
      display: flex;
      background: rgba(255,253,248,.13);
      border: 1px solid rgba(255,253,248,.18);
    }}
    .seg {{ height: 100%; min-width: 0; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}
    .stat {{
      background: rgba(255,253,248,.08);
      border: 1px solid rgba(255,253,248,.12);
      border-radius: 8px;
      padding: 10px;
      min-height: 78px;
    }}
    .stat small {{ display:block; color: rgba(255,253,248,.72); }}
    .stat strong {{ display:block; color:#fffdf8; font-size: 24px; margin-top: 3px; }}
    .controls, .cards {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }}
    .card, .table-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 9px;
      padding: 12px;
    }}
    .card small {{ color: var(--muted); display:block; margin-bottom: 4px; }}
    .card strong {{ word-break: break-word; }}
    .toolbar {{
      display: grid;
      grid-template-columns: 150px 1fr 1fr;
      gap: 8px;
      margin: 12px 0;
    }}
    select, input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 9px 10px;
      background: #fffdf8;
      color: var(--ink);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      text-align: left;
      padding: 8px 7px;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 700; background: #faf8f2; position: sticky; top: 0; }}
    .status {{
      display:inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      color: white;
      font-size: 12px;
      min-width: 68px;
      text-align: center;
    }}
    .links a {{ margin-right: 8px; color: #0f766e; font-weight: 700; text-decoration: none; }}
    .error {{ color: #9f1239; max-width: 420px; }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 860px) {{
      .stats, .controls, .cards, .toolbar {{ grid-template-columns: 1fr; }}
      .wrap {{ padding: 10px; }}
      table {{ min-width: 860px; }}
      .table-scroll {{ overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="hero-top">
        <div>
          <h1>批次 AI 分析儀表板</h1>
          <div class="meta" id="meta">讀取中...</div>
        </div>
        <div class="badge" id="badge">同步中</div>
      </div>
      <div class="bar" id="bar"></div>
      <div class="meta" id="progressText"></div>
      <div class="stats" id="stats"></div>
    </section>
    <section class="controls">
      <div class="card"><small>更新狀態</small><strong id="updated">-</strong></div>
      <div class="card"><small>可接續自動跑</small><strong id="autoContinue">-</strong></div>
      <div class="card"><small>需人工檢核</small><strong id="manualReview">-</strong></div>
      <div class="card"><small>資料來源</small><strong id="path">-</strong></div>
    </section>
    <section class="cards">
      <div class="card"><small>目前處理</small><strong id="current">-</strong></div>
      <div class="card"><small>最後完成</small><strong id="lastDone">-</strong></div>
      <div class="card"><small>下一筆待跑</small><strong id="nextPending">-</strong></div>
    </section>
    <section class="table-card" style="margin-top:12px;">
      <div class="toolbar">
        <select id="statusFilter">
          <option value="">全部狀態</option>
          <option value="done">完成</option>
          <option value="running">執行中</option>
          <option value="pending">待跑</option>
          <option value="paused">暫停</option>
          <option value="failed">失敗</option>
          <option value="stale">停滯</option>
        </select>
        <input id="cidFilter" placeholder="篩選 cid">
        <input id="textFilter" placeholder="篩選標題、錯誤、run_id">
      </div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>cid</th><th>標題</th><th>狀態</th><th>次數</th><th>run_id</th><th>連結</th><th>開始</th><th>完成</th><th>錯誤</th>
            </tr>
          </thead>
          <tbody id="rows"><tr><td colspan="9">讀取中...</td></tr></tbody>
        </table>
      </div>
    </section>
  </div>
  <script>
    const batch = "{batch_query}";
    const labels = {{done:"完成", running:"執行中", pending:"待跑", paused:"暫停", failed:"失敗", stale:"停滯"}};
    const colors = {{done:"#16a34a", running:"#0284c7", pending:"#d97706", paused:"#be123c", failed:"#dc2626", stale:"#7c3aed"}};
    let latestRows = [];
    function esc(value) {{
      return String(value ?? "").replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
    }}
    function statusBadge(status) {{
      return `<span class="status" style="background:${{colors[status] || "#64748b"}}">${{esc(labels[status] || status || "-")}}</span>`;
    }}
    function first(rows, status) {{ return rows.find(row => row.status === status) || {{}}; }}
    function last(rows, status) {{ const found = rows.filter(row => row.status === status); return found[found.length - 1] || {{}}; }}
    function badge(summary) {{
      if ((summary.running || 0) > 0) return '<span class="pulse"></span>執行中';
      if ((summary.paused || 0) > 0) return '需要人工處理';
      if ((summary.failed || 0) > 0 || (summary.stale || 0) > 0) return '需要重跑或覆核';
      if ((summary.pending || 0) > 0) return '等待續跑';
      return '全部完成';
    }}
    function renderRows() {{
      const statusFilter = document.getElementById("statusFilter").value;
      const cidFilter = document.getElementById("cidFilter").value.trim().toLowerCase();
      const textFilter = document.getElementById("textFilter").value.trim().toLowerCase();
      const rows = latestRows.filter(row => {{
        if (statusFilter && row.status !== statusFilter) return false;
        if (cidFilter && !String(row.cid || "").toLowerCase().includes(cidFilter)) return false;
        const hay = `${{row.title || ""}} ${{row.error || ""}} ${{row.run_id || ""}}`.toLowerCase();
        return !textFilter || hay.includes(textFilter);
      }});
      document.getElementById("rows").innerHTML = rows.map(row => {{
        const links = [
          row.ai_response_url ? `<a href="${{row.ai_response_url}}" target="_blank">回覆</a>` : "",
          row.citation_review_url ? `<a href="${{row.citation_review_url}}" target="_blank">覆核</a>` : "",
          row.analysis_dir_url ? `<a href="${{row.analysis_dir_url}}" target="_blank">資料夾</a>` : ""
        ].join("");
        return `<tr>
          <td><strong>${{esc(row.cid)}}</strong></td>
          <td>${{esc(row.title)}}</td>
          <td>${{statusBadge(row.status)}}</td>
          <td>${{esc(row.attempts)}}</td>
          <td>${{esc(row.run_id)}}</td>
          <td class="links">${{links}}</td>
          <td>${{esc(row.started_at)}}</td>
          <td>${{esc(row.finished_at)}}</td>
          <td class="error">${{esc(row.error)}}</td>
        </tr>`;
      }}).join("") || '<tr><td colspan="9">沒有符合篩選的案件</td></tr>';
    }}
    async function load() {{
      try {{
        const response = await fetch(`/api/batch?batch=${{batch}}`, {{cache:"no-store"}});
        const data = await response.json();
        if (!data.ok) throw new Error(data.error || "讀取失敗");
        const summary = data.summary;
        latestRows = data.rows || [];
        const total = Math.max(Number(summary.planned_total || 0), 1);
        const done = Number(summary.done || 0);
        document.getElementById("meta").textContent = `${{data.batch}}｜${{summary.provider || ""}}｜${{summary.model_name || ""}}`;
        document.getElementById("badge").innerHTML = badge(summary);
        document.getElementById("progressText").textContent = `完成 ${{done}} / ${{total}}，完成率 ${{((done / total) * 100).toFixed(1)}}%`;
        document.getElementById("bar").innerHTML = ["done","running","pending","paused","failed","stale"].map(status => {{
          const count = Number(summary[status] || 0);
          return count ? `<div class="seg" style="width:${{(count / total) * 100}}%; background:${{colors[status]}}"></div>` : "";
        }}).join("") || '<div class="seg" style="width:100%; background:rgba(255,253,248,.18)"></div>';
        document.getElementById("stats").innerHTML = ["done","running","pending","paused","failed","stale"].map(status => {{
          const count = Number(summary[status] || 0);
          return `<div class="stat"><small style="color:${{colors[status]}}">${{labels[status]}}</small><strong>${{count}}</strong><small>${{((count / total) * 100).toFixed(1)}}%</small></div>`;
        }}).join("");
        document.getElementById("updated").textContent = summary.last_refreshed || "-";
        document.getElementById("autoContinue").textContent = `${{data.auto_continue_count || 0}} 件`;
        document.getElementById("manualReview").textContent = `${{data.manual_review_count || 0}} 件`;
        document.getElementById("path").textContent = data.batch_path || "-";
        const current = first(latestRows, "running");
        const lastDone = last(latestRows, "done");
        const nextPending = first(latestRows, "pending");
        document.getElementById("current").textContent = current.cid ? `${{current.cid}}｜${{current.started_at || ""}}` : "無執行中案件";
        document.getElementById("lastDone").textContent = lastDone.cid ? `${{lastDone.cid}}｜${{lastDone.finished_at || ""}}` : "尚無完成";
        document.getElementById("nextPending").textContent = nextPending.cid || "無待跑案件";
        renderRows();
      }} catch (error) {{
        document.getElementById("badge").textContent = "讀取失敗";
        document.getElementById("rows").innerHTML = `<tr><td colspan="9">${{esc(error.message)}}</td></tr>`;
      }}
    }}
    ["statusFilter","cidFilter","textFilter"].forEach(id => document.getElementById(id).addEventListener("input", renderRows));
    load();
    setInterval(load, 5000);
  </script>
</body>
</html>"""


class BatchStatusHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/batches":
                json_response(self, {"ok": True, "batches": [path.name for path in batch_dirs()]})
                return
            if parsed.path == "/api/batch":
                batch_dir = safe_batch_dir(params.get("batch", [""])[0])
                json_response(self, status_payload(batch_dir))
                return
            if parsed.path == "/dashboard":
                batch_dir = safe_batch_dir(params.get("batch", [""])[0])
                html_response(self, dashboard_html(batch_dir.name))
                return
            if parsed.path in {"/", ""}:
                batch_dir = safe_batch_dir("")
                self.send_response(302)
                self.send_header("Location", f"/dashboard?batch={quote(batch_dir.name)}")
                self.end_headers()
                return
            error_response(self, "not found", status=404)
        except Exception as exc:
            error_response(self, str(exc), status=500)

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), BatchStatusHandler)
    print(f"batch status server: http://{host}:{port}/", flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="本機批次 AI 分析 AJAX 狀態儀表板")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
