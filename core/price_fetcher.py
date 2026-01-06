import pandas as pd
from datetime import timedelta
import os
from .db_manager import PriceDatabaseManager
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Import entsoe - this is required
try:
    from entsoe import EntsoePandasClient
    ENTSOE_AVAILABLE = True
except ImportError:
    ENTSOE_AVAILABLE = False
    logger.error("entsoe-py not installed - this is required for price data")


class PriceFetcher:
    """Fetch electricity prices from ENTSO-E Transparency Platform."""

    # Normalize various inputs to standard area codes
    ZONE_MAP = {
        'SE1': 'SE1', 'SE-1': 'SE1', 'SE_1': 'SE1',
        'SE2': 'SE2', 'SE-2': 'SE2', 'SE_2': 'SE2',
        'SE3': 'SE3', 'SE-3': 'SE3', 'SE_3': 'SE3',
        'SE4': 'SE4', 'SE-4': 'SE4', 'SE_4': 'SE4',
    }

    # ENTSO-E area codes for Swedish bidding zones
    ENTSOE_ZONE_MAP = {
        'SE1': '10Y1001A1001A44P',
        'SE2': '10Y1001A1001A45N',
        'SE3': '10Y1001A1001A46L',
        'SE4': '10Y1001A1001A47J',
    }

    def __init__(self, db_path='data/price_data.db'):
        self.db_manager = PriceDatabaseManager(db_path)
        self.entsoe_client = None
        entsoe_key = os.getenv('ENTSOE_API_KEY')
        if ENTSOE_AVAILABLE and entsoe_key:
            self.entsoe_client = EntsoePandasClient(api_key=entsoe_key)
            logger.info("ENTSO-E client initialized with API key")
        elif not ENTSOE_AVAILABLE:
            logger.error("entsoe-py not installed - price fetching will not work")
        else:
            logger.error("ENTSOE_API_KEY not set - price fetching will not work")

    def get_price_data(self, area_code, start_date, end_date, force_api: bool = False):
        """Get price data for area and date range, fetching from ENTSO-E if needed.

        Params:
            area_code: e.g. 'SE3', 'SE_4', or 'SE-3'. Normalized internally.
            start_date, end_date: pandas/py datetime; end exclusive.
            force_api: if True, bypass cache and request from API.
        """
        # Normalize area code
        zone = self.ZONE_MAP.get(str(area_code).upper(), area_code)

        ts_start = pd.Timestamp(start_date)
        ts_end = pd.Timestamp(end_date)

        # Use cache if available and not forcing API
        if not force_api and self.db_manager.has_data_for_period(zone, ts_start, ts_end):
            logger.info(f"Using cached data for {zone} from {ts_start} to {ts_end}")
            return self.db_manager.get_price_data(zone, ts_start, ts_end)

        # Fetch from ENTSO-E API
        logger.info(f"Fetching price data from ENTSO-E for {zone} (force_api={force_api})")

        df_entsoe = self._fetch_from_entsoe(zone, ts_start, ts_end)
        if df_entsoe is not None and not df_entsoe.empty:
            self.db_manager.store_price_data(df_entsoe, zone)
            return df_entsoe

        # Fallback to whatever exists in DB
        logger.warning(f"Could not fetch from ENTSO-E, checking cache for {zone}")
        return self.db_manager.get_price_data(zone, ts_start, ts_end)

    def _fetch_from_entsoe(self, area_code: str, start: pd.Timestamp, end: pd.Timestamp) -> Optional[pd.DataFrame]:
        """Fetch price data from ENTSO-E Transparency Platform.

        Params:
            area_code: Normalized area code (e.g., 'SE4')
            start, end: Timestamps for the date range

        Returns:
            DataFrame with price_eur_per_mwh column, indexed by timestamp (Europe/Stockholm, tz-naive)
        """
        if not self.entsoe_client:
            logger.error("ENTSO-E client not initialized - check ENTSOE_API_KEY")
            return None

        entsoe_zone = self.ENTSOE_ZONE_MAP.get(area_code)
        if not entsoe_zone:
            logger.warning(f"No ENTSO-E zone mapping for {area_code}")
            return None

        try:
            # ENTSO-E requires timezone-aware timestamps
            start_tz = start.tz_localize('Europe/Stockholm') if start.tzinfo is None else start
            end_tz = end.tz_localize('Europe/Stockholm') if end.tzinfo is None else end

            logger.info(f"Fetching from ENTSO-E for {area_code} ({entsoe_zone}) from {start_tz} to {end_tz}")

            # Query day-ahead prices
            prices = self.entsoe_client.query_day_ahead_prices(
                entsoe_zone,
                start=pd.Timestamp(start_tz),
                end=pd.Timestamp(end_tz)
            )

            if prices is None or prices.empty:
                logger.warning(f"No data from ENTSO-E for {area_code}")
                return None

            # Convert to DataFrame with expected format
            df = pd.DataFrame({'price_eur_per_mwh': prices})

            # Make tz-naive for consistency
            if df.index.tzinfo is not None:
                df.index = df.index.tz_convert('Europe/Stockholm').tz_localize(None)

            logger.info(f"Fetched {len(df)} price points from ENTSO-E for {area_code}")
            return df

        except Exception as e:
            logger.error(f"Error fetching from ENTSO-E: {e}")
            return None

    def populate_historical_data(self, area_code: str, start_year: int = 2022):
        """Populate database with historical price data from ENTSO-E.

        Params:
            area_code: Zone to populate (e.g., 'SE4')
            start_year: Year to start from (default 2022)

        Returns:
            Number of records added
        """
        zone = self.ZONE_MAP.get(str(area_code).upper(), area_code)

        # Fetch from start of year to now
        start = pd.Timestamp(f'{start_year}-01-01', tz='Europe/Stockholm')
        end = pd.Timestamp.now(tz='Europe/Stockholm') + pd.Timedelta(days=1)

        logger.info(f"Populating historical data for {zone} from {start} to {end}")

        # ENTSO-E has limits, so fetch in chunks of ~30 days
        chunk_days = 30
        current = start
        total_records = 0

        while current < end:
            chunk_end = min(current + pd.Timedelta(days=chunk_days), end)

            try:
                df = self._fetch_from_entsoe(zone, current.tz_localize(None), chunk_end.tz_localize(None))
                if df is not None and not df.empty:
                    self.db_manager.store_price_data(df, zone)
                    total_records += len(df)
                    logger.info(f"Stored {len(df)} records for {zone} ({current.date()} to {chunk_end.date()})")
            except Exception as e:
                logger.error(f"Error fetching chunk for {zone}: {e}")

            current = chunk_end

        logger.info(f"Finished populating {zone}: {total_records} total records")
        return total_records
