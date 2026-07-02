"use client";

import Link from "next/link";
import { BookOpenText, MonitorCog, RefreshCcw, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AuthMenu, ROLE_LABELS, type Role } from "./auth-menu";
import type { CaseIndexItem, Manifest } from "../lib/types";

type DataState =
  | { status: "loading" }
  | { status: "ready"; cases: CaseIndexItem[]; manifest: Manifest }
  | { status: "error"; message: string };

function includesValue(value: string, needle: string) {
  if (!needle) return true;
  return value.toLocaleLowerCase("zh-Hant").includes(needle.toLocaleLowerCase("zh-Hant"));
}

const ROLE_WEIGHT: Record<Role, number> = {
  guest: 0,
  public: 1,
  private: 2,
  admin: 3,
};

const ONLINE_MODULES: Array<{
  title: string;
  status: "online" | "local";
  role: Role;
  detail: string;
  href?: string;
}> = [
  {
    title: "公開評議書搜尋",
    status: "online",
    role: "guest",
    detail: "關鍵字、年度、結果與案由篩選已在此站上線。",
  },
  {
    title: "公開案件閱讀",
    status: "online",
    role: "guest",
    detail: "公開案件全文頁已靜態部署，可直接分享連結。",
  },
  {
    title: "公開 AI 上傳包",
    status: "online",
    role: "public",
    detail: "線上提供案件選取與來源整理入口；實際 AI 分析仍由你指定工具執行。",
  },
  {
    title: "公開 AI 分析結果",
    status: "online",
    role: "guest",
    detail: "已保存的公開案件 AI 回覆可在雲端閱讀；僅匯出 public bundle 結果。",
    href: "/analysis",
  },
  {
    title: "資料狀態",
    status: "online",
    role: "public",
    detail: "公開資料 manifest、案件數與更新時間可直接在雲端檢查。",
  },
  {
    title: "私人案件與文件匯入",
    status: "local",
    role: "private",
    detail: "會接觸 private_cases.db、uploaded_cases 與原始檔，保留在本機 Streamlit。",
  },
  {
    title: "AI 批次分析與稽核",
    status: "local",
    role: "private",
    detail: "ChatGPT/Gemini 瀏覽器自動化、分析結果保存與誤判稽核保留本機執行。",
  },
  {
    title: "模組權限管理",
    status: "local",
    role: "admin",
    detail: "正式帳號、模組權限檔與密碼雜湊保存在本機工作台。",
  },
];

function canSeeModule(role: Role, required: Role) {
  return ROLE_WEIGHT[role] >= ROLE_WEIGHT[required];
}

export default function HomePage() {
  const [data, setData] = useState<DataState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [issueType, setIssueType] = useState("");
  const [result, setResult] = useState("");
  const [year, setYear] = useState("");
  const [role, setRole] = useState<Role>("guest");

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

  useEffect(() => {
    const savedRole = window.localStorage.getItem("teacherAppealRole") as Role | null;
    if (savedRole && savedRole in ROLE_LABELS) {
      setRole(savedRole);
    }
    function handleRole(event: Event) {
      const detail = (event as CustomEvent<Role>).detail;
      if (detail && detail in ROLE_LABELS) {
        setRole(detail);
      }
    }
    window.addEventListener("teacher-appeal-role", handleRole);
    return () => window.removeEventListener("teacher-appeal-role", handleRole);
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
  const visibleModules = ONLINE_MODULES.filter((item) => canSeeModule(role, item.role));

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
          <div className="topbar-actions">
            <div className="muted">更新：{new Date(data.manifest.generatedAt).toLocaleString("zh-TW")}</div>
            <AuthMenu />
          </div>
        </div>
      </header>

      <div className="container">
        {role !== "guest" ? (
          <section className="workspace-band" aria-label="線上工作台">
            <div className="workspace-head">
              <div>
                <div className="section-kicker">ONLINE WORKSPACE</div>
                <h1 className="workspace-title">線上工作台</h1>
              </div>
              <div className="workspace-role">目前權限：{ROLE_LABELS[role]}</div>
            </div>
            <div className="workspace-grid">
              {visibleModules.map((item) => {
                const content = (
                  <>
                    <div className={`module-status ${item.status}`}>
                      {item.status === "online" ? "已上線" : "本機執行"}
                    </div>
                    <h2>{item.title}</h2>
                    <p>{item.detail}</p>
                  </>
                );
                return item.href ? (
                  <Link className="workspace-module workspace-module-link" href={item.href} key={item.title}>
                    {content}
                  </Link>
                ) : (
                  <div className="workspace-module" key={item.title}>
                    {content}
                  </div>
                );
              })}
            </div>
            <div className="local-note">
              <MonitorCog size={18} aria-hidden="true" />
              分析執行、私人文件與瀏覽器自動化保留在本機；線上站提供公開資料、入口與狀態。
            </div>
          </section>
        ) : null}

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
