"use client";

import Link from "next/link";
import { ArrowLeft, BookOpenText, FileText, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AuthMenu } from "../auth-menu";
import type { PublicAnalysisIndex, PublicAnalysisRun } from "../../lib/types";

type AnalysisState =
  | { status: "loading" }
  | { status: "ready"; index: PublicAnalysisIndex; selectedRun: PublicAnalysisRun | null }
  | { status: "error"; message: string };

function formatDate(value: string) {
  if (!value) return "未記錄";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-TW");
}

function selectedRunIdFromLocation() {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("run") || "";
}

export default function AnalysisPage() {
  const [state, setState] = useState<AnalysisState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");

  useEffect(() => {
    async function loadIndex() {
      try {
        const response = await fetch("/data/analysis/index.json");
        if (!response.ok) throw new Error("公開 AI 分析索引載入失敗");
        const index = (await response.json()) as PublicAnalysisIndex;
        const initialRunId = selectedRunIdFromLocation() || index.runs[0]?.runId || "";
        setSelectedRunId(initialRunId);
        setState({ status: "ready", index, selectedRun: null });
      } catch (error) {
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "公開 AI 分析索引載入失敗",
        });
      }
    }
    loadIndex();
  }, []);

  useEffect(() => {
    if (state.status !== "ready" || !selectedRunId) return;

    const index = state.index;
    let cancelled = false;
    async function loadRun() {
      const item = index.runs.find((run) => run.runId === selectedRunId);
      if (!item) return;
      const response = await fetch(item.dataPath);
      if (!response.ok) return;
      const selectedRun = (await response.json()) as PublicAnalysisRun;
      if (!cancelled) {
        setState((current) => (current.status === "ready" ? { ...current, selectedRun } : current));
        window.history.replaceState(null, "", `/analysis?run=${encodeURIComponent(selectedRun.runId)}`);
      }
    }
    loadRun();
    return () => {
      cancelled = true;
    };
  }, [selectedRunId, state.status, state.status === "ready" ? state.index : null]);

  const filteredRuns = useMemo(() => {
    if (state.status !== "ready") return [];
    const needle = query.trim().toLocaleLowerCase("zh-Hant");
    if (!needle) return state.index.runs;
    return state.index.runs.filter((run) => {
      const haystack = [
        run.runId,
        run.provider,
        run.modelName,
        run.caseIds.join(" "),
        run.cases.map((item) => item.title).join(" "),
        run.excerpt,
      ]
        .join(" ")
        .toLocaleLowerCase("zh-Hant");
      return haystack.includes(needle);
    });
  }, [query, state]);

  const selectedRun =
    state.status === "ready" && state.selectedRun?.runId === selectedRunId ? state.selectedRun : null;
  const selectedIndexItem =
    state.status === "ready" ? state.index.runs.find((run) => run.runId === selectedRunId) : undefined;

  if (state.status === "loading") {
    return <div className="loading">載入公開 AI 分析結果中...</div>;
  }

  if (state.status === "error") {
    return <div className="loading">{state.message}</div>;
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <Link className="brand" href="/">
            <div className="brand-mark" aria-hidden="true">
              <BookOpenText size={21} />
            </div>
            <div>
              <div className="brand-title">公開 AI 分析結果</div>
              <div className="brand-subtitle">只顯示公開評議書 bundle 的已保存分析</div>
            </div>
          </Link>
          <div className="topbar-actions">
            <Link className="button secondary" href="/">
              <ArrowLeft size={17} aria-hidden="true" />
              回查詢
            </Link>
            <AuthMenu />
          </div>
        </div>
      </header>

      <div className="container">
        <section className="workspace-band analysis-summary" aria-label="公開 AI 分析摘要">
          <div className="workspace-head">
            <div>
              <div className="section-kicker">PUBLIC AI RESULTS</div>
              <h1 className="workspace-title">公開 AI 分析結果</h1>
            </div>
            <div className="workspace-role">共 {state.index.runCount} 筆</div>
          </div>
          <div className="local-note">
            <ShieldCheck size={18} aria-hidden="true" />
            此頁只匯出公開案件分析結果；私人案件、原始本機路徑、分析執行工具與 API/瀏覽器自動化仍保留在本機。
          </div>
        </section>

        <section className="analysis-layout">
          <aside className="analysis-list-panel" aria-label="公開分析清單">
            <label className="field analysis-search">
              <FileText size={18} aria-hidden="true" />
              <input
                className="input with-icon"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜尋 run、案號或摘要"
                aria-label="搜尋公開 AI 分析結果"
              />
            </label>

            <div className="analysis-list">
              {filteredRuns.map((run) => (
                <button
                  className={`analysis-list-item${run.runId === selectedRunId ? " active" : ""}`}
                  key={run.runId}
                  type="button"
                  onClick={() => setSelectedRunId(run.runId)}
                >
                  <span className="analysis-item-meta">
                    {formatDate(run.analysisTime)} · {run.provider || "AI"}
                  </span>
                  <span className="analysis-item-title">{run.cases.map((item) => item.cid).join("、")}</span>
                  <span className="analysis-item-excerpt">{run.excerpt || "尚無摘要"}</span>
                </button>
              ))}
            </div>
          </aside>

          <section className="analysis-reader" aria-label="公開 AI 分析內容">
            {selectedIndexItem ? (
              <>
                <div className="reader-card analysis-meta-card">
                  <div className="case-meta">
                    <span className="tag">{selectedIndexItem.provider || "AI"}</span>
                    <span className="tag gold">{selectedIndexItem.modelName || "未記錄模型"}</span>
                    <span>{formatDate(selectedIndexItem.analysisTime)}</span>
                    <span>{selectedIndexItem.caseCount} 案</span>
                  </div>
                  <h2 className="case-title">{selectedIndexItem.runId}</h2>
                  <div className="analysis-case-links">
                    {selectedIndexItem.cases.map((item) => (
                      <Link className="chip" href={item.href} key={item.cid}>
                        {item.cid}
                      </Link>
                    ))}
                  </div>
                </div>

                <article className="reader-card analysis-response">
                  <h2 className="panel-title">AI 回覆</h2>
                  {selectedRun ? (
                    <div className="document-text">{selectedRun.aiResponse}</div>
                  ) : (
                    <div className="empty">載入分析內容中...</div>
                  )}
                </article>

                {selectedRun?.citationReview ? (
                  <article className="reader-card analysis-response">
                    <h2 className="panel-title">引用核對表</h2>
                    <div className="document-text">{selectedRun.citationReview}</div>
                  </article>
                ) : null}
              </>
            ) : (
              <div className="empty">尚無公開 AI 分析結果。</div>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}
