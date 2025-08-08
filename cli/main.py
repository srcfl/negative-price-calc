import argparse
import logging
from pathlib import Path
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from core.production_loader import ProductionLoader
from core.price_fetcher import PriceFetcher

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def cmd_inspect_production(path: str):
    loader = ProductionLoader()
    try:
        df, gran = loader.load_production(path, use_llm=False)
    except FileNotFoundError:
        print(f"File not found: {path}")
        return
    except Exception as e:
        msg = str(e) if str(e) else e.__class__.__name__
        print(f"Error: {msg}\n"
              "Unrecognized production file format. This tool accepts:\n"
              "  1) Hourly data: timestamps at hour resolution with kWh per hour.\n"
              "  2) Daily totals: one row per day with total kWh (analysis will be approximate).")
        return

    total = float(df["production_kwh"].sum()) if len(df) else 0.0
    print("Production CSV inspection")
    print(f"- Granularity: {gran}")
    if gran == 'hourly':
        start = df.index.min()
        end = df.index.max()
        hours = len(df)
        by_day = df.resample('D').sum(numeric_only=True)
        avg_day = float(by_day['production_kwh'].mean()) if len(by_day) else 0.0
        print(f"- Rows (hours): {hours}")
        print(f"- Date range: {start} to {end}")
        print(f"- Total kWh: {total:.3f}")
        print(f"- Average kWh/day: {avg_day:.3f}")
    else:
        days = len(df)
        start = df.index.min().date() if days else None
        end = df.index.max().date() if days else None
        avg = float(df["production_kwh"].mean()) if days else 0.0
        median = float(df["production_kwh"].median()) if days else 0.0
        zeros = int((df["production_kwh"] == 0).sum()) if days else 0
        top5 = df.sort_values("production_kwh", ascending=False).head(5)
        print(f"- Rows (days): {days}")
        print(f"- Date range: {start} to {end}")
        print(f"- Total kWh: {total:.3f}")
        print(f"- Average kWh/day: {avg:.3f}")
        print(f"- Median kWh/day: {median:.3f}")
        print(f"- Zero-production days: {zeros}")
        print("- Top 5 days:")
        for dt, row in top5.iterrows():
            print(f"  {dt.date()}: {row['production_kwh']:.3f} kWh")


