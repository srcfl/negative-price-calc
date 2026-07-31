"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Badge,
  Button,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@sourceful-energy/ui";
import {
  Zap,
  TrendingDown,
  Clock,
  Coins,
  AlertTriangle,
  Download,
  FileJson,
  Sparkles,
  Plug,
  PiggyBank,
  Banknote,
  TrendingDown as TrendingDownIcon,
  CalendarDays,
  Info,
  SlidersHorizontal,
  ArrowUpCircle,
  ArrowDownCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { PriceChart } from "./price-chart";
import { LossChart } from "./loss-chart";
import { FuseChart } from "./fuse-chart";

interface AnalysisData {
  hero?: {
    // New nested structure
    produktion?: {
      total_kwh?: number;
      totala_intakter_sek?: number;
      genomsnittspris_erhållet_sek_per_kwh?: number;
      enkelt_snitt_pris_sek_per_kwh?: number;
      timing_förlust_pct?: number;
    };
    export_förluster?: {
      intervaller_som_kostat_dig?: number;
      kwh_exporterat_med_förlust?: number;
      andel_olönsam_export_pct?: number;
      kostnad_negativ_export_sek?: number;
    };
    tidsanalys?: {
      intervall_minuter?: number;
      totala_intervaller?: number;
      produktionsintervaller?: number;
      negativa_intervaller_totalt?: number;
      negativa_intervaller?: number;
    };
    tekniska_mått?: {
      hours_total?: number;
      hours_producing?: number;
      hours_negative_total?: number;
      hours_negative_during_production?: number;
      production_kwh?: number;
      revenue_sek?: number;
      negative_value_sek?: number;
      realized_price_wavg_sek_per_kwh?: number;
      simple_average_price_sek_per_kwh?: number;
      timing_discount_pct?: number;
    };
    // Legacy flat structure (fallback)
    production_kwh?: number;
    revenue_sek?: number;
    hours_negative_total?: number;
    hours_total?: number;
    negative_value_sek?: number;
    realized_price_wavg_sek_per_kwh?: number;
    simple_average_price_sek_per_kwh?: number;
  };
  ai_explanation_sv?: string;
  input?: {
    date_range?: {
      start?: string;
      end?: string;
      start_utc?: string;
      end_utc?: string;
    };
    granularity?: string;
  };
  aggregates?: {
    monthly?: Array<{
      period?: string;
      month?: string;
      production_kwh?: number;
      revenue_sek?: number;
      avg_price_sek_per_kwh?: number;
      negative_intervaller?: number;
      negative_kwh?: number;
      negative_value_sek?: number;
    }>;
    daily?: Array<{
      date?: string;
      production_kwh?: number;
      revenue_sek?: number;
      negative_kwh?: number;
      negative_value_sek?: number;
    }>;
  };
  manads_prognos?: {
    antal_manader?: number;
    fullstandiga_manader?: number;
    /** False when no fixed monthly fee was entered — the net columns are then omitted. */
    har_fasta_avgifter?: boolean;
    elnat_avgift_sek_per_man?: number;
    elhandel_avgift_sek_per_man?: number;
    fasta_avgifter_sek_per_man?: number;
    manader?: Array<{
      period?: string;
      complete?: boolean;
      dagar_med_data?: number;
      dagar_i_manad?: number;
      production_kwh?: number;
      effektiv_ersattning_sek?: number;
      fasta_avgifter_sek?: number;
      netto_sek?: number;
    }>;
    snitt_production_kwh?: number;
    snitt_effektiv_ersattning_sek?: number;
    snitt_netto_sek?: number;
  };
  natanslutning?: {
    sakring_amp?: number;
    sakring_kw?: number;
    hogsta_effekt_kw?: number;
    intervaller_vid_max?: number;
    andel_tid_vid_max_pct?: number;
    andel_bas_soltimmar?: boolean;
    namnare_kvartar?: number;
    energi_vid_max_kwh?: number;
    serie?: Array<{ date?: string; peak_kw?: number }>;
  };
  sakringsuppgradering?: {
    nuvarande_sakring_amp?: number;
    nuvarande_sakring_kw?: number;
    nasta_sakring_amp?: number;
    nasta_sakring_kw?: number;
    nuvarande_avgift_kr_per_man?: number;
    nasta_avgift_kr_per_man?: number;
    extra_avgift_kr_per_man?: number;
    extra_avgift_kr_per_ar?: number;
    extra_avgift_over_period_sek?: number;
    kvartar_vid_max?: number;
    installerad_kwp?: number;
    begransas_av_kwp?: boolean;
    period_dagar?: number;
    uppskattad_extra_export_kwh?: number;
    uppskattat_extra_varde_sek?: number;
    uppskattad_extra_export_kwh_per_ar?: number;
    uppskattat_extra_varde_per_ar_sek?: number;
    netto_over_period_sek?: number;
    netto_per_ar_sek?: number;
    vart_att_uppgradera?: boolean;
  };
  sakringsnedgradering?: {
    nuvarande_sakring_amp?: number;
    nuvarande_sakring_kw?: number;
    lagre_sakring_amp?: number;
    lagre_sakring_kw?: number;
    nuvarande_avgift_kr_per_man?: number;
    lagre_avgift_kr_per_man?: number;
    sparad_avgift_kr_per_man?: number;
    sparad_avgift_kr_per_ar?: number;
    sparad_avgift_over_period_sek?: number;
    kvartar_over_lagre_tak?: number;
    period_dagar?: number;
    kapad_export_kwh?: number;
    kapat_varde_sek?: number;
    kapad_export_kwh_per_ar?: number;
    kapat_varde_per_ar_sek?: number;
    netto_over_period_sek?: number;
    netto_per_ar_sek?: number;
    vart_att_sanka?: boolean;
  };
  forlust_export?: {
    antal?: number;
    intervall_minuter?: number;
    troskel_spot_sek_per_kwh?: number;
    total_kwh?: number;
    total_forlust_sek?: number;
    poster?: Array<{
      start?: string;
      spot_sek_per_kwh?: number;
      effektivt_pris_sek_per_kwh?: number;
      kwh?: number;
      forlust_sek?: number;
    }>;
    serie?: Array<{ date?: string; forlust_sek?: number }>;
  };
  exportersattning?: {
    moms_pct?: number;
    moms_pa_forsaljning?: boolean;
    spot_sek_per_kwh?: number;
    elnat_fast_sek_per_kwh?: number;
    elnat_pct?: number;
    elnat_rorlig_sek_per_kwh?: number;
    elnat_total_sek_per_kwh?: number;
    elhandel_fast_sek_per_kwh?: number;
    elhandel_pct?: number;
    elhandel_rorlig_sek_per_kwh?: number;
    elhandel_total_sek_per_kwh?: number;
    pris_innan_moms_sek_per_kwh?: number;
    effektivt_pris_sek_per_kwh?: number;
    brytpunkt_spot_sek_per_kwh?: number;
    spot_total_sek?: number;
    effektiv_total_sek?: number;
    skillnad_mot_spot_sek?: number;
  };
  sjalvkonsumtion?: {
    moms_pct?: number;
    kvartpris?: boolean;
    spot_sek_per_kwh?: number;
    energiskatt_sek_per_kwh?: number;
    natavgift_sek_per_kwh?: number;
    varde_self_sek_per_kwh?: number;
    export_varde_sek_per_kwh?: number;
    okning_vs_export_sek_per_kwh?: number;
    manader?: Array<{
      period?: string;
      production_kwh?: number;
      varde_self_sek_per_kwh?: number;
      export_varde_sek_per_kwh?: number;
      besparing_sek?: number;
    }>;
    total_besparing_sek?: number;
  };
  meta?: {
    price_granularity?: string;
    price_intervals?: number;
    production_intervals?: number;
    matched_kwh_pct?: number;
  };
  solinstralning?: {
    kwh_per_m2?: number;
    potentiell_produktion_kwh?: number;
    kwp?: number;
    from?: string;
    to?: string;
  };
  parametrar?: {
    elomrade?: string;
    huvudsakring_a?: string;
    moms_pct?: string;
    momsregistrerad?: boolean;
    elnat_fast_ore_per_kwh?: string;
    elnat_rorlig_pct?: string;
    elhandel_fast_ore_per_kwh?: string;
    elhandel_rorlig_pct?: string;
    elnat_manadsavgift_kr?: string;
    elnat_manadsavgift_nasta_sakring_kr?: string;
    elnat_manadsavgift_lagre_sakring_kr?: string;
    installerad_kwp?: string;
    elhandel_manadsavgift_kr?: string;
    energiskatt_ore_per_kwh?: string;
    natavgift_ore_per_kwh?: string;
    kvartspris_elhandel?: boolean;
  };
}

interface AnalysisResultsProps {
  data: AnalysisData;
  metadata: {
    filename: string;
    area: string;
    currency: string;
    granularity?: string;
  };
  onDownloadXlsx: () => void;
  onDownloadJson: () => void;
}

function formatNumber(value: number | undefined, decimals = 0): string {
  if (value === undefined || value === null) return "-";
  return value.toLocaleString("sv-SE", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatCurrency(value: number | undefined): string {
  if (value === undefined || value === null) return "-";
  return `${formatNumber(value, 2)} kr`;
}

/** Small per-kWh amounts are shown in öre (1 kr = 100 öre). */
function formatOre(valueSek: number | undefined, decimals = 1): string {
  if (valueSek === undefined || valueSek === null) return "-";
  return `${formatNumber(valueSek * 100, decimals)} öre`;
}

/** Signed öre, e.g. "+8,0 öre" / "−2,0 öre" — for adjustments that can be negative. */
function formatOreSigned(valueSek: number | undefined, decimals = 1): string {
  if (valueSek === undefined || valueSek === null) return "-";
  const sign = valueSek > 0 ? "+" : valueSek < 0 ? "−" : "";
  return `${sign}${formatNumber(Math.abs(valueSek) * 100, decimals)} öre`;
}

/** Format a "YYYY-MM" period as "maj 2026". */
function formatMonth(period: string | undefined): string {
  if (!period) return "";
  const m = period.match(/^(\d{4})-(\d{2})/);
  if (!m) return period;
  const months = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
  return `${months[parseInt(m[2], 10) - 1]} ${m[1]}`;
}

/** Format a wall-clock ISO timestamp as "15 maj 13:45" (no timezone shift). */
function formatLossTime(iso: string | undefined): string {
  if (!iso) return "";
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return iso;
  const months = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
  return `${parseInt(m[3], 10)} ${months[parseInt(m[2], 10) - 1]} ${m[4]}:${m[5]}`;
}

/** Format an interval as "15 maj 14:00–14:15" given the start and its length in minutes. */
function formatLossRange(iso: string | undefined, minutes: number | undefined): string {
  const start = formatLossTime(iso);
  if (!iso || !minutes || minutes <= 0) return start;
  const m = iso.match(/^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})/);
  if (!m) return start;
  const endTotal = (parseInt(m[1], 10) * 60 + parseInt(m[2], 10) + Math.round(minutes)) % (24 * 60);
  const eh = String(Math.floor(endTotal / 60)).padStart(2, "0");
  const em = String(endTotal % 60).padStart(2, "0");
  return `${start}–${eh}:${em}`;
}

function formatSwedishDate(dateStr: string | undefined): string {
  if (!dateStr) return "";
  const months = [
    "jan", "feb", "mar", "apr", "maj", "jun",
    "jul", "aug", "sep", "okt", "nov", "dec"
  ];
  const date = new Date(dateStr);
  const day = date.getDate();
  const month = months[date.getMonth()];
  const year = date.getFullYear();
  return `${day} ${month} ${year}`;
}

const TOTAL_EXPORT_INFO = "Summan av all el du matat ut på nätet under perioden (kWh).";
const TOTAL_REVENUE_INFO =
  "Värdet av din export till rena spotpriset (SEK), summerat över perioden – före påslag/avgifter och moms.";
const NEG_QUARTERS_INFO =
  "Antal kvartar (15 min) då själva spotpriset var negativt medan du exporterade – ett mått på din marknadsexponering, räknat på rå spot (utan offset). Om du faktiskt gick med förlust beror på dina offset: ”Kostnad negativa priser” och ”Kvartar du exporterade med förlust” räknas offset-medvetet (effektivt pris under brytpunkten), och kan därför gälla färre kvartar.";
const NEG_COST_INFO =
  "Vad det kostade dig totalt att exportera när ditt effektiva pris var under noll (spotpris under brytpunkten, inkl. förlustersättning/påslag och moms). Samma offset-medvetna belopp som ”uppskattad total förlust” längre ner – inte enbart råspot.";
const EXPORT_COMP_INFO =
  "Vad du faktiskt får betalt för exporten = (spot + förlustersättning [elnät] + påslag/avdrag [elhandel]) × 1,25 (moms, om momsregistrerad). De rörliga delarna räknas på spotpriset i varje kvart du exporterade (produktionsviktat), inte på ett tidssnitt.";
const FORECAST_INFO =
  "Förväntad ekonomi per hel månad: effektiv ersättning minus fasta månadsavgifter. Delmånader räknas upp till en hel månad.";
const SELF_INFO =
  "Hur mycket du skulle spara på att använda elen själv i stället för att exportera den (sparat inköp = spot + energiskatt + nätavgift, × moms).";
const LOSS_INFO =
  "Kvartar då ditt effektiva pris var under noll – du betalade för att exportera. Tabellen visar de värst drabbade tillfällena.";
const GRID_INFO =
  "Hur ofta din exporteffekt nådde huvudsäkringens gräns (kapade toppar). Diagrammet visar daglig toppeffekt mot säkringsgränsen.";
const POTENTIAL_PROD_INFO =
  "Grov uppskattning av hur mycket anläggningen kunde ha producerat under perioden = solinstrålning (SMHI STRÅNG) × installerad effekt (kWp) × 0,82 (riktverkningsgrad). Bygger på global horisontell instrålning, så paneltak/-riktning ignoreras – en övre referens, inte en garanti. ”export X%” = din uppmätta export delat med detta.";
const KVARTAR_VID_MAX_INFO =
  "Antal kvartar (15 min) då exporteffekten låg vid säkringstaket (≥98 % av gränsen). Andelen mäts mot den tid du faktiskt kan exportera: SMHI STRÅNG:s soltimmar (timmar då solen var uppe) när en plats är vald, annars de kvartar du producerade. Natten räknas inte med – du kan ändå inte exportera då.";
const PEAK_POWER_INFO =
  "Den högsta medeleffekten (kW) under en enskild kvart – din kraftigaste exporttopp. Jämför med säkringsgränsen i diagrammet nedan.";
const UPGRADE_INFO =
  "Väger den högre abonnemangsavgiften för nästa säkringssteg mot det (optimistiskt uppskattade) värdet av den export en större säkring hade frigjort under de kvartar du slår i taket. Frigjord export sker mitt på dagen när spotpriset ofta är lågt, så värdet är litet.";
const DOWNGRADE_INFO =
  "Väger den lägre abonnemangsavgiften för ett steg mindre säkring mot exporten du då skulle kapa (effekten över den lägre gränsen). Till skillnad från uppgraderingen är detta konkret – det räknas på din faktiska produktion, eftersom vi ser exakt vad som hade kapats. Lönar sig om besparingen är större än det kapade värdet per år.";
const TIMING_INFO =
  "Hur mycket lägre (eller högre) pris du fick jämfört med marknadens enkla snittpris för perioden. Solel produceras mest mitt på dagen då spotpriset ofta är lägre.";
const REALIZED_PRICE_INFO =
  "Det volymviktade snittpriset du faktiskt fick – totala intäkter delat med exporterad kWh. Varje kWh viktas med priset i den kvart den exporterades.";
const MARKET_AVG_INFO =
  "Enkelt snittpris (spot) över hela perioden, oavsett om du producerade just då.";

/**
 * A small info icon that reveals an explanation. On desktop it opens on hover/focus; on
 * touch devices (where Radix tooltips never open on hover) a tap toggles it. It's a
 * controlled tooltip: the tap handler runs on `pointerDown` and calls `preventDefault()`,
 * which—via Radix's composed event handlers—skips the built-in "close on pointer down" so
 * the tap reliably toggles instead of being swallowed. Tapping outside or pressing Escape
 * closes it.
 */
function InfoTooltip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);

  // Close when tapping/clicking anywhere that isn't this trigger or the tooltip bubble.
  useEffect(() => {
    if (!open) return;
    const onDocPointerDown = (e: PointerEvent) => {
      const t = e.target as Element | null;
      if (t?.closest('[role="tooltip"]') || t?.closest("[data-info-tooltip-trigger]")) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", onDocPointerDown, true);
    return () => document.removeEventListener("pointerdown", onDocPointerDown, true);
  }, [open]);

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label="Förklaring"
            aria-expanded={open}
            data-info-tooltip-trigger
            onPointerDown={(e) => {
              e.preventDefault(); // skip Radix's close-on-pointer-down so the tap toggles
              setOpen((o) => !o);
            }}
            className="inline-flex align-middle text-muted-foreground hover:text-foreground"
          >
            <Info className="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <p className="text-xs leading-relaxed">{text}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function getGranularityLabel(granularity: string | undefined): string {
  switch (granularity?.toLowerCase()) {
    case "hourly":
      return "Timdata (60 min)";
    case "15min":
    case "15-min":
    case "quarterly":
      return "PT15M (15 min)";
    case "daily":
      return "Dygnsdata";
    default:
      return granularity || "";
  }
}

