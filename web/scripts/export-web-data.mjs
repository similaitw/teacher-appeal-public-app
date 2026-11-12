import { parse } from "csv-parse/sync";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const webRoot = path.resolve(process.cwd());
const repoRoot = path.resolve(webRoot, "..");
const dataRoot = path.join(repoRoot, "data");
const csvPath = path.join(dataRoot, "cases.csv");
const analysisRunsRoot = path.join(dataRoot, "ai_exports", "analysis_runs");
const outputRoot = path.join(webRoot, "public", "data");
const casesOutputRoot = path.join(outputRoot, "cases");
const analysisOutputRoot = path.join(outputRoot, "analysis");
const analysisRunsOutputRoot = path.join(analysisOutputRoot, "runs");
// 可公開、可提交到 repo 的 AI 分析（由 --publish-analysis 產生）；Vercel 建置時以此為來源。
const committedAnalysisRunsRoot = path.join(dataRoot, "public_analysis", "runs");
const downloadedCidsPath = path.join(dataRoot, "downloaded_cids.txt");
const checkOnly = process.argv.includes("--check");
const publishAnalysis = process.argv.includes("--publish-analysis");

function normalizeText(value) {
  return String(value || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
}

function normalizePath(value) {
  return String(value || "").replace(/\\/g, "/");
}

function firstNonEmpty(...values) {
  for (const value of values) {
    const normalized = normalizeText(value);
    if (normalized) return normalized;
  }
  return "";
}

function excerptFromText(text) {
  const cleaned = normalizeText(text)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => ![":::", "網站導覽", "評議書查詢", "回首頁"].includes(line))
    .join(" ");
  return cleaned.slice(0, 220);
}

function readJsonIfExists(filePath) {
  if (!fs.existsSync(filePath)) return null;
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null;
  }
}

function readTextIfExists(filePath) {
  return fs.existsSync(filePath) ? fs.readFileSync(filePath, "utf8") : "";
}

function uniqueSorted(values) {
  return [...new Set(values.map(normalizeText).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "zh-Hant"),
  );
}

function publicAnalysisCaseTitles(caseIds, caseIndexByCid) {
  return caseIds.map((cid) => {
    const record = caseIndexByCid.get(cid);
    return {
      cid,
      title: record?.title || `${cid} 評議書`,
      href: `/cases/${cid}`,
    };
  });
}

function sourceKeysFromText(text) {
  const keys = new Set();
  const pattern = /\[來源：([^，,\] ]+)，第([^段\]]+)段\]/g;
  for (const match of text.matchAll(pattern)) {
    keys.add(`${normalizeText(match[1])}:${normalizeText(match[2])}`);
  }
  return keys;
}

function parseSourceContextParagraphs(contextText) {
  const paragraphs = new Map();
  const pattern = /### 第\s*(\d+)\s*段\s*\n+\[來源：([^，,\] ]+)，第[^\]]+段\]\s*\n+([\s\S]*?)(?=\n### 第\s*\d+\s*段|\n# |\s*$)/g;
  for (const match of contextText.matchAll(pattern)) {
    const paragraphNo = normalizeText(match[1]);
    const sourceId = normalizeText(match[2]);
    const text = normalizeText(match[3]);
    if (sourceId && paragraphNo && text) {
      paragraphs.set(`${sourceId}:${paragraphNo}`, text);
    }
  }
  return paragraphs;
}

function parseCsvText(csvText) {
  if (!csvText.trim()) return [];
  return parse(csvText, {
    columns: true,
    bom: true,
    relax_quotes: true,
    skip_empty_lines: true,
  });
}

