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
