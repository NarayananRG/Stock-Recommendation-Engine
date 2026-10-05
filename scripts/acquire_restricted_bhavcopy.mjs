#!/usr/bin/env node
/**
 * Acquire public NSE CM UDiFF bhavcopy archives for the restricted audit window.
 *
 * The script uses the same documented reports endpoint and report descriptor as
 * the public NSE Historical Reports page. It is resumable, rate limited, and
 * stores raw ZIPs plus its local acquisition log only below the gitignored raw
 * evidence directory. It does not call the per-symbol MCP service.
 */
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const rawDir = join(
  root,
  "data",
  "external_authoritative",
  "free_official",
  "restricted_window",
  "bhavcopy_udiff",
);
const logPath = join(rawDir, "acquisition_log.json");
const START = "2024-10-01";
const END = "2026-10-01";
const RATE_LIMIT_MS = 175;
const SPECIAL_SESSIONS = new Set(["2025-02-01", "2026-02-01"]);
const BASE = "https://www.nseindia.com";
const REPORT_NAME = "CM-UDiFF Common Bhavcopy Final (zip)";
const descriptor = [{
  name: REPORT_NAME,
  type: "daily-reports",
  category: "capital-market",
  section: "equities",
}];

function isoDays(start, end) {
  const days = [];
  for (let d = new Date(`${start}T00:00:00Z`); d <= new Date(`${end}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + 1)) {
    const iso = d.toISOString().slice(0, 10);
    if ((d.getUTCDay() !== 0 && d.getUTCDay() !== 6) || SPECIAL_SESSIONS.has(iso)) days.push(iso);
  }
  return days;
}

function reportDate(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${String(day).padStart(2, "0")}-${names[month - 1]}-${year}`;
}

function sha256(data) {
  return createHash("sha256").update(data).digest("hex");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function priorLog() {
  if (!existsSync(logPath)) return { attempts: {} };
  try {
    const value = JSON.parse(await readFile(logPath, "utf8"));
    if (!value.attempts || typeof value.attempts !== "object") return { attempts: {} };
    return value;
  } catch {
    return { attempts: {} };
  }
}

async function persist(log) {
  const ordered = Object.fromEntries(Object.entries(log.attempts).sort(([a], [b]) => a.localeCompare(b)));
  await writeFile(logPath, `${JSON.stringify({
    artifact_type: "LOCAL_NSE_RESTRICTED_BHAVCOPY_ACQUISITION_LOG_V1",
    source_page: `${BASE}/resources/historical-reports-capital-market-daily-monthly-archives`,
    source_endpoint: `${BASE}/api/reports`,
    report_name: REPORT_NAME,
    target_start: START,
    target_end: END,
    rate_limit_ms: RATE_LIMIT_MS,
    special_sessions: [...SPECIAL_SESSIONS].sort(),
    attempts: ordered,
  }, null, 2)}\n`, "utf8");
}

async function main() {
  await mkdir(rawDir, { recursive: true });
  const log = await priorLog();
  const dates = isoDays(START, END);
  let acquired = 0;
  let unavailable = 0;
  let failed = 0;
  for (let index = 0; index < dates.length; index += 1) {
    const iso = dates[index];
    const expectedName = `BhavCopy_NSE_CM_0_0_0_${iso.replaceAll("-", "")}_F_0000.csv.zip`;
    const output = join(rawDir, expectedName);
    if (existsSync(output)) {
      const data = await readFile(output);
      log.attempts[iso] = {
        status: "ACQUIRED",
        file_name: expectedName,
        bytes: data.length,
        sha256: sha256(data),
      };
      acquired += 1;
      continue;
    }
    const query = new URLSearchParams({
      archives: JSON.stringify(descriptor),
      date: reportDate(iso),
      type: "Equities",
      mode: "single",
    });
    const reportApiUrl = `${BASE}/api/reports?${query.toString()}`;
    const directArchiveUrl = `https://nsearchives.nseindia.com/content/cm/${expectedName}`;
    try {
      let response = await fetch(reportApiUrl, {
        headers: {
          Accept: "application/zip,application/octet-stream,*/*",
          Referer: `${BASE}/resources/historical-reports-capital-market-daily-monthly-archives`,
          "User-Agent": "Stock-Recommendation-Engine research audit (public NSE report acquisition)",
        },
      });
      let data = Buffer.from(await response.arrayBuffer());
      let disposition = response.headers.get("content-disposition") || "";
      let isZip = data.length >= 4 && data.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
      let resolvedUrl = reportApiUrl;
      // The reports catalogue occasionally omits a valid historical session.
      // Its attachment naming convention points to this public archive path.
      if (!response.ok || !isZip) {
        response = await fetch(directArchiveUrl, {
          headers: {
            Accept: "application/zip,application/octet-stream,*/*",
            Referer: `${BASE}/resources/historical-reports-capital-market-daily-monthly-archives`,
            "User-Agent": "Stock-Recommendation-Engine research audit (public NSE report acquisition)",
          },
        });
        data = Buffer.from(await response.arrayBuffer());
        disposition = response.headers.get("content-disposition") || "";
        isZip = data.length >= 4 && data.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
        resolvedUrl = directArchiveUrl;
      }
      if (response.ok && isZip) {
        await writeFile(output, data);
        log.attempts[iso] = {
          status: "ACQUIRED",
          file_name: expectedName,
          bytes: data.length,
          sha256: sha256(data),
          content_disposition: disposition,
          source_url: resolvedUrl,
        };
        acquired += 1;
      } else if (response.status === 404 || response.status === 400 || (response.ok && !isZip)) {
        log.attempts[iso] = {
          status: "NO_PUBLIC_REPORT_FOR_DATE",
          http_status: response.status,
          response_bytes: data.length,
          response_sha256: sha256(data),
        };
        unavailable += 1;
      } else {
        log.attempts[iso] = {
          status: "HTTP_FAILURE",
          http_status: response.status,
          response_bytes: data.length,
          response_sha256: sha256(data),
        };
        failed += 1;
      }
    } catch (error) {
      log.attempts[iso] = { status: "NETWORK_FAILURE", error: String(error?.message || error) };
      failed += 1;
    }
    if ((index + 1) % 25 === 0) {
      await persist(log);
      process.stdout.write(`${index + 1}/${dates.length} acquired=${acquired} unavailable=${unavailable} failed=${failed}\n`);
    }
    await sleep(RATE_LIMIT_MS);
  }
  await persist(log);
  process.stdout.write(JSON.stringify({ candidates: dates.length, acquired, unavailable, failed, log: logPath }) + "\n");
  if (failed) process.exitCode = 2;
}

await main();