function exportSourceReferences(manifest, aiResponse, caseIndexByCid) {
  const wantedKeys = sourceKeysFromText(aiResponse);
  if (!wantedKeys.size || !Array.isArray(manifest.source_files)) return {};

  const sourceFiles = manifest.source_files
    .map((file) => ({
      ...file,
      normalizedPath: normalizePath(file.path),
      absolutePath: path.join(repoRoot, normalizePath(file.path)),
    }))
    .filter((file) => file.normalizedPath.startsWith("data/ai_exports/web_ai_batches/"));

  const contextsByDir = new Map();
  for (const file of sourceFiles.filter((item) => item.role === "source_context")) {
    const contextText = readTextIfExists(file.absolutePath);
    contextsByDir.set(path.dirname(file.normalizedPath), parseSourceContextParagraphs(contextText));
  }

  const references = {};
  for (const file of sourceFiles.filter((item) => item.role === "source_index")) {
    const rows = parseCsvText(readTextIfExists(file.absolutePath));
    const context = contextsByDir.get(path.dirname(file.normalizedPath)) || new Map();
    for (const row of rows) {
      const sourceId = normalizeText(row.source_id);
      const paragraphNo = normalizeText(row.paragraph_no);
      const key = `${sourceId}:${paragraphNo}`;
      if (!sourceId || !paragraphNo || !wantedKeys.has(key)) continue;

      const cid = normalizeText(row.cid);
      const caseRecord = caseIndexByCid.get(cid);
      const entry = {
        sourceId,
        paragraphNo,
        cid,
        caseTitle: caseRecord?.title || `${cid} 評議書`,
        caseHref: cid ? `/cases/${cid}` : "",
        section: normalizeText(row.section),
        heading: normalizeText(row.heading),
        text: context.get(key) || "",
      };
      if (!references[key]) references[key] = [];
      references[key].push(entry);
    }
  }

  return references;
}

function indexEntryForRun(publicRun) {
  return {
    runId: publicRun.runId,
    provider: publicRun.provider,
    modelName: publicRun.modelName,
    analysisTime: publicRun.analysisTime,
    caseIds: publicRun.caseIds,
    caseCount: publicRun.caseCount,
    cases: publicRun.cases,
    excerpt: excerptFromText(publicRun.aiResponse),
    responseSha256: publicRun.responseSha256,
    href: `/analysis?run=${encodeURIComponent(publicRun.runId)}`,
    dataPath: `/data/analysis/runs/${publicRun.runId}.json`,
  };
}

function isSafeRunId(runId) {
  return /^[A-Za-z0-9_.-]+$/.test(runId) && !runId.startsWith(".");
}

// 已提交到 repo 的公開分析：再檢查一次 scope 與 cid，並只保留公開欄位。
function loadCommittedAnalysisRuns(caseIndexByCid, skipped) {
  const runs = new Map();
  if (!fs.existsSync(committedAnalysisRunsRoot)) return runs;
  for (const name of fs.readdirSync(committedAnalysisRunsRoot).filter((item) => item.endsWith(".json")).sort()) {
    const record = readJsonIfExists(path.join(committedAnalysisRunsRoot, name));
    const runId = normalizeText(record?.runId);
    const caseIds = Array.isArray(record?.caseIds) ? record.caseIds.map((cid) => normalizeText(cid)).filter(Boolean) : [];
    const valid =
      record &&
      record.scope === "public_bundle" &&
      isSafeRunId(runId) &&
      `${runId}.json` === name &&
      caseIds.length > 0 &&
      caseIds.every((cid) => caseIndexByCid.has(cid)) &&
      normalizeText(record.aiResponse);
    if (!valid) {
      skipped.push(name);
      continue;
    }
    runs.set(runId, {
      runId,
      scope: "public_bundle",
      provider: normalizeText(record.provider),
      modelName: normalizeText(record.modelName),
      analysisTime: normalizeText(record.analysisTime),
      caseIds,
      caseCount: Number(record.caseCount || caseIds.length),
      cases: publicAnalysisCaseTitles(caseIds, caseIndexByCid),
      aiResponse: String(record.aiResponse),
      citationReview: String(record.citationReview || ""),
      notes: String(record.notes || ""),
      sourceReferences: record.sourceReferences && typeof record.sourceReferences === "object" ? record.sourceReferences : {},
      responseSha256: normalizeText(record.responseSha256),
      notesSha256: normalizeText(record.notesSha256),
    });
  }
  return runs;
}

