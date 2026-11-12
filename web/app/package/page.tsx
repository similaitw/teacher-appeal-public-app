"use client";

import Link from "next/link";
import { BookOpenText, Download, RefreshCcw, Search } from "lucide-react";
import { strToU8, zipSync } from "fflate";
import { useEffect, useMemo, useState } from "react";
import { buildBundleFiles, bundleBaseName, exportTime, type PackageMode } from "../../lib/ai-package";
import { packageInputFromRecord } from "../../lib/ai-package-input";
import type { CaseIndexItem, CaseRecord, Manifest } from "../../lib/types";
import { SiteNav } from "../site-nav";

type DataState =
  | { status: "loading" }
  | { status: "ready"; cases: CaseIndexItem[]; manifest: Manifest }
  | { status: "error"; message: string };

type BuildState =
  | { status: "idle" }
  | { status: "working"; done: number; total: number }
  | { status: "done"; fileName: string; caseCount: number; sizeKb: number }
  | { status: "error"; message: string };

const SUGGESTED_BATCH = 20;
const USAGE_TEXT =
  "請先上傳這個 ZIP，或上傳其中各案的 case_full_context.md；再貼上 multi_case_prompt.md。" +
  "請只根據資料包內來源分析，並逐項引用 cid 與 D001 段落。";

function matches(item: CaseIndexItem, needle: string) {
  if (!needle) return true;
  return item.searchText.includes(needle.toLocaleLowerCase("zh-Hant"));
}

