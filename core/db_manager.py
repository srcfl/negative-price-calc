import sqlite3
import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class PriceDatabaseManager:
    def __init__(self, db_path="data/price_data.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._create_tables()

    def _create_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_data (
                    datetime TEXT,
                    area_code TEXT,
                    price_eur_per_mwh REAL,
                    PRIMARY KEY (datetime, area_code)
                )
            """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_datetime ON price_data(datetime)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_area ON price_data(area_code)")

    def store_price_data(self, df, area_code):
        """Upsert price data into database for given area_code."""
        if df is None or df.empty:
            return
        rows = [
            (pd.Timestamp(idx).strftime("%Y-%m-%d %H:%M:%S"), area_code, float(val))
            for idx, val in df["price_eur_per_mwh"].items()
            if pd.notna(val)
        ]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO price_data (datetime, area_code, price_eur_per_mwh)
                VALUES (?, ?, ?)
                ON CONFLICT(datetime, area_code) DO UPDATE SET
                    price_eur_per_mwh = excluded.price_eur_per_mwh
                """,
                rows,
            )
        logger.info(f"Stored {len(rows)} price records for {area_code}")

    def get_price_data(self, area_code, start_date, end_date):
        """Retrieve price data from database."""
        query = """
            SELECT datetime, price_eur_per_mwh 
            FROM price_data 
            WHERE area_code = ? AND datetime BETWEEN ? AND ?
            ORDER BY datetime
        """

        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                query,
                conn,
                params=[
                    area_code,
                    pd.Timestamp(start_date).strftime("%Y-%m-%d %H:%M:%S"),
                    pd.Timestamp(end_date).strftime("%Y-%m-%d %H:%M:%S"),
                ],
                parse_dates=["datetime"],
                index_col="datetime",
            )

        return df

    def has_data_for_period(self, area_code, start_date, end_date):
        """Check if database has data for the specified period."""
        query = """
            SELECT COUNT(*) FROM price_data 
            WHERE area_code = ? AND datetime BETWEEN ? AND ?
        """

        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                query,
                [
                    area_code,
                    pd.Timestamp(start_date).strftime("%Y-%m-%d %H:%M:%S"),
                    pd.Timestamp(end_date).strftime("%Y-%m-%d %H:%M:%S"),
                ],
            ).fetchone()[0]

        expected_hours = (
            pd.Timestamp(end_date) - pd.Timestamp(start_date)
        ).total_seconds() / 3600
        return count >= expected_hours * 0.8  # Allow 20% missing data
