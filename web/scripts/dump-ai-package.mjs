// 供 tests/test_web_ai_package_parity.py 使用：
// 以 web/public/data 的案件 JSON 產生 AI 分析包，輸出 {路徑: 內容} 的 JSON。
// 用法：node scripts/dump-ai-package.mjs <mode> <exportTime> <cid> [cid...]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildBundleFiles } from "../lib/ai-package.ts";
import { packageInputFromRecord } from "../lib/ai-package-input.ts";

const [mode, exportedAt, ...cids] = process.argv.slice(2);
const casesRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "public", "data", "cases");
const inputs = cids.map((cid) =>
  packageInputFromRecord(JSON.parse(fs.readFileSync(path.join(casesRoot, `${cid}.json`), "utf8"))),
);
process.stdout.write(JSON.stringify(buildBundleFiles(inputs, mode, exportedAt)));
