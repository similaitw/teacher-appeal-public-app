"use client";

import Link from "next/link";
import { ArrowLeft, ExternalLink, FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { AuthMenu } from "../../auth-menu";
import type { CaseRecord, PublicAnalysisIndex, PublicAnalysisIndexItem } from "../../../lib/types";

type CaseState =
  | { status: "loading"; cid: string }
  | { status: "ready"; record: CaseRecord; analysisRuns: PublicAnalysisIndexItem[] }
  | { status: "missing"; cid: string };

export default function CaseClient({ cid }: { cid: string }) {
  const [state, setState] = useState<CaseState>({ status: "loading", cid });

  useEffect(() => {
    async function loadCase() {
      setState({ status: "loading", cid });
      try {
        const [caseResponse, analysisResponse] = await Promise.all([
          fetch(`/data/cases/${cid}.json`),
          fetch("/data/analysis/index.json"),
        ]);
        if (!caseResponse.ok) {
          setState({ status: "missing", cid });
          return;
        }
        const record = (await caseResponse.json()) as CaseRecord;
        const analysisIndex = analysisResponse.ok ? ((await analysisResponse.json()) as PublicAnalysisIndex) : null;
        const analysisRuns = (analysisIndex?.runs || [])
          .filter((run) => run.caseIds.includes(cid))
          .sort((a, b) => String(b.analysisTime).localeCompare(String(a.analysisTime)));
        setState({ status: "ready", record, analysisRuns });
      } catch {
        setState({ status: "missing", cid });
      }
    }
    loadCase();
  }, [cid]);

  if (state.status === "loading") {
    return <div className="loading">載入 cid {state.cid} 中...</div>;
  }

  if (state.status === "missing") {
    return (
      <main className="container">
        <div className="empty">找不到 cid {state.cid} 的公開案件資料。</div>
        <p>
          <Link className="button secondary" href="/">
            <ArrowLeft size={17} aria-hidden="true" />
            回查詢頁
          </Link>
        </p>
      </main>
    );
  }

  const { record, analysisRuns } = state;
  const primaryAnalysis = analysisRuns[0];

  return (
    <main className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <div>
              <div className="brand-title">教師申訴評議書公開查詢</div>
              <div className="brand-subtitle">cid {record.cid}</div>
            </div>
          </div>
          <div className="topbar-actions">
            <AuthMenu />
            <Link className="button secondary" href="/">
              <ArrowLeft size={17} aria-hidden="true" />
              回查詢頁
            </Link>
          </div>
        </div>
      </header>

      <article className="container">
        <div className="reader-header">
          <div className="case-meta">
            <span className="tag">{record.result}</span>
            <span className="tag gold">{record.issueType}</span>
            <span>{record.dateText || record.year}</span>
          </div>
          <h1 className="reader-title">{record.title}</h1>
          <div className="reader-actions">
            {record.url ? (
              <a className="button" href={record.url} target="_blank" rel="noreferrer">
                <ExternalLink size={17} aria-hidden="true" />
                原始頁面
              </a>
            ) : null}
            {primaryAnalysis ? (
              <Link className="button secondary" href={`/analysis?run=${encodeURIComponent(primaryAnalysis.runId)}`}>
                <FileText size={17} aria-hidden="true" />
                查看 AI 分析
              </Link>
            ) : null}
          </div>
        </div>

        {analysisRuns.length ? (
          <section className="reader-card related-analysis-card" aria-label="相關 AI 分析">
            <div>
              <h2 className="panel-title">相關 AI 分析</h2>
              <p className="muted">此公開案件已有 {analysisRuns.length} 筆已保存分析結果。</p>
            </div>
            <div className="related-analysis-list">
              {analysisRuns.slice(0, 5).map((run) => (
                <Link className="related-analysis-link" href={`/analysis?run=${encodeURIComponent(run.runId)}`} key={run.runId}>
                  <span>{run.runId}</span>
                  <span>{run.provider || "AI"} · {run.modelName || "未記錄模型"}</span>
                </Link>
              ))}
            </div>
          </section>
        ) : null}

        <section className="reader-card">
          <div className="source-grid" aria-label="案件資訊">
            <div className="source-item">
              <div className="source-label">文號</div>
              <div className="source-value">{record.docNo || "未標示"}</div>
            </div>
            <div className="source-item">
              <div className="source-label">案件類型</div>
              <div className="source-value">{record.caseType || "未標示"}</div>
            </div>
            <div className="source-item">
              <div className="source-label">資料來源</div>
              <div className="source-value">{record.sourcePaths.text || "data/cases.csv"}</div>
            </div>
          </div>
          <div className="document-text">{record.fullText}</div>
        </section>
      </article>
    </main>
  );
}
