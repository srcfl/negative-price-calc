"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Badge,
  Button,
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
} from "lucide-react";
import { PriceChart } from "./price-chart";

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
      timmar_som_kostat_dig?: number;
      kwh_exporterat_med_förlust?: number;
      andel_olönsam_export_pct?: number;
      kostnad_negativ_export_sek?: number;
    };
    tidsanalys?: {
      totala_timmar?: number;
      produktionstimmar?: number;
      negativa_timmar_totalt?: number;
      negativa_timmar_under_produktion?: number;
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
      negative_hours?: number;
      negative_kwh?: number;
      negative_value_sek?: number;
    }>;
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

function getGranularityLabel(granularity: string | undefined): string {
  switch (granularity?.toLowerCase()) {
    case "hourly":
      return "Timdata";
    case "15min":
    case "15-min":
    case "quarterly":
      return "15-minutersdata";
    case "daily":
      return "Dygnsdata";
    default:
      return granularity || "";
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
  const exportForluster = hero.export_förluster || {};
  const tidsanalys = hero.tidsanalys || {};
  const tekniskaMatt = hero.tekniska_mått || {};

  // Use Swedish structure first, then tekniska_mått, then legacy flat
  const totalExport = produktion.total_kwh ?? tekniskaMatt.production_kwh ?? hero.production_kwh;
  const totalRevenue = produktion.totala_intakter_sek ?? tekniskaMatt.revenue_sek ?? hero.revenue_sek;
  const negativeHours = exportForluster.timmar_som_kostat_dig ?? tidsanalys.negativa_timmar_under_produktion ?? tekniskaMatt.hours_negative_during_production ?? hero.hours_negative_total;
  const totalHours = tidsanalys.totala_timmar ?? tekniskaMatt.hours_total ?? hero.hours_total;
  const negativeCost = exportForluster.kostnad_negativ_export_sek ?? tekniskaMatt.negative_value_sek ?? hero.negative_value_sek;
  const realizedPrice = produktion.genomsnittspris_erhållet_sek_per_kwh ?? tekniskaMatt.realized_price_wavg_sek_per_kwh ?? hero.realized_price_wavg_sek_per_kwh;
  const avgPrice = produktion.enkelt_snitt_pris_sek_per_kwh ?? tekniskaMatt.simple_average_price_sek_per_kwh ?? hero.simple_average_price_sek_per_kwh;
  const negativeExportPercent = exportForluster.andel_olönsam_export_pct;

  const negativeHoursPercent =
    totalHours && negativeHours
      ? ((negativeHours / totalHours) * 100).toFixed(1)
      : negativeExportPercent?.toFixed(1) ?? "0";

  const timingDiscount =
    realizedPrice && avgPrice
      ? (((realizedPrice - avgPrice) / avgPrice) * 100).toFixed(1)
      : produktion.timing_förlust_pct?.toFixed(1) ?? tekniskaMatt.timing_discount_pct?.toFixed(1) ?? null;

  // Extract date range info
  const startDate = data.input?.date_range?.start ?? data.input?.date_range?.start_utc?.split("T")[0];
  const endDate = data.input?.date_range?.end ?? data.input?.date_range?.end_utc?.split("T")[0];
  const granularityLabel = getGranularityLabel(data.input?.granularity || metadata.granularity);

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
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary/10 border border-primary/20">
                <Clock className="h-4 w-4 text-primary" />
                <span className="font-medium text-foreground">
                  {formatSwedishDate(startDate)} → {formatSwedishDate(endDate)}
                </span>
              </div>
              {granularityLabel && (
                <Badge variant="secondary" className="text-sm">
                  {granularityLabel}
                  {totalHours && ` (${formatNumber(totalHours)} timmar)`}
                </Badge>
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
            Excel
          </Button>
        </div>
      </div>

      {/* Hero Metrics */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total export
            </CardTitle>
            <Zap className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">
              {formatNumber(totalExport)} <span className="text-lg">kWh</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total intäkt
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
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Negativa pristimmar
            </CardTitle>
            <Clock className="h-4 w-4 text-destructive" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">
              {formatNumber(negativeHours)}
              <span className="text-lg text-muted-foreground ml-2">
                ({negativeHoursPercent}%)
              </span>
            </div>
          </CardContent>
        </Card>

        <Card className={negativeCost && negativeCost > 0 ? "border-destructive/50" : ""}>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Kostnad negativa priser
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

      {/* Timing Discount */}
      {timingDiscount && (
        <Card className="border-primary/20 bg-primary/5">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <TrendingDown className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Timing-rabatt</CardTitle>
            </div>
            <CardDescription>
              Din solexport sammanfaller med lågpristimmar
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold font-mono text-primary">
                {timingDiscount}%
              </span>
              <span className="text-muted-foreground">
                lägre pris än marknadens snitt
              </span>
            </div>
            <div className="mt-2 text-sm text-muted-foreground">
              Realiserat pris: {formatNumber(realizedPrice, 2)} kr/kWh vs
              snitt: {formatNumber(avgPrice, 2)} kr/kWh
            </div>
          </CardContent>
        </Card>
      )}

      {/* Monthly Chart */}
      {data.aggregates?.monthly && data.aggregates.monthly.length > 1 && (
        <PriceChart monthlyData={data.aggregates.monthly} />
      )}

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