function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function PackagePage() {
  const [data, setData] = useState<DataState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [issueType, setIssueType] = useState("");
  const [result, setResult] = useState("");
  const [year, setYear] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<PackageMode>("single");
  const [build, setBuild] = useState<BuildState>({ status: "idle" });

  useEffect(() => {
    async function loadData() {
      try {
        const [manifestResponse, indexResponse] = await Promise.all([
          fetch("/data/manifest.json"),
          fetch("/data/cases-index.json"),
        ]);
        if (!manifestResponse.ok || !indexResponse.ok) throw new Error("公開資料載入失敗");
        setData({
          status: "ready",
          manifest: (await manifestResponse.json()) as Manifest,
          cases: (await indexResponse.json()) as CaseIndexItem[],
        });
      } catch (error) {
        setData({ status: "error", message: error instanceof Error ? error.message : "公開資料載入失敗" });
      }
    }
    loadData();
  }, []);

  const filteredCases = useMemo(() => {
    if (data.status !== "ready") return [];
    const needle = query.trim();
    return data.cases.filter(
      (item) =>
        matches(item, needle) &&
        (!issueType || item.issueType.includes(issueType)) &&
        (!result || item.result === result) &&
        (!year || item.year === year),
    );
  }, [data, issueType, query, result, year]);

  if (data.status === "loading") return <div className="loading">載入公開案件資料中...</div>;
  if (data.status === "error") return <div className="loading">{data.message}</div>;

  // 依案件清單的順序輸出，與畫面一致。
  const selectedCases = data.cases.filter((item) => selected.has(item.cid));
  const allFilteredSelected = filteredCases.length > 0 && filteredCases.every((item) => selected.has(item.cid));
  const working = build.status === "working";

  function toggle(cid: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(cid)) next.delete(cid);
      else next.add(cid);
      return next;
    });
    setBuild({ status: "idle" });
  }

  function toggleAllFiltered() {
    setSelected((current) => {
      const next = new Set(current);
      for (const item of filteredCases) {
        if (allFilteredSelected) next.delete(item.cid);
        else next.add(item.cid);
      }
      return next;
    });
    setBuild({ status: "idle" });
  }

  async function generate() {
    const targets = selectedCases;
    if (!targets.length) return;
    setBuild({ status: "working", done: 0, total: targets.length });
    try {
      const inputs = [];
      for (const [position, item] of targets.entries()) {
        const response = await fetch(`/data/cases/${item.cid}.json`);
        if (!response.ok) throw new Error(`cid=${item.cid} 全文載入失敗`);
        inputs.push(packageInputFromRecord((await response.json()) as CaseRecord));
        setBuild({ status: "working", done: position + 1, total: targets.length });
      }
      const now = new Date();
      const files = buildBundleFiles(inputs, mode, exportTime(now));
      const zipped = zipSync(
        Object.fromEntries(Object.entries(files).map(([name, content]) => [name, strToU8(content)])),
        { level: 6 },
      );
      const fileName = `${bundleBaseName(mode, inputs.length, now)}.zip`;
      saveBlob(new Blob([zipped as BlobPart], { type: "application/zip" }), fileName);
      setBuild({ status: "done", fileName, caseCount: inputs.length, sizeKb: zipped.length / 1024 });
    } catch (error) {
      setBuild({ status: "error", message: error instanceof Error ? error.message : "產生失敗" });
    }
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
              <div className="brand-title">公開 AI 分析包</div>
              <div className="brand-subtitle">勾選公開評議書，下載給 ChatGPT / Gemini 使用的上傳包</div>
            </div>
          </Link>
          <div className="topbar-actions">
            <SiteNav current="package" />
          </div>
        </div>
      </header>

      <div className="container">
        <div className="local-note package-note">
          上傳包在你的瀏覽器裡產生，本站不呼叫任何 AI 服務，也不會上傳你的選取內容。AI 的分析結果請回到評議書全文核對後再引用。
        </div>

        <section className="toolbar" aria-label="篩選案件">
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

        <section className="content-grid package-grid">
          <aside className="side-panel package-panel" aria-label="產生上傳包">
            <h2 className="panel-title">
              <Download size={17} aria-hidden="true" /> 產生上傳包
            </h2>
            <div className="package-count">
              已選 <strong>{selectedCases.length}</strong> 件
            </div>
            <fieldset className="package-modes">
              <legend>工作包模式</legend>
              <label>
                <input type="radio" name="mode" checked={mode === "single"} onChange={() => setMode("single")} />
                單案分析包（各案分別分析）
              </label>
              <label>
                <input type="radio" name="mode" checked={mode === "compare"} onChange={() => setMode("compare")} />
                多案比較包（比較異同）
              </label>
            </fieldset>
            {selectedCases.length > SUGGESTED_BATCH ? (
              <p className="package-warning">
                已選超過 {SUGGESTED_BATCH} 件，建議分批產生，避免超過 ChatGPT / Gemini 的上傳或內容長度限制。
              </p>
            ) : null}
            {mode === "compare" && selectedCases.length === 1 ? (
              <p className="package-warning">多案比較建議至少選 2 件。</p>
            ) : null}
            <button className="button" type="button" onClick={generate} disabled={!selectedCases.length || working}>
              <Download size={17} aria-hidden="true" />
              {working ? `打包中 ${build.done} / ${build.total}` : "下載 ZIP 上傳包"}
            </button>
            {selectedCases.length ? (
              <button
                className="button secondary"
                type="button"
                onClick={() => {
                  setSelected(new Set());
                  setBuild({ status: "idle" });
                }}
                disabled={working}
              >
                <RefreshCcw size={17} aria-hidden="true" />
                清除選取
              </button>
            ) : null}
            <div role="status" aria-live="polite">
              {build.status === "done" ? (
                <div className="package-done">
                  <p>
                    已下載 {build.fileName}（{build.caseCount} 件，{build.sizeKb.toFixed(0)} KB）。
                  </p>
                  <p className="muted">建議貼給 AI 的說明：</p>
                  <p className="package-usage">{USAGE_TEXT}</p>
                  <div className="package-links">
                    <a className="button secondary" href="https://chatgpt.com/" target="_blank" rel="noreferrer">
                      開啟 ChatGPT
                    </a>
                    <a className="button secondary" href="https://gemini.google.com/" target="_blank" rel="noreferrer">
                      開啟 Gemini
                    </a>
                  </div>
                </div>
              ) : null}
              {build.status === "error" ? <p className="package-warning">{build.message}，請再試一次。</p> : null}
            </div>
          </aside>

          <section aria-label="案件清單">
            <div className="result-header">
              <label className="package-select-all">
                <input
                  type="checkbox"
                  checked={allFilteredSelected}
                  onChange={toggleAllFiltered}
                  disabled={!filteredCases.length}
                />
                全選目前篩選結果（{filteredCases.length} 筆）
              </label>
            </div>
            {filteredCases.length ? (
              <div className="package-list">
                {filteredCases.map((item) => (
                  <label className={`package-row${selected.has(item.cid) ? " selected" : ""}`} key={item.cid}>
                    <input type="checkbox" checked={selected.has(item.cid)} onChange={() => toggle(item.cid)} />
                    <span className="package-row-body">
                      <span className="package-row-title">{item.title}</span>
                      <span className="case-meta">
                        <span className="tag">{item.result}</span>
                        <span className="tag gold">{item.issueType}</span>
                        <span>{item.dateText || item.year}</span>
                        <span>cid {item.cid}</span>
                      </span>
                    </span>
                    <Link className="package-row-link" href={`/cases/${item.cid}`} target="_blank">
                      閱讀
                    </Link>
                  </label>
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
