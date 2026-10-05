#!/usr/bin/env node
/** Acquire only the free official evidence needed for restricted-window closure. */
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const raw = join(here, "..", "data", "external_authoritative", "free_official", "restricted_closure");
const sources = [
  ["SIEMENS_ABLBL_EXIT", "https://www.niftyindices.com/Press_Release/ind_prs25062025_2.pdf", "ind_prs25062025_2.pdf"],
  ["TATA_MOTORS_EXIT", "https://www.niftyindices.com/Press_Release/ind_prs13112025.pdf", "ind_prs13112025.pdf"],
  ["VEDANTA_POWER_STEEL_EXIT", "https://www.niftyindices.com/Press_Release/ind_prs17062026.pdf", "ind_prs17062026.pdf"],
  ["VEDANTA_OIL_GAS_EXIT", "https://www.niftyindices.com/Press_Release/ind_prs22062026.pdf", "ind_prs22062026.pdf"],
  ["NSE_MCP_TERMS", "https://www.nseindia.com/nse-mcp", "nse_mcp.html"],
  ["NSE_DATA_POLICY", "https://www.nseindia.com/static/market-data/nse-data-policy", "nse_data_policy.html"],
  ["NIFTY_DATA_SUBSCRIPTION", "https://www.niftyindices.com/offerings/data-subscription", "nifty_data_subscription.html"],
  ["NIFTY_TERMS_OF_USE", "https://www.niftyindices.com/terms-of-use", "nifty_terms_of_use.html"],
];
const headers = { Accept: "*/*", Referer: "https://www.nseindia.com/", "User-Agent": "Stock-Recommendation-Engine research audit" };
const sha256 = data => createHash("sha256").update(data).digest("hex");

await mkdir(raw, { recursive: true });
const acquired = [];
for (const [id, url, fileName] of sources) {
  const response = await fetch(url, { headers, redirect: "follow" });
  const data = Buffer.from(await response.arrayBuffer());
  if (!response.ok) throw new Error(`${id}: HTTP ${response.status}`);
  if (fileName.endsWith(".pdf") && !data.subarray(0, 5).equals(Buffer.from("%PDF-"))) throw new Error(`${id}: NOT_PDF`);
  await writeFile(join(raw, fileName), data);
  acquired.push({ id, url, file_name: fileName, bytes: data.length, sha256: sha256(data), http_status: response.status });
}
const manifest = { artifact_type: "LOCAL_RESTRICTED_CLOSURE_EVIDENCE_LOG_V1", retrieved_at_utc: new Date().toISOString(), sources: acquired };
await writeFile(join(raw, "acquisition_log.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify(manifest)}\n`);
