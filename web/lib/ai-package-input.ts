import type { PackageCaseInput } from "./ai-package.ts";

type RecordLike = {
  cid: string;
  title: string;
  url: string;
  caseType: string;
  issueType: string;
  result: string;
  dateText: string;
  docNo: string;
  fullText: string;
  packageMeta?: {
    title: string;
    date_text: string;
    doc_no: string;
    result: string;
    case_type: string;
    issue_type: string;
    url: string;
  };
};

/** 把網站的案件 JSON 轉成分析包輸入；優先使用 CSV 原始欄位。 */
export function packageInputFromRecord(record: RecordLike): PackageCaseInput {
  const meta = record.packageMeta;
  return {
    cid: record.cid,
    title: meta?.title ?? record.title,
    date_text: meta?.date_text ?? record.dateText,
    doc_no: meta?.doc_no ?? record.docNo,
    result: meta?.result ?? record.result,
    case_type: meta?.case_type ?? record.caseType,
    issue_type: meta?.issue_type ?? record.issueType,
    url: meta?.url ?? record.url,
    fullText: record.fullText,
  };
}
