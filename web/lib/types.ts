export type CaseIndexItem = {
  cid: string;
  title: string;
  url: string;
  caseType: string;
  issueType: string;
  result: string;
  year: string;
  dateText: string;
  docNo: string;
  matchedKeywords: string;
  excerpt: string;
  searchText: string;
  updatedAt: string;
};

export type CaseRecord = Omit<CaseIndexItem, "excerpt" | "searchText"> & {
  sourcePaths: {
    text: string;
    html: string;
  };
  fullText: string;
};

export type Manifest = {
  generatedAt: string;
  caseCount: number;
  expectedCaseCount: number;
  source: string;
  issueTypes: string[];
  results: string[];
  years: string[];
};

export type PublicAnalysisCaseRef = {
  cid: string;
  title: string;
  href: string;
};

export type PublicAnalysisIndexItem = {
  runId: string;
  provider: string;
  modelName: string;
  analysisTime: string;
  caseIds: string[];
  caseCount: number;
  cases: PublicAnalysisCaseRef[];
  excerpt: string;
  responseSha256: string;
  href: string;
  dataPath: string;
};

export type PublicAnalysisIndex = {
  generatedAt: string;
  runCount: number;
  source: string;
  privacyRule: string;
  skippedCount: number;
  runs: PublicAnalysisIndexItem[];
};

export type PublicSourceReference = {
  sourceId: string;
  paragraphNo: string;
  cid: string;
  caseTitle: string;
  caseHref: string;
  section: string;
  heading: string;
  text: string;
};

export type PublicAnalysisRun = Omit<PublicAnalysisIndexItem, "excerpt" | "href" | "dataPath"> & {
  scope: "public_bundle";
  aiResponse: string;
  citationReview: string;
  notes: string;
  sourceReferences?: Record<string, PublicSourceReference[]>;
  notesSha256: string;
};