// 本機 data/ai_exports/analysis_runs（不進 repo）：只匯出 public_bundle 且全為公開 cid 的分析。
function loadLocalAnalysisRuns(caseIndexByCid, skipped) {
  const runs = new Map();
  if (!fs.existsSync(analysisRunsRoot)) return runs;
  const runDirs = fs
    .readdirSync(analysisRunsRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort()
    .reverse();

  for (const runDirName of runDirs) {
    const runDir = path.join(analysisRunsRoot, runDirName);
    const manifest = readJsonIfExists(path.join(runDir, "input_manifest.json"));
    if (!manifest || manifest.scope !== "public_bundle") {
      skipped.push(runDirName);
      continue;
    }

    const caseIds = Array.isArray(manifest.case_ids)
      ? manifest.case_ids.map((cid) => normalizeText(cid)).filter(Boolean)
      : [];
    const hasOnlyPublicCases = caseIds.length > 0 && caseIds.every((cid) => caseIndexByCid.has(cid));
    if (!hasOnlyPublicCases) {
      skipped.push(runDirName);
      continue;
    }

    const aiResponse = readTextIfExists(path.join(runDir, "ai_response.md"));
    const runId = normalizeText(manifest.run_id || runDirName);
    if (!aiResponse.trim() || !isSafeRunId(runId)) {
      skipped.push(runDirName);
      continue;
    }

    runs.set(runId, {
      runId,
      scope: "public_bundle",
      provider: normalizeText(manifest.provider),
      modelName: normalizeText(manifest.model_name),
      analysisTime: normalizeText(manifest.analysis_time),
      caseIds,
      caseCount: Number(manifest.case_count || caseIds.length),
      cases: publicAnalysisCaseTitles(caseIds, caseIndexByCid),
      aiResponse,
      citationReview: readTextIfExists(path.join(runDir, "citation_review.md")),
      notes: readTextIfExists(path.join(runDir, "notes.md")),
      sourceReferences: exportSourceReferences(manifest, aiResponse, caseIndexByCid),
      responseSha256: normalizeText(manifest.ai_response_sha256),
      notesSha256: normalizeText(manifest.notes_sha256),
    });
  }
  return runs;
}

function exportPublicAnalysisRuns(caseIndex, exportedAt) {
  fs.mkdirSync(analysisRunsOutputRoot, { recursive: true });

  const caseIndexByCid = new Map(caseIndex.map((item) => [item.cid, item]));
  const skipped = [];
  const committed = loadCommittedAnalysisRuns(caseIndexByCid, skipped);
  const local = loadLocalAnalysisRuns(caseIndexByCid, skipped);
  // 本機有較新的分析時以本機為準。
  const merged = new Map([...committed, ...local]);
  for (const [runId, publicRun] of local) {
    // 本機批次來源檔已清掉時，保留 repo 內已整理好的引用段落。
    const previous = committed.get(runId);
    if (previous && !Object.keys(publicRun.sourceReferences).length) {
      merged.set(runId, { ...publicRun, sourceReferences: previous.sourceReferences });
    }
  }

  if (publishAnalysis) {
    fs.mkdirSync(committedAnalysisRunsRoot, { recursive: true });
    for (const publicRun of merged.values()) {
      fs.writeFileSync(
        path.join(committedAnalysisRunsRoot, `${publicRun.runId}.json`),
        JSON.stringify(publicRun, null, 1) + "\n",
      );
    }
  }

  const runs = [];
  for (const publicRun of merged.values()) {
    fs.writeFileSync(
      path.join(analysisRunsOutputRoot, `${publicRun.runId}.json`),
      JSON.stringify(publicRun),
    );
    runs.push(indexEntryForRun(publicRun));
  }

  runs.sort(
    (a, b) =>
      String(b.analysisTime).localeCompare(String(a.analysisTime)) || String(b.runId).localeCompare(String(a.runId)),
  );

  fs.writeFileSync(
    path.join(analysisOutputRoot, "index.json"),
    JSON.stringify(
      {
        generatedAt: exportedAt,
        runCount: runs.length,
        source: "data/public_analysis/runs + data/ai_exports/analysis_runs (public_bundle only)",
        privacyRule: "Only scope=public_bundle runs with public case ids are exported. Private analysis runs and source file paths are excluded.",
        skippedCount: skipped.length,
        runs,
      },
      null,
      2,
    ),
  );

  return {
    exported: runs.length,
    skipped: skipped.length,
    committed: committed.size,
    local: local.size,
    missingFromRepo: [...local.keys()].filter((runId) => !committed.has(runId)).length,
  };
}

if (!fs.existsSync(csvPath)) {
  const manifestPath = path.join(outputRoot, "manifest.json");
  const indexPath = path.join(outputRoot, "cases-index.json");
  if (fs.existsSync(manifestPath) && fs.existsSync(indexPath) && fs.existsSync(casesOutputRoot)) {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    const caseFiles = fs.readdirSync(casesOutputRoot).filter((name) => name.endsWith(".json"));
    if (manifest.caseCount > 0 && caseFiles.length === manifest.caseCount) {
      console.log("Using pre-exported public data from web/public/data");
      process.exit(0);
    }
  }
  throw new Error(`Missing public cases CSV and pre-exported public data: ${csvPath}`);
}

const csv = fs.readFileSync(csvPath, "utf8");
const rows = parse(csv, {
  columns: true,
  bom: true,
  relax_quotes: true,
  skip_empty_lines: true,
});

fs.rmSync(outputRoot, { recursive: true, force: true });
fs.mkdirSync(casesOutputRoot, { recursive: true });

const exportedAt = new Date().toISOString();
const index = [];
const missingTexts = [];

for (const row of rows) {
  const cid = firstNonEmpty(row.cid, row["\ufeffcid"]);
  if (!cid) continue;

  const textPath = normalizePath(row.text_path);
  const localTextPath = textPath ? path.join(repoRoot, textPath) : "";
  const fileText = localTextPath && fs.existsSync(localTextPath)
    ? fs.readFileSync(localTextPath, "utf8")
    : "";
  const fullText = firstNonEmpty(fileText, row.full_text);

  if (!fullText) missingTexts.push(cid);

  const title = firstNonEmpty(row.title, `${cid} 評議書`);
  const caseRecord = {
    cid,
    title,
    url: firstNonEmpty(row.url),
    caseType: firstNonEmpty(row.case_type),
    issueType: firstNonEmpty(row.issue_type, "未分類"),
    result: firstNonEmpty(row.result, "未標示"),
    year: firstNonEmpty(row.year),
    dateText: firstNonEmpty(row.date_text),
    docNo: firstNonEmpty(row.doc_no),
    matchedKeywords: firstNonEmpty(row.matched_keywords),
    sourcePaths: {
      text: textPath,
      html: normalizePath(row.html_path),
    },
    fullText,
    updatedAt: firstNonEmpty(row.updated_at, row.created_at),
    // AI 分析包使用 CSV 原始欄位（不補「未分類」等預設值），與 scripts/public_ai_export.py 一致。
    packageMeta: {
      title: String(row.title ?? ""),
      date_text: String(row.date_text ?? ""),
      doc_no: String(row.doc_no ?? ""),
      result: String(row.result ?? ""),
      case_type: String(row.case_type ?? ""),
      issue_type: String(row.issue_type ?? ""),
      url: String(row.url ?? ""),
    },
  };

  fs.writeFileSync(
    path.join(casesOutputRoot, `${cid}.json`),
    JSON.stringify(caseRecord),
  );

  index.push({
    cid,
    title,
    url: caseRecord.url,
    caseType: caseRecord.caseType,
    issueType: caseRecord.issueType,
    result: caseRecord.result,
    year: caseRecord.year,
    dateText: caseRecord.dateText,
    docNo: caseRecord.docNo,
    matchedKeywords: caseRecord.matchedKeywords,
    excerpt: excerptFromText(fullText),
    searchText: normalizeText([
      cid,
      title,
      caseRecord.caseType,
      caseRecord.issueType,
      caseRecord.result,
      caseRecord.year,
      caseRecord.dateText,
      caseRecord.docNo,
      caseRecord.matchedKeywords,
      fullText.slice(0, 4000),
    ].join(" ")).toLocaleLowerCase("zh-Hant"),
    updatedAt: caseRecord.updatedAt,
  });
}

index.sort((a, b) => {
  const byYear = String(b.year).localeCompare(String(a.year));
  if (byYear !== 0) return byYear;
  return String(b.cid).localeCompare(String(a.cid));
});

// 預期筆數以爬蟲的已下載清單為準，資料更新後不必改程式。
const expectedCaseCount = fs.existsSync(downloadedCidsPath)
  ? new Set(fs.readFileSync(downloadedCidsPath, "utf8").split(/\r?\n/).map((line) => line.trim()).filter(Boolean)).size
  : index.length;
// 資料最後成功更新時間：案件紀錄中最新的 updated_at（不是網站建置時間）。
const dataUpdatedAt = index.map((item) => item.updatedAt).filter(Boolean).sort().at(-1) || "";

const manifest = {
  generatedAt: exportedAt,
  dataUpdatedAt,
  caseCount: index.length,
  expectedCaseCount,
  source: "data/cases.csv",
  issueTypes: uniqueSorted(index.flatMap((item) => item.issueType.split(/[、,，]/))),
  results: uniqueSorted(index.map((item) => item.result)),
  years: uniqueSorted(index.map((item) => item.year)).reverse(),
};

fs.writeFileSync(path.join(outputRoot, "cases-index.json"), JSON.stringify(index));
fs.writeFileSync(path.join(outputRoot, "manifest.json"), JSON.stringify(manifest, null, 2));
const analysisExport = exportPublicAnalysisRuns(index, exportedAt);

const caseFiles = fs.readdirSync(casesOutputRoot).filter((name) => name.endsWith(".json"));
const errors = [];
if (index.length !== manifest.expectedCaseCount) {
  errors.push(`Expected ${manifest.expectedCaseCount} cases, exported ${index.length}.`);
}
if (caseFiles.length !== index.length) {
  errors.push(`Index has ${index.length} cases, but ${caseFiles.length} case JSON files exist.`);
}
if (missingTexts.length) {
  errors.push(`Missing full text for cids: ${missingTexts.join(", ")}`);
}

// 自動部署（Vercel）時若 repo 內沒有任何公開分析，多半是忘了先提交 data/public_analysis；
// 擋下建置，避免線上的 AI 分析結果頁被清空。確定要以空白上線時設 ALLOW_EMPTY_ANALYSIS=1。
if (process.env.VERCEL && !analysisExport.exported && process.env.ALLOW_EMPTY_ANALYSIS !== "1") {
  errors.push(
    "No public AI analysis runs found in data/public_analysis/runs. " +
      "Run `npm run publish:analysis` locally and commit the result before deploying.",
  );
}

if (errors.length) {
  for (const error of errors) console.error(error);
  process.exitCode = 1;
} else {
  console.log(`Exported ${index.length} public cases to ${path.relative(repoRoot, outputRoot)}`);
  console.log(
    `Exported ${analysisExport.exported} public AI analysis runs ` +
      `(repo ${analysisExport.committed}, local ${analysisExport.local}); skipped ${analysisExport.skipped}.`,
  );
  if (publishAnalysis) {
    console.log(`Wrote public analysis runs to ${path.relative(repoRoot, committedAnalysisRunsRoot)}; review and commit them.`);
  } else if (analysisExport.missingFromRepo) {
    console.warn(
      `${analysisExport.missingFromRepo} local public analysis runs are not in data/public_analysis yet. ` +
        "Run `npm run publish:analysis` and commit, or the auto-deployed site will not include them.",
    );
  }
}

if (checkOnly && !errors.length) {
  console.log("Data export check passed.");
}