/** Short resolution label used inline (e.g. for the price badge). */
function getGranularityShort(granularity: string | undefined): string {
  switch (granularity?.toLowerCase()) {
    case "hourly":
      return "60 min";
    case "15min":
    case "15-min":
    case "quarterly":
      return "15 min (kvart)";
    case "daily":
      return "dygn";
    default:
      return granularity || "okänd";
  }
}

/** True when a granularity string represents quarter-hour (15-minute) resolution. */
function isQuarterHour(granularity: string | undefined): boolean {
  const g = granularity?.toLowerCase();
  return g === "15min" || g === "15-min" || g === "quarterly";
}

/**
 * Label an interval count in the data's native resolution unit, e.g. "4 992 kvartar"
 * for 15-minute data, "52 dygn" for daily, "X intervall" otherwise.
 */
function intervalCountLabel(granularity: string | undefined, count: number | undefined): string {
  if (count == null) return "";
  switch (granularity?.toLowerCase()) {
    case "15min":
    case "15-min":
    case "quarterly":
      return `${formatNumber(count)} kvartar`;
    case "daily":
      return `${formatNumber(count)} dygn`;
    default:
      return `${formatNumber(count)} intervall`;
  }
}

export function AnalysisResults({
  data,
  metadata,
  onDownloadXlsx,
  onDownloadJson,
}: AnalysisResultsProps) {
  const hero = data.hero || {};

  // Extract values from new nested structure or fallback to legacy flat structure
  const produktion = hero.produktion || {};
  const tidsanalys = hero.tidsanalys || {};
  const tekniskaMatt = hero.tekniska_mått || {};

  // Use Swedish structure first, then tekniska_mått, then legacy flat
  const totalExport = produktion.total_kwh ?? tekniskaMatt.production_kwh ?? hero.production_kwh;
  const totalRevenue = produktion.totala_intakter_sek ?? tekniskaMatt.revenue_sek ?? hero.revenue_sek;
  const totalIntervals = tidsanalys.totala_intervaller;
  // Offset-aware: the cost of exporting when the *effective* price was below zero (spot under
  // the break-even, incl. förlustersättning/påslag + moms) — same figure as the loss-quarters
  // card. Absent loss block = no effective-loss quarters = 0 (not the raw spot cost).
  const negativeCost = data.forlust_export?.total_forlust_sek ?? 0;
  const realizedPrice = produktion.genomsnittspris_erhållet_sek_per_kwh ?? tekniskaMatt.realized_price_wavg_sek_per_kwh ?? hero.realized_price_wavg_sek_per_kwh;
  const avgPrice = produktion.enkelt_snitt_pris_sek_per_kwh ?? tekniskaMatt.simple_average_price_sek_per_kwh ?? hero.simple_average_price_sek_per_kwh;

  // Negative-price exposure counted in intervals (≈ quarters for 15-min data).
  const negativeIntervals = tidsanalys.negativa_intervaller;
  const producingIntervalCount = tidsanalys.produktionsintervaller;
  const negativeIntervalPct =
    producingIntervalCount && negativeIntervals != null
      ? ((negativeIntervals / producingIntervalCount) * 100).toFixed(1)
      : null;

  // Positive = your realized price was LOWER than the period's simple average (a "discount").
  const timingDiscountPct =
    realizedPrice != null && avgPrice
      ? ((avgPrice - realizedPrice) / avgPrice) * 100
      : produktion.timing_förlust_pct ?? tekniskaMatt.timing_discount_pct ?? null;

  // Extract date range info
  const startDate = data.input?.date_range?.start ?? data.input?.date_range?.start_utc?.split("T")[0];
  const endDate = data.input?.date_range?.end ?? data.input?.date_range?.end_utc?.split("T")[0];
  const productionGranularity = data.input?.granularity || metadata.granularity;
  const granularityLabel = getGranularityLabel(productionGranularity);
  const priceGranularity = data.meta?.price_granularity;
  const computesOnQuarters = isQuarterHour(productionGranularity) || isQuarterHour(priceGranularity);
  const intervalLabel = intervalCountLabel(productionGranularity, totalIntervals);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-3">
          <div>
            <h2 className="text-2xl font-bold text-foreground">Analysresultat</h2>
            <p className="text-muted-foreground">
              {metadata.filename} &bull; {metadata.area}
            </p>
          </div>

          {/* Prominent Date Range */}
          {startDate && endDate && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary/10 border border-primary/20">
                  <Clock className="h-4 w-4 text-primary" />
                  <span className="font-medium text-foreground">
                    {formatSwedishDate(startDate)} → {formatSwedishDate(endDate)}
                  </span>
                </div>
                {granularityLabel && (
                  <Badge variant="secondary" className="text-sm">
                    Produktion: {granularityLabel}
                    {intervalLabel ? ` (${intervalLabel})` : ""}
                  </Badge>
                )}
                {priceGranularity && (
                  <Badge variant="outline" className="text-sm">
                    Priser: {getGranularityShort(priceGranularity)}
                  </Badge>
                )}
              </div>
              {computesOnQuarters && (
                <p className="text-xs text-muted-foreground">
                  Beräknat intervallmedvetet per kvart (15 minuter) – produktion och spotpriser
                  matchas mot varandra på 15-minutersupplösning.
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onDownloadJson}>
            <FileJson className="h-4 w-4 mr-2" />
            JSON
          </Button>
          <Button variant="default" size="sm" onClick={onDownloadXlsx}>
            <Download className="h-4 w-4 mr-2" />
            CSV
          </Button>
        </div>
      </div>

      {/* Hero Metrics */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
              Total export <InfoTooltip text={TOTAL_EXPORT_INFO} />
            </CardTitle>
            <Zap className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">
              {formatNumber(totalExport)} <span className="text-lg">kWh</span>
            </div>
            {data.solinstralning?.potentiell_produktion_kwh != null ? (
              <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                ≈ {formatNumber(data.solinstralning.potentiell_produktion_kwh, 0)} kWh möjlig produktion
                {(totalExport ?? 0) > 0 && data.solinstralning.potentiell_produktion_kwh > 0
                  ? ` · export ${formatNumber(((totalExport ?? 0) / data.solinstralning.potentiell_produktion_kwh) * 100, 0)}%`
                  : ""}
                <InfoTooltip text={POTENTIAL_PROD_INFO} />
              </p>
            ) : data.solinstralning?.kwh_per_m2 != null ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Instrålning {formatNumber(data.solinstralning.kwh_per_m2, 0)} kWh/m² – ange kWp för möjlig produktion.
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
              Total intäkt <InfoTooltip text={TOTAL_REVENUE_INFO} />
            </CardTitle>
            <Coins className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">
              {formatCurrency(totalRevenue)}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
              {isQuarterHour(productionGranularity) ? "Negativa priskvartar" : "Negativa prisintervall"}{" "}
              <InfoTooltip text={NEG_QUARTERS_INFO} />
            </CardTitle>
            <Clock className="h-4 w-4 text-destructive" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">
              {formatNumber(negativeIntervals)}
              {negativeIntervalPct != null && (
                <span className="text-lg text-muted-foreground ml-2">({negativeIntervalPct}%)</span>
              )}
            </div>
          </CardContent>
        </Card>

        <Card className={negativeCost && negativeCost > 0 ? "border-destructive/50" : ""}>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
              Kostnad negativa priser <InfoTooltip text={NEG_COST_INFO} />
            </CardTitle>
            <AlertTriangle className="h-4 w-4 text-destructive" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-destructive">
              {formatCurrency(negativeCost)}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Timing discount */}
      {timingDiscountPct != null && (
        <Card className="border-primary/20 bg-primary/5">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <TrendingDown className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Timing-rabatt</CardTitle>
              <InfoTooltip text={TIMING_INFO} />
            </div>
            <CardDescription>
              Hur mycket {timingDiscountPct >= 0 ? "lägre" : "högre"} pris du fick jämfört med periodens snittpris –
              solel produceras mest mitt på dagen, då spotpriset ofta är {timingDiscountPct >= 0 ? "lägre" : "högre"}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold font-mono text-primary">
                {Math.abs(timingDiscountPct).toFixed(1)}%
              </span>
              <span className="text-muted-foreground">
                {timingDiscountPct >= 0 ? "lägre" : "högre"} pris än marknadens snitt
              </span>
            </div>
            <div className="mt-2 text-sm text-muted-foreground">
              Realiserat pris <InfoTooltip text={REALIZED_PRICE_INFO} /> {formatOre(realizedPrice)}/kWh
              {" "}vs marknadens snitt <InfoTooltip text={MARKET_AVG_INFO} /> {formatOre(avgPrice)}/kWh.
            </div>
          </CardContent>
        </Card>
      )}

      {/* Grid connection (main fuse) peaks */}
      {data.natanslutning && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Plug className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Nätanslutning</CardTitle>
              <InfoTooltip text={GRID_INFO} />
            </div>
            <CardDescription>
              Hur ofta din export nådde huvudsäkringens gräns ({formatNumber(data.natanslutning.sakring_amp)} A
              ≈ {formatNumber(data.natanslutning.sakring_kw, 1)} kW)
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <div className="text-2xl font-bold font-mono">
                  {formatNumber(data.natanslutning.intervaller_vid_max)}{" "}
                  <span className="text-base">{isQuarterHour(productionGranularity) ? "kvartar" : "intervall"}</span>
                </div>
                <p className="flex items-center gap-1 text-sm text-muted-foreground">
                  vid max ({formatNumber(data.natanslutning.andel_tid_vid_max_pct, 1)}% av{" "}
                  {data.natanslutning.andel_bas_soltimmar ? "soltimmarna" : "produktionstiden"})
                  <InfoTooltip text={KVARTAR_VID_MAX_INFO} />
                </p>
              </div>
              <div>
                <div className="text-2xl font-bold font-mono">
                  {formatNumber(data.natanslutning.hogsta_effekt_kw, 1)} <span className="text-base">kW</span>
                </div>
                <p className="flex items-center gap-1 text-sm text-muted-foreground">
                  högsta uppmätta effekt
                  <InfoTooltip text={PEAK_POWER_INFO} />
                </p>
              </div>
            </div>
            {data.natanslutning.serie && data.natanslutning.serie.length > 0 && (
              <div className="mt-4">
                <p className="text-sm text-muted-foreground mb-2">Daglig toppeffekt mot säkringsgränsen:</p>
                <FuseChart serie={data.natanslutning.serie} limitKw={data.natanslutning.sakring_kw} />
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Fuse upgrade worthiness */}
      {data.sakringsuppgradering && (
        <Card className={data.sakringsuppgradering.vart_att_uppgradera ? "border-primary/30" : ""}>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <ArrowUpCircle className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Är det värt att uppgradera huvudsäkringen?</CardTitle>
              <InfoTooltip text={UPGRADE_INFO} />
            </div>
            <CardDescription>
              Från {formatNumber(data.sakringsuppgradering.nuvarande_sakring_amp)} A
              {" "}(≈ {formatNumber(data.sakringsuppgradering.nuvarande_sakring_kw, 1)} kW) till{" "}
              {formatNumber(data.sakringsuppgradering.nasta_sakring_amp)} A
              {" "}(≈ {formatNumber(data.sakringsuppgradering.nasta_sakring_kw, 1)} kW)
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <div
                className={`text-2xl font-bold ${
                  data.sakringsuppgradering.vart_att_uppgradera ? "text-primary" : "text-destructive"
                }`}
              >
                {data.sakringsuppgradering.vart_att_uppgradera ? "Kan löna sig" : "Lönar sig troligen inte"}
              </div>
              <p className="text-sm text-muted-foreground">
                Bästa fall netto över perioden ({formatNumber(data.sakringsuppgradering.period_dagar, 0)} dgr):{" "}
                <span className="font-mono font-semibold text-foreground">
                  {formatCurrency(data.sakringsuppgradering.netto_over_period_sek)}
                </span>{" "}
                <span className="text-xs">(≈ {formatCurrency(data.sakringsuppgradering.netto_per_ar_sek)}/år)</span>
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <div className="text-xl font-bold font-mono text-destructive">
                  +{formatCurrency(data.sakringsuppgradering.extra_avgift_over_period_sek)}
                </div>
                <p className="text-sm text-muted-foreground">
                  högre abonnemang över perioden (+{formatCurrency(data.sakringsuppgradering.extra_avgift_kr_per_man)}/mån)
                </p>
              </div>
              <div>
                <div className="text-xl font-bold font-mono">
                  {formatNumber(data.sakringsuppgradering.uppskattad_extra_export_kwh, 0)} kWh
                </div>
                <p className="text-sm text-muted-foreground">uppskattad frigjord export (bästa fall)</p>
              </div>
              <div>
                <div className="text-xl font-bold font-mono text-primary">
                  {formatCurrency(data.sakringsuppgradering.uppskattat_extra_varde_sek)}
                </div>
                <p className="text-sm text-muted-foreground">värde av den frigjorda exporten</p>
              </div>
            </div>

            <div className="rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-sm text-muted-foreground space-y-1">
              <p className="font-medium text-foreground">Antaganden</p>
              <ul className="list-disc space-y-0.5 pl-4">
                <li>
                  Endast <span className="font-medium text-foreground">sammanhängande</span> kapning räknas: {formatNumber(data.sakringsuppgradering.kvartar_vid_max)}{" "}
                  kvartar där du slog i taket minst två kvartar i rad, under{" "}
                  {formatNumber(data.sakringsuppgradering.period_dagar, 0)} dagars data (enstaka toppar ignoreras). Siffrorna avser den inlästa perioden; /år är en uppräkning.
                </li>
                <li>
                  Bästa fall: antar att produktionen de kvartarna kunnat nå{" "}
                  {data.sakringsuppgradering.installerad_kwp != null
                    ? `upp till ${formatNumber(Math.min(data.sakringsuppgradering.installerad_kwp ?? 0, data.sakringsuppgradering.nasta_sakring_kw ?? 0), 1)} kW (lägst av nästa säkring och din effekt ${formatNumber(data.sakringsuppgradering.installerad_kwp, 1)} kWp)`
                    : `hela vägen upp till ${formatNumber(data.sakringsuppgradering.nasta_sakring_kw, 1)} kW`}
                  {" "}(frigjord effekt × tid).
                </li>
                {data.sakringsuppgradering.begransas_av_kwp && (
                  <li className="text-foreground">
                    Din installerade effekt ({formatNumber(data.sakringsuppgradering.installerad_kwp, 1)} kWp) ligger under nästa
                    säkrings gräns – det är panelerna, inte säkringen, som sätter taket för hur mycket mer du kan exportera.
                  </li>
                )}
                <li>
                  Den frigjorda exporten sker mitt på dagen då spotpriset ofta är lågt eller negativt – därför värderas den
                  till det effektiva priset just de kvartarna, inte snittet.
                </li>
                <li>
                  Den faktiskt &quot;kapade&quot; produktionen går inte att mäta exakt utan data bakom mätaren; detta är en
                  optimistisk övre gräns.
                </li>
              </ul>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Fuse downgrade worthiness */}
      {data.sakringsnedgradering && (
        <Card className={data.sakringsnedgradering.vart_att_sanka ? "border-primary/30" : ""}>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <ArrowDownCircle className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Skulle det löna sig att sänka huvudsäkringen?</CardTitle>
              <InfoTooltip text={DOWNGRADE_INFO} />
            </div>
            <CardDescription>
              Från {formatNumber(data.sakringsnedgradering.nuvarande_sakring_amp)} A
              {" "}(≈ {formatNumber(data.sakringsnedgradering.nuvarande_sakring_kw, 1)} kW) till{" "}
              {formatNumber(data.sakringsnedgradering.lagre_sakring_amp)} A
              {" "}(≈ {formatNumber(data.sakringsnedgradering.lagre_sakring_kw, 1)} kW)
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <div
                className={`text-2xl font-bold ${
                  data.sakringsnedgradering.vart_att_sanka ? "text-primary" : "text-destructive"
                }`}
              >
                {data.sakringsnedgradering.vart_att_sanka ? "Kan löna sig" : "Lönar sig troligen inte"}
              </div>
              <p className="text-sm text-muted-foreground">
                Netto över perioden ({formatNumber(data.sakringsnedgradering.period_dagar, 0)} dgr):{" "}
                <span className="font-mono font-semibold text-foreground">
                  {formatCurrency(data.sakringsnedgradering.netto_over_period_sek)}
                </span>{" "}
                <span className="text-xs">(≈ {formatCurrency(data.sakringsnedgradering.netto_per_ar_sek)}/år)</span>
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <div className="text-xl font-bold font-mono text-primary">
                  +{formatCurrency(data.sakringsnedgradering.sparad_avgift_over_period_sek)}
                </div>
                <p className="text-sm text-muted-foreground">
                  lägre abonnemang över perioden (+{formatCurrency(data.sakringsnedgradering.sparad_avgift_kr_per_man)}/mån)
                </p>
              </div>
              <div>
                <div className="text-xl font-bold font-mono text-destructive">
                  {formatNumber(data.sakringsnedgradering.kapad_export_kwh, 0)} kWh
                </div>
                <p className="text-sm text-muted-foreground">
                  kapad export ({formatNumber(data.sakringsnedgradering.kvartar_over_lagre_tak)} kvartar över gränsen)
                </p>
              </div>
              <div>
                <div className="text-xl font-bold font-mono text-destructive">
                  −{formatCurrency(data.sakringsnedgradering.kapat_varde_sek)}
                </div>
                <p className="text-sm text-muted-foreground">förlorat exportvärde över perioden</p>
              </div>
            </div>

            <div className="rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
              {data.sakringsnedgradering.kapad_export_kwh != null && data.sakringsnedgradering.kapad_export_kwh <= 0 ? (
                <p>
                  Din effekt överskred aldrig {formatNumber(data.sakringsnedgradering.lagre_sakring_kw, 1)} kW under perioden –
                  en lägre säkring hade inte kapat något, så du sparar abonnemanget utan förlust.
                </p>
              ) : (
                <p>
                  Konkret uppskattning från din faktiska produktion: bara energin <span className="text-foreground">mellan den lägre
                  gränsen ({formatNumber(data.sakringsnedgradering.lagre_sakring_kw, 1)} kW) och vad du producerade</span> räknas som kapad.
                  Siffrorna avser den inlästa perioden ({formatNumber(data.sakringsnedgradering.period_dagar, 0)} dgr); /år är en uppräkning.
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Effective export compensation (what you actually get paid) */}
      {data.exportersattning && (
        <Card className="border-primary/20 bg-primary/5">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Banknote className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Ersättning för exporterad el</CardTitle>
              <InfoTooltip text={EXPORT_COMP_INFO} />
            </div>
            <CardDescription>
              Vad du faktiskt får betalt per exporterad kWh{" "}
              {data.exportersattning.moms_pa_forsaljning
                ? `(inkl. ${formatNumber(data.exportersattning.moms_pct, 0)}% moms)`
                : "(utan moms – ej momsregistrerad)"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {data.exportersattning.brytpunkt_spot_sek_per_kwh !== undefined ? (
              <div>
                <div className="text-sm text-muted-foreground">Du säljer med förlust när spotpriset går under</div>
                <div className="text-3xl font-bold font-mono text-destructive">
                  {formatOre(data.exportersattning.brytpunkt_spot_sek_per_kwh)}/kWh
                </div>
              </div>
            ) : (
              <div className="flex items-baseline gap-2">
                <span
                  className={`text-3xl font-bold font-mono ${
                    (data.exportersattning.effektivt_pris_sek_per_kwh ?? 0) < 0 ? "text-destructive" : "text-primary"
                  }`}
                >
                  {formatOre(data.exportersattning.effektivt_pris_sek_per_kwh)}/kWh
                </span>
                <span className="text-muted-foreground">effektivt pris</span>
              </div>
            )}
            <div className="mt-3 space-y-0.5 text-sm text-muted-foreground">
              <div>Spotpris: {formatOre(data.exportersattning.spot_sek_per_kwh)}/kWh</div>
              <div>
                Elnätsbolag (förlustersättning): {formatOreSigned(data.exportersattning.elnat_total_sek_per_kwh)}/kWh
                {" "}— fast {formatOreSigned(data.exportersattning.elnat_fast_sek_per_kwh)} + rörlig {formatOreSigned(data.exportersattning.elnat_rorlig_sek_per_kwh)} ({formatNumber(data.exportersattning.elnat_pct, 1)}%)
              </div>
              <div>
                Elhandelsbolag (påslag/avdrag): {formatOreSigned(data.exportersattning.elhandel_total_sek_per_kwh)}/kWh
                {" "}— fast {formatOreSigned(data.exportersattning.elhandel_fast_sek_per_kwh)} + rörlig {formatOreSigned(data.exportersattning.elhandel_rorlig_sek_per_kwh)} ({formatNumber(data.exportersattning.elhandel_pct, 1)}%)
              </div>
              <div>
                Innan moms: {formatOre(data.exportersattning.pris_innan_moms_sek_per_kwh)}/kWh ×{" "}
                {(1 + (data.exportersattning.moms_pct ?? 0) / 100).toLocaleString("sv-SE", { maximumFractionDigits: 4 })}{" "}
                {data.exportersattning.moms_pa_forsaljning ? "(moms)" : "(ingen moms – ej momsregistrerad)"}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-baseline gap-x-6 gap-y-1">
              <span className="text-sm">
                Totalt beräknad intäkt:{" "}
                <span className="font-mono font-semibold text-base text-foreground">{formatCurrency(data.exportersattning.effektiv_total_sek)}</span>
              </span>
              <span className="text-sm text-muted-foreground">
                Effektivt pris i snitt:{" "}
                <span className={`font-mono ${(data.exportersattning.effektivt_pris_sek_per_kwh ?? 0) < 0 ? "text-destructive" : "text-foreground"}`}>
                  {formatOre(data.exportersattning.effektivt_pris_sek_per_kwh)}/kWh
                </span>
              </span>
              <span className="text-sm text-muted-foreground">
                ({data.exportersattning.skillnad_mot_spot_sek !== undefined && data.exportersattning.skillnad_mot_spot_sek >= 0 ? "+" : "−"}
                {formatCurrency(Math.abs(data.exportersattning.skillnad_mot_spot_sek ?? 0))} mot enbart spotpris {formatCurrency(data.exportersattning.spot_total_sek)})
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Monthly forecast — what to expect per full-data month. Without any fixed monthly fee
          the net-after-fees figures are omitted rather than computed against 0 kr. */}
      {data.manads_prognos && (data.manads_prognos.fullstandiga_manader ?? 0) > 0 && (() => {
        const hasFixedFees =
          data.manads_prognos.har_fasta_avgifter ?? data.manads_prognos.snitt_netto_sek != null;
        return (
        <Card className="border-primary/20 bg-primary/5">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <CalendarDays className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Vad du kan förvänta dig per månad</CardTitle>
              <InfoTooltip text={FORECAST_INFO} />
            </div>
            <CardDescription>
              Per hel månad (delmånader är uppräknade till full månad) över {formatNumber(data.manads_prognos.antal_manader)} månader
              {hasFixedFees
                ? `, efter fasta avgifter (${formatCurrency(data.manads_prognos.fasta_avgifter_sek_per_man)}/mån)`
                : ", före fasta avgifter"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {hasFixedFees ? (
              <>
                <div className="flex items-baseline gap-2">
                  <span className={`text-3xl font-bold font-mono ${(data.manads_prognos.snitt_netto_sek ?? 0) < 0 ? "text-destructive" : "text-primary"}`}>
                    {formatCurrency(data.manads_prognos.snitt_netto_sek)}
                  </span>
                  <span className="text-muted-foreground">netto per månad i snitt</span>
                </div>
                <div className="mt-2 text-sm text-muted-foreground">
                  Ersättning {formatCurrency(data.manads_prognos.snitt_effektiv_ersattning_sek)}/mån − fasta avgifter{" "}
                  {formatCurrency(data.manads_prognos.fasta_avgifter_sek_per_man)}/mån. Snittproduktion{" "}
                  {formatNumber(data.manads_prognos.snitt_production_kwh, 0)} kWh/mån.
                </div>
              </>
            ) : (
              <>
                <div className="flex items-baseline gap-2">
                  <span className="text-3xl font-bold font-mono text-primary">
                    {formatCurrency(data.manads_prognos.snitt_effektiv_ersattning_sek)}
                  </span>
                  <span className="text-muted-foreground">ersättning per månad i snitt</span>
                </div>
                <div className="mt-2 text-sm text-muted-foreground">
                  Snittproduktion {formatNumber(data.manads_prognos.snitt_production_kwh, 0)} kWh/mån. Fyll i{" "}
                  <span className="text-foreground">fasta månadsavgifter</span> i inställningarna för att få netto efter
                  avgifter.
                </div>
              </>
            )}

            {data.manads_prognos.manader && data.manads_prognos.manader.length > 0 && (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-muted-foreground">
                      <th className="py-2 pr-4 font-medium">Månad</th>
                      <th className="py-2 pr-4 font-medium text-right">Produktion</th>
                      <th className={`py-2 font-medium text-right${hasFixedFees ? " pr-4" : ""}`}>Ersättning</th>
                      {hasFixedFees && (
                        <>
                          <th className="py-2 pr-4 font-medium text-right">Fasta avgifter</th>
                          <th className="py-2 font-medium text-right">Netto</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody className="font-mono">
                    {data.manads_prognos.manader.map((m, i) => (
                      <tr key={i} className="border-b border-border/30">
                        <td className="py-1.5 pr-4 font-sans">
                          {formatMonth(m.period)}
                          {m.complete === false && (
                            <span className="text-xs text-muted-foreground"> (uppräknad, {formatNumber(m.dagar_med_data, 0)}/{formatNumber(m.dagar_i_manad, 0)} dgr)</span>
                          )}
                        </td>
                        <td className="py-1.5 pr-4 text-right">{formatNumber(m.production_kwh, 0)} kWh</td>
                        <td className={`py-1.5 text-right${hasFixedFees ? " pr-4" : ""}`}>{formatCurrency(m.effektiv_ersattning_sek)}</td>
                        {hasFixedFees && (
                          <>
                            <td className="py-1.5 pr-4 text-right text-muted-foreground">−{formatCurrency(m.fasta_avgifter_sek)}</td>
                            <td className={`py-1.5 text-right ${(m.netto_sek ?? 0) < 0 ? "text-destructive" : "text-foreground"}`}>
                              {formatCurrency(m.netto_sek)}
                            </td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
        );
      })()}

      {/* Self-consumption valuation (separate, optional) — per-month savings breakdown */}
      {data.sjalvkonsumtion && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <PiggyBank className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Värde av självkonsumtion</CardTitle>
              <InfoTooltip text={SELF_INFO} />
            </div>
            <CardDescription>
              Hur mycket du skulle spara på att använda din produktion själv i stället för att exportera den (inkl. {formatNumber(data.sjalvkonsumtion.moms_pct, 0)}% moms)
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold font-mono text-primary">
                {formatCurrency(data.sjalvkonsumtion.total_besparing_sek)}
              </span>
              <span className="text-muted-foreground">möjlig besparing om all produktion används själv</span>
            </div>
            <div className="mt-2 text-sm text-muted-foreground">
              {formatOreSigned(data.sjalvkonsumtion.okning_vs_export_sek_per_kwh)}/kWh mer värt än att exportera. Bygger på spot
              {" "}+ energiskatt {formatOre(data.sjalvkonsumtion.energiskatt_sek_per_kwh)} + nätavgift{" "}
              {formatOre(data.sjalvkonsumtion.natavgift_sek_per_kwh)}, spotpris enligt{" "}
              {data.sjalvkonsumtion.kvartpris ? "PT15M-pris" : "periodens snittspris"}.
            </div>

            {data.sjalvkonsumtion.manader && data.sjalvkonsumtion.manader.length > 0 && (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-muted-foreground">
                      <th className="py-2 pr-4 font-medium">Månad</th>
                      <th className="py-2 pr-4 font-medium text-right">Produktion</th>
                      <th className="py-2 pr-4 font-medium text-right">Värde självkons.</th>
                      <th className="py-2 pr-4 font-medium text-right">Värde export</th>
                      <th className="py-2 font-medium text-right">Besparing</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono">
                    {data.sjalvkonsumtion.manader.map((m, i) => (
                      <tr key={i} className="border-b border-border/30">
                        <td className="py-1.5 pr-4 font-sans">{formatMonth(m.period)}</td>
                        <td className="py-1.5 pr-4 text-right">{formatNumber(m.production_kwh, 0)} kWh</td>
                        <td className="py-1.5 pr-4 text-right">{formatOre(m.varde_self_sek_per_kwh)}/kWh</td>
                        <td className="py-1.5 pr-4 text-right">{formatOre(m.export_varde_sek_per_kwh)}/kWh</td>
                        <td className="py-1.5 text-right text-primary">{formatCurrency(m.besparing_sek)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Quarters exported at a loss */}
      {data.forlust_export && (data.forlust_export.antal ?? 0) > 0 && (
        <Card className="border-destructive/30">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <TrendingDownIcon className="h-5 w-5 text-destructive" />
              <CardTitle className="text-lg">
                {data.forlust_export.intervall_minuter === 15 ? "Kvartar" : "Tillfällen"} du exporterade med förlust
              </CardTitle>
              <InfoTooltip text={LOSS_INFO} />
            </div>
            <CardDescription>
              Tillfällen då ditt effektiva pris var under noll – du betalade för att exportera.
              Brytpunkt: spotpris under {formatOre(data.forlust_export.troskel_spot_sek_per_kwh)}/kWh.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="mb-4">
              <div className="text-3xl font-bold font-mono text-destructive">
                {formatCurrency(data.forlust_export.total_forlust_sek)}
              </div>
              <p className="text-sm text-muted-foreground">uppskattad total förlust</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 mb-4">
              <div>
                <div className="text-2xl font-bold font-mono text-destructive">
                  {formatNumber(data.forlust_export.antal)}
                </div>
                <p className="text-sm text-muted-foreground">
                  {data.forlust_export.intervall_minuter === 15 ? "kvartar" : "tillfällen"} med förlust
                </p>
              </div>
              <div>
                <div className="text-2xl font-bold font-mono">
                  {formatNumber(data.forlust_export.total_kwh, 1)} <span className="text-base">kWh</span>
                </div>
                <p className="text-sm text-muted-foreground">exporterat med förlust</p>
              </div>
            </div>

            <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
              {formatNumber(data.forlust_export.antal)} {data.forlust_export.intervall_minuter === 15 ? "kvartar" : "tillfällen"} hade
              spotpris under brytpunkten ({formatOre(data.forlust_export.troskel_spot_sek_per_kwh)}/kWh). Om du
              begränsat exporten (inte matat ut) under dessa hade du sluppit{" "}
              <span className="font-mono font-semibold text-foreground">{formatCurrency(data.forlust_export.total_forlust_sek)}</span> i förlust.
            </div>

            <LossChart serie={data.forlust_export.serie} />

            {data.forlust_export.poster && data.forlust_export.poster.length > 0 && (
              <div className="mt-4">
                <p className="text-sm text-muted-foreground mb-2">
                  Värst drabbade tillfällen{data.forlust_export.poster.length < (data.forlust_export.antal ?? 0) ? ` (topp ${data.forlust_export.poster.length})` : ""}:
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50 text-left text-muted-foreground">
                        <th className="py-2 pr-4 font-medium">Tidpunkt</th>
                        <th className="py-2 pr-4 font-medium text-right">Spotpris</th>
                        <th className="py-2 pr-4 font-medium text-right">Effektivt pris</th>
                        <th className="py-2 pr-4 font-medium text-right">Volym</th>
                        <th className="py-2 font-medium text-right">Förlust</th>
                      </tr>
                    </thead>
                    <tbody className="font-mono">
                      {data.forlust_export.poster.map((row, i) => (
                        <tr key={i} className="border-b border-border/30">
                          <td className="py-1.5 pr-4 font-sans">{formatLossRange(row.start, data.forlust_export?.intervall_minuter)}</td>
                          <td className="py-1.5 pr-4 text-right">{formatOre(row.spot_sek_per_kwh)}</td>
                          <td className="py-1.5 pr-4 text-right text-destructive">{formatOre(row.effektivt_pris_sek_per_kwh)}</td>
                          <td className="py-1.5 pr-4 text-right">{formatNumber(row.kwh, 2)} kWh</td>
                          <td className="py-1.5 text-right text-destructive">{formatCurrency(row.forlust_sek)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Daily overview chart (net value bars + production area + daily spot-price line) */}
      {data.aggregates?.daily && data.aggregates.daily.length > 1 && (
        <PriceChart dailyData={data.aggregates.daily} />
      )}

      {/* Price parameters used for this analysis */}
      {data.parametrar && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Prisparametrar</CardTitle>
            </div>
            <CardDescription>Inställningarna som användes för den här analysen</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
              {(() => {
                const pp = data.parametrar;
                const rows: Array<[string, string]> = [];
                const push = (label: string, v?: string) => {
                  if (v) rows.push([label, v]);
                };
                push("Elområde", pp.elomrade);
                push("Huvudsäkring", pp.huvudsakring_a ? `${pp.huvudsakring_a} A` : undefined);
                push("Moms", pp.moms_pct ? `${pp.moms_pct} %` : undefined);
                push("Momsregistrerad", pp.momsregistrerad ? "Ja" : "Nej");
                push("Elnät fast", pp.elnat_fast_ore_per_kwh ? `${pp.elnat_fast_ore_per_kwh} öre/kWh` : undefined);
                push("Elnät rörlig", pp.elnat_rorlig_pct ? `${pp.elnat_rorlig_pct} % av spot` : undefined);
                push("Elhandel fast", pp.elhandel_fast_ore_per_kwh ? `${pp.elhandel_fast_ore_per_kwh} öre/kWh` : undefined);
                push("Elhandel rörlig", pp.elhandel_rorlig_pct ? `${pp.elhandel_rorlig_pct} % av spot` : undefined);
                push("Elnät månadsavgift", pp.elnat_manadsavgift_kr ? `${pp.elnat_manadsavgift_kr} kr/mån` : undefined);
                push("Elnät månadsavgift (nästa säkring)", pp.elnat_manadsavgift_nasta_sakring_kr ? `${pp.elnat_manadsavgift_nasta_sakring_kr} kr/mån` : undefined);
                push("Elnät månadsavgift (lägre säkring)", pp.elnat_manadsavgift_lagre_sakring_kr ? `${pp.elnat_manadsavgift_lagre_sakring_kr} kr/mån` : undefined);
                push("Installerad effekt", pp.installerad_kwp ? `${pp.installerad_kwp} kWp` : undefined);
                push("Elhandel månadsavgift", pp.elhandel_manadsavgift_kr ? `${pp.elhandel_manadsavgift_kr} kr/mån` : undefined);
                push("Energiskatt", pp.energiskatt_ore_per_kwh ? `${pp.energiskatt_ore_per_kwh} öre/kWh` : undefined);
                push("Nätavgift", pp.natavgift_ore_per_kwh ? `${pp.natavgift_ore_per_kwh} öre/kWh` : undefined);
                push("PT15M-pris elhandel", pp.kvartspris_elhandel ? "Ja" : "Nej");
                return rows.map(([label, value]) => (
                  <div key={label} className="flex flex-col">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="font-medium text-foreground font-mono">{value}</dd>
                  </div>
                ));
              })()}
            </dl>
          </CardContent>
        </Card>
      )}

      {/* Data sources & method */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center gap-2">
            <Info className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">Datakällor &amp; metod</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <div>
            <p className="font-medium text-foreground">Spotpriser</p>
            <p>
              elprisetjustnu.se – per timme/kvart för valt elområde (SEK/kWh), hämtas direkt i webbläsaren utan nyckel.
              All ekonomi (intäkter, effektivt pris, brytpunkt, månadsprognos) bygger på dina exporterade kWh × dessa priser.
            </p>
          </div>
          <div>
            <p className="font-medium text-foreground">Solinstrålning – SMHI STRÅNG</p>
            <p>
              <span className="text-foreground">Vad:</span> SMHI:s STRÅNG-modell för global horisontell solinstrålning
              (W/m²) – en historisk <span className="text-foreground">modell</span> (~2,5 km rutnät, per timme, sedan 1999),
              inte mätvärden på din exakta punkt.
            </p>
            <p>
              <span className="text-foreground">Hur:</span> hämtas direkt från SMHI:s öppna API i din webbläsare (ingen
              nyckel). Endast vald position (latitud/longitud) och datumintervall skickas – ingen av dina data lämnar webbläsaren.
            </p>
            <p>
              <span className="text-foreground">Var:</span> (1) i diagrammet
              <span className="text-foreground"> &quot;Dagligt spotpris under soltimmar&quot;</span> – när en plats är vald
              används STRÅNG för att avgöra vilka timmar solen var uppe (instrålning &gt; 0), så snittspotpriset per dag
              räknas bara över de timmar du faktiskt kan exportera (inte natten och inte ett tidssnitt över dygnet).
              (2) i inställningarnas platsväljare (&quot;Hämta solinstrålning&quot;) för periodens instrålning (kWh/m²) och,
              med din effekt (kWp), en grov uppskattad potentiell produktion (instrålning × kWp × 0,82). STRÅNG påverkar
              inte intäkts-/exportkronorna – de bygger på din uppmätta export.
            </p>
          </div>
          <p>All analys körs i din webbläsare – inga filer eller resultat skickas till någon server.</p>
        </CardContent>
      </Card>

      {/* AI Explanation */}
      {data.ai_explanation_sv && (
        <Card className="border-primary/20">
          <CardHeader>
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              <CardTitle>AI-sammanfattning</CardTitle>
              <Badge variant="energy">Svenska</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <p className="text-foreground whitespace-pre-wrap leading-relaxed">
                {data.ai_explanation_sv}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

    </div>
  );
}
