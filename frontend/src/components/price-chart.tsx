"use client";

import { useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@sourceful-energy/ui";
import { TrendingUp } from "lucide-react";

interface MonthlyData {
  period?: string;
  month?: string;
  production_kwh?: number;
  revenue_sek?: number;
  avg_price_sek_per_kwh?: number;
  negative_hours?: number;
  negative_kwh?: number;
  negative_value_sek?: number;
}

interface PriceChartProps {
  monthlyData?: MonthlyData[];
  title?: string;
}

export function PriceChart({ monthlyData, title = "Månatlig översikt" }: PriceChartProps) {
  const chartData = useMemo(() => {
    if (!monthlyData || monthlyData.length === 0) return [];

    return monthlyData.map((item) => {
      const period = item.period || item.month || "";
      // Extract month name from period (e.g., "2024-01" -> "Jan 24")
      const [year, month] = period.split("-");
      const monthNames = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"];
      const monthName = month ? monthNames[parseInt(month, 10) - 1] : "";
      const shortYear = year ? year.slice(-2) : "";

      return {
        name: `${monthName} ${shortYear}`,
        fullPeriod: period,
        production: item.production_kwh || 0,
        revenue: item.revenue_sek || 0,
        avgPrice: item.avg_price_sek_per_kwh || 0,
        negativeHours: item.negative_hours || 0,
        negativeCost: Math.abs(item.negative_value_sek || 0),
      };
    });
  }, [monthlyData]);

  if (chartData.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-primary" />
          <CardTitle className="text-lg">{title}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={chartData}
              margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="colorRevenue" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00FF84" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#00FF84" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="colorNegative" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis
                dataKey="name"
                stroke="#666"
                fontSize={12}
                tickLine={false}
              />
              <YAxis
                stroke="#666"
                fontSize={12}
                tickLine={false}
                tickFormatter={(value) => `${value.toFixed(0)}`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1a1a1a",
                  border: "1px solid #333",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
                labelStyle={{ color: "#fff" }}
                formatter={(value, name) => {
                  const numValue = typeof value === "number" ? value : 0;
                  if (name === "Intäkt") return [`${numValue.toFixed(0)} kr`, name];
                  if (name === "Förlust") return [`${numValue.toFixed(0)} kr`, name];
                  return [`${numValue}`, name];
                }}
              />
              <ReferenceLine y={0} stroke="#666" />
              <Area
                type="monotone"
                dataKey="revenue"
                name="Intäkt"
                stroke="#00FF84"
                fillOpacity={1}
                fill="url(#colorRevenue)"
                strokeWidth={2}
              />
              <Area
                type="monotone"
                dataKey="negativeCost"
                name="Förlust"
                stroke="#ef4444"
                fillOpacity={1}
                fill="url(#colorNegative)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="flex justify-center gap-6 mt-4 text-sm">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-primary" />
            <span className="text-muted-foreground">Intäkt (kr)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-destructive" />
            <span className="text-muted-foreground">Negativ export (kr)</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
