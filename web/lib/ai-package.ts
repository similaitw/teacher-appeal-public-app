// 公開 AI 分析包產生器（瀏覽器端）。
//
// 這是 scripts/public_ai_export.py 的移植版，輸出內容必須與 Python 版逐字一致；
// tests/test_web_ai_package_parity.py 會拿全部公開案件比對兩邊產出。
// 修改任一邊的格式或提示詞時，另一邊要同步修改。
// 本檔只使用可直接去除的型別語法，讓 Node 可不經編譯直接載入做比對。

export type PackageMode = "single" | "compare";

export type PackageCaseInput = {
  cid: string;
  title: string;
  date_text: string;
  doc_no: string;
  result: string;
  case_type: string;
  issue_type: string;
  url: string;
  fullText: string;
};

export type PublicParagraph = {
  paragraphNo: number;
  section: string;
  heading: string;
  content: string;
  charStart: number;
  charEnd: number;
};

export const SOURCE_ID = "D001";

const BOILERPLATE_LINES = new Set([
  "跳到主要內容區塊",
  "教育部訴願案件查詢系統",
  ":::",
  "網站導覽",
  "評議書查詢",
  "評議案件進度查詢",
  "回首頁",
  "轉存PDF檔",
  "轉存ODF檔",
  "資通安全及隱私政策",
]);

const SECTION_HEADINGS: Record<string, string> = {
  "主文": "主文",
  "主 文": "主文",
  "主　文": "主文",
  "事實": "事實",
  "事 實": "事實",
  "事　實": "事實",
  "理由": "理由",
  "理 由": "理由",
  "理　由": "理由",
};

const TITLE_SUFFIX = "-教育部教師申訴案件查詢系統";

// 與 Python str.splitlines()、str.strip()、re 的 \s 相同的字元集合。
const PY_LINE_BREAK = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;
const PY_SPACE = "\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, "g");
const PY_SPACE_ALL = new RegExp(`[${PY_SPACE}]+`, "g");

// Python 的 \d 涵蓋全形數字等 Unicode 十進位數字。
const NUMBERED_HEADING = new RegExp("^\\p{Nd}+[.．、]", "u");

function pyStrip(value: string): string {
  return value.replace(PY_STRIP, "");
}

function pySplitLines(value: string): string[] {
  return value.split(PY_LINE_BREAK);
}

function codePointLength(value: string): number {
  let count = 0;
  for (const _ of value) count += 1;
  return count;
}

function headPrefix(line: string): string {
  // 等同 Python 的 line.split("。", 1)[0][:60]（以字元而非 UTF-16 單位計算）。
  return Array.from(line.split("。")[0]).slice(0, 60).join("");
}

export function cleanPublicText(rawText: string): string {
  const cleaned: string[] = [];
  let inFooter = false;
  for (const rawLine of pySplitLines(rawText)) {
    let line = pyStrip(rawLine.replace(/[ \t\r\f\v]+/g, " "));
    if (!line) continue;
    if (line.startsWith("歡迎蒞臨教育部")) inFooter = true;
    if (inFooter) continue;
    if (BOILERPLATE_LINES.has(line)) continue;
    if (line.endsWith(TITLE_SUFFIX)) {
      line = pyStrip(line.split(TITLE_SUFFIX).join(""));
    }
    cleaned.push(line);
  }
  return cleaned.join("\n");
}

function sectionForLine(line: string, currentSection: string): string {
  const compact = line.replace(PY_SPACE_ALL, "");
  if (Object.hasOwn(SECTION_HEADINGS, line)) return SECTION_HEADINGS[line];
  if (Object.hasOwn(SECTION_HEADINGS, compact)) return SECTION_HEADINGS[compact];
  if (line.startsWith("發文日期") || line.startsWith("發文字號") || line.startsWith("教育部")) {
    return "案件基本資料";
  }
  if (line.startsWith("申訴人") || line.startsWith("原措施")) {
    return currentSection || "案件基本資料";
  }
  return currentSection || "本文";
}

function headingForLine(line: string, section: string): string {
  const compact = line.replace(PY_SPACE_ALL, "");
  if (Object.hasOwn(SECTION_HEADINGS, line)) return SECTION_HEADINGS[line];
  if (Object.hasOwn(SECTION_HEADINGS, compact)) return SECTION_HEADINGS[compact];
  if (/^[一二三四五六七八九十]+、/.test(line)) return headPrefix(line);
  if (/^\([一二三四五六七八九十]+\)/.test(line)) return headPrefix(line);
  if (NUMBERED_HEADING.test(line)) return headPrefix(line);
  return section;
}

