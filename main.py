#!/usr/bin/env python3
"""
Sourceful Energy - Core Analysis CLI

Command-line interface for the core functionality.
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv

from core.price_fetcher import PriceFetcher
from core.production_loader import ProductionLoader
from core.price_analyzer import PriceAnalyzer
from utils.ai_explainer import AIExplainer


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Sourceful Energy Analysis Tool")
    parser.add_argument(
        "--production-file", required=True, help="CSV file with production data"
    )
    parser.add_argument(
        "--area", required=True, help="Electricity area code (e.g., SE_4)"
    )
    parser.add_argument("--start-date", help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date YYYY-MM-DD")
    parser.add_argument(
        "--currency", default="SEK", help="Currency for output (default: SEK)"
    )
    parser.add_argument("--output", help="Output file for results (JSON)")
    parser.add_argument(
        "--ai-explain", action="store_true", help="Generate AI explanation"
    )

    args = parser.parse_args()

    try:
        # Initialize components
        price_fetcher = PriceFetcher()
        production_loader = ProductionLoader()
        analyzer = PriceAnalyzer()

        # Load production data
        print(f"Loading production data from {args.production_file}...")
        production_df = production_loader.load_production_data(args.production_file)

        # Determine date range
        production_start = pd.Timestamp(
            production_df.index.min(), tz="Europe/Stockholm"
        )
        production_end = pd.Timestamp(production_df.index.max(), tz="Europe/Stockholm")

        start_date = (
            pd.Timestamp(args.start_date, tz="Europe/Stockholm")
            if args.start_date
            else production_start
        )
        end_date = (
            pd.Timestamp(args.end_date, tz="Europe/Stockholm")
            if args.end_date
            else production_end
        )

        # Get price data
        print(
            f"Fetching price data for {args.area} from {start_date.date()} to {end_date.date()}..."
        )
        prices_df = price_fetcher.get_price_data(args.area, start_date, end_date)

        if prices_df.empty:
            print("No price data available for the specified period.")
            sys.exit(1)

        # Currency conversion rate (simplified)
        currency_rates = {"SEK": 11.5, "EUR": 1.0, "USD": 1.1, "NOK": 12.0}
        currency_rate = currency_rates.get(args.currency.upper(), 11.5)

        # Merge and analyze
        print("Analyzing data...")
        merged_df = analyzer.merge_data(prices_df, production_df, currency_rate)
        analysis = analyzer.analyze_data(merged_df)

        # Print summary
        print("\n=== ANALYSIS RESULTS ===")
        print(
            f"Period: {analysis['period_days']} days ({analysis['total_hours']} hours)"
        )
        print(f"Total production: {analysis['production_total']:.2f} kWh")
        print(f"Hours with negative prices: {analysis['negative_price_hours']}")
        print(
            f"Production during negative prices: {analysis['production_during_negative_prices']:.2f} kWh"
        )
        print(
            f"Cost from negative prices: {analysis['negative_export_cost_abs_sek']:.2f} {args.currency}"
        )
        print(
            f"Total export value: {analysis['total_export_value_sek']:.2f} {args.currency}"
        )

        # AI explanation
        if args.ai_explain:
            print("\n=== AI EXPLANATION ===")
            explainer = AIExplainer()
            metadata = {
                "area_code": args.area,
                "currency": args.currency,
                "file_name": Path(args.production_file).name,
            }
            explanation = explainer.explain_analysis(analysis, metadata)
            print(explanation)

        # Save results
        if args.output:
            import json

            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(
                    {"analysis": analysis, "metadata": metadata},
                    f,
                    indent=2,
                    default=str,
                )
            print(f"\nResults saved to {args.output}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
