import pandas as pd
from datetime import timedelta
import os
from .db_manager import PriceDatabaseManager
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

class PriceFetcher:
    # Normalize various inputs to Sourceful API expected area codes
    ZONE_MAP = {
        'SE1': 'SE1', 'SE-1': 'SE1', 'SE_1': 'SE1',
        'SE2': 'SE2', 'SE-2': 'SE2', 'SE_2': 'SE2',
        'SE3': 'SE3', 'SE-3': 'SE3', 'SE_3': 'SE3',
        'SE4': 'SE4', 'SE-4': 'SE4', 'SE_4': 'SE4',
    }

    SOURCEFUL_API_BASE = 'https://mainnet.srcful.dev/price/electricity'

    def __init__(self, db_path='data/price_data.db'):
        self.db_manager = PriceDatabaseManager(db_path)
        logger.info("Using Sourceful Price API (no API key required)")

    def get_price_data(self, area_code, start_date, end_date, force_api: bool = False):
        """Get price data for area and date range, fetching from API if needed.

        Params:
            area_code: e.g. 'SE3', 'SE_4', or 'SE-3'. Normalized to Sourceful format.
            start_date, end_date: pandas/py datetime; end exclusive.
            force_api: if True, bypass cache and request from API.
        """
        # Normalize area code
        zone = self.ZONE_MAP.get(str(area_code).upper(), area_code)

        # Use cache if available and not forcing API
        if not force_api and self.db_manager.has_data_for_period(area_code, start_date, end_date):
            logger.info(f"Using cached data for {area_code} from {start_date} to {end_date}")
            return self.db_manager.get_price_data(area_code, start_date, end_date)

        # Fetch from Sourceful API
        logger.info(f"Fetching price data from Sourceful API for {zone} (force_api={force_api})")

        ts_start = pd.Timestamp(start_date)
        ts_end = pd.Timestamp(end_date)

        # Sourceful API returns data per day, so we need to fetch each day
        current_date = ts_start.normalize()
        end_date_norm = ts_end.normalize()
        frames = []

        while current_date < end_date_norm:
            try:
                df_day = self._fetch_from_sourceful_api(zone, current_date)
                if df_day is not None and not df_day.empty:
                    frames.append(df_day)
                    self.db_manager.store_price_data(df_day, area_code)
                else:
                    logger.warning(f"No data returned for {zone} on {current_date.date()}")
            except Exception as e:
                logger.error(f"Error fetching data for {zone} on {current_date.date()}: {e}")

            current_date += pd.Timedelta(days=1)

        if frames:
            df = pd.concat(frames).sort_index()
            df = df[~df.index.duplicated(keep='last')]
            # Filter to requested range
            df = df[(df.index >= ts_start) & (df.index < ts_end)]
            return df

        # Fallback to whatever exists in DB
        logger.warning(f"Incomplete data available for {area_code} from {start_date} to {end_date}")
        return self.db_manager.get_price_data(area_code, start_date, end_date)
    
    def _fetch_from_sourceful_api(self, area_code: str, date: pd.Timestamp) -> Optional[pd.DataFrame]:
        """Fetch price data from Sourceful API for a specific date.

        Params:
            area_code: Normalized area code (e.g., 'SE3')
            date: The date to fetch prices for

        Returns:
            DataFrame with price_eur_per_mwh column, indexed by timestamp (Europe/Stockholm, tz-naive)
        """
        try:
            # Format date as YYYY-MM-DD
            date_str = date.strftime('%Y-%m-%d')
            url = f"{self.SOURCEFUL_API_BASE}/{area_code}"
            params = {'date': date_str}

            logger.debug(f"Requesting {url} with params {params}")
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            # Parse the response
            if 'prices' not in data or not data['prices']:
                logger.warning(f"No prices in response for {area_code} on {date_str}")
                return None

            # Convert to DataFrame
            prices = data['prices']
            df = pd.DataFrame(prices)

            # Convert datetime strings to timestamps
            df['datetime'] = pd.to_datetime(df['datetime'])

            # Convert from UTC to Europe/Stockholm and make tz-naive for consistency
            df['datetime'] = df['datetime'].dt.tz_convert('Europe/Stockholm').dt.tz_localize(None)

            # Set datetime as index
            df.set_index('datetime', inplace=True)

            # Rename price column to match expected format
            df.rename(columns={'price': 'price_eur_per_mwh'}, inplace=True)

            # Ensure numeric type
            df['price_eur_per_mwh'] = pd.to_numeric(df['price_eur_per_mwh'], errors='coerce')

            logger.debug(f"Fetched {len(df)} price points for {area_code} on {date_str}")
            return df

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error fetching from Sourceful API: {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Error parsing Sourceful API response: {e}")
            return None

    def _fetch_from_api(self, area_code, start_date, end_date):
        """Deprecated: Use _fetch_from_sourceful_api instead."""
        return None

    def _parse_xml_response(self, xml_text):
        """Deprecated: No longer used with Sourceful API."""
        return None