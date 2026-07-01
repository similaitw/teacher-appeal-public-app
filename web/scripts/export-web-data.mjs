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
const checkOnly = process.argv.includes("--check");

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

function exportPublicAnalysisRuns(caseIndex, exportedAt) {
  fs.mkdirSync(analysisRunsOutputRoot, { recursive: true });

  const caseIndexByCid = new Map(caseIndex.map((item) => [item.cid, item]));
  const runs = [];
  const skipped = [];

  if (fs.existsSync(analysisRunsRoot)) {
    const runDirs = fs
      .readdirSync(analysisRunsRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort()
      .reverse();

    for (const runId of runDirs) {
      const runDir = path.join(analysisRunsRoot, runId);
      const manifest = readJsonIfExists(path.join(runDir, "input_manifest.json"));
      if (!manifest || manifest.scope !== "public_bundle") {
        skipped.push(runId);
        continue;
      }

      const caseIds = Array.isArray(manifest.case_ids)
        ? manifest.case_ids.map((cid) => normalizeText(cid)).filter(Boolean)
        : [];
      const hasOnlyPublicCases = caseIds.length > 0 && caseIds.every((cid) => caseIndexByCid.has(cid));
      if (!hasOnlyPublicCases) {
        skipped.push(runId);
        continue;
      }

      const aiResponse = readTextIfExists(path.join(runDir, "ai_response.md"));
      if (!aiResponse.trim()) {
        skipped.push(runId);
        continue;
      }

      const citationReview = readTextIfExists(path.join(runDir, "citation_review.md"));
      const notes = readTextIfExists(path.join(runDir, "notes.md"));
      const publicRun = {
        runId: normalizeText(manifest.run_id || runId),
        scope: "public_bundle",
        provider: normalizeText(manifest.provider),
        modelName: normalizeText(manifest.model_name),
        analysisTime: normalizeText(manifest.analysis_time),
        caseIds,
        caseCount: Number(manifest.case_count || caseIds.length),
        cases: publicAnalysisCaseTitles(caseIds, caseIndexByCid),
        aiResponse,
        citationReview,
        notes,
        responseSha256: normalizeText(manifest.ai_response_sha256),
        notesSha256: normalizeText(manifest.notes_sha256),
      };

      fs.writeFileSync(
        path.join(analysisRunsOutputRoot, `${publicRun.runId}.json`),
        JSON.stringify(publicRun),
      );

      runs.push({
        runId: publicRun.runId,
        provider: publicRun.provider,
        modelName: publicRun.modelName,
        analysisTime: publicRun.analysisTime,
        caseIds: publicRun.caseIds,
        caseCount: publicRun.caseCount,
        cases: publicRun.cases,
        excerpt: excerptFromText(aiResponse),
        responseSha256: publicRun.responseSha256,
        href: `/analysis?run=${encodeURIComponent(publicRun.runId)}`,
        dataPath: `/data/analysis/runs/${publicRun.runId}.json`,
      });
    }
  }

  runs.sort((a, b) => String(b.analysisTime).localeCompare(String(a.analysisTime)));

  fs.writeFileSync(
    path.join(analysisOutputRoot, "index.json"),
    JSON.stringify(
      {
        generatedAt: exportedAt,
        runCount: runs.length,
        source: "data/ai_exports/analysis_runs public_bundle only",
        privacyRule: "Only scope=public_bundle runs with public case ids are exported. Private analysis runs and source file paths are excluded.",
        skippedCount: skipped.length,
        runs,
      },
      null,
      2,
    ),
  );

  return { exported: runs.length, skipped: skipped.length };
}

if (!fs.existsSync(csvPath)) {
  const manifestPath = path.join(outputRoot, "manifest.json");
  const indexPath = path.join(outputRoot, "cases-index.json");
  if (fs.existsSync(manifestPath) && fs.existsSync(indexPath) && fs.existsSync(casesOutputRoot)) {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    const caseFiles = fs.readdirSync(casesOutputRoot).filter((name) => name.endsWith(".json"));
    if (manifest.caseCount === 324 && caseFiles.length === 324) {
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

const manifest = {
  generatedAt: exportedAt,
  caseCount: index.length,
  expectedCaseCount: 324,
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

if (errors.length) {
  for (const error of errors) console.error(error);
  process.exitCode = 1;
} else {
  console.log(`Exported ${index.length} public cases to ${path.relative(repoRoot, outputRoot)}`);
  console.log(`Exported ${analysisExport.exported} public AI analysis runs; skipped ${analysisExport.skipped}.`);
}

if (checkOnly && !errors.length) {
  console.log("Data export check passed.");
}
