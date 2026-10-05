#!/usr/bin/env node
/** Acquire public NSE calendar, benchmark, and corporate-action evidence. */
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const raw = join(here, "..", "data", "external_authoritative", "free_official", "restricted_window", "metadata");
const headers = {
  Accept: "application/json,*/*",
  Referer: "https://www.nseindia.com/",
  "User-Agent": "Stock-Recommendation-Engine research audit (public NSE metadata acquisition)",
};

function hash(data) {
  return createHash("sha256").update(data).digest("hex");
}

async function acquire(id, url, fileName) {
  const response = await fetch(url, { headers });
  const data = Buffer.from(await response.arrayBuffer());
  if (!response.ok) throw new Error(`${id}: HTTP ${response.status}`);
  JSON.parse(data.toString("utf8"));
  await writeFile(join(raw, fileName), data);
  return { id, url, file_name: fileName, bytes: data.length, sha256: hash(data), http_status: response.status };
}

async function main() {
  await mkdir(raw, { recursive: true });
  const sources = [];
  for (const year of [2024, 2025, 2026]) {
    sources.push(await acquire(
      `NSE_TRADING_HOLIDAYS_${year}`,
      `https://www.nseindia.com/api/holiday-master?type=trading&year=${year}`,
      `nse_trading_holidays_${year}.json`,
    ));
  }
  // Keep each request below the endpoint's observed 70-row response cap.
  const periods = [
    ["2024-10-01", "2024-12-31"],
    ["2025-01-01", "2025-03-31"],
    ["2025-04-01", "2025-06-30"],
    ["2025-07-01", "2025-09-30"],
    ["2025-10-01", "2025-12-31"],
    ["2026-01-01", "2026-03-31"],
    ["2026-04-01", "2026-06-30"],
    ["2026-07-01", "2026-09-30"],
    ["2026-10-01", "2026-10-01"],
  ];
  for (const indexName of ["NIFTY 50", "NIFTY 500"]) {
    for (const [start, end] of periods) {
      const from = start.split("-").reverse().join("-");
      const to = end.split("-").reverse().join("-");
      const slug = indexName.toLowerCase().replaceAll(" ", "_");
      sources.push(await acquire(
        `${indexName}_${start}_${end}`,
        `https://www.nseindia.com/api/historicalOR/indicesHistory?indexType=${encodeURIComponent(indexName)}&from=${from}&to=${to}`,
        `${slug}_${start}_${end}.json`,
      ));
    }
  }
  sources.push(await acquire(
    "NSE_CORPORATE_ACTIONS_RESTRICTED_WINDOW",
    "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=01-10-2024&to_date=01-10-2026",
    "nse_corporate_actions_2024-10-01_2026-10-01.json",
  ));
  const manifest = {
    artifact_type: "LOCAL_NSE_RESTRICTED_METADATA_ACQUISITION_LOG_V1",
    retrieved_at_utc: new Date().toISOString(),
    sources,
  };
  await writeFile(join(raw, "acquisition_log.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(manifest)}\n`);
}

await main();
