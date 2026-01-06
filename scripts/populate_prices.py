#!/usr/bin/env python3
"""Populate price database with historical ENTSO-E data for all Swedish zones."""

import sys
import os
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.price_fetcher import PriceFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    # Check for API key
    if not os.getenv('ENTSOE_API_KEY'):
        logger.error("ENTSOE_API_KEY not set!")
        logger.error("Set it with: export ENTSOE_API_KEY=your_api_key")
        sys.exit(1)

    fetcher = PriceFetcher(db_path='data/price_data.db')

    zones = ['SE1', 'SE2', 'SE3', 'SE4']
    start_year = 2022

    logger.info(f"Populating price data from {start_year} to today for zones: {zones}")

    total = 0
    for zone in zones:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing {zone}")
        logger.info(f"{'='*50}")

        records = fetcher.populate_historical_data(zone, start_year=start_year)
        total += records
        logger.info(f"Added {records} records for {zone}")

    logger.info(f"\n{'='*50}")
    logger.info(f"COMPLETE: Added {total} total records")
    logger.info(f"{'='*50}")


if __name__ == '__main__':
    main()
