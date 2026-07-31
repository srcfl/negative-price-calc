// Client-side production-file parsing (CSV / text + Excel). Handles the common Swedish
// meter export quirks: semicolon delimiters, decimal commas, thousands separators, and
// hourly / 15-minute / daily granularity. Excel (.xlsx / .xlsm) is read with a tiny
// dependency-free reader (see ./xlsx) so the static bundle stays light.

import type { Granularity, ParsedProduction, ProductionInterval } from "./types";
import { readWorkbook, type WorkbookSheet } from "./xlsx.ts";

const DATE_HINTS = /(datum|date|tid|time|timestamp|från|start|period|hour|timme)/i;
/** Columns holding the interval's *end* timestamp (E.ON "Sluttidpunkt"). Kept narrow so
 *  ordinary words that merely contain "end" (e.g. "Kalender") don't match. */
const END_HINTS = /(^slut|sluttid|slutdatum|^end\b|end_?(time|date)|^till$|t\.o\.m)/i;
const PROD_HINTS =
  /(produktion|production|export|inmatning|inmatad|levererad|kwh|mwh|energi|förbrukning|consumption|effekt|power|värde|value|netto|kvantitet|quantity|mängd)/i;
const PREFERRED_PROD = /(export|inmat|produktion|production|kwh|kvantitet|quantity)/i;
/** Column that says whether a row is production or consumption (E.ON "Energiriktning"). */
const DIRECTION_HINTS = /(riktning|direction)/i;
const PRODUCTION_DIRECTION = /(produktion|production|export|inmatning|inmatad|utmatad|levererad)/i;

/** Parse a Swedish/European or plain number string into a float, or NaN. */
export function parseNumber(raw: string): number {
  if (raw == null) return NaN;
  let s = String(raw).trim().replace(/ /g, "").replace(/\s/g, "");
  if (s === "") return NaN;
  const hasComma = s.includes(",");
  const hasDot = s.includes(".");
  if (hasComma && hasDot) {
    // Both present: assume "." thousands, "," decimal (European).
    s = s.replace(/\./g, "").replace(",", ".");
  } else if (hasComma) {
    s = s.replace(",", ".");
  }
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : NaN;
}

/**
 * Parse a timestamp string into a local Europe/Stockholm wall-clock number (ms).
 * Offsets are intentionally dropped so production lines up with price wall-clock.
 */
export function parseTimestamp(raw: string): number | null {
  if (!raw) return null;
  const s = String(raw).trim();
  if (s === "") return null;

  // ISO-ish with optional offset/zone: 2025-11-03T00:00:00+01:00 / with space separator.
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (m) {
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], m[6] ? +m[6] : 0);
  }
  // Date only: 2025-11-03 (or with / )
  m = s.match(/^(\d{4})[-/](\d{2})[-/](\d{2})$/);
  if (m) {
    return Date.UTC(+m[1], +m[2] - 1, +m[3], 0, 0, 0);
  }
  // European D.M.Y or D/M/Y with optional time.
  m = s.match(/^(\d{1,2})[./](\d{1,2})[./](\d{4})(?:[ T](\d{2}):(\d{2}))?/);
  if (m) {
    return Date.UTC(+m[3], +m[2] - 1, +m[1], m[4] ? +m[4] : 0, m[5] ? +m[5] : 0, 0);
  }
  // Fallback: let the engine try, then re-interpret as local wall-clock.
  const t = Date.parse(s);
  if (!Number.isNaN(t)) {
    const d = new Date(t);
    return Date.UTC(
      d.getFullYear(),
      d.getMonth(),
      d.getDate(),
      d.getHours(),
      d.getMinutes(),
      d.getSeconds()
    );
  }
  return null;
}

function detectDelimiter(headerLine: string): string {
  const candidates = [";", "\t", ","];
  let best = ",";
  let bestCount = -1;
  for (const c of candidates) {
    const count = headerLine.split(c).length - 1;
    if (count > bestCount) {
      bestCount = count;
      best = c;
    }
  }
  return best;
}

function splitLine(line: string, delim: string): string[] {
  // Minimal CSV split with quote support.
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === delim && !inQuotes) {
      out.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  out.push(cur);
  return out.map((c) => c.trim());
}

