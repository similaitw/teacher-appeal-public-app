"use client";

import Link from "next/link";
import { BookOpenText, RefreshCcw, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CaseIndexItem, Manifest } from "../lib/types";

type DataState =
  | { status: "loading" }
  | { status: "ready"; cases: CaseIndexItem[]; manifest: Manifest }
  | { status: "error"; message: string };

function includesValue(value: string, needle: string) {
  if (!needle) return true;
  return value.toLocaleLowerCase("zh-Hant").includes(needle.toLocaleLowerCase("zh-Hant"));
}

export default function HomePage() {
  const [data, setData] = useState<DataState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [issueType, setIssueType] = useState("");
  const [result, setResult] = useState("");
  const [year, setYear] = useState("");

  useEffect(() => {
    async function loadData() {
      try {
        const [manifestResponse, indexResponse] = await Promise.all([
          fetch("/data/manifest.json"),
          fetch("/data/cases-index.json"),
        ]);
        if (!manifestResponse.ok || !indexResponse.ok) {
          throw new Error("公開資料載入失敗");
        }
        const manifest = (await manifestResponse.json()) as Manifest;
        const cases = (await indexResponse.json()) as CaseIndexItem[];
        setData({ status: "ready", manifest, cases });
      } catch (error) {
        setData({
          status: "error",
          message: error instanceof Error ? error.message : "公開資料載入失敗",
        });
      }
    }
    loadData();
  }, []);

  const filteredCases = useMemo(() => {
    if (data.status !== "ready") return [];
    return data.cases.filter((item) => {
      const matchesQuery = includesValue(item.searchText, query.trim());
      const matchesIssue = !issueType || item.issueType.includes(issueType);
      const matchesResult = !result || item.result === result;
      const matchesYear = !year || item.year === year;
      return matchesQuery && matchesIssue && matchesResult && matchesYear;
    });
  }, [data, issueType, query, result, year]);

  const visibleCases = filteredCases.slice(0, 80);

  if (data.status === "loading") {
    return <div className="loading">載入公開案件資料中...</div>;
  }

  if (data.status === "error") {
    return <div className="loading">{data.message}</div>;
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">
              <BookOpenText size={21} />
            </div>
            <div>
              <div className="brand-title">教師申訴評議書公開查詢</div>
              <div className="brand-subtitle">教育部公開評議書資料，供快速檢索與閱讀</div>
            </div>
          </div>
          <div className="muted">更新：{new Date(data.manifest.generatedAt).toLocaleString("zh-TW")}</div>
        </div>
      </header>

      <div className="container">
        <section className="stats" aria-label="資料概況">
          <div className="stat">
            <div className="stat-label">公開案件</div>
            <div className="stat-value">{data.manifest.caseCount}</div>
          </div>
          <div className="stat">
            <div className="stat-label">搜尋結果</div>
            <div className="stat-value">{filteredCases.length}</div>
          </div>
          <div className="stat">
            <div className="stat-label">年度範圍</div>
            <div className="stat-value">{data.manifest.years.length}</div>
          </div>
          <div className="stat">
            <div className="stat-label">案件類型</div>
            <div className="stat-value">{data.manifest.issueTypes.length}</div>
          </div>
        </section>

        <section className="toolbar" aria-label="搜尋與篩選">
          <label className="field">
            <Search size={18} />
            <input
              className="input with-icon"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜尋關鍵字、案號、理由、法規..."
              aria-label="搜尋關鍵字"
            />
          </label>
          <select className="select" value={issueType} onChange={(event) => setIssueType(event.target.value)} aria-label="案由">
            <option value="">全部案由</option>
            {data.manifest.issueTypes.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select className="select" value={result} onChange={(event) => setResult(event.target.value)} aria-label="結果">
            <option value="">全部結果</option>
            {data.manifest.results.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select className="select" value={year} onChange={(event) => setYear(event.target.value)} aria-label="年度">
            <option value="">全部年度</option>
            {data.manifest.years.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </section>

        <section className="content-grid">
          <aside className="side-panel" aria-label="常見案由">
            <h2 className="panel-title">
              <SlidersHorizontal size={17} aria-hidden="true" /> 常見案由
            </h2>
            <div className="chip-list">
              {data.manifest.issueTypes.slice(0, 18).map((item) => (
                <button key={item} className="chip" type="button" onClick={() => setIssueType(item)}>
                  {item}
                </button>
              ))}
            </div>
          </aside>

          <section aria-label="案件列表">
            <div className="result-header">
              <div className="muted">
                顯示 {visibleCases.length} / {filteredCases.length} 筆
              </div>
              <button
                className="button secondary"
                type="button"
                onClick={() => {
                  setQuery("");
                  setIssueType("");
                  setResult("");
                  setYear("");
                }}
              >
                <RefreshCcw size={17} aria-hidden="true" />
                重設
              </button>
            </div>

            {visibleCases.length ? (
              <div className="case-list">
                {visibleCases.map((item) => (
                  <Link className="case-card" href={`/cases/${item.cid}`} key={item.cid}>
                    <div className="case-meta">
                      <span className="tag">{item.result}</span>
                      <span className="tag gold">{item.issueType}</span>
                      <span>{item.dateText || item.year}</span>
                      <span>cid {item.cid}</span>
                    </div>
                    <h2 className="case-title">{item.title}</h2>
                    <p className="case-excerpt">{item.excerpt}</p>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="empty">沒有符合條件的公開案件。</div>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}
