// Sanity tests for the interval-aware analysis engine.
// Run: node --experimental-strip-types frontend/scripts/test-analyze.mjs
import { analyze, nextFuseStep, prevFuseStep } from "../src/lib/analyze.ts";
import {
  parseProductionCsv,
  parseProductionXlsx,
  assessResolution,
  combineProduction,
  dropBeforeQuarterHourSwitch,
  QUARTER_HOUR_SWITCH_MS,
} from "../src/lib/parseProduction.ts";

let failures = 0;
function approx(actual, expected, label, eps = 1e-6) {
  const ok = Math.abs(actual - expected) <= eps;
  if (!ok) {
    failures++;
    console.error(`  ✗ ${label}: got ${actual}, expected ${expected}`);
  } else {
    console.log(`  ✓ ${label} = ${actual}`);
  }
}

function eq(actual, expected, label) {
  if (actual !== expected) {
    failures++;
    console.error(`  ✗ ${label}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  } else {
    console.log(`  ✓ ${label} = ${JSON.stringify(actual)}`);
  }
}

const H = 3_600_000;
const base = Date.UTC(2025, 10, 3, 0, 0, 0); // 2025-11-03 00:00 wall-clock

// --- Test 1: hourly production x hourly prices (legacy behaviour) ---
console.log("Test 1: hourly x hourly");
{
  const prod = [
    { start: base, end: base + H, kwh: 2 },
    { start: base + H, end: base + 2 * H, kwh: 3 },
  ];
  const prices = [
    { start: base, end: base + H, sekPerKwh: 1.0, eurPerKwh: 0.09 },
    { start: base + H, end: base + 2 * H, sekPerKwh: -0.5, eurPerKwh: -0.045 },
  ];
  const r = analyze(prod, prices, { productionGranularity: "hourly", priceGranularity: "hourly" });
  approx(r.hero.produktion.total_kwh, 5, "total kWh");
  approx(r.hero.produktion.totala_intakter_sek, 0.5, "revenue SEK");
  approx(r.hero.export_förluster.kwh_exporterat_med_förlust, 3, "negative kWh");
  approx(r.hero.export_förluster.kostnad_negativ_export_sek, 1.5, "negative cost SEK");
  approx(r.hero.tidsanalys.totala_intervaller, 2, "total intervals");
  approx(r.hero.tidsanalys.negativa_intervaller, 1, "negative producing intervals");
  approx(r.hero.produktion.genomsnittspris_erhållet_sek_per_kwh, 0.1, "realized price");
  approx(r.hero.produktion.enkelt_snitt_pris_sek_per_kwh, 0.25, "simple avg price");
}

// --- Test 2: hourly production x 15-minute prices (the new market resolution) ---
console.log("Test 2: hourly production x 15-min prices");
{
  const Q = H / 4;
  const prod = [{ start: base, end: base + H, kwh: 4 }];
  const prices = [
    { start: base + 0 * Q, end: base + 1 * Q, sekPerKwh: 1, eurPerKwh: 0 },
    { start: base + 1 * Q, end: base + 2 * Q, sekPerKwh: 1, eurPerKwh: 0 },
    { start: base + 2 * Q, end: base + 3 * Q, sekPerKwh: -2, eurPerKwh: 0 },
    { start: base + 3 * Q, end: base + 4 * Q, sekPerKwh: 1, eurPerKwh: 0 },
  ];
  const r = analyze(prod, prices, { productionGranularity: "hourly", priceGranularity: "15min" });
  approx(r.hero.produktion.total_kwh, 4, "total kWh");
  // 1*1 + 1*1 + 1*(-2) + 1*1 = 1
  approx(r.hero.produktion.totala_intakter_sek, 1, "revenue SEK");
  approx(r.hero.export_förluster.kwh_exporterat_med_förlust, 1, "negative kWh (one quarter)");
  approx(r.hero.export_förluster.kostnad_negativ_export_sek, 2, "negative cost SEK");
  approx(r.hero.tidsanalys.totala_intervaller, 4, "total intervals (4 quarters)");
  // 15-min producing series: the hour splits into 4 quarters.
  eq(r.series.length, 4, "series: 4 quarters");
  approx(r.series[2].spot_sek_per_kwh, -2, "series: quarter 3 spot price");
  approx(r.series[2].production_kwh, 1, "series: quarter 3 production");
  approx(r.hero.tidsanalys.produktionsintervaller, 4, "producing intervals (quarters)");
  approx(r.hero.tidsanalys.negativa_intervaller, 1, "negative price quarters");
}

// --- Test 3: daily production x hourly prices (coarse production, fine prices) ---
console.log("Test 3: daily production x hourly prices");
{
  const D = 24 * H;
  const prod = [{ start: base, end: base + D, kwh: 24 }]; // 24 kWh spread over a day
  const prices = [];
  for (let h = 0; h < 24; h++) {
    prices.push({ start: base + h * H, end: base + (h + 1) * H, sekPerKwh: h < 2 ? -1 : 1, eurPerKwh: 0 });
  }
  const r = analyze(prod, prices, { productionGranularity: "daily", priceGranularity: "hourly" });
  approx(r.hero.produktion.total_kwh, 24, "total kWh");
  // 2 hours negative (1 kWh each) => -2 ; 22 hours positive (1 kWh each) => 22 ; total 20
  approx(r.hero.produktion.totala_intakter_sek, 20, "revenue SEK");
  approx(r.hero.export_förluster.kwh_exporterat_med_förlust, 2, "negative kWh");
  approx(r.hero.tidsanalys.negativa_intervaller, 2, "negative producing intervals (2 hours)");
}

// --- Test 4: fuse / grid-connection flat-peak analysis ---
console.log("Test 4: fuse flat-peak analysis");
{
  // Hour 1: 12 kWh in 1h -> 12 kW (above 16A limit). Hour 2: 5 kWh -> 5 kW (below).
  const prod = [
    { start: base, end: base + H, kwh: 12 },
    { start: base + H, end: base + 2 * H, kwh: 5 },
  ];
  const prices = [
    { start: base, end: base + H, sekPerKwh: 1, eurPerKwh: 0 },
    { start: base + H, end: base + 2 * H, sekPerKwh: 1, eurPerKwh: 0 },
  ];
  const r = analyze(prod, prices, { fuseAmps: 16 });
  const n = r.natanslutning;
  approx(n.sakring_kw, Math.sqrt(3) * 400 * 16 / 1000, "fuse limit kW", 0.01); // ~11.08
  approx(n.hogsta_effekt_kw, 12, "peak power kW");
  approx(n.intervaller_vid_max, 1, "intervals at max (only hour 1)");
  approx(n.andel_tid_vid_max_pct, 50, "share of time at max");
}

// --- Test 5: export compensation + self-consumption valuation ---
console.log("Test 5: export compensation + self-consumption");
{
  const prod = [
    { start: base, end: base + H, kwh: 2 },
    { start: base + H, end: base + 2 * H, kwh: 2 },
  ];
  const prices = [
    { start: base, end: base + H, sekPerKwh: 1.0, eurPerKwh: 0 },
    { start: base + H, end: base + 2 * H, sekPerKwh: 2.0, eurPerKwh: 0 },
  ];
  // realized spot = (2*1 + 2*2)/4 = 1.5 ; spot revenue = 6 ; total = 4 kWh
  // elnät: 5 öre fast + 10% rörlig ; elhandel: 10 öre fast + 0% rörlig
  const r = analyze(prod, prices, {
    vatRate: 25,
    vatRegistered: true,
    gridFixed: 0.05,
    gridPct: 10,
    traderFixed: 0.1,
    traderPct: 0,
    selfEnergyTax: 0.4,
    selfGridFee: 0.6,
  });

  const e = r.exportersattning;
  approx(e.spot_sek_per_kwh, 1.5, "export: spot");
  approx(e.elnat_rorlig_sek_per_kwh, 0.15, "export: elnät rörlig (10% of 1.5)");
  approx(e.elnat_total_sek_per_kwh, 0.2, "export: elnät total (0.05 + 0.15)");
  approx(e.elhandel_total_sek_per_kwh, 0.1, "export: elhandel total (0.10 fast)");
  approx(e.pris_innan_moms_sek_per_kwh, 1.8, "export: price before VAT");
  approx(e.effektivt_pris_sek_per_kwh, 2.25, "export: effective price (incl 25% VAT)");
  approx(e.brytpunkt_spot_sek_per_kwh, -0.15 / 1.1, "export: break-even spot (-totalFixed/(1+loss%))", 1e-4);
  approx(e.spot_total_sek, 6, "export: spot total");
  approx(e.effektiv_total_sek, 9, "export: effective total");
  approx(e.skillnad_mot_spot_sek, 3, "export: uplift vs spot");

  const s = r.sjalvkonsumtion;
  approx(s.spot_sek_per_kwh, 1.5, "self: spot");
  approx(s.varde_self_sek_per_kwh, 3.125, "self: value (spot+tax+fee)*1.25");
  approx(s.export_varde_sek_per_kwh, 2.25, "self: export reference price");
  approx(s.okning_vs_export_sek_per_kwh, 0.875, "self: increment vs export");
  eq(s.manader.length, 1, "self: one month in breakdown");
  approx(s.total_besparing_sek, 3.5, "self: total saving (4 kWh * 0.875)");
  approx(s.manader[0].besparing_sek, 3.5, "self: month saving");
}

// --- Test 5b: blocks are omitted when their inputs are absent ---
console.log("Test 5b: optional blocks omitted without inputs");
{
  const prod = [{ start: base, end: base + H, kwh: 2 }];
  const prices = [{ start: base, end: base + H, sekPerKwh: 1.0, eurPerKwh: 0 }];
  const r = analyze(prod, prices, {}); // no settings at all
  eq(r.exportersattning, undefined, "no export block without inputs");
  eq(r.sjalvkonsumtion, undefined, "no self-consumption block without inputs");
}

// --- Test 6: 15-minute parsing + resolution validation ---
console.log("Test 6: 15-min parsing + resolution validation");
{
  const lines = ["Datum;Produktion kWh"];
  const t0 = Date.UTC(2026, 4, 1, 0, 0, 0); // 2026-05-01 00:00
  for (let i = 0; i < 12; i++) {
    const d = new Date(t0 + i * 15 * 60000);
    const iso = d.toISOString().slice(0, 16).replace("T", " "); // "2026-05-01 00:15"
    lines.push(`${iso};0,${i}`);
  }
  const parsed = parseProductionCsv(lines.join("\n"), "kvart.csv");
  eq(parsed.granularity, "15min", "granularity detected");
  approx(parsed.stepMinutes, 15, "step minutes");
  approx(parsed.stepConsistencyPct, 100, "step consistency %");
  const a = assessResolution(parsed);
  eq(a.isQuarterHour, true, "assessResolution.isQuarterHour");
  eq(a.level, "ok", "assessResolution.level");
}

// --- Test 7: hourly file is flagged as NOT quarter-hour ---
console.log("Test 7: hourly file flagged as not 15-min");
{
  const lines = ["Datum;Produktion kWh"];
  const t0 = Date.UTC(2026, 4, 1, 0, 0, 0);
  for (let i = 0; i < 6; i++) {
    const d = new Date(t0 + i * 60 * 60000);
    const iso = d.toISOString().slice(0, 16).replace("T", " ");
    lines.push(`${iso};1,5`);
  }
  const parsed = parseProductionCsv(lines.join("\n"), "tim.csv");
  eq(parsed.granularity, "hourly", "granularity detected");
  const a = assessResolution(parsed);
  eq(a.isQuarterHour, false, "assessResolution.isQuarterHour");
  eq(a.level, "warning", "assessResolution.level");
}

// --- Test 8: quarters exported at a loss (offset shifts the threshold) ---
console.log("Test 8: export-at-a-loss quarters");
{
  const Q = H / 4;
  const prod = [{ start: base, end: base + H, kwh: 4 }]; // 1 kWh per quarter
  const prices = [
    { start: base + 0 * Q, end: base + 1 * Q, sekPerKwh: 1.0, eurPerKwh: 0 },
    { start: base + 1 * Q, end: base + 2 * Q, sekPerKwh: -0.5, eurPerKwh: 0 },
    { start: base + 2 * Q, end: base + 3 * Q, sekPerKwh: 0.05, eurPerKwh: 0 },
    { start: base + 3 * Q, end: base + 4 * Q, sekPerKwh: 1.0, eurPerKwh: 0 },
  ];
  // 10 öre avdrag from the trader (no loss%, no VAT): effective = spot - 0.10.
  // Break-even spot = 0.10; q2 (-0.5) and q3 (0.05) fall below it -> losses.
  const r = analyze(prod, prices, {
    productionGranularity: "hourly",
    priceGranularity: "15min",
    traderFixed: -0.1,
  });
  const f = r.forlust_export;
  approx(f.antal, 2, "loss: number of quarters");
  approx(f.intervall_minuter, 15, "loss: interval minutes (kvart)");
  approx(f.troskel_spot_sek_per_kwh, 0.1, "loss: spot break-even threshold");
  approx(f.total_kwh, 2, "loss: kWh exported at a loss");
  approx(f.total_forlust_sek, 0.65, "loss: total loss SEK (0.60 + 0.05)");
  approx(f.poster.length, 2, "loss: table rows");
  approx(f.poster[0].forlust_sek, 0.6, "loss: worst row loss (sorted desc)");
  approx(f.poster[0].effektivt_pris_sek_per_kwh, -0.6, "loss: worst row effective price");
  eq(f.serie.length, 1, "loss: one day in series");
}

// --- Test 9: monthly forecast (full months) + daily aggregate ---
console.log("Test 9: monthly forecast + daily aggregate");
{
  const nov1 = Date.UTC(2025, 10, 1, 0, 0, 0);
  const dec31_23 = Date.UTC(2025, 11, 31, 23, 0, 0);
  const prod = [
    { start: nov1, end: nov1 + H, kwh: 10 },
    { start: dec31_23, end: dec31_23 + H, kwh: 20 },
  ];
  const prices = [
    { start: nov1, end: nov1 + H, sekPerKwh: 1.0, eurPerKwh: 0 },
    { start: dec31_23, end: dec31_23 + H, sekPerKwh: 2.0, eurPerKwh: 0 },
  ];
  // Data spans all of Nov + Dec -> both months are "complete". VAT 25%, fixed fees 120/mån.
  const r = analyze(prod, prices, { vatRate: 25, vatRegistered: true, gridMonthlyFee: 100, traderMonthlyFee: 20 });
  const f = r.manads_prognos;
  approx(f.fullstandiga_manader, 2, "forecast: full months");
  approx(f.fasta_avgifter_sek_per_man, 120, "forecast: fixed monthly fees");
  approx(f.snitt_effektiv_ersattning_sek, 31.25, "forecast: avg effective comp (1.25*(10,40))");
  approx(f.snitt_netto_sek, -88.75, "forecast: avg net after fees");
  approx(f.snitt_production_kwh, 15, "forecast: avg production");
  eq(r.aggregates.daily.length, 2, "daily aggregate has 2 days");
}

// --- Test 10: self-consumption quarter-price toggle (realized vs average spot) ---
console.log("Test 10: self-consumption quarter-price toggle");
{
  const prod = [
    { start: base, end: base + H, kwh: 3 }, // more production in the cheap hour
    { start: base + H, end: base + 2 * H, kwh: 1 },
  ];
  const prices = [
    { start: base, end: base + H, sekPerKwh: 1.0, eurPerKwh: 0 },
    { start: base + H, end: base + 2 * H, sekPerKwh: 3.0, eurPerKwh: 0 },
  ];
  // realized (production-weighted) = 1.5 ; average (time-weighted) = 2.0
  const on = analyze(prod, prices, { vatRate: 25, vatRegistered: true, selfEnergyTax: 0.4, selfGridFee: 0.6, selfQuarterPrice: true });
  eq(on.sjalvkonsumtion.kvartpris, true, "self ON: kvartpris flag");
  approx(on.sjalvkonsumtion.spot_sek_per_kwh, 1.5, "self ON: spot basis = realized");
  approx(on.sjalvkonsumtion.varde_self_sek_per_kwh, 3.125, "self ON: value (1.5+0.4+0.6)*1.25");

  const off = analyze(prod, prices, { vatRate: 25, vatRegistered: true, selfEnergyTax: 0.4, selfGridFee: 0.6, selfQuarterPrice: false });
  eq(off.sjalvkonsumtion.kvartpris, false, "self OFF: kvartpris flag");
  approx(off.sjalvkonsumtion.spot_sek_per_kwh, 2.0, "self OFF: spot basis = average");
  approx(off.sjalvkonsumtion.varde_self_sek_per_kwh, 3.75, "self OFF: value (2.0+0.4+0.6)*1.25");
  approx(off.sjalvkonsumtion.export_varde_sek_per_kwh, 1.875, "self OFF: export ref still realized (1.5*1.25)");
}

// --- Test 11: partial month is normalized to a full month ---
console.log("Test 11: partial month normalized to full month");
{
  const prod = [];
  const prices = [];
  const apr1 = Date.UTC(2025, 3, 1, 0, 0, 0); // April (30 days)
  for (let h = 0; h < 15 * 24; h++) {
    const s = apr1 + h * H; // first 15 days only
    prod.push({ start: s, end: s + H, kwh: 1 });
    prices.push({ start: s, end: s + H, sekPerKwh: 1.0, eurPerKwh: 0 });
  }
  // 15 of 30 days covered -> scale 2. No VAT/offsets; fixed 100/mån.
  const r = analyze(prod, prices, { vatRate: 0, gridMonthlyFee: 100 });
  const f = r.manads_prognos;
  approx(f.antal_manader, 1, "forecast: months included");
  approx(f.fullstandiga_manader, 0, "forecast: complete months (April partial)");
  eq(f.manader[0].complete, false, "forecast: April flagged not complete");
  approx(f.manader[0].dagar_med_data, 15, "forecast: covered days");
  approx(f.manader[0].dagar_i_manad, 30, "forecast: days in month");
  approx(f.manader[0].production_kwh, 720, "forecast: normalized production (360*2)");
  approx(f.manader[0].netto_sek, 620, "forecast: net (720 - 100 fixed)");
}

// --- Test 12: fuse upgrade worthiness ---
console.log("Test 12: fuse upgrade");
{
  eq(nextFuseStep(20), 25, "nextFuseStep(20) = 25");
  eq(nextFuseStep(16), 20, "nextFuseStep(16) = 20");
  eq(nextFuseStep(250), undefined, "nextFuseStep(250) = undefined (top)");

  // 16 A @ 400 V ≈ 11.08 kW. Build 24h of 15-min producing intervals that sit AT the cap
  // (so every quarter is "vid max"), priced at a positive spot, over 1 day. Next step = 20 A.
  const H = 3_600_000;
  const Q = H / 4;
  const d0 = Date.UTC(2025, 5, 1, 0, 0, 0);
  const capKw = (Math.sqrt(3) * 400 * 16) / 1000; // ≈ 11.08
  const prod = [];
  const prices = [];
  for (let i = 0; i < 96; i++) {
    const s = d0 + i * Q;
    prod.push({ start: s, end: s + Q, kwh: capKw * 0.25 }); // power == cap
    prices.push({ start: s, end: s + Q, sekPerKwh: 1.0, eurPerKwh: 0 });
  }
  const r = analyze(prod, prices, {
    productionGranularity: "15min",
    priceGranularity: "15min",
    fuseAmps: 16,
    vatRate: 0,
    gridMonthlyFee: 200,
    nextFuseMonthlyFee: 275, // +75/mån -> +900/år
  });
  const u = r.sakringsuppgradering;
  if (!u) {
    failures++;
    console.error("  ✗ sakringsuppgradering missing");
  } else {
    eq(u.nuvarande_sakring_amp, 16, "upgrade: current fuse 16 A");
    eq(u.nasta_sakring_amp, 20, "upgrade: next fuse 20 A");
    eq(u.kvartar_vid_max, 96, "upgrade: 96 sustained quarters (all consecutive)");
    approx(u.extra_avgift_kr_per_man, 75, "upgrade: +75 kr/mån");
    approx(u.extra_avgift_kr_per_ar, 900, "upgrade: +900 kr/år");
    // Headroom = (20-16)/16 * capKw ≈ 0.25*11.08 = 2.77 kW over 24h = 66.5 kWh unlocked/day,
    // at spot 1.0 (no VAT/offsets) => ~66.5 kr/day. Just check it's positive and annualizes up.
    const ok = u.uppskattat_extra_varde_sek > 0 && u.uppskattat_extra_varde_per_ar_sek > u.uppskattat_extra_varde_sek;
    if (ok) console.log(`  ✓ upgrade: unlocked value positive & annualized (${u.uppskattat_extra_varde_per_ar_sek}/år)`);
    else {
      failures++;
      console.error(`  ✗ upgrade: unlocked value annualization off (${JSON.stringify(u)})`);
    }
  }

  // 12b: isolated single maxed quarters (not consecutive) must NOT count as clipping.
  {
    const prod2 = [];
    const prices2 = [];
    for (let i = 0; i < 96; i++) {
      const s = d0 + i * Q;
      // Every OTHER quarter at the cap, the rest near zero -> no two in a row.
      prod2.push({ start: s, end: s + Q, kwh: i % 2 === 0 ? capKw * 0.25 : 0.001 });
      prices2.push({ start: s, end: s + Q, sekPerKwh: 1.0, eurPerKwh: 0 });
    }
    const r2 = analyze(prod2, prices2, {
      productionGranularity: "15min", priceGranularity: "15min",
      fuseAmps: 16, vatRate: 0, gridMonthlyFee: 200, nextFuseMonthlyFee: 275,
    });
    eq(r2.sakringsuppgradering.kvartar_vid_max, 0, "upgrade: isolated peaks don't count (need ≥2 in a row)");
    approx(r2.sakringsuppgradering.uppskattat_extra_varde_sek, 0, "upgrade: no sustained clipping -> 0 unlocked");
  }

  // 12c: installed kWp below the next fuse limit bounds the headroom (and flags it).
  {
    const r3 = analyze(prod, prices, {
      productionGranularity: "15min", priceGranularity: "15min",
      fuseAmps: 16, vatRate: 0, gridMonthlyFee: 200, nextFuseMonthlyFee: 275,
      installedKwp: 11.2, // just above 16 A cap (~11.08 kW), well below 20 A (~13.86 kW)
    });
    const u3 = r3.sakringsuppgradering;
    eq(u3.begransas_av_kwp, true, "upgrade: flagged kWp-bounded");
    // Headroom now min(13.86,11.2)-11.08 ≈ 0.12 kW << full 2.77 kW -> much less unlocked value.
    const less = u3.uppskattat_extra_varde_sek < u.uppskattat_extra_varde_sek;
    if (less) console.log(`  ✓ upgrade: kWp bound shrinks unlocked value (${u3.uppskattat_extra_varde_sek} < ${u.uppskattat_extra_varde_sek})`);
    else { failures++; console.error(`  ✗ upgrade: kWp bound did not shrink value (${JSON.stringify(u3)})`); }
  }
}

// --- Test 13: combine multiple production files (3-month chunks) ---
console.log("Test 13: combine multi-file");
{
  const Q = 3_600_000 / 4;
  const d = Date.UTC(2025, 0, 1, 0, 0, 0);
  const mk = (rows) => ({
    rows,
    granularity: "15min",
    stepMinutes: 15,
    stepConsistencyPct: 100,
    datetimeColumn: "Datum",
    productionColumn: "kWh",
  });
  // Two chunks; the second repeats the last row of the first (overlapping boundary).
  const a = mk([
    { start: d, end: d + Q, kwh: 1 },
    { start: d + Q, end: d + 2 * Q, kwh: 2 },
  ]);
  const b = mk([
    { start: d + Q, end: d + 2 * Q, kwh: 2 }, // duplicate boundary row
    { start: d + 2 * Q, end: d + 3 * Q, kwh: 3 },
  ]);
  const c = combineProduction([b, a]); // pass out of order on purpose
  eq(c.filesCombined, 2, "combine: files combined = 2");
  eq(c.rows.length, 3, "combine: 3 unique rows after dedup");
  eq(c.duplicatesRemoved, 1, "combine: 1 overlapping row removed");
  eq(c.granularitiesMatch, true, "combine: granularities match");
  approx(c.rows[0].start, d, "combine: sorted, first row earliest");
  approx(c.rows[2].kwh, 3, "combine: last row kept");
  // Single-file passthrough.
  const one = combineProduction([a]);
  eq(one.filesCombined, 1, "combine: single file passthrough");
  eq(one.rows.length, 2, "combine: single file rows unchanged");
}

// --- Test 14: asymmetric VAT (sales only if momsregistrerad; buy side always) ---
console.log("Test 14: asymmetric VAT");
{
  const prod = [{ start: base, end: base + H, kwh: 4 }];
  const prices = [{ start: base, end: base + H, sekPerKwh: 1.0, eurPerKwh: 0 }];
  const opts = { vatRate: 25, gridFixed: 0.1, selfEnergyTax: 0.4, selfGridFee: 0.6 };

  // Not VAT-registered (default): export is paid ex-moms; self-use still avoids moms on buying.
  const notReg = analyze(prod, prices, opts);
  approx(notReg.exportersattning.effektivt_pris_sek_per_kwh, 1.1, "export ex-moms (1.0 + 0.10)");
  eq(notReg.exportersattning.moms_pa_forsaljning, false, "flag: no VAT on sales");
  approx(notReg.sjalvkonsumtion.varde_self_sek_per_kwh, 2.5, "self value WITH moms ((1+0.4+0.6)*1.25)");
  approx(notReg.sjalvkonsumtion.export_varde_sek_per_kwh, 1.1, "self export ref ex-moms");
  // Self-use beats export by the avoided 25% on buying + the lost export uplift.
  approx(notReg.sjalvkonsumtion.okning_vs_export_sek_per_kwh, 1.4, "self increment vs export (2.5 - 1.1)");

  // VAT-registered: export gets +25% too.
  const reg = analyze(prod, prices, { ...opts, vatRegistered: true });
  approx(reg.exportersattning.effektivt_pris_sek_per_kwh, 1.375, "export incl moms (1.1 * 1.25)");
  eq(reg.exportersattning.moms_pa_forsaljning, true, "flag: VAT on sales");
  approx(reg.sjalvkonsumtion.varde_self_sek_per_kwh, 2.5, "self value unchanged (buy side always moms)");
  approx(reg.sjalvkonsumtion.export_varde_sek_per_kwh, 1.375, "self export ref incl moms");
}

// --- Test 15: daily spot averaged over STRÅNG sunlit hours ---
console.log("Test 15: daily spot over sunlit hours");
{
  const prod = [];
  const prices = [];
  for (let h = 0; h < 4; h++) {
    prod.push({ start: base + h * H, end: base + (h + 1) * H, kwh: 1 });
    prices.push({ start: base + h * H, end: base + (h + 1) * H, sekPerKwh: h + 1, eurPerKwh: 0 });
  }
  // Mark only hours 01 and 02 as sunlit (spots 2 and 3).
  const sunlit = new Set(["2025-11-03T01", "2025-11-03T02"]);
  const r = analyze(prod, prices, {
    productionGranularity: "hourly",
    priceGranularity: "hourly",
    sunlitHourKeys: sunlit,
  });
  const day = r.aggregates.daily.find((d) => d.date === "2025-11-03");
  approx(day.spot_sunlit_sek_per_kwh, 2.5, "sunlit: daily avg over sunlit hours = (2+3)/2");

  const r2 = analyze(prod, prices, { productionGranularity: "hourly", priceGranularity: "hourly" });
  const day2 = r2.aggregates.daily.find((d) => d.date === "2025-11-03");
  eq(day2.spot_sunlit_sek_per_kwh, undefined, "no sunlit set -> field undefined");
}

// --- Test 16: "% at the cap" measured over sunlit (or producing) quarters ---
console.log("Test 16: fuse share over sunlit/producing quarters");
{
  // Hours: 12,12,1,0 kWh -> powers 12,12,1,0 kW; fuse 16 A (~11.08) -> hours 0,1 at max.
  const prod = [12, 12, 1, 0].map((kwh, h) => ({ start: base + h * H, end: base + (h + 1) * H, kwh }));
  const prices = [0, 1, 2, 3].map((_, h) => ({ start: base + h * H, end: base + (h + 1) * H, sekPerKwh: 1, eurPerKwh: 0 }));

  // No location: denominator = producing quarters (3: hours 0,1,2) -> 2/3 = 66.7%.
  const noLoc = analyze(prod, prices, { fuseAmps: 16 }).natanslutning;
  approx(noLoc.intervaller_vid_max, 2, "share: 2 quarters at max");
  eq(noLoc.andel_bas_soltimmar, false, "share: not sunlit-based without location");
  approx(noLoc.namnare_kvartar, 3, "share: denominator = producing quarters");
  approx(noLoc.andel_tid_vid_max_pct, 66.7, "share: 2/3 of producing time");

  // With STRÅNG sunlit set covering all 4 hours -> denominator 4 -> 2/4 = 50%.
  const sunlit = new Set(["2025-11-03T00", "2025-11-03T01", "2025-11-03T02", "2025-11-03T03"]);
  const loc = analyze(prod, prices, { fuseAmps: 16, sunlitHourKeys: sunlit }).natanslutning;
  eq(loc.andel_bas_soltimmar, true, "share: sunlit-based with STRÅNG");
  approx(loc.namnare_kvartar, 4, "share: denominator = sunlit quarters");
  approx(loc.andel_tid_vid_max_pct, 50, "share: 2/4 of sunlit time");
}

// --- Test 17: fuse downgrade (smaller fuse: fee saving vs clipped peaks) ---
console.log("Test 17: fuse downgrade");
{
  eq(prevFuseStep(20), 16, "prevFuseStep(20) = 16");
  eq(prevFuseStep(16), undefined, "prevFuseStep(16) = undefined (smallest)");

  // Current 20 A (~13.86 kW). Lower = 16 A (~11.08 kW). One hour at 13 kW (above 11.08),
  // one at 5 kW (below). Lowering clips (13 - 11.08) kWh that hour.
  const lowerKw = (Math.sqrt(3) * 400 * 16) / 1000;
  const prod = [
    { start: base, end: base + H, kwh: 13 },
    { start: base + H, end: base + 2 * H, kwh: 5 },
  ];
  const prices = [
    { start: base, end: base + H, sekPerKwh: 1, eurPerKwh: 0 },
    { start: base + H, end: base + 2 * H, sekPerKwh: 1, eurPerKwh: 0 },
  ];
  const r = analyze(prod, prices, { fuseAmps: 20, vatRate: 0, gridMonthlyFee: 250, lowerFuseMonthlyFee: 150 });
  const d = r.sakringsnedgradering;
  eq(d.lagre_sakring_amp, 16, "downgrade: lower fuse 16 A");
  approx(d.sparad_avgift_kr_per_man, 100, "downgrade: saving 100/mån");
  approx(d.sparad_avgift_kr_per_ar, 1200, "downgrade: saving 1200/år");
  eq(d.kvartar_over_lagre_tak, 1, "downgrade: 1 quarter above lower limit");
  approx(d.kapad_export_kwh, 13 - lowerKw, "downgrade: clipped kWh = 13 - 11.08", 0.05);
  approx(d.kapat_varde_sek, (13 - lowerKw) * 1, "downgrade: clipped value at spot 1", 0.05);
  // Over-period figures: clipped value is the period total (= kapat_varde_sek), saving is
  // scaled to the period, and netto = period saving − period clipped value.
  approx(d.netto_over_period_sek, d.sparad_avgift_over_period_sek - d.kapat_varde_sek, "downgrade: netto över perioden", 0.02);
  eq(typeof d.vart_att_sanka, "boolean", "downgrade: verdict present");

  // No lower-fee given -> no block.
  const r2 = analyze(prod, prices, { fuseAmps: 20 });
  eq(r2.sakringsnedgradering, undefined, "downgrade: omitted without lower fee");
}

// --- Helpers: build a minimal .xlsx (ZIP of XML parts) in memory for parser tests ---
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
async function deflateRaw(bytes) {
  const cs = new CompressionStream("deflate-raw");
  const stream = new Blob([bytes]).stream().pipeThrough(cs);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
async function buildXlsx(parts) {
  const enc = new TextEncoder();
  const files = parts.map((p) => ({ name: p.name, raw: enc.encode(p.xml) }));
  const chunks = [];
  const central = [];
  let offset = 0;
  for (const f of files) {
    const comp = await deflateRaw(f.raw);
    const crc = crc32(f.raw);
    const nameBytes = enc.encode(f.name);
    const lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true);
    lh.setUint16(4, 20, true); // version needed
    lh.setUint16(6, 0, true); // flags
    lh.setUint16(8, 8, true); // method = deflate
    lh.setUint32(14, crc, true);
    lh.setUint32(18, comp.length, true);
    lh.setUint32(22, f.raw.length, true);
    lh.setUint16(26, nameBytes.length, true);
    chunks.push(new Uint8Array(lh.buffer), nameBytes, comp);
    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true);
    ch.setUint16(4, 20, true);
    ch.setUint16(6, 20, true);
    ch.setUint16(10, 8, true);
    ch.setUint32(16, crc, true);
    ch.setUint32(20, comp.length, true);
    ch.setUint32(24, f.raw.length, true);
    ch.setUint16(28, nameBytes.length, true);
    ch.setUint32(42, offset, true);
    central.push({ header: new Uint8Array(ch.buffer), nameBytes });
    offset += 30 + nameBytes.length + comp.length;
  }
  const cdStart = offset;
  let cdSize = 0;
  for (const c of central) {
    chunks.push(c.header, c.nameBytes);
    cdSize += c.header.length + c.nameBytes.length;
  }
  const eocd = new DataView(new ArrayBuffer(22));
  eocd.setUint32(0, 0x06054b50, true);
  eocd.setUint16(8, files.length, true);
  eocd.setUint16(10, files.length, true);
  eocd.setUint32(12, cdSize, true);
  eocd.setUint32(16, cdStart, true);
  chunks.push(new Uint8Array(eocd.buffer));
  const total = chunks.reduce((s, c) => s + c.length, 0);
  const out = new Uint8Array(total);
  let pos = 0;
  for (const c of chunks) {
    out.set(c, pos);
    pos += c.length;
  }
  return out.buffer;
}
const WORKBOOK_RELS =
  '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
  '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
  '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
  "</Relationships>";
function inlineCell(ref, text) {
  return `<c r="${ref}" t="inlineStr"><is><t>${text}</t></is></c>`;
}
function numCell(ref, value, style) {
  return `<c r="${ref}"${style != null ? ` s="${style}"` : ""}><v>${value}</v></c>`;
}
function sheetXml(rows) {
  const body = rows
    .map((cells, i) => `<row r="${i + 1}">${cells.join("")}</row>`)
    .join("");
  return (
    '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    `<sheetData>${body}</sheetData></worksheet>`
  );
}
function workbookXml(sheetName) {
  return (
    '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
    `<sheets><sheet name="${sheetName}" sheetId="1" r:id="rId1"/></sheets></workbook>`
  );
}

// --- Test 18: generic .xlsx table (date serials + numeric values) ---
console.log("Test 18: xlsx generic table + serial dates");
{
  const styles =
    '<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs></styleSheet>';
  const epoch = Date.UTC(1899, 11, 30);
  const serial = (ms) => (ms - epoch) / 86400000;
  const day0 = Date.UTC(2025, 5, 1, 0, 0, 0); // 2025-06-01
  const rows = [[inlineCell("A1", "Datum"), inlineCell("B1", "Värde")]];
  for (let h = 0; h < 4; h++) {
    const s = serial(day0 + h * H);
    rows.push([numCell(`A${h + 2}`, s, 1), numCell(`B${h + 2}`, (h + 1).toString())]);
  }
  const buf = await buildXlsx([
    { name: "[Content_Types].xml", xml: '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>' },
    { name: "xl/workbook.xml", xml: workbookXml("Blad1") },
    { name: "xl/_rels/workbook.xml.rels", xml: WORKBOOK_RELS },
    { name: "xl/styles.xml", xml: styles },
    { name: "xl/worksheets/sheet1.xml", xml: sheetXml(rows) },
  ]);
  const p = await parseProductionXlsx(buf, "general.xlsx");
  eq(p.rows.length, 4, "xlsx generic: 4 rows parsed");
  eq(p.granularity, "hourly", "xlsx generic: hourly granularity");
  approx(p.rows[0].start, day0, "xlsx generic: first serial date decoded to 2025-06-01 00:00");
  approx(p.rows[0].kwh, 1, "xlsx generic: first value");
  approx(p.rows[3].kwh, 4, "xlsx generic: last value");
}

// --- Test 19: "El Rapport" template (hidden Serie matrix, formula-only month tabs) ---
console.log("Test 19: xlsx El Rapport Serie matrix");
{
  // Header row 2 names the months; January sits at col L (index 12), February col M (13).
  // Data rows below: 24 consecutive rows per day (hour 0..23). We give day 1 hours 0..2.
  const rows = [];
  rows.push([inlineCell("A1", "2025")]); // year, top-left
  // Full month header row at cols L..W (Jan..Dec), as in the real template.
  const MONTHS = ["januari","Februari","Mars","April","Maj","Juni","Juli","Augusti","September","Oktober","November","December"];
  const MONTH_COLS = ["L","M","N","O","P","Q","R","S","T","U","V","W"];
  rows.push(MONTHS.map((name, i) => inlineCell(`${MONTH_COLS[i]}2`, name))); // month headers
  // Day 1, hours 0..2 for January (col L) and February (col M).
  rows.push([numCell("L3", "3.262"), numCell("M3", "9.9")]); // hour 0
  rows.push([numCell("L4", "1.13"), numCell("M4", "8.8")]); // hour 1
  rows.push([numCell("L5", "6.768"), numCell("M5", "7.7")]); // hour 2
  const buf = await buildXlsx([
    { name: "xl/workbook.xml", xml: workbookXml("Serie") },
    { name: "xl/_rels/workbook.xml.rels", xml: WORKBOOK_RELS.replace(/<Relationship Id="rId2"[^/]*\/>/, "") },
    { name: "xl/worksheets/sheet1.xml", xml: sheetXml(rows) },
  ]);
  const p = await parseProductionXlsx(buf, "El_Rapport.xlsm");
  // 3 hours for January + 3 for February = 6 rows.
  eq(p.rows.length, 6, "El Rapport: 6 hourly values reconstructed");
  const jan0 = p.rows.find((r) => {
    const d = new Date(r.start);
    return d.getUTCMonth() === 0 && d.getUTCDate() === 1 && d.getUTCHours() === 0;
  });
  approx(jan0.kwh, 3.262, "El Rapport: Jan-01 00:00 = 3.262 (Serie!L3)");
  const feb1 = p.rows.find((r) => {
    const d = new Date(r.start);
    return d.getUTCMonth() === 1 && d.getUTCDate() === 1 && d.getUTCHours() === 1;
  });
  approx(feb1.kwh, 8.8, "El Rapport: Feb-01 01:00 = 8.8 (Serie!M4)");
  eq(p.granularity, "hourly", "El Rapport: hourly granularity");
}

// --- Test 20: drop production before the 2025-10-01 15-minute market switch ---
console.log("Test 20: drop data before 2025-10-01");
{
  eq(QUARTER_HOUR_SWITCH_MS, Date.UTC(2025, 9, 1, 0, 0, 0), "cutoff = 2025-10-01 00:00");
  const mk = (rows) => ({
    rows,
    granularity: "15min",
    stepMinutes: 15,
    stepConsistencyPct: 100,
    datetimeColumn: "Datum",
    productionColumn: "kWh",
  });
  const before = QUARTER_HOUR_SWITCH_MS - 60 * 60 * 1000; // 2025-09-30 23:00
  const atCut = QUARTER_HOUR_SWITCH_MS; // 2025-10-01 00:00
  const after = QUARTER_HOUR_SWITCH_MS + 60 * 60 * 1000;
  const parsed = mk([
    { start: before, end: before + 9e5, kwh: 1 },
    { start: atCut, end: atCut + 9e5, kwh: 2 },
    { start: after, end: after + 9e5, kwh: 3 },
  ]);
  const trimmed = dropBeforeQuarterHourSwitch(parsed);
  eq(trimmed.droppedRows, 1, "dropped 1 row before cutoff");
  eq(trimmed.rows.length, 2, "kept 2 rows (on/after cutoff)");
  approx(trimmed.rows[0].start, atCut, "first kept row starts exactly at the cutoff");
  eq(trimmed.granularity, "15min", "granularity preserved");
  eq(trimmed.datetimeColumn, "Datum", "columns preserved");

  // All-before case: everything dropped.
  const allBefore = dropBeforeQuarterHourSwitch(mk([{ start: before, end: before + 9e5, kwh: 1 }]));
  eq(allBefore.rows.length, 0, "all-before: nothing kept");
  eq(allBefore.droppedRows, 1, "all-before: 1 dropped");
}

// --- Test 21: E.ON "Mätvärdesexport" CSV (metadata preamble + start/end + direction) ---
console.log("Test 21: E.ON Mätvärdesexport format");
{
  const eon = [
    "﻿Anläggnings-id;Tidpunkt för export;Energiprodukt;Starttidpunkt;Sluttidpunkt;Måttenhet",
    "735999114013307011;2026-07-30 12:57:06;Aktiv energi;2025-10-01 00:00:00;2025-10-01 01:00:00;kWh",
    "",
    "Starttidpunkt;Sluttidpunkt;Energiriktning;Kvalitet;Kvantitet",
    "2025-10-01 00:00:00;2025-10-01 00:15:00;Produktion;Uppmätt;0,100",
    "2025-10-01 00:15:00;2025-10-01 00:30:00;Produktion;Uppmätt;0,200",
    "2025-10-01 00:30:00;2025-10-01 00:45:00;Produktion;Uppmätt;0,300",
    "2025-10-01 00:45:00;2025-10-01 01:00:00;Produktion;Uppmätt;0,400",
  ].join("\n");
  const p = parseProductionCsv(eon);
  eq(p.rows.length, 4, "eon: metadata preamble skipped, 4 data rows");
  eq(p.datetimeColumn, "Starttidpunkt", "eon: datetime column from the real header");
  eq(p.productionColumn, "Kvantitet", "eon: value column is Kvantitet, not Energiriktning");
  eq(p.granularity, "15min", "eon: 15-min granularity");
  eq(p.stepMinutes, 15, "eon: step from declared start/end");
  approx(p.rows.reduce((s, r) => s + r.kwh, 0), 1.0, "eon: total kWh");
  approx(p.rows[0].end - p.rows[0].start, 15 * 60 * 1000, "eon: interval end taken from Sluttidpunkt");
  eq(assessResolution(p).isQuarterHour, true, "eon: passes 15-min validation");

  // Mixed-direction export: consumption rows must not be summed into production.
  const mixed = [
    "Starttidpunkt;Sluttidpunkt;Energiriktning;Kvalitet;Kvantitet",
    "2025-10-01 00:00:00;2025-10-01 00:15:00;Produktion;Uppmätt;1,000",
    "2025-10-01 00:00:00;2025-10-01 00:15:00;Förbrukning;Uppmätt;9,000",
    "2025-10-01 00:15:00;2025-10-01 00:30:00;Produktion;Uppmätt;2,000",
    "2025-10-01 00:15:00;2025-10-01 00:30:00;Förbrukning;Uppmätt;9,000",
  ].join("\n");
  const pm = parseProductionCsv(mixed);
  eq(pm.rows.length, 2, "eon mixed: consumption rows filtered out");
  approx(pm.rows.reduce((s, r) => s + r.kwh, 0), 3.0, "eon mixed: only production summed");

  // Unit declared in the metadata block rather than the value column header.
  const mwh = [
    "Anläggnings-id;Måttenhet",
    "735999;MWh",
    "",
    "Starttidpunkt;Sluttidpunkt;Energiriktning;Kvalitet;Kvantitet",
    "2025-10-01 00:00:00;2025-10-01 00:15:00;Produktion;Uppmätt;1,000",
    "2025-10-01 00:15:00;2025-10-01 00:30:00;Produktion;Uppmätt;2,000",
  ].join("\n");
  approx(
    parseProductionCsv(mwh).rows.reduce((s, r) => s + r.kwh, 0),
    3000,
    "eon: MWh from metadata converted to kWh"
  );

  // Spring-forward DST: E.ON writes 01:45 -> 03:00 for one quarter (wall clock jumps).
  const dst = [
    "Starttidpunkt;Sluttidpunkt;Energiriktning;Kvalitet;Kvantitet",
    "2026-03-29 01:15:00;2026-03-29 01:30:00;Produktion;Uppmätt;1,000",
    "2026-03-29 01:30:00;2026-03-29 01:45:00;Produktion;Uppmätt;1,000",
    "2026-03-29 01:45:00;2026-03-29 03:00:00;Produktion;Uppmätt;1,000",
    "2026-03-29 03:00:00;2026-03-29 03:15:00;Produktion;Uppmätt;1,000",
  ].join("\n");
  const pd = parseProductionCsv(dst);
  const lengths = [...new Set(pd.rows.map((r) => (r.end - r.start) / 60000))];
  eq(lengths.length, 1, "eon DST: no over-long interval survives");
  eq(lengths[0], 15, "eon DST: 75-minute wall-clock gap capped to the 15-min step");
}

// --- Test 22: fixed monthly fees are optional -> smaller report ---
console.log("Test 22: optional fixed monthly fees");
{
  const prod = [];
  const prices = [];
  // One full month of hourly data so the forecast block is produced.
  for (let h = 0; h < 24 * 31; h++) {
    const t = Date.UTC(2025, 9, 1) + h * H;
    prod.push({ start: t, end: t + H, kwh: 1 });
    prices.push({ start: t, end: t + H, sekPerKwh: 1.0, eurPerKwh: 0 });
  }
  const withoutFees = analyze(prod, prices, { fuseAmps: 20, nextFuseMonthlyFee: 500, lowerFuseMonthlyFee: 300 });
  eq(withoutFees.manads_prognos.har_fasta_avgifter, false, "no fees: flagged as missing");
  eq(withoutFees.manads_prognos.snitt_netto_sek, undefined, "no fees: net omitted, not computed vs 0 kr");
  eq(withoutFees.manads_prognos.fasta_avgifter_sek_per_man, undefined, "no fees: fee field omitted");
  eq(withoutFees.manads_prognos.manader[0].netto_sek, undefined, "no fees: per-month net omitted");
  eq(withoutFees.manads_prognos.snitt_production_kwh > 0, true, "no fees: production still reported");
  eq(withoutFees.manads_prognos.snitt_effektiv_ersattning_sek > 0, true, "no fees: compensation still reported");
  // The fuse verdicts compare against the current fee, so they need it.
  eq(withoutFees.sakringsuppgradering, undefined, "no current fee: upgrade verdict omitted");
  eq(withoutFees.sakringsnedgradering, undefined, "no current fee: downgrade verdict omitted");

  const withFees = analyze(prod, prices, {
    fuseAmps: 20,
    gridMonthlyFee: 400,
    nextFuseMonthlyFee: 500,
    lowerFuseMonthlyFee: 300,
  });
  eq(withFees.manads_prognos.har_fasta_avgifter, true, "with fees: flagged present");
  approx(withFees.manads_prognos.fasta_avgifter_sek_per_man, 400, "with fees: fee reported");
  eq(typeof withFees.manads_prognos.snitt_netto_sek, "number", "with fees: net computed");
  approx(withFees.sakringsuppgradering.extra_avgift_kr_per_man, 100, "with fees: upgrade delta 500-400");
  approx(withFees.sakringsnedgradering.sparad_avgift_kr_per_man, 100, "with fees: downgrade saving 400-300");

  // Only the trader fee given: still enough to report a net.
  const traderOnly = analyze(prod, prices, { traderMonthlyFee: 59 });
  eq(traderOnly.manads_prognos.har_fasta_avgifter, true, "trader fee only: net still reported");
  approx(traderOnly.manads_prognos.fasta_avgifter_sek_per_man, 59, "trader fee only: fee = 59");
  eq(traderOnly.manads_prognos.elnat_avgift_sek_per_man, undefined, "trader fee only: grid fee omitted");
}

console.log(failures === 0 ? "\nALL PASSED" : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
