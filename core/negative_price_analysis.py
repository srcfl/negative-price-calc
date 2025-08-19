#!/usr/bin/env python3
"""
Negative Price Export Cost Calculator

Analyzes the cost of exporting solar energy during negative price periods.

Usage:
    python negative_price_analysis.py updated_merged_analysis.csv
"""

import pandas as pd
import sys
from datetime import datetime


def analyze_negative_pricing(csv_file):
    """Analyze negative pricing costs from merged data."""

    print("Loading merged data...")
    df = pd.read_csv(csv_file, index_col=0)
    df.index = pd.to_datetime(df.index)

    # Filter negative price periods
    negative = df[df["price_eur_per_mwh"] < 0].copy()
    negative_with_production = negative[negative["production_kwh"] > 0].copy()

    print("\n" + "=" * 70)
    print("NEGATIVE PRICE EXPORT COST ANALYSIS")
    print("=" * 70)

    print(f"\nOVERVIEW:")
    print(f"  Total data period: {df.index.min().date()} to {df.index.max().date()}")
    print(f"  Total hours in dataset: {len(df):,}")
    print(f"  Hours with negative prices: {len(negative):,}")
    print(
        f"  Hours with negative prices AND production: {len(negative_with_production):,}"
    )

    if len(negative_with_production) == 0:
        print("\nNo production during negative price periods!")
        return

    print(f"\nNEGATIVE PRICE STATISTICS:")
    print(
        f"  Lowest price: {negative['price_eur_per_mwh'].min():.2f} EUR/MWh ({negative['price_sek_per_kwh'].min():.4f} SEK/kWh)"
    )
    print(
        f"  Average negative price: {negative['price_eur_per_mwh'].mean():.2f} EUR/MWh ({negative['price_sek_per_kwh'].mean():.4f} SEK/kWh)"
    )

    print(f"\nPRODUCTION DURING NEGATIVE PRICES:")
    print(f"  Total production: {negative['production_kwh'].sum():.2f} kWh")
    print(
        f"  Average hourly production: {negative_with_production['production_kwh'].mean():.3f} kWh"
    )
    print(
        f"  Max hourly production: {negative_with_production['production_kwh'].max():.3f} kWh"
    )

    print(f"\nCOST ANALYSIS:")
    total_cost = abs(negative["export_value_sek"].sum())
    print(f"  TOTAL COST of negative price exports: {total_cost:.2f} SEK")
    print(
        f"  Most expensive single hour: {abs(negative['export_value_sek'].min()):.2f} SEK"
    )
    print(
        f"  Average cost per kWh during negative prices: {total_cost / negative['production_kwh'].sum():.4f} SEK/kWh"
    )

    # Monthly breakdown
    print(f"\nMONTHLY BREAKDOWN:")
    negative["month"] = negative.index.to_period("M")
    monthly = negative.groupby("month").agg(
        {"production_kwh": "sum", "export_value_sek": "sum"}
    )
    monthly["cost_sek"] = abs(monthly["export_value_sek"])
    monthly = monthly[
        monthly["production_kwh"] > 0
    ]  # Only months with production during negative prices

    for month, row in monthly.iterrows():
        print(
            f"  {month}: {row['production_kwh']:.1f} kWh exported, cost: {row['cost_sek']:.2f} SEK"
        )

    # Top 10 most expensive hours
    print(f"\nTOP 10 MOST EXPENSIVE NEGATIVE EXPORT HOURS:")
    top_expensive = negative_with_production.nsmallest(10, "export_value_sek")
    for idx, row in top_expensive.iterrows():
        print(
            f"  {idx}: {row['production_kwh']:.3f} kWh @ {row['price_sek_per_kwh']:.4f} SEK/kWh = {abs(row['export_value_sek']):.3f} SEK"
        )

    # Daily summary
    print(f"\nDAILY COST SUMMARY:")
    negative["date"] = negative.index.date
    daily_costs = negative.groupby("date").agg(
        {"production_kwh": "sum", "export_value_sek": "sum"}
    )
    daily_costs["cost_sek"] = abs(daily_costs["export_value_sek"])
    daily_costs = daily_costs[daily_costs["production_kwh"] > 0]

    print(f"  Number of days with negative export costs: {len(daily_costs)}")
    print(f"  Average daily cost: {daily_costs['cost_sek'].mean():.2f} SEK")
    print(
        f"  Most expensive day: {daily_costs['cost_sek'].max():.2f} SEK on {daily_costs['cost_sek'].idxmax()}"
    )

    # Comparison with total export value
    total_export_value = df["export_value_sek"].sum()
    positive_export_value = df[df["price_eur_per_mwh"] > 0]["export_value_sek"].sum()

    print(f"\nIMPACT ON TOTAL EXPORT VALUE:")
    print(f"  Total export value: {total_export_value:.2f} SEK")
    print(f"  Positive price export value: {positive_export_value:.2f} SEK")
    print(f"  Negative price cost: -{total_cost:.2f} SEK")
    print(f"  Net export value: {total_export_value:.2f} SEK")
    print(
        f"  Negative pricing reduces income by: {(total_cost/positive_export_value)*100:.2f}%"
    )

    print("\n" + "=" * 70)

    return {
        "total_cost_sek": total_cost,
        "production_kwh": negative["production_kwh"].sum(),
        "hours_affected": len(negative_with_production),
        "monthly_breakdown": monthly,
        "daily_costs": daily_costs,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python negative_price_analysis.py <csv_file>")
        sys.exit(1)

    csv_file = sys.argv[1]
    results = analyze_negative_pricing(csv_file)
