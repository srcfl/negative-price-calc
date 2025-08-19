#!/usr/bin/env python3
"""
Price Production Analyzer

Downloads electricity price data and merges it with solar production data for analysis.
Caches price data to avoid unnecessary API calls.

Usage:
    python price_production_analyzer.py --production production.csv --area SE_4
    python price_production_analyzer.py --production "Produktion - Solvägen 33a.csv" --area SE_4 --start-date 2025-01-01 --end-date 2025-08-03
"""

import argparse
import pandas as pd
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from entsoe import EntsoePandasClient
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PriceDatabase:
    def __init__(self, db_path="price_data.db"):
        """Initialize the price database."""
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Initialize the database tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_data (
                    area_code TEXT NOT NULL,
                    datetime TEXT NOT NULL,
                    price_eur_per_mwh REAL NOT NULL,
                    PRIMARY KEY (area_code, datetime)
                )
            """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_area_datetime ON price_data(area_code, datetime)"
            )

    def get_data_range(self, area_code):
        """Get the available date range for an area."""
        with sqlite3.connect(self.db_path) as conn:
            query = """
                SELECT MIN(datetime) as min_date, MAX(datetime) as max_date, COUNT(*) as count
                FROM price_data 
                WHERE area_code = ?
            """
            result = conn.execute(query, (area_code,)).fetchone()
            if result[0] is None:
                return None, None, 0
            return pd.to_datetime(result[0]), pd.to_datetime(result[1]), result[2]

    def has_data_for_period(self, area_code, start_date, end_date):
        """Check if we have complete data for the requested period."""
        min_date, max_date, count = self.get_data_range(area_code)
        if min_date is None:
            return False

        # Check if our data range covers the requested period
        requested_start = pd.to_datetime(start_date).tz_localize(None)
        requested_end = pd.to_datetime(end_date).tz_localize(None)

        return (min_date <= requested_start) and (max_date >= requested_end)

    def get_missing_periods(self, area_code, start_date, end_date):
        """Identify periods that need to be downloaded."""
        min_date, max_date, count = self.get_data_range(area_code)

        requested_start = pd.to_datetime(start_date).tz_localize(None)
        requested_end = pd.to_datetime(end_date).tz_localize(None)

        missing_periods = []

        if min_date is None:
            # No data at all
            missing_periods.append((requested_start, requested_end))
        else:
            # Check if we need data before our earliest date
            if requested_start < min_date:
                missing_periods.append(
                    (
                        requested_start,
                        min(min_date - pd.Timedelta(hours=1), requested_end),
                    )
                )

            # Check if we need data after our latest date
            if requested_end > max_date:
                missing_periods.append(
                    (
                        max(max_date + pd.Timedelta(hours=1), requested_start),
                        requested_end,
                    )
                )

        return missing_periods

    def store_data(self, area_code, price_data):
        """Store price data in the database."""
        logger.info(f"Storing {len(price_data)} price records for {area_code}")

        # Prepare data for insertion
        records = []
        for timestamp, price in price_data.items():
            # Ensure timezone-naive timestamp
            if hasattr(timestamp, "tz") and timestamp.tz is not None:
                timestamp = timestamp.tz_localize(None)
            records.append((area_code, timestamp.isoformat(), float(price)))

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO price_data (area_code, datetime, price_eur_per_mwh) VALUES (?, ?, ?)",
                records,
            )

    def query_data(self, area_code, start_date, end_date):
        """Query price data for a specific period."""
        start_str = pd.to_datetime(start_date).tz_localize(None).isoformat()
        end_str = pd.to_datetime(end_date).tz_localize(None).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            query = """
                SELECT datetime, price_eur_per_mwh 
                FROM price_data 
                WHERE area_code = ? AND datetime >= ? AND datetime <= ?
                ORDER BY datetime
            """
            df = pd.read_sql_query(query, conn, params=(area_code, start_str, end_str))

        if len(df) == 0:
            return pd.DataFrame(columns=["price_eur_per_mwh"])

        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
        return df


class PriceProductionAnalyzer:
    def __init__(self, api_key: Optional[str] = None, db_path: str = "price_data.db"):
        """
        Initialize the analyzer with API key and database.

        Args:
            api_key (str, optional): ENTSO-E API key. If not provided, will try to get from ENTSOE_API_KEY environment variable.
            db_path (str): Path to the SQLite database file
        """
        # Get API key from parameter or environment
        if api_key is None:
            api_key = os.getenv("ENTSOE_API_KEY")
            if not api_key:
                raise ValueError(
                    "ENTSO-E API key is required. Set ENTSOE_API_KEY environment variable or pass api_key parameter. "
                    "Get your API key from: https://transparency.entsoe.eu/usrm/user/createPublicApiKey"
                )

        self.api_key = api_key
        self.client = EntsoePandasClient(api_key=api_key)
        self.db = PriceDatabase(db_path)

    def get_price_data(self, area_code, start_date, end_date):
        """
        Get electricity price data, using database cache and downloading missing data.

        Args:
            area_code (str): Electricity area code (e.g., 'SE_4')
            start_date (pd.Timestamp): Start date
            end_date (pd.Timestamp): End date

        Returns:
            pd.DataFrame: Price data with datetime index
        """
        logger.info(
            f"Getting price data for {area_code} from {start_date.date()} to {end_date.date()}"
        )

        # Check what data we already have
        min_date, max_date, count = self.db.get_data_range(area_code)
        if min_date is not None:
            logger.info(
                f"Database contains {count} records for {area_code} from {min_date.date()} to {max_date.date()}"
            )

        # Find missing periods that need to be downloaded
        missing_periods = self.db.get_missing_periods(area_code, start_date, end_date)

        # Download missing data
        for period_start, period_end in missing_periods:
            if period_start <= period_end:  # Valid period
                logger.info(
                    f"Downloading missing data from {period_start.date()} to {period_end.date()}"
                )
                try:
                    # Convert to timezone-aware for API call
                    api_start = pd.Timestamp(period_start, tz="Europe/Stockholm")
                    api_end = pd.Timestamp(period_end, tz="Europe/Stockholm")

                    new_data = self.client.query_day_ahead_prices(
                        area_code, start=api_start, end=api_end
                    )

                    # Convert to timezone-naive for storage
                    if hasattr(new_data.index, "tz") and new_data.index.tz is not None:
                        new_data.index = new_data.index.tz_convert(
                            "Europe/Stockholm"
                        ).tz_localize(None)

                    # Convert Series to proper format if needed
                    if isinstance(new_data, pd.Series):
                        price_series = new_data
                    else:
                        price_series = new_data.iloc[:, 0]

                    # Store in database
                    self.db.store_data(area_code, price_series)

                except Exception as e:
                    logger.error(
                        f"Failed to download price data for period {period_start.date()} to {period_end.date()}: {e}"
                    )
                    raise

        # Now query the requested data from database
        prices_df = self.db.query_data(area_code, start_date, end_date)

        if len(prices_df) == 0:
            raise ValueError(
                f"No price data available for {area_code} in the requested period"
            )

        logger.info(f"Retrieved {len(prices_df)} price records from database")
        return prices_df

    def load_production_data(self, production_file):
        """
        Load solar production data from CSV file.

        Args:
            production_file (str): Path to production CSV file

        Returns:
            pd.DataFrame: Production data with datetime index
        """
        logger.info(f"Loading production data from {production_file}")

        # Auto-detect separator and decimal
        try:
            # Try semicolon separator first (common in European CSV)
            production_df = pd.read_csv(production_file, sep=";", decimal=",", nrows=5)
            if len(production_df.columns) > 1:
                # Semicolon worked, load full file
                production_df = pd.read_csv(production_file, sep=";", decimal=",")
            else:
                # Try comma separator
                production_df = pd.read_csv(production_file, sep=",", decimal=".")
        except:
            # Fallback to comma separator
            production_df = pd.read_csv(production_file, sep=",", decimal=".")

        # Find datetime and production columns
        datetime_cols = [
            col
            for col in production_df.columns
            if any(word in col.lower() for word in ["datum", "date", "time", "tid"])
        ]
        production_cols = [
            col
            for col in production_df.columns
            if any(
                word in col.lower()
                for word in ["produktion", "production", "kwh", "mwh", "power"]
            )
        ]

        if not datetime_cols:
            raise ValueError("Could not find datetime column in production file")
        if not production_cols:
            raise ValueError("Could not find production column in production file")

        datetime_col = datetime_cols[0]
        production_col = production_cols[0]

        logger.info(
            f"Using datetime column: '{datetime_col}' and production column: '{production_col}'"
        )

        # Parse datetime and set as index
        production_df[datetime_col] = pd.to_datetime(production_df[datetime_col])
        production_df = production_df.set_index(datetime_col)

        # Keep only production column and rename it
        production_df = production_df[[production_col]].copy()
        production_df.columns = ["production_kwh"]

        # Convert to numeric
        production_df["production_kwh"] = pd.to_numeric(
            production_df["production_kwh"], errors="coerce"
        )

        logger.info(
            f"Loaded production data: {len(production_df)} rows from {production_df.index.min()} to {production_df.index.max()}"
        )

        return production_df

    def merge_data(self, prices_df, production_df, eur_sek_rate=11.5):
        """
        Merge price and production data on datetime index.

        Args:
            prices_df (pd.DataFrame): Price data
            production_df (pd.DataFrame): Production data
            eur_sek_rate (float): EUR to SEK exchange rate

        Returns:
            pd.DataFrame: Merged data
        """
        logger.info("Merging price and production data")

        # Merge on datetime index
        merged_df = pd.merge(
            prices_df, production_df, left_index=True, right_index=True, how="inner"
        )

        # Add SEK pricing (convert from EUR/MWh to SEK/kWh)
        merged_df["price_sek_per_kwh"] = (
            merged_df["price_eur_per_mwh"] * eur_sek_rate
        ) / 1000

        # Calculate export value/cost for each hour
        merged_df["export_value_sek"] = (
            merged_df["production_kwh"] * merged_df["price_sek_per_kwh"]
        )

        # Add daily aggregations
        merged_df["production_daily"] = merged_df.groupby(merged_df.index.date)[
            "production_kwh"
        ].transform("sum")
        merged_df["price_daily_avg"] = merged_df.groupby(merged_df.index.date)[
            "price_eur_per_mwh"
        ].transform("mean")
        merged_df["export_value_daily_sek"] = merged_df.groupby(merged_df.index.date)[
            "export_value_sek"
        ].transform("sum")

        logger.info(
            f"Merged data: {len(merged_df)} rows from {merged_df.index.min()} to {merged_df.index.max()}"
        )

        return merged_df

    def analyze_data(self, merged_df):
        """
        Perform basic analysis on merged data.

        Args:
            merged_df (pd.DataFrame): Merged price and production data

        Returns:
            dict: Analysis results
        """
        analysis = {}

        # Basic statistics
        analysis["period_days"] = (merged_df.index.max() - merged_df.index.min()).days
        analysis["total_hours"] = len(merged_df)

        # Price statistics in SEK/kWh (user-friendly format)
        analysis["price_min_sek_kwh"] = merged_df["price_sek_per_kwh"].min()
        analysis["price_max_sek_kwh"] = merged_df["price_sek_per_kwh"].max()
        analysis["price_mean_sek_kwh"] = merged_df["price_sek_per_kwh"].mean()
        analysis["price_median_sek_kwh"] = merged_df["price_sek_per_kwh"].median()

        # Keep EUR/MWh for reference (internal use)
        analysis["price_min_eur_mwh"] = merged_df["price_eur_per_mwh"].min()
        analysis["price_max_eur_mwh"] = merged_df["price_eur_per_mwh"].max()
        analysis["price_mean_eur_mwh"] = merged_df["price_eur_per_mwh"].mean()
        analysis["price_median_eur_mwh"] = merged_df["price_eur_per_mwh"].median()

        # Production statistics
        analysis["production_total"] = merged_df["production_kwh"].sum()
        analysis["production_mean"] = merged_df["production_kwh"].mean()
        analysis["production_max"] = merged_df["production_kwh"].max()
        analysis["hours_with_production"] = (merged_df["production_kwh"] > 0).sum()

        # Negative price analysis
        negative_prices = merged_df[merged_df["price_eur_per_mwh"] < 0]
        analysis["negative_price_hours"] = len(negative_prices)
        analysis["production_during_negative_prices"] = negative_prices[
            "production_kwh"
        ].sum()
        analysis["negative_export_cost_sek"] = negative_prices[
            "export_value_sek"
        ].sum()  # This will be negative
        analysis["negative_export_cost_abs_sek"] = abs(
            negative_prices["export_value_sek"].sum()
        )  # Absolute cost

        if len(negative_prices) > 0:
            analysis["avg_production_during_negative_prices"] = negative_prices[
                "production_kwh"
            ].mean()
            analysis["avg_negative_price_sek_per_kwh"] = negative_prices[
                "price_sek_per_kwh"
            ].mean()
            analysis["min_negative_price_sek_per_kwh"] = negative_prices[
                "price_sek_per_kwh"
            ].min()
        else:
            analysis["avg_production_during_negative_prices"] = 0
            analysis["avg_negative_price_sek_per_kwh"] = 0
            analysis["min_negative_price_sek_per_kwh"] = 0

        # Total export value
        analysis["total_export_value_sek"] = merged_df["export_value_sek"].sum()
        analysis["positive_export_value_sek"] = merged_df[
            merged_df["price_eur_per_mwh"] > 0
        ]["export_value_sek"].sum()

        return analysis

    def print_analysis(self, analysis):
        """Print analysis results in a formatted way."""
        print("\n" + "=" * 60)
        print("PRICE-PRODUCTION ANALYSIS RESULTS")
        print("=" * 60)

        print(f"\nPERIOD OVERVIEW:")
        print(f"  Period covered: {analysis['period_days']} days")
        print(f"  Total hours of data: {analysis['total_hours']}")

        print(f"\nPRICE STATISTICS (SEK/kWh):")
        print(
            f"  Min price: {analysis['price_min_sek_kwh']:.4f} SEK/kWh ({analysis['price_min_eur_mwh']:.2f} EUR/MWh)"
        )
        print(
            f"  Max price: {analysis['price_max_sek_kwh']:.4f} SEK/kWh ({analysis['price_max_eur_mwh']:.2f} EUR/MWh)"
        )
        print(
            f"  Mean price: {analysis['price_mean_sek_kwh']:.4f} SEK/kWh ({analysis['price_mean_eur_mwh']:.2f} EUR/MWh)"
        )
        print(
            f"  Median price: {analysis['price_median_sek_kwh']:.4f} SEK/kWh ({analysis['price_median_eur_mwh']:.2f} EUR/MWh)"
        )

        print(f"\nPRODUCTION STATISTICS:")
        print(f"  Total production: {analysis['production_total']:.2f} kWh")
        print(f"  Average hourly production: {analysis['production_mean']:.3f} kWh")
        print(f"  Max hourly production: {analysis['production_max']:.3f} kWh")
        print(f"  Hours with production > 0: {analysis['hours_with_production']}")

        print(f"\nNEGATIVE PRICE ANALYSIS:")
        print(f"  Hours with negative prices: {analysis['negative_price_hours']}")
        if analysis["negative_price_hours"] > 0:
            print(
                f"  Production during negative prices: {analysis['production_during_negative_prices']:.2f} kWh"
            )
            print(
                f"  Average production during negative prices: {analysis['avg_production_during_negative_prices']:.3f} kWh"
            )
            print(
                f"  Lowest negative price: {analysis['min_negative_price_sek_per_kwh']:.4f} SEK/kWh"
            )
            print(
                f"  Average negative price: {analysis['avg_negative_price_sek_per_kwh']:.4f} SEK/kWh"
            )
            print(
                f"  COST of negative price exports: {analysis['negative_export_cost_abs_sek']:.2f} SEK"
            )
        else:
            print(f"  No negative price periods found")

        print(f"\nEXPORT VALUE ANALYSIS:")
        print(f"  Total export value: {analysis['total_export_value_sek']:.2f} SEK")
        print(
            f"  Positive price export value: {analysis['positive_export_value_sek']:.2f} SEK"
        )
        print(
            f"  Net export value (after negative costs): {analysis['total_export_value_sek']:.2f} SEK"
        )

        print("\n" + "=" * 60)

    def run_analysis(
        self,
        production_file,
        area_code,
        start_date=None,
        end_date=None,
        output_file=None,
        eur_sek_rate=11.5,
    ):
        """
        Run complete analysis pipeline.

        Args:
            production_file (str): Path to production CSV file
            area_code (str): Electricity area code
            start_date (str, optional): Start date (YYYY-MM-DD)
            end_date (str, optional): End date (YYYY-MM-DD)
            output_file (str, optional): Output file path
            eur_sek_rate (float): EUR to SEK exchange rate
        """
        # Load production data first to determine date range if not provided
        production_df = self.load_production_data(production_file)

        # Set date range - use full production timeframe by default
        production_start = pd.Timestamp(
            production_df.index.min(), tz="Europe/Stockholm"
        )
        production_end = pd.Timestamp(production_df.index.max(), tz="Europe/Stockholm")

        # Only limit timeframe if explicitly provided
        if start_date is not None:
            start_date = pd.Timestamp(start_date, tz="Europe/Stockholm")
            if start_date > production_start:
                production_df = production_df[
                    production_df.index >= start_date.tz_localize(None)
                ]
                logger.info(
                    f"Limiting production data to start from: {start_date.date()}"
                )
        else:
            start_date = production_start

        if end_date is not None:
            end_date = pd.Timestamp(end_date, tz="Europe/Stockholm")
            if end_date < production_end:
                production_df = production_df[
                    production_df.index <= end_date.tz_localize(None)
                ]
                logger.info(f"Limiting production data to end at: {end_date.date()}")
        else:
            end_date = production_end

        logger.info(f"Analysis period: {start_date.date()} to {end_date.date()}")

        # Get price data for the determined timeframe
        prices_df = self.get_price_data(area_code, start_date, end_date)

        # Merge data
        merged_df = self.merge_data(prices_df, production_df, eur_sek_rate)

        # Perform analysis
        analysis = self.analyze_data(merged_df)

        # Print results
        self.print_analysis(analysis)

        # Save merged data if output file specified
        if output_file:
            logger.info(f"Saving merged data to {output_file}")
            merged_df.to_csv(output_file)

        return merged_df, analysis


def main():
    parser = argparse.ArgumentParser(
        description="Analyze electricity prices and solar production data"
    )
    parser.add_argument(
        "--production", required=True, help="Path to production CSV file"
    )
    parser.add_argument(
        "--area", required=True, help="Electricity area code (e.g., SE_4)"
    )
    parser.add_argument(
        "--start-date",
        help="Start date (YYYY-MM-DD) - if not provided, uses full production data range",
    )
    parser.add_argument(
        "--end-date",
        help="End date (YYYY-MM-DD) - if not provided, uses full production data range",
    )
    parser.add_argument("--output", help="Output file path for merged data")
    parser.add_argument(
        "--db-path",
        default="price_data.db",
        help="Path to the price database file (default: price_data.db)",
    )
    parser.add_argument(
        "--eur-sek-rate",
        type=float,
        default=11.5,
        help="EUR to SEK exchange rate (default: 11.5)",
    )

    args = parser.parse_args()

    # Create analyzer
    analyzer = PriceProductionAnalyzer(db_path=args.db_path)

    # Run analysis
    try:
        merged_df, analysis = analyzer.run_analysis(
            production_file=args.production,
            area_code=args.area,
            start_date=args.start_date,
            end_date=args.end_date,
            output_file=args.output,
            eur_sek_rate=args.eur_sek_rate,
        )

        print(f"\nAnalysis completed successfully!")
        if args.output:
            print(f"Merged data saved to: {args.output}")

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