export function splitPublicParagraphs(cleanedText: string): PublicParagraph[] {
  const paragraphs: PublicParagraph[] = [];
  let currentSection = "案件基本資料";
  // Python 的位移以字元（code point）計算；JavaScript 字串以 UTF-16 單位計算，
  // 所以另外維護一份字元位移。
  let unitCursor = 0;
  let pointCursor = 0;
  for (const rawLine of pySplitLines(cleanedText)) {
    const line = pyStrip(rawLine);
    if (!line) {
      unitCursor += 1;
      pointCursor += 1;
      continue;
    }
    let unitStart = cleanedText.indexOf(line, unitCursor);
    let pointStart: number;
    if (unitStart < 0) {
      unitStart = unitCursor;
      pointStart = pointCursor;
    } else {
      pointStart = pointCursor + codePointLength(cleanedText.slice(unitCursor, unitStart));
    }
    const unitEnd = unitStart + line.length;
    const pointEnd = pointStart + codePointLength(line);
    currentSection = sectionForLine(line, currentSection);
    paragraphs.push({
      paragraphNo: paragraphs.length + 1,
      section: currentSection,
      heading: headingForLine(line, currentSection),
      content: line,
      charStart: pointStart,
      charEnd: pointEnd,
    });
    unitCursor = unitEnd;
    pointCursor = pointEnd;
  }
  return paragraphs;
}

export function analysisPrompt(item: PackageCaseInput): string {
  return `# AI 分析指令

請只根據 \`case_full_context.md\` 的 D001 來源段落分析本案，不得使用外部資料補充事實。

請輸出：

1. 案件基本資料
2. 程序時間軸
3. 申訴人主張
4. 機關／學校說明
5. 申評會理由
6. 爭點
7. 可引用重點
8. 不確定事項
9. 引用核對表

要求：

- 每項重要事實都標示 \`[來源：D001，第N段]\`。
- 不得摘要成無來源結論。
- 不得引用未提供的法規條號或未出現在來源的事實。
- 單方陳述使用「主張」、「表示」或「稱」。
- 客觀資料使用「依資料顯示」或「評議書記載」。

本案 cid：${item.cid}
本案標題：${item.title}
`;
}

type CaseManifest = {
  cid: string;
  title: string;
  date_text: string;
  doc_no: string;
  result: string;
  case_type: string;
  issue_type: string;
  url: string;
  source_text_path: string;
  paragraph_count: number;
  export_time: string;
};

export function multiCasePrompt(cases: CaseManifest[], mode: PackageMode): string {
  const caseLines = cases
    .map((item) => `- cid=${item.cid}｜${item.title}｜${item.date_text}｜${item.result}`)
    .join("\n");
  const modeNote = mode === "compare" ? "多案比較" : "多個單案分別分析";
  return `# ChatGPT / Gemini 分析指令

本資料包用途：${modeNote}。

請先讀取各案件子資料夾中的 \`case_full_context.md\`，再依本指令分析。每個案件的事實來源都只有該案件自己的 D001 段落。

## 已選案件

${caseLines}

## 絕對限制

- 不得把任一案件的人物、日期、學校、程序、主張、理由或結論套用到其他案件。
- 引用事實時必須同時標示 cid 與來源段落，例如：\`cid=114070228，[來源：D001，第12段]\`。
- 不得使用未出現在資料包內的外部資料補充事實。
- 若來源不足，請寫「來源不足，無法判斷」，不要推測。
- 單方陳述使用「主張」、「表示」或「稱」；評議書記載事項使用「依評議書記載」。

## 請輸出

1. 逐案結構化摘要
2. 逐案程序時間軸
3. 逐案申訴人主張
4. 逐案機關／學校說明
5. 逐案申評會理由
6. 共同爭點與差異
7. 相同爭點下的不同見解
8. 可引用段落清單
9. 不確定事項
10. 引用核對表
`;
}

