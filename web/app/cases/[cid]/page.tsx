import fs from "node:fs";
import path from "node:path";
import CaseClient from "./case-client";

export function generateStaticParams() {
  const casesRoot = path.join(process.cwd(), "public", "data", "cases");
  if (!fs.existsSync(casesRoot)) return [];
  return fs
    .readdirSync(casesRoot)
    .filter((name) => name.endsWith(".json"))
    .map((name) => ({ cid: name.replace(/\.json$/, "") }));
}

export default async function CasePage({ params }: { params: Promise<{ cid: string }> }) {
  const { cid } = await params;
  return <CaseClient cid={cid} />;
}
