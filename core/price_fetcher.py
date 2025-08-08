import pandas as pd
from datetime import timedelta
import os
from .db_manager import PriceDatabaseManager
import logging
from entsoe import EntsoePandasClient

logger = logging.getLogger(__name__)

class PriceFetcher:
    # Normalize various inputs to entsoe-py expected bidding zone codes
    ZONE_MAP = {
        'SE1': 'SE_1', 'SE-1': 'SE_1', 'SE_1': 'SE_1',
        'SE2': 'SE_2', 'SE-2': 'SE_2', 'SE_2': 'SE_2',
        'SE3': 'SE_3', 'SE-3': 'SE_3', 'SE_3': 'SE_3',
        'SE4': 'SE_4', 'SE-4': 'SE_4', 'SE_4': 'SE_4',
    }

    def __init__(self, db_path='data/price_data.db'):
        self.api_key = os.getenv('ENTSOE_API_KEY')
        self.db_manager = PriceDatabaseManager(db_path)
        self.client = EntsoePandasClient(api_key=self.api_key) if self.api_key else None

        if not self.api_key:
            logger.warning("No ENTSO-E API key found. Using existing database data only.")

    def get_price_data(self, area_code, start_date, end_date, force_api: bool = False):
        """Get price data for area and date range, fetching from API if needed.

        Params:
            area_code: e.g. 'SE_4' or EIC code. Stored in DB as provided.
            start_date, end_date: pandas/py datetime; end exclusive.
            force_api: if True, bypass cache and request API when key present.
        """
        # Use cache if available and not forcing API
        if not force_api and self.db_manager.has_data_for_period(area_code, start_date, end_date):
            logger.info(f"Using cached data for {area_code} from {start_date} to {end_date}")
            return self.db_manager.get_price_data(area_code, start_date, end_date)

        # Fetch from API if key exists
        if self.client is not None:
            logger.info(f"Fetching price data from ENTSO-E API for {area_code} (force_api={force_api})")
            # ENTSO-E enforces max P1Y window; chunk by <= 365 days
            ts_start = pd.Timestamp(start_date)
            ts_end = pd.Timestamp(end_date)
            if ts_start.tzinfo is None:
                ts_start = ts_start.tz_localize('Europe/Stockholm')
            else:
                ts_start = ts_start.tz_convert('Europe/Stockholm')
            if ts_end.tzinfo is None:
                ts_end = ts_end.tz_localize('Europe/Stockholm')
            else:
                ts_end = ts_end.tz_convert('Europe/Stockholm')
            chunk_start = ts_start
            chunk_end = ts_end
            frames = []
            zone = self.ZONE_MAP.get(str(area_code).upper(), area_code)
            while chunk_start < chunk_end:
                next_end = min(chunk_start + pd.Timedelta(days=365), chunk_end)
                try:
                    # entsoe-py returns EUR/MWh Series indexed by tz-aware UTC timestamps
                    series = self.client.query_day_ahead_prices(zone, chunk_start.tz_convert('UTC'), next_end.tz_convert('UTC'))
                except Exception as e:
                    logger.error(f"ENTSOE client error for chunk {chunk_start} to {next_end}: {e}")
                    series = None
                if series is not None and not series.empty:
                    # Ensure tz-aware UTC
                    idx = pd.DatetimeIndex(series.index)
                    if idx.tz is None:
                        idx = idx.tz_localize('UTC')
                    # Convert to Europe/Stockholm, then drop tz for project-wide consistency
                    idx = idx.tz_convert('Europe/Stockholm').tz_localize(None)
                    df_chunk = series.to_frame(name='price_eur_per_mwh')
                    df_chunk.index = idx
                    frames.append(df_chunk)
                    self.db_manager.store_price_data(df_chunk, area_code)
                else:
                    logger.warning(f"No data returned for chunk {chunk_start} to {next_end}")
                chunk_start = next_end
            if frames:
                df = pd.concat(frames).sort_index()
                df = df[~df.index.duplicated(keep='last')]
                return df

        # Fallback to whatever exists in DB
        logger.warning(f"Incomplete data available for {area_code} from {start_date} to {end_date}")
        return self.db_manager.get_price_data(area_code, start_date, end_date)
    
    def _fetch_from_api(self, area_code, start_date, end_date):
        """Deprecated: retained for compatibility; entsoe-py client is used instead."""
        return None
    
    def _parse_xml_response(self, xml_text):
        return None