// 等同 Python csv 模組預設（QUOTE_MINIMAL、\r\n 換行）加上 utf-8-sig 的 BOM。
function csvField(value: string | number): string {
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function csvText(fieldnames: string[], rows: Array<Record<string, string | number>>): string {
  const lines = [fieldnames.join(",")];
  for (const row of rows) {
    lines.push(fieldnames.map((name) => csvField(row[name] ?? "")).join(","));
  }
  return "\ufeff" + lines.map((line) => line + "\r\n").join("");
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** 本地時間，格式同 Python datetime.now().isoformat(timespec="seconds")。 */
export function exportTime(now: Date = new Date()): string {
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
  );
}

export function bundleBaseName(mode: PackageMode, caseCount: number, now: Date = new Date()): string {
  const stamp =
    `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${stamp}_${mode}_${caseCount}_cases`;
}

function casePackageFiles(item: PackageCaseInput, exportedAt: string): { files: Record<string, string>; manifest: CaseManifest } {
  const cid = item.cid.trim();
  if (!cid) throw new Error("案件缺少 cid");
  const paragraphs = splitPublicParagraphs(cleanPublicText(item.fullText));
  if (!paragraphs.length) throw new Error(`cid=${cid} 沒有可匯出的段落`);

  const manifest: CaseManifest = {
    cid: item.cid,
    title: item.title,
    date_text: item.date_text,
    doc_no: item.doc_no,
    result: item.result,
    case_type: item.case_type,
    issue_type: item.issue_type,
    url: item.url,
    source_text_path: `data/texts/${cid}.txt`,
    paragraph_count: paragraphs.length,
    export_time: exportedAt,
  };

  const contextLines = [
    "# 案件基本資料",
    "",
    `- cid：${cid}`,
    `- 標題：${item.title}`,
    `- 日期：${item.date_text}`,
    `- 文號：${item.doc_no}`,
    `- 案件類型：${item.case_type}`,
    `- 爭點分類：${item.issue_type}`,
    `- 結果：${item.result}`,
    `- 原始網址：${item.url}`,
    `- 匯出時間：${exportedAt}`,
    "",
    "# 文件內容",
    "",
    `## 文件 ${SOURCE_ID}：${item.title}`,
    "",
  ];
  for (const paragraph of paragraphs) {
    contextLines.push(
      `### 第 ${paragraph.paragraphNo} 段`,
      "",
      `[來源：${SOURCE_ID}，第${paragraph.paragraphNo}段]`,
      "",
      paragraph.content,
      "",
    );
  }

  const sourceIndex = csvText(
    ["source_id", "cid", "section", "paragraph_no", "heading", "char_start", "char_end"],
    paragraphs.map((paragraph) => ({
      source_id: SOURCE_ID,
      cid,
      section: paragraph.section,
      paragraph_no: paragraph.paragraphNo,
      heading: paragraph.heading,
      char_start: paragraph.charStart,
      char_end: paragraph.charEnd,
    })),
  );

  return {
    manifest,
    files: {
      "case_manifest.json": JSON.stringify(manifest, null, 2),
      "case_full_context.md": contextLines.join("\n"),
      "source_index.csv": sourceIndex,
      "case_prompt.md": analysisPrompt(item),
    },
  };
}

/** 回傳 ZIP 內的所有檔案：路徑 → 文字內容（結構同 Python 的 export_public_case_bundle）。 */
export function buildBundleFiles(cases: PackageCaseInput[], mode: PackageMode, exportedAt: string): Record<string, string> {
  if (mode !== "single" && mode !== "compare") throw new Error("mode 必須是 single 或 compare");
  const seen = new Set<string>();
  const selected = cases.filter((item) => {
    const cid = item.cid.trim();
    if (!cid || seen.has(cid)) return false;
    seen.add(cid);
    return true;
  });
  if (!selected.length) throw new Error("沒有可匯出的案件");

  const files: Record<string, string> = {};
  const manifests: CaseManifest[] = [];
  for (const item of selected) {
    const result = casePackageFiles(item, exportedAt);
    manifests.push(result.manifest);
    for (const [name, content] of Object.entries(result.files)) {
      files[`cases/${item.cid.trim()}/${name}`] = content;
    }
  }

  const summaries = manifests.map((item) => ({
    cid: item.cid,
    title: item.title,
    date_text: item.date_text,
    doc_no: item.doc_no,
    result: item.result,
    case_type: item.case_type,
    issue_type: item.issue_type,
    url: item.url,
    paragraph_count: item.paragraph_count,
  }));
  files["bundle_manifest.json"] = JSON.stringify(
    {
      export_time: exportedAt,
      mode,
      case_count: manifests.length,
      cids: manifests.map((item) => item.cid),
      cases: summaries,
    },
    null,
    2,
  );
  files["selected_cases.csv"] = csvText(
    ["cid", "title", "date_text", "doc_no", "result", "case_type", "issue_type", "url", "paragraph_count"],
    summaries,
  );
  files["multi_case_prompt.md"] = multiCasePrompt(manifests, mode);
  return files;
}