def main():
    # Load environment variables (ENTSOE_API_KEY, OPENAI_API_KEY, etc.)
    load_dotenv()
    parser = argparse.ArgumentParser(description="Sourceful Energy CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_inspect = sub.add_parser("inspect-production", help="Inspect a production CSV")
    p_inspect.add_argument("path", help="Path to the production CSV file")

    # New unified 'analyze' command
    p_analyze = sub.add_parser("analyze", help="Analyze production with prices (auto hourly or daily-approx)")
    p_analyze.add_argument("path", help="Path to the production CSV file")
    p_analyze.add_argument("--area", "-a", required=True, help="Electricity area code (e.g., SE_4)")
    p_analyze.add_argument("--currency", default="SEK", help="Currency for display (SEK/EUR)")
    p_analyze.add_argument("--output", help="Optional path to save merged CSV")
    p_analyze.add_argument("--force-api", action="store_true", help="Force fetching prices from ENTSO-E API (bypass cache)")

    # Backward-compatible alias
    p_merge = sub.add_parser("analyze-daily", help="(Alias) Analyze production with prices (auto hourly or daily-approx)")
    p_merge.add_argument("path", help="Path to the production CSV file")
    p_merge.add_argument("--area", "-a", required=True, help="Electricity area code (e.g., SE_4)")
    p_merge.add_argument("--currency", default="SEK", help="Currency for display (SEK/EUR)")
    p_merge.add_argument("--output", help="Optional path to save merged CSV")
    p_merge.add_argument("--force-api", action="store_true", help="Force fetching prices from ENTSO-E API (bypass cache)")

    args = parser.parse_args()
    if args.cmd == "inspect-production":
        cmd_inspect_production(args.path)
        return

    if args.cmd in ("analyze", "analyze-daily"):
        # Load production and auto-detect granularity
        loader = ProductionLoader()
        try:
            prod_df, gran = loader.load_production(args.path, use_llm=False)
        except FileNotFoundError:
            print(f"File not found: {args.path}")
            return
        except Exception as e:
            msg = str(e) if str(e) else e.__class__.__name__
            print(f"Error: {msg}\n"
                  "Unrecognized production file format. This tool accepts:\n"
                  "  1) Hourly data: timestamps at hour resolution with kWh per hour.\n"
                  "  2) Daily totals: one row per day with total kWh (analysis will be approximate).")
            return

        if prod_df.empty:
            print("No production data found.")
            return

        # Determine date range
        if gran == 'hourly':
            start_date = pd.Timestamp(prod_df.index.min(), tz='Europe/Stockholm')
            end_date = pd.Timestamp(prod_df.index.max(), tz='Europe/Stockholm') + pd.Timedelta(hours=1)
        else:
            start_date = pd.Timestamp(prod_df.index.min(), tz='Europe/Stockholm')
            # Include the full last day by extending one day (ENTSO-E period end is exclusive)
            end_date = pd.Timestamp(prod_df.index.max(), tz='Europe/Stockholm') + pd.Timedelta(days=1)

        # Fetch hourly prices covering the full range
        fetcher = PriceFetcher()
        prices_hourly = fetcher.get_price_data(args.area, start_date, end_date, force_api=args.force_api)

        if prices_hourly is None or prices_hourly.empty:
            print("No price data available for the specified period/area.")
            return

        currency_rates = {'SEK': 11.5, 'EUR': 1.0}
        rate = currency_rates.get(args.currency.upper(), 11.5)

        if gran == 'hourly':
            # True hourly merge
            price_hourly = prices_hourly['price_eur_per_mwh']
            price_sek_per_kwh_hr = (price_hourly * rate) / 1000
            aligned = pd.DataFrame({'prod_kwh': prod_df['production_kwh']}).join(
                price_sek_per_kwh_hr.to_frame('sek_per_kwh'), how='left'
            )
            aligned['revenue_sek'] = aligned['prod_kwh'] * aligned['sek_per_kwh']
            # Summaries
            total_prod_kwh = float(aligned['prod_kwh'].sum())
            total_revenue_sek = float(aligned['revenue_sek'].sum())
            neg_hours = int((aligned['sek_per_kwh'] < 0).sum())
            neg_cost_sek = float((-aligned.loc[aligned['sek_per_kwh'] < 0, 'revenue_sek']).clip(lower=0).sum())

            # Daily aggregates for display
            by_day = aligned.resample('D').sum(numeric_only=True)
            print("Hourly production x price merge")
            print(f"- Hours: {len(aligned)}  Days: {len(by_day)}")
            print(f"- Date range: {aligned.index.min()} to {aligned.index.max()}")
            print(f"- Total production: {total_prod_kwh:.3f} kWh")
            print(f"- Total revenue:    {total_revenue_sek:.2f} SEK")
            print(f"- Negative price hours: {neg_hours} (cost: {neg_cost_sek:.2f} SEK)")

            if args.output:
                out = by_day.copy()
                out.index.name = 'date'
                out_path = Path(args.output).expanduser()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out.to_csv(str(out_path))
                try:
                    resolved = out_path.resolve()
                except Exception:
                    resolved = out_path
                print(f"Saved daily aggregate CSV to {resolved}")
        else:
            # Daily input: always approximate hourly production using a solar-shaped curve
            start_h, end_h, peak_h, sigma = 8, 16, 12, 2.0
            hourly_series = []
            for dt, row in prod_df.iterrows():
                total_kwh = float(row['production_kwh'])
                if total_kwh <= 0:
                    continue
                hours = np.arange(24)
                weights = np.exp(-0.5 * ((hours - peak_h) / sigma) ** 2)
                window = (hours >= start_h) & (hours <= end_h)
                weights = weights * window
                s = weights.sum()
                if s <= 0:
                    continue
                weights = weights / s
                values = weights * total_kwh
                day = pd.Timestamp(dt).normalize()
                idx = pd.date_range(day, periods=24, freq='h')
                hourly_series.append(pd.Series(values, index=idx))

            approx_total_revenue_sek = 0.0
            approx_neg_cost_sek = 0.0
            if hourly_series:
                approx_prod = pd.concat(hourly_series).sort_index()
                price_hourly = prices_hourly['price_eur_per_mwh']
                price_sek_per_kwh_hr = (price_hourly * rate) / 1000
                aligned = pd.DataFrame({'prod_kwh': approx_prod}).join(
                    price_sek_per_kwh_hr.to_frame('sek_per_kwh'), how='left'
                )
                aligned['revenue_sek'] = aligned['prod_kwh'] * aligned['sek_per_kwh']
                approx_total_revenue_sek = float(aligned['revenue_sek'].sum())
                neg_mask_hr = aligned['sek_per_kwh'] < 0
                approx_neg_cost_sek = float((-aligned.loc[neg_mask_hr, 'revenue_sek']).clip(lower=0).sum())
                by_day = aligned.resample('D').sum(numeric_only=True)
            else:
                by_day = prod_df.copy()

            total_prod_kwh = float(prod_df['production_kwh'].sum())
            print("Daily production (approx hourly) x price merge")
            print(f"- Days: {len(prod_df)}")
            print(f"- Date range: {prod_df.index.min().date()} to {prod_df.index.max().date()}")
            print(f"- Total production: {total_prod_kwh:.3f} kWh")
            print(f"- Total revenue (approx): {approx_total_revenue_sek:.2f} SEK")
            print(f"- Negative price cost (approx): {approx_neg_cost_sek:.2f} SEK")
            print("Note: Daily input was approximated to hourly (08–16, peak at 12:00). For best accuracy, supply hourly production.")

            if args.output:
                out = by_day.copy()
                out.index.name = 'date'
                out_path = Path(args.output).expanduser()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out.to_csv(str(out_path))
                try:
                    resolved = out_path.resolve()
                except Exception:
                    resolved = out_path
                print(f"Saved daily aggregate CSV to {resolved}")
        return

    # Fallback: show help
    parser.print_help()
