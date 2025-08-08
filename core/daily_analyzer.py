#!/usr/bin/env python3
"""
Daily Analysis Engine

Simplified analysis logic for daily electricity prices and production data.
Handles daily data aggregation and basic statistics without negative price analysis.
"""

import pandas as pd
import logging
from typing import Dict, Any
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DailyAnalyzer:
    """Simplified analysis engine for daily price and production data."""
    
    @staticmethod
    def merge_daily_data(prices_df: pd.DataFrame, production_df: pd.DataFrame, eur_sek_rate: float = 11.5) -> pd.DataFrame:
        """
        Merge daily price and production data.
        
        Args:
            prices_df (pd.DataFrame): Hourly price data with datetime index
            production_df (pd.DataFrame): Daily production data with datetime index
            eur_sek_rate (float): EUR to SEK exchange rate
            
        Returns:
            pd.DataFrame: Merged daily data with calculated columns
        """
        logger.info("Merging daily price and production data")
        
        # Prepare aggregation dictionary based on available columns
        agg_dict = {'price_eur_per_mwh': 'mean'}
        if 'area' in prices_df.columns:
            agg_dict['area'] = 'first'
        
        # Aggregate hourly prices to daily averages
        daily_prices = prices_df.groupby(prices_df.index.date).agg(agg_dict).reset_index()
        daily_prices['index'] = pd.to_datetime(daily_prices['index'])
        daily_prices.set_index('index', inplace=True)
        daily_prices.index.name = 'datetime'
        
        # Ensure production data is properly indexed
        if not isinstance(production_df.index, pd.DatetimeIndex):
            production_df.index = pd.to_datetime(production_df.index)
        
        # Merge on date
        merged_df = pd.merge(daily_prices, production_df, left_index=True, right_index=True, how='inner')
        
        # Add SEK pricing (convert from EUR/MWh to SEK/kWh)
        merged_df['price_sek_per_kwh'] = (merged_df['price_eur_per_mwh'] * eur_sek_rate) / 1000
        
        # Calculate daily export value
        merged_df['export_value_sek'] = merged_df['production_kwh'] * merged_df['price_sek_per_kwh']
        
        logger.info(f"Merged daily data: {len(merged_df)} rows from {merged_df.index.min()} to {merged_df.index.max()}")
        
        return merged_df
    
    @staticmethod
    def analyze_daily_data(merged_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Perform simplified daily analysis without negative price calculations.
        
        Args:
            merged_df (pd.DataFrame): Merged daily data
            
        Returns:
            Dict[str, Any]: Analysis results
        """
        logger.info("Performing daily analysis")
        
        # Basic statistics
        total_production = merged_df['production_kwh'].sum()
        total_export_value = merged_df['export_value_sek'].sum()
        avg_daily_production = merged_df['production_kwh'].mean()
        avg_daily_price = merged_df['price_eur_per_mwh'].mean()
        avg_daily_price_sek = merged_df['price_sek_per_kwh'].mean()
        
        # Find best and worst days
        best_price_idx = merged_df['price_eur_per_mwh'].idxmax()
        worst_price_idx = merged_df['price_eur_per_mwh'].idxmin()
        best_production_idx = merged_df['production_kwh'].idxmax()
        worst_production_idx = merged_df['production_kwh'].idxmin()
        best_value_idx = merged_df['export_value_sek'].idxmax()
        
        best_price_day = merged_df.loc[best_price_idx]
        worst_price_day = merged_df.loc[worst_price_idx]
        best_production_day = merged_df.loc[best_production_idx]
        worst_production_day = merged_df.loc[worst_production_idx]
        best_value_day = merged_df.loc[best_value_idx]
        
        # Monthly aggregations - convert to JSON-serializable format
        monthly_data = merged_df.groupby(pd.Grouper(freq='ME')).agg({
            'production_kwh': 'sum',
            'export_value_sek': 'sum',
            'price_eur_per_mwh': 'mean'
        })
        
        # Convert monthly data to JSON-serializable format
        monthly_summary = {}
        for date_index, row in monthly_data.iterrows():
            month_key = date_index.strftime('%Y-%m')
            monthly_summary[month_key] = {
                'production_kwh': float(row['production_kwh']),
                'export_value_sek': float(row['export_value_sek']),
                'avg_price_eur_per_mwh': float(row['price_eur_per_mwh'])
            }
        
        # Price distribution
        price_percentiles = merged_df['price_eur_per_mwh'].quantile([0.1, 0.25, 0.5, 0.75, 0.9])
        
        analysis = {
            'analysis_type': 'daily',
            'data_period': {
                'start': merged_df.index.min().strftime('%Y-%m-%d'),
                'end': merged_df.index.max().strftime('%Y-%m-%d'),
                'days': len(merged_df)
            },
            'production_summary': {
                'total_kwh': float(total_production),
                'average_daily_kwh': float(avg_daily_production),
                'max_daily_kwh': float(merged_df['production_kwh'].max()),
                'min_daily_kwh': float(merged_df['production_kwh'].min()),
                'std_daily_kwh': float(merged_df['production_kwh'].std())
            },
            'price_summary': {
                'average_eur_per_mwh': float(avg_daily_price),
                'average_sek_per_kwh': float(avg_daily_price_sek),
                'max_eur_per_mwh': float(merged_df['price_eur_per_mwh'].max()),
                'min_eur_per_mwh': float(merged_df['price_eur_per_mwh'].min()),
                'std_eur_per_mwh': float(merged_df['price_eur_per_mwh'].std()),
                'percentiles': {
                    '10th': float(price_percentiles[0.1]),
                    '25th': float(price_percentiles[0.25]),
                    '50th': float(price_percentiles[0.5]),
                    '75th': float(price_percentiles[0.75]),
                    '90th': float(price_percentiles[0.9])
                }
            },
            'value_summary': {
                'total_export_value_sek': float(total_export_value),
                'average_daily_value_sek': float(merged_df['export_value_sek'].mean()),
                'value_per_kwh_sek': float(total_export_value / total_production if total_production > 0 else 0)
            },
            'best_days': {
                'highest_price': {
                    'date': best_price_idx.strftime('%Y-%m-%d'),
                    'price_eur_per_mwh': float(best_price_day['price_eur_per_mwh']),
                    'production_kwh': float(best_price_day['production_kwh']),
                    'value_sek': float(best_price_day['export_value_sek'])
                },
                'lowest_price': {
                    'date': worst_price_idx.strftime('%Y-%m-%d'),
                    'price_eur_per_mwh': float(worst_price_day['price_eur_per_mwh']),
                    'production_kwh': float(worst_price_day['production_kwh']),
                    'value_sek': float(worst_price_day['export_value_sek'])
                },
                'highest_production': {
                    'date': best_production_idx.strftime('%Y-%m-%d'),
                    'production_kwh': float(best_production_day['production_kwh']),
                    'price_eur_per_mwh': float(best_production_day['price_eur_per_mwh']),
                    'value_sek': float(best_production_day['export_value_sek'])
                },
                'lowest_production': {
                    'date': worst_production_idx.strftime('%Y-%m-%d'),
                    'production_kwh': float(worst_production_day['production_kwh']),
                    'price_eur_per_mwh': float(worst_production_day['price_eur_per_mwh']),
                    'value_sek': float(worst_production_day['export_value_sek'])
                },
                'highest_value': {
                    'date': best_value_idx.strftime('%Y-%m-%d'),
                    'production_kwh': float(best_value_day['production_kwh']),
                    'price_eur_per_mwh': float(best_value_day['price_eur_per_mwh']),
                    'value_sek': float(best_value_day['export_value_sek'])
                }
            },
            'monthly_summary': monthly_summary,
            'warning': {
                'message': 'Daglig data användes för analys. För negativ prisanalys krävs timdata.',
                'recommendation': 'Ladda upp data med timupplösning för att få fullständig negativ prisanalys.',
                'analysis_limitations': [
                    'Inga negativa priser analyseras (dagliga snitt är alltid positiva)',
                    'Timvisa variationer syns inte',
                    'Optimal export-timing kan inte beräknas'
                ],
                'zap_info': 'Med en Sourceful Energy ZAP får du automatisk realtidsdata och timvis analys av negativa elpriser.'
            }
        }
        
        logger.info(f"Daily analysis completed: {total_production:.1f} kWh total production, "
                   f"{total_export_value:.2f} SEK total value")
        
        return analysis
