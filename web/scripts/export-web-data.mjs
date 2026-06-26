import { parse } from "csv-parse/sync";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const webRoot = path.resolve(process.cwd());
const repoRoot = path.resolve(webRoot, "..");
const dataRoot = path.join(repoRoot, "data");
const csvPath = path.join(dataRoot, "cases.csv");
const outputRoot = path.join(webRoot, "public", "data");
const casesOutputRoot = path.join(outputRoot, "cases");
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

function uniqueSorted(values) {
  return [...new Set(values.map(normalizeText).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "zh-Hant"),
  );
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
}

if (checkOnly && !errors.length) {
  console.log("Data export check passed.");
}