function median(nums: number[]): number {
  if (nums.length === 0) return 0;
  const s = [...nums].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

function granularityFromMinutes(step: number): Granularity {
  if (step <= 0) return "unknown";
  if (step <= 20) return "15min";
  if (step <= 90) return "hourly";
  return "daily";
}

/**
 * Find the row that actually heads the data table.
 *
 * Most exports put the header on line 1, but E.ON's "Mätvärdesexport" (and a few other
 * Swedish meter exports) prepend a metadata block — plant id, export timestamp, unit —
 * with its own header/value pair, then a blank line, then the real table. Naively taking
 * line 1 makes every data row unparseable.
 *
 * Scores each candidate by how many rows immediately below it share its column count and
 * look like data (a parseable timestamp plus a parseable number). The real header is
 * followed by thousands of such rows; a metadata header is followed by one. Ties go to the
 * earliest row, so ordinary single-header files behave exactly as before.
 */
function findHeaderRow(lines: string[]): { index: number; delim: string } {
  const MAX_PREAMBLE = 25; // metadata blocks are a handful of lines, never deep
  const MAX_PROBE = 40; // enough to separate "real table" from "one metadata row"
  let best = { index: 0, delim: detectDelimiter(lines[0]), score: -1 };

  for (let h = 0; h < Math.min(lines.length - 1, MAX_PREAMBLE); h++) {
    const delim = detectDelimiter(lines[h]);
    const width = splitLine(lines[h], delim).length;
    if (width < 2) continue;
    let score = 0;
    for (let r = h + 1; r < lines.length && score < MAX_PROBE; r++) {
      const row = splitLine(lines[r], delim);
      if (row.length !== width) break;
      const hasTs = row.some((c) => parseTimestamp(c) != null);
      const hasNum = row.some((c) => Number.isFinite(parseNumber(c)));
      if (!hasTs || !hasNum) break;
      score++;
    }
    if (score > best.score) best = { index: h, delim, score };
  }
  return best;
}

/**
 * Unit of the value column. E.ON states it in the metadata block ("Måttenhet;kWh") rather
 * than in the value column's own header, so fall back to scanning the skipped preamble.
 */
function detectMwh(valueHeader: string, preamble: string[][]): boolean {
  if (/mwh/i.test(valueHeader)) return !/kwh/i.test(valueHeader);
  for (const row of preamble) {
    for (const cell of row) {
      if (/^mwh$/i.test(cell.trim())) return true;
      if (/^kwh$/i.test(cell.trim())) return false;
    }
  }
  return false;
}

export function parseProductionCsv(text: string, filename = ""): ParsedProduction {
  if (/\.xls[xm]?$/i.test(filename) && /PK/.test(text.slice(0, 4))) {
    // Excel files are binary (a ZIP); route them through parseProductionXlsx, not here.
    throw new Error(
      "Excel-filer måste läsas som binärdata (använd Excel-inläsaren). Exportera som CSV om problemet kvarstår."
    );
  }

  const rawLines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  if (rawLines.length < 2) throw new Error("Filen verkar tom eller saknar datarader.");

  // Skip any metadata preamble (E.ON) and use the row that really heads the table.
  const { index: headerIdx, delim } = findHeaderRow(rawLines);
  const header = splitLine(rawLines[headerIdx], delim);
  const preamble = rawLines.slice(0, headerIdx).map((l) => splitLine(l, delim));
  const firstDataRow = headerIdx + 1 < rawLines.length ? splitLine(rawLines[headerIdx + 1], delim) : [];

  // Locate columns by header hints.
  let dtIdx = header.findIndex((h) => DATE_HINTS.test(h));
  if (dtIdx === -1) dtIdx = 0;

  // An explicit interval-end column ("Sluttidpunkt") is authoritative — but only if it
  // really holds timestamps, so a look-alike header can't hijack the value column.
  const endIdx = header.findIndex(
    (h, i) =>
      i !== dtIdx && END_HINTS.test(h) && parseTimestamp(firstDataRow[i] ?? "") != null
  );

  // Rows may be tagged production vs consumption; we only want what was fed to the grid.
  const dirIdx = header.findIndex((h, i) => i !== dtIdx && i !== endIdx && DIRECTION_HINTS.test(h));

  const skip = (i: number) => i === dtIdx || i === endIdx || i === dirIdx;

  let prodIdx = -1;
  // Prefer columns whose header clearly means exported energy.
  for (let i = 0; i < header.length; i++) {
    if (skip(i)) continue;
    if (PREFERRED_PROD.test(header[i])) {
      prodIdx = i;
      break;
    }
  }
  if (prodIdx === -1) prodIdx = header.findIndex((h, i) => !skip(i) && PROD_HINTS.test(h));

  // Fallback: first numeric column that isn't a timestamp/direction column.
  if (prodIdx === -1) {
    prodIdx = firstDataRow.findIndex(
      (v, i) => !skip(i) && Number.isFinite(parseNumber(v)) && parseTimestamp(v) == null
    );
  }
  if (prodIdx === -1) throw new Error("Hittade ingen produktions-/exportkolumn i filen.");

  const isMwh = detectMwh(header[prodIdx], preamble);

  // Parse rows.
  const points: { start: number; end: number | null; kwh: number }[] = [];
  const widest = Math.max(dtIdx, prodIdx, endIdx, dirIdx);
  for (let r = headerIdx + 1; r < rawLines.length; r++) {
    const cols = splitLine(rawLines[r], delim);
    if (cols.length <= widest) continue;
    // Consumption/import row in a mixed export — not our series.
    if (dirIdx >= 0 && cols[dirIdx] && !PRODUCTION_DIRECTION.test(cols[dirIdx])) continue;
    const ts = parseTimestamp(cols[dtIdx]);
    const val = parseNumber(cols[prodIdx]);
    if (ts == null || !Number.isFinite(val)) continue;
    const end = endIdx >= 0 ? parseTimestamp(cols[endIdx]) : null;
    points.push({ start: ts, end: end != null && end > ts ? end : null, kwh: isMwh ? val * 1000 : val });
  }

  if (points.length === 0) throw new Error("Kunde inte tolka några giltiga rader (datum + värde).");
  points.sort((a, b) => a.start - b.start);

  // Interval length: prefer each row's own declared duration (E.ON ships start+end), and
  // fall back to the spacing between consecutive start timestamps. Declared durations stay
  // correct across gaps in the series, where start-to-start spacing does not.
  const declaredMin = points.filter((p) => p.end != null).map((p) => (p.end! - p.start) / 60000);
  const diffsMin: number[] = [];
  for (let i = 1; i < points.length; i++) {
    const d = (points[i].start - points[i - 1].start) / 60000;
    if (d > 0) diffsMin.push(d);
  }
  // Only trust declared durations when most rows carry one.
  const useDeclared = declaredMin.length >= points.length * 0.9 && declaredMin.length > 0;
  const sample = useDeclared ? declaredMin : diffsMin;
  const stepMinutes = sample.length ? median(sample) : 60;
  const stepMs = stepMinutes * 60000;

  // How regular is the data? (share of intervals equal to the dominant step, within 10%).
  const tol = Math.max(1, stepMinutes * 0.1);
  const matching = sample.filter((d) => Math.abs(d - stepMinutes) <= tol).length;
  const stepConsistencyPct = sample.length
    ? Math.round((matching / sample.length) * 1000) / 10
    : 100;

  const rows: ProductionInterval[] = points.map((p, i) => {
    if (p.end != null) {
      // A declared span far longer than the step is a clock artifact rather than a real
      // duration: at the spring-forward DST switch E.ON writes "01:45 -> 03:00" for a
      // single quarter, because the wall clock jumps an hour. Timestamps here are naive
      // wall-clock, so charging that row 75 minutes would give it five times its true
      // weight in the duration-based metrics. Cap it at the normal step.
      const end = p.end - p.start > 2 * stepMs ? p.start + stepMs : p.end;
      return { start: p.start, end, kwh: p.kwh };
    }
    const next = i + 1 < points.length ? points[i + 1].start : p.start + stepMs;
    // Guard against gaps: cap an interval at the inferred step length.
    const end = Math.min(next, p.start + stepMs);
    return { start: p.start, end: end > p.start ? end : p.start + stepMs, kwh: p.kwh };
  });

  return {
    rows,
    granularity: granularityFromMinutes(stepMinutes),
    stepMinutes,
    stepConsistencyPct,
    datetimeColumn: header[dtIdx] || `col${dtIdx}`,
    productionColumn: header[prodIdx] || `col${prodIdx}`,
  };
}

/** Lowercase Swedish month names, January-first, as used in the "El Rapport" template. */
const SWE_MONTHS = [
  "januari",
  "februari",
  "mars",
  "april",
  "maj",
  "juni",
  "juli",
  "augusti",
  "september",
  "oktober",
  "november",
  "december",
];

function daysInMonth(year: number, month1: number): number {
  return new Date(Date.UTC(year, month1, 0)).getUTCDate();
}

/**
 * Reconstruct an hourly series from the Swedish "El Rapport" Excel template (the
 * monthly-consumption workbook many grid companies hand out). Its visible monthly tabs
 * are formula-only (no cached values), but the hidden "Serie" sheet holds the real
 * hourly numbers as a matrix: one column per month, and 24 consecutive rows per day
 * (hour 0..23), starting just below a header row that lists the month names.
 *
 * Returns "Datum;Värde" CSV text (so the normal CSV path handles intervals/units), or
 * null if the workbook isn't this template.
 */
function reconstructElRapport(sheets: WorkbookSheet[]): string | null {
  const serie = sheets.find((s) => s.name.trim().toLowerCase() === "serie");
  if (!serie) return null;
  const grid = serie.grid;

  // Find the header row that names the months, and which column each month sits in.
  let headerRow = -1;
  const monthCol: number[] = new Array(12).fill(-1);
  for (let r = 0; r < Math.min(grid.length, 6); r++) {
    const row = grid[r];
    let hits = 0;
    const cols = new Array(12).fill(-1);
    for (let c = 0; c < row.length; c++) {
      const idx = SWE_MONTHS.indexOf(row[c].trim().toLowerCase());
      if (idx >= 0 && cols[idx] === -1) {
        cols[idx] = c;
        hits++;
      }
    }
    if (hits >= 6) {
      headerRow = r;
      for (let i = 0; i < 12; i++) monthCol[i] = cols[i];
      break;
    }
  }
  if (headerRow < 0) return null;

  // Find the year (e.g. "2025"), usually in the top-left corner.
  let year = -1;
  for (let r = 0; r < Math.min(grid.length, headerRow + 1); r++) {
    for (const cell of grid[r]) {
      const m = /^(19|20)\d\d$/.exec(cell.trim());
      if (m) {
        year = +m[0];
        break;
      }
    }
    if (year > 0) break;
  }
  if (year < 0) return null;

  const lines = ["Datum;Värde"];
  for (let m = 0; m < 12; m++) {
    const col = monthCol[m];
    if (col < 0) continue;
    const dim = daysInMonth(year, m + 1);
    for (let i = 0; ; i++) {
      const r = headerRow + 1 + i;
      if (r >= grid.length) break;
      const day = Math.floor(i / 24) + 1;
      const hour = i % 24;
      if (day > 31) break; // past this month's block in the matrix
      if (day > dim) continue; // non-existent day (e.g. Feb 30) — skip
      const raw = grid[r][col];
      if (raw == null || raw.trim() === "") continue;
      if (!Number.isFinite(parseNumber(raw))) continue;
      const ts = `${year}-${String(m + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}T${String(
        hour
      ).padStart(2, "0")}:00:00`;
      lines.push(`${ts};${raw}`);
    }
  }
  return lines.length > 1 ? lines.join("\n") : null;
}

/** Turn a worksheet grid into semicolon-delimited text the CSV parser can consume. */
function gridToCsv(grid: string[][]): string {
  return grid
    .map((row) => row.map((c) => (c.includes(";") || c.includes('"') ? `"${c.replace(/"/g, '""')}"` : c)).join(";"))
    .filter((l) => l.replace(/;/g, "").trim() !== "")
    .join("\n");
}

/**
 * Parse an Excel workbook (.xlsx / .xlsm) into a production series. First tries the
 * "El Rapport" monthly-consumption template (data lives in a hidden matrix sheet);
 * otherwise treats each sheet as a plain table and reuses the CSV column detection,
 * keeping whichever sheet yields the most rows.
 */
export async function parseProductionXlsx(
  buf: ArrayBuffer,
  filename = ""
): Promise<ParsedProduction> {
  const wb = await readWorkbook(buf);

  const elRapport = reconstructElRapport(wb.sheets);
  if (elRapport) {
    return parseProductionCsv(elRapport, filename);
  }

  let best: ParsedProduction | null = null;
  let lastErr: unknown = null;
  for (const sheet of wb.sheets) {
    const text = gridToCsv(sheet.grid);
    if (text.split(/\r?\n/).filter((l) => l.trim() !== "").length < 2) continue;
    try {
      const parsed = parseProductionCsv(text, filename);
      if (!best || parsed.rows.length > best.rows.length) best = parsed;
    } catch (e) {
      lastErr = e;
    }
  }
  if (best) return best;
  throw new Error(
    lastErr instanceof Error
      ? `Kunde inte tolka Excel-filen: ${lastErr.message}`
      : "Kunde inte hitta någon datum-/produktionskolumn i Excel-filen."
  );
}

/** Result of validating that a parsed file is in 15-minute (quarter-hour) resolution. */
export interface ResolutionAssessment {
  granularity: Granularity;
  stepMinutes: number;
  consistencyPct: number;
  /** True when the data is in 15-minute (quarter-hour) resolution. */
  isQuarterHour: boolean;
  /** "ok" when it's clean 15-min data, otherwise "warning". */
  level: "ok" | "warning";
  message: string;
}

/**
 * Validate that production data is in 15-minute (quarter-hour) resolution.
 *
 * The analysis is interval-aware and still works for hourly/daily input, but the
 * Swedish market moved to 15-minute settlement on 2025-10-01 and quarter-hour data
 * is required to see negative-price quarters and short export peaks. This surfaces a
 * clear message the UI (and CLI) can show.
 */
export function assessResolution(parsed: ParsedProduction): ResolutionAssessment {
  const { granularity, stepMinutes, stepConsistencyPct } = parsed;
  const base = { granularity, stepMinutes, consistencyPct: stepConsistencyPct };

  if (granularity === "15min") {
    if (stepConsistencyPct < 90) {
      return {
        ...base,
        isQuarterHour: true,
        level: "warning",
        message:
          `Datan ser ut att vara 15-minutersdata, men bara ${stepConsistencyPct}% av intervallen ` +
          `är exakt 15 minuter (ojämn tidsstämpling). Kontrollera filen om resultatet ser fel ut.`,
      };
    }
    return {
      ...base,
      isQuarterHour: true,
      level: "ok",
      message: "Upplösning bekräftad: 15-minutersdata (kvart).",
    };
  }

  const what =
    granularity === "hourly"
      ? "timupplösning (60 minuter)"
      : granularity === "daily"
        ? "dygnsupplösning"
        : `okänd upplösning (~${stepMinutes} min mellan rader)`;
  return {
    ...base,
    isQuarterHour: false,
    level: "warning",
    message:
      `Filen är i ${what}, inte 15-minutersdata. Analysen körs ändå (intervallmedveten), ` +
      `men för att fånga negativa kvartar och korta effekttoppar rekommenderas 15-minutersdata.`,
  };
}

/**
 * Combine several parsed production files into one continuous series. Swedish grid companies
 * often cap 15-minute export downloads at ~3 months at a time, so users have to stitch several
 * chunks together. Rows are merged, sorted by start time, and de-duplicated by start timestamp
 * (chunk boundaries may overlap by a row or two). Granularity/columns are taken from the file
 * with the most rows. `granularitiesMatch` is false if the files weren't all the same resolution.
 */
export function combineProduction(
  parts: ParsedProduction[]
): ParsedProduction & { filesCombined: number; duplicatesRemoved: number; granularitiesMatch: boolean } {
  if (parts.length === 0) throw new Error("Inga filer att kombinera.");
  if (parts.length === 1) {
    return { ...parts[0], filesCombined: 1, duplicatesRemoved: 0, granularitiesMatch: true };
  }
  const all: ProductionInterval[] = parts
    .flatMap((p) => p.rows)
    .sort((a, b) => a.start - b.start);
  const rows: ProductionInterval[] = [];
  let duplicatesRemoved = 0;
  for (const r of all) {
    const prev = rows[rows.length - 1];
    if (prev && prev.start === r.start) {
      duplicatesRemoved += 1; // same interval coming from an overlapping chunk — keep the first
      continue;
    }
    rows.push(r);
  }
  // Use the dominant (most rows) file for granularity/columns; they're the same export type.
  const dominant = [...parts].sort((a, b) => b.rows.length - a.rows.length)[0];
  const granularitiesMatch = parts.every((p) => p.granularity === parts[0].granularity);
  return {
    rows,
    granularity: dominant.granularity,
    stepMinutes: dominant.stepMinutes,
    stepConsistencyPct: dominant.stepConsistencyPct,
    datetimeColumn: dominant.datetimeColumn,
    productionColumn: dominant.productionColumn,
    filesCombined: parts.length,
    duplicatesRemoved,
    granularitiesMatch,
  };
}

/**
 * Start of the Swedish 15-minute (quarter-hour) settlement market: 2025-10-01 00:00
 * Europe/Stockholm wall-clock. Timestamps are stored as `Date.UTC(...local fields)`, so the
 * cutoff is expressed the same way.
 */
export const QUARTER_HOUR_SWITCH_MS = Date.UTC(2025, 9, 1, 0, 0, 0);

/**
 * Drop production rows that start before the 15-minute market switch (2025-10-01). Spot prices
 * were only hourly (60-minute) before that date, so any 15-minute production from earlier can't be
 * matched against quarter-hour prices — the comparison would be misleading. Rows on/after the
 * cutoff are kept untouched. Returns the trimmed series plus how many rows were dropped.
 */
export function dropBeforeQuarterHourSwitch(
  parsed: ParsedProduction
): ParsedProduction & { droppedRows: number } {
  const rows = parsed.rows.filter((r) => r.start >= QUARTER_HOUR_SWITCH_MS);
  return { ...parsed, rows, droppedRows: parsed.rows.length - rows.length };
}
