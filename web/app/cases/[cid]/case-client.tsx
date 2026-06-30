"use client";

import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";
import { AuthMenu } from "../../auth-menu";
import type { CaseRecord } from "../../../lib/types";

type CaseState =
  | { status: "loading"; cid: string }
  | { status: "ready"; record: CaseRecord }
  | { status: "missing"; cid: string };

export default function CaseClient({ cid }: { cid: string }) {
  const [state, setState] = useState<CaseState>({ status: "loading", cid });

  useEffect(() => {
    async function loadCase() {
      setState({ status: "loading", cid });
      try {
        const response = await fetch(`/data/cases/${cid}.json`);
        if (!response.ok) {
          setState({ status: "missing", cid });
          return;
        }
        const record = (await response.json()) as CaseRecord;
        setState({ status: "ready", record });
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

  const { record } = state;

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
          </div>
        </div>

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
