"use client";

import Link from "next/link";
import {
  Anchor,
  ArrowLeft,
  BookOpenText,
  FileText,
  ListTree,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import { AuthMenu } from "../auth-menu";
import type { PublicAnalysisIndex, PublicAnalysisRun, PublicSourceReference } from "../../lib/types";

type AnalysisState =
  | { status: "loading" }
  | { status: "ready"; index: PublicAnalysisIndex; selectedRun: PublicAnalysisRun | null }
  | { status: "error"; message: string };

type SourceRef = {
  id: string;
  label: string;
  sourceId: string;
  paragraphNo: string;
  sectionTitle: string;
};

type ActiveSourceRef = SourceRef & {
  references: PublicSourceReference[];
};

type AnalysisSection = {
  id: string;
  title: string;
  level: number;
  lines: string[];
  sourceRefs: SourceRef[];
};

const SOURCE_REF_PATTERN = /\[來源：([^，,\] ]+)，第([^段\]]+)段\]/g;

function formatDate(value: string) {
  if (!value) return "未記錄";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-TW");
}

function normalizeHeading(line: string) {
  const trimmed = line.trim();
  const markdown = trimmed.match(/^(#{1,4})\s+(.+)$/);
  if (markdown) {
    return { level: markdown[1].length, title: markdown[2].trim() };
  }
  const numbered = trimmed.match(/^((?:\d+|[一二三四五六七八九十]+)[.、])\s*(.+)$/);
  if (numbered && trimmed.length <= 48) {
    return { level: numbered[1].includes(".") ? 2 : 1, title: trimmed };
  }
  const shortLabel = trimmed.match(/^(案件基本資料|程序與時間軸|事件時間軸|申訴人主張|學校主張|證據|爭點|分析|理由|結論|引用核對|待補資料)[:：]?$/);
  if (shortLabel) {
    return { level: 1, title: trimmed.replace(/[:：]$/, "") };
  }
  return null;
}

function sourceRefsInLine(line: string, sectionId: string, sectionTitle: string) {
  const refs: SourceRef[] = [];
  for (const match of line.matchAll(SOURCE_REF_PATTERN)) {
    refs.push({
      id: `${sectionId}-source-${refs.length}-${match.index || 0}`,
      label: match[0],
      sourceId: match[1],
      paragraphNo: match[2],
      sectionTitle,
    });
  }
  return refs;
}

function parseAnalysisSections(text: string) {
  const rawLines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const sections: AnalysisSection[] = [];
  let current: AnalysisSection | null = null;

  function openSection(title: string, level: number) {
    const id = `analysis-section-${sections.length + 1}`;
    current = { id, title, level, lines: [], sourceRefs: [] };
    sections.push(current);
    return current;
  }

  for (const rawLine of rawLines) {
    const line = rawLine.trimEnd();
    const heading = normalizeHeading(line);
    if (heading) {
      openSection(heading.title, heading.level);
      continue;
    }
    if (!current) {
      current = openSection("總覽", 1);
    }
    current.lines.push(line);
  }

  for (const section of sections) {
    section.sourceRefs = section.lines.flatMap((line) => sourceRefsInLine(line, section.id, section.title));
  }

  return sections.length ? sections : [{ id: "analysis-section-1", title: "總覽", level: 1, lines: [text], sourceRefs: [] }];
}

function asciiTreeForSections(sections: AnalysisSection[]) {
  if (!sections.length) return "AI 回覆";
  const rows = ["AI 回覆"];
  sections.forEach((section, index) => {
    const branch = index === sections.length - 1 ? "`-" : "|-";
    const indent = section.level > 1 ? "   " : "";
    const refs = section.sourceRefs.length ? ` (${section.sourceRefs.length} refs)` : "";
    rows.push(`${indent}${branch} ${section.title}  #${section.id}${refs}`);
  });
  return rows.join("\n");
}

function renderLineWithRefs(
  line: string,
  section: AnalysisSection,
  sourceReferences: Record<string, PublicSourceReference[]> | undefined,
  onSelectRef: (ref: ActiveSourceRef) => void,
) {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let refIndex = 0;
  for (const match of line.matchAll(SOURCE_REF_PATTERN)) {
    const start = match.index || 0;
    if (start > lastIndex) {
      parts.push(<span key={`text-${start}`}>{line.slice(lastIndex, start)}</span>);
    }
    const ref: SourceRef = {
      id: `${section.id}-inline-source-${refIndex}-${start}`,
      label: match[0],
      sourceId: match[1],
      paragraphNo: match[2],
      sectionTitle: section.title,
    };
    const refKey = `${ref.sourceId}:${ref.paragraphNo}`;
    const references = sourceReferences?.[refKey] || [];
    parts.push(
      <button
        className={`source-ref-button${references.length ? "" : " unresolved"}`}
        key={ref.id}
        type="button"
        onClick={() => onSelectRef({ ...ref, references })}
        title={references.length ? "查看公開原文段落" : "尚未找到對應原文段落"}
      >
        {match[1]}:{match[2]}
      </button>,
    );
    lastIndex = start + match[0].length;
    refIndex += 1;
  }
  if (lastIndex < line.length) {
    parts.push(<span key="text-tail">{line.slice(lastIndex)}</span>);
  }
  return parts;
}

function selectedRunIdFromLocation() {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("run") || "";
}

export default function AnalysisPage() {
  const [state, setState] = useState<AnalysisState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [activeRef, setActiveRef] = useState<ActiveSourceRef | null>(null);
  const [showRunList, setShowRunList] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    async function loadIndex() {
      try {
        const response = await fetch("/data/analysis/index.json");
        if (!response.ok) throw new Error("公開 AI 分析索引載入失敗");
        const index = (await response.json()) as PublicAnalysisIndex;
        const initialRunId = selectedRunIdFromLocation();
        setSelectedRunId(initialRunId);
        setShowRunList(!initialRunId);
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
        setActiveRef(null);
        window.history.replaceState(null, "", `/analysis?run=${encodeURIComponent(selectedRun.runId)}`);
      }
    }
    loadRun();
    return () => {
      cancelled = true;
    };
  }, [selectedRunId, state.status, state.status === "ready" ? state.index : null]);

  useEffect(() => {
    if (state.status !== "ready" || !showRunList || selectedRunId) return;
    window.requestAnimationFrame(() => searchInputRef.current?.focus());
  }, [selectedRunId, showRunList, state.status]);

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
  const analysisSections = useMemo(
    () => (selectedRun ? parseAnalysisSections(selectedRun.aiResponse) : []),
    [selectedRun],
  );
  const asciiTree = useMemo(() => asciiTreeForSections(analysisSections), [analysisSections]);

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
            <div className="summary-actions">
              <button
                className="button secondary compact-button"
                type="button"
                onClick={() => setShowRunList((value) => !value)}
                aria-expanded={showRunList}
                aria-controls="analysis-run-list"
              >
                {showRunList ? <PanelLeftClose size={17} aria-hidden="true" /> : <PanelLeftOpen size={17} aria-hidden="true" />}
                {showRunList ? "隱藏案件清單" : "顯示案件清單"}
              </button>
              <div className="workspace-role">共 {state.index.runCount} 筆</div>
            </div>
          </div>
          <div className="local-note">
            <ShieldCheck size={18} aria-hidden="true" />
            此頁只匯出公開案件分析結果；私人案件、原始本機路徑、分析執行工具與 API/瀏覽器自動化仍保留在本機。
          </div>
        </section>

        <section className={`analysis-layout${showRunList ? "" : " list-hidden"}`}>
          {showRunList ? (
          <aside className="analysis-list-panel" id="analysis-run-list" aria-label="公開分析清單">
            <label className="field analysis-search">
              <FileText size={18} aria-hidden="true" />
              <input
                ref={searchInputRef}
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
                  onClick={() => {
                    setSelectedRunId(run.runId);
                    setShowRunList(false);
                  }}
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
          ) : null}

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

                <div className="analysis-reading-grid">
                  <aside className="reader-card analysis-outline" aria-label="AI 回覆目錄">
                    <h2 className="panel-title">
                      <ListTree size={17} aria-hidden="true" />
                      ASCII 樹狀結構
                    </h2>
                    {selectedRun ? (
                      <>
                        <pre className="ascii-tree">{asciiTree}</pre>
                        <div className="anchor-list">
                          {analysisSections.map((section) => (
                            <a className="anchor-link" href={`#${section.id}`} key={section.id}>
                              <Anchor size={14} aria-hidden="true" />
                              {section.title}
                            </a>
                          ))}
                        </div>
                      </>
                    ) : (
                      <div className="empty compact">載入目錄中...</div>
                    )}
                  </aside>

                  <article className="reader-card analysis-response structured-response">
                    <h2 className="panel-title">AI 回覆</h2>
                    {selectedRun ? (
                      <div className="analysis-sections">
                        {analysisSections.map((section) => (
                          <section className="analysis-section" id={section.id} key={section.id}>
                            <div className="section-anchor-row">
                              <h3>{section.title}</h3>
                              <a className="section-anchor" href={`#${section.id}`}>
                                #{section.id.replace("analysis-section-", "S")}
                              </a>
                            </div>
                            <div className="analysis-paragraphs">
                              {section.lines.filter(Boolean).map((line, index) => (
                                <p key={`${section.id}-${index}`}>
                                  {renderLineWithRefs(line, section, selectedRun.sourceReferences, setActiveRef)}
                                </p>
                              ))}
                            </div>
                          </section>
                        ))}
                      </div>
                    ) : (
                      <div className="empty">載入分析內容中...</div>
                    )}
                  </article>
                </div>

                {selectedRun && activeRef ? (
                  <aside className="floating-reference open" aria-label="浮動補充視窗">
                    <div className="floating-reference-head">
                      <div>
                        <div className="section-kicker">REFERENCE</div>
                        <h2>浮動補充視窗</h2>
                      </div>
                      <button className="icon-button" type="button" onClick={() => setActiveRef(null)} aria-label="關閉補充視窗">
                        <X size={18} aria-hidden="true" />
                      </button>
                    </div>
                    <div className="reference-body">
                      <div className="source-badge">{activeRef.sourceId}:{activeRef.paragraphNo}</div>
                      <dl>
                        <div>
                          <dt>AI 回覆所在章節</dt>
                          <dd>{activeRef.sectionTitle}</dd>
                        </div>
                      </dl>
                      {activeRef.references.length ? (
                        <div className="reference-source-list">
                          {activeRef.references.map((reference, index) => (
                            <section className="reference-source-card" key={`${reference.cid}-${reference.sourceId}-${reference.paragraphNo}-${index}`}>
                              <div className="reference-source-meta">
                                <span>{reference.cid}</span>
                                <span>{reference.section || reference.heading || "原文段落"}</span>
                              </div>
                              <p>{reference.text || "此段公開原文尚未匯出。"}</p>
                              {reference.caseHref ? (
                                <Link className="reference-case-link" href={reference.caseHref}>
                                  開啟公開案件原文
                                </Link>
                              ) : null}
                            </section>
                          ))}
                        </div>
                      ) : (
                        <div className="reference-missing">
                          尚未找到這個參照錨點的公開原文段落。若這是多案件比較結果，可能需要回到本機來源包核對。
                        </div>
                      )}
                    </div>
                  </aside>
                ) : null}

                {selectedRun?.citationReview ? (
                  <article className="reader-card analysis-response">
                    <h2 className="panel-title">引用核對表</h2>
                    <div className="document-text">{selectedRun.citationReview}</div>
                  </article>
                ) : null}
              </>
            ) : (
              <div className="empty analysis-start-card">
                搜尋 run、案號或摘要後，選擇一筆公開 AI 分析結果開始閱讀。
              </div>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}
