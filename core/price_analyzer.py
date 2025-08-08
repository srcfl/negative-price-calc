#!/usr/bin/env python3
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

class PriceAnalyzer:
    def __init__(self):
        pass
    
    def merge_data(self, prices_df, production_df, currency_rate=11.5):
        """Merge price and production data on datetime index."""
        # Ensure both dataframes have datetime index
        if not isinstance(prices_df.index, pd.DatetimeIndex):
            prices_df.index = pd.to_datetime(prices_df.index)
        if not isinstance(production_df.index, pd.DatetimeIndex):
            production_df.index = pd.to_datetime(production_df.index)
        
        # Merge on datetime index
        merged_df = pd.merge(
            prices_df, production_df,
            left_index=True, right_index=True,
            how='inner'
        )
        
        # Calculate derived columns
        merged_df['price_sek_per_kwh'] = merged_df['price_eur_per_mwh'] * currency_rate / 1000
        merged_df['export_value_sek'] = merged_df['production_kwh'] * merged_df['price_sek_per_kwh']
        
        logger.info(f"Merged data: {len(merged_df)} records from {merged_df.index.min()} to {merged_df.index.max()}")
        
        return merged_df
    
    def analyze_data(self, merged_df):
        """Perform comprehensive analysis on merged data."""
        analysis = {}
        
        # Basic statistics
        analysis['period_days'] = (merged_df.index.max() - merged_df.index.min()).days + 1
        analysis['total_hours'] = len(merged_df)
        
        # Price statistics
        analysis['price_min_eur_mwh'] = merged_df['price_eur_per_mwh'].min()
        analysis['price_max_eur_mwh'] = merged_df['price_eur_per_mwh'].max()
        analysis['price_mean_eur_mwh'] = merged_df['price_eur_per_mwh'].mean()
        analysis['price_median_eur_mwh'] = merged_df['price_eur_per_mwh'].median()
        
        # Production statistics
        analysis['production_total'] = merged_df['production_kwh'].sum()
        analysis['production_mean'] = merged_df['production_kwh'].mean()
        analysis['production_max'] = merged_df['production_kwh'].max()
        analysis['hours_with_production'] = (merged_df['production_kwh'] > 0).sum()
        
        # Negative price analysis
        negative_mask = merged_df['price_eur_per_mwh'] < 0
        analysis['negative_price_hours'] = negative_mask.sum()
        
        if analysis['negative_price_hours'] > 0:
            negative_production_mask = negative_mask & (merged_df['production_kwh'] > 0)
            analysis['production_during_negative_prices'] = merged_df.loc[negative_production_mask, 'production_kwh'].sum()
            analysis['avg_production_during_negative_prices'] = merged_df.loc[negative_production_mask, 'production_kwh'].mean()
            analysis['negative_export_cost_abs_sek'] = abs(merged_df.loc[negative_mask, 'export_value_sek'].sum())
        else:
            analysis['production_during_negative_prices'] = 0
            analysis['avg_production_during_negative_prices'] = 0
            analysis['negative_export_cost_abs_sek'] = 0
        
        # Export value analysis
        analysis['total_export_value_sek'] = merged_df['export_value_sek'].sum()
        positive_mask = merged_df['price_eur_per_mwh'] > 0
        analysis['positive_export_value_sek'] = merged_df.loc[positive_mask, 'export_value_sek'].sum()
        
        # Time series data for charts
        analysis['time_series'] = {
            'timestamps': merged_df.index.strftime('%Y-%m-%d %H:%M').tolist(),
            'prices_eur_mwh': merged_df['price_eur_per_mwh'].tolist(),
            'production_kwh': merged_df['production_kwh'].tolist(),
            'export_values_sek': merged_df['export_value_sek'].tolist()
        }
        
        # Daily summary
        daily_summary = self.get_daily_summary(merged_df)
        analysis['daily_series'] = {
            'dates': daily_summary.index.strftime('%Y-%m-%d').tolist(),
            'daily_production': daily_summary['production_kwh_sum'].tolist(),
            'daily_export_value': daily_summary['export_value_sek_sum'].tolist(),
            'daily_avg_price': daily_summary['price_sek_per_kwh_mean'].tolist()
        }
        
        return analysis
    
    def get_daily_summary(self, merged_df):
        """Get daily summary statistics."""
        daily_summary = merged_df.resample('D').agg({
            'production_kwh': ['sum', 'mean', 'max'],
            'price_sek_per_kwh': ['mean', 'min', 'max'],
            'export_value_sek': ['sum', 'mean']
        })
        
        # Flatten column names
        daily_summary.columns = [f"{col[0]}_{col[1]}" for col in daily_summary.columns]
        
        return daily_summary
    
    def analyze_negative_prices(self, merged_df):
        """Detailed analysis of negative price periods."""
        negative_mask = merged_df['price_eur_per_mwh'] < 0
        negative_df = merged_df[negative_mask].copy()
        
        if negative_df.empty:
            return {
                'has_negative_prices': False,
                'message': 'No negative prices found in the dataset'
            }
        
        # Find consecutive negative periods
        negative_df['date'] = negative_df.index.date
        negative_df['hour'] = negative_df.index.hour
        
        # Group by date
        daily_negative = negative_df.groupby('date').agg({
            'production_kwh': 'sum',
            'export_value_sek': 'sum',
            'price_eur_per_mwh': ['min', 'mean']
        })
        
        # Monthly breakdown
        negative_df['month'] = negative_df.index.to_period('M')
        monthly_negative = negative_df.groupby('month').agg({
            'production_kwh': 'sum',
            'export_value_sek': 'sum'
        })
        
        return {
            'has_negative_prices': True,
            'total_negative_hours': len(negative_df),
            'total_cost_sek': abs(negative_df['export_value_sek'].sum()),
            'average_negative_price_eur_mwh': negative_df['price_eur_per_mwh'].mean(),
            'lowest_price_eur_mwh': negative_df['price_eur_per_mwh'].min(),
            'daily_breakdown': daily_negative,
            'monthly_breakdown': monthly_negative,
            'most_expensive_hours': negative_df.nsmallest(10, 'export_value_sek')
        }

import pandas as pd
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PriceAnalyzer:
    """Core analysis engine for price and production data."""
    
    @staticmethod
    def merge_data(prices_df: pd.DataFrame, production_df: pd.DataFrame, eur_sek_rate: float = 11.5) -> pd.DataFrame:
        """
        Merge price and production data on datetime index.
        
        Args:
            prices_df (pd.DataFrame): Price data with datetime index
            production_df (pd.DataFrame): Production data with datetime index
            eur_sek_rate (float): EUR to SEK exchange rate
            
        Returns:
            pd.DataFrame: Merged data with calculated columns
        """
        logger.info("Merging price and production data")
        
        # Merge on datetime index
        merged_df = pd.merge(prices_df, production_df, left_index=True, right_index=True, how='inner')
        
        # Add SEK pricing (convert from EUR/MWh to SEK/kWh)
        merged_df['price_sek_per_kwh'] = (merged_df['price_eur_per_mwh'] * eur_sek_rate) / 1000
        
        # Calculate export value/cost for each hour
        merged_df['export_value_sek'] = merged_df['production_kwh'] * merged_df['price_sek_per_kwh']
        
        # Add daily aggregations
        merged_df['production_daily'] = merged_df.groupby(merged_df.index.date)['production_kwh'].transform('sum')
        merged_df['price_daily_avg'] = merged_df.groupby(merged_df.index.date)['price_eur_per_mwh'].transform('mean')
        merged_df['export_value_daily_sek'] = merged_df.groupby(merged_df.index.date)['export_value_sek'].transform('sum')
        
        logger.info(f"Merged data: {len(merged_df)} rows from {merged_df.index.min()} to {merged_df.index.max()}")
        
        return merged_df
    
    @staticmethod
    def analyze_data(merged_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Perform comprehensive analysis on merged price and production data.
        
        Args:
            merged_df (pd.DataFrame): Merged price and production data
            
        Returns:
            Dict[str, Any]: Analysis results with statistics and insights
        """
        analysis = {}
        
        # Basic statistics
        analysis['period_days'] = (merged_df.index.max() - merged_df.index.min()).days
        analysis['total_hours'] = len(merged_df)
        
        # Time series data for charts (limit to prevent large payloads)
        time_series_limit = min(len(merged_df), 720)  # Max 30 days of hourly data
        sample_df = merged_df.head(time_series_limit) if len(merged_df) > time_series_limit else merged_df
        
        analysis['time_series'] = {
            'timestamps': [dt.isoformat() for dt in sample_df.index],
            'production': sample_df['production_kwh'].tolist(),
            'prices_eur_mwh': sample_df['price_eur_per_mwh'].tolist(),
            'prices_sek_kwh': sample_df['price_sek_per_kwh'].tolist(),
            'export_values': sample_df['export_value_sek'].tolist(),
            'negative_price_mask': (sample_df['price_eur_per_mwh'] < 0).tolist()
        }
        
        # Daily aggregations for monthly/weekly views
        daily_data = merged_df.groupby(merged_df.index.date).agg({
            'production_kwh': 'sum',
            'price_eur_per_mwh': 'mean',
            'export_value_sek': 'sum'
        }).reset_index()
        
        analysis['daily_series'] = {
            'dates': [d.isoformat() for d in daily_data['index']],
            'daily_production': daily_data['production_kwh'].tolist(),
            'daily_avg_price': daily_data['price_eur_per_mwh'].tolist(),
            'daily_export_value': daily_data['export_value_sek'].tolist()
        }
        
        # Negative pricing insights
        negative_periods = merged_df[merged_df['price_eur_per_mwh'] < 0]
        if len(negative_periods) > 0:
            analysis['negative_price_timeline'] = {
                'timestamps': [dt.isoformat() for dt in negative_periods.index],
                'production_kwh': negative_periods['production_kwh'].tolist(),
                'prices_eur_mwh': negative_periods['price_eur_per_mwh'].tolist(),
                'cost_sek': negative_periods['export_value_sek'].tolist()
            }
        else:
            analysis['negative_price_timeline'] = None
        
        # Price statistics in SEK/kWh (user-friendly format)
        analysis['price_min_sek_kwh'] = merged_df['price_sek_per_kwh'].min()
        analysis['price_max_sek_kwh'] = merged_df['price_sek_per_kwh'].max()
        analysis['price_mean_sek_kwh'] = merged_df['price_sek_per_kwh'].mean()
        analysis['price_median_sek_kwh'] = merged_df['price_sek_per_kwh'].median()
        
        # Keep EUR/MWh for reference (internal use)
        analysis['price_min_eur_mwh'] = merged_df['price_eur_per_mwh'].min()
        analysis['price_max_eur_mwh'] = merged_df['price_eur_per_mwh'].max()
        analysis['price_mean_eur_mwh'] = merged_df['price_eur_per_mwh'].mean()
        analysis['price_median_eur_mwh'] = merged_df['price_eur_per_mwh'].median()
        
        # Production statistics
        analysis['production_total'] = merged_df['production_kwh'].sum()
        analysis['production_mean'] = merged_df['production_kwh'].mean()
        analysis['production_max'] = merged_df['production_kwh'].max()
        analysis['hours_with_production'] = (merged_df['production_kwh'] > 0).sum()
        
        # Negative price analysis (Enhanced)
        negative_prices = merged_df[merged_df['price_eur_per_mwh'] < 0]
        analysis['negative_price_hours'] = len(negative_prices)
        analysis['production_during_negative_prices'] = negative_prices['production_kwh'].sum()
        analysis['negative_export_cost_sek'] = negative_prices['export_value_sek'].sum()  # This will be negative
        analysis['negative_export_cost_abs_sek'] = abs(negative_prices['export_value_sek'].sum())  # Absolute cost
        
        # Enhanced negative pricing metrics
        analysis['negative_price_percentage'] = (len(negative_prices) / len(merged_df)) * 100 if len(merged_df) > 0 else 0
        analysis['production_percentage_negative_prices'] = (analysis['production_during_negative_prices'] / analysis['production_total']) * 100 if analysis['production_total'] > 0 else 0
        
        if len(negative_prices) > 0:
            analysis['avg_production_during_negative_prices'] = negative_prices['production_kwh'].mean()
            analysis['avg_negative_price_sek_per_kwh'] = negative_prices['price_sek_per_kwh'].mean()
            analysis['min_negative_price_sek_per_kwh'] = negative_prices['price_sek_per_kwh'].min()
            
            # Find the worst negative price period
            worst_negative_idx = negative_prices['price_eur_per_mwh'].idxmin()
            analysis['worst_negative_price_datetime'] = worst_negative_idx.isoformat()
            analysis['worst_negative_price_eur_mwh'] = negative_prices.loc[worst_negative_idx, 'price_eur_per_mwh']
            analysis['worst_negative_price_production'] = negative_prices.loc[worst_negative_idx, 'production_kwh']
            analysis['worst_negative_price_cost'] = abs(negative_prices.loc[worst_negative_idx, 'export_value_sek'])
        else:
            analysis['avg_production_during_negative_prices'] = 0
            analysis['avg_negative_price_sek_per_kwh'] = 0
            analysis['min_negative_price_sek_per_kwh'] = 0
            analysis['worst_negative_price_datetime'] = None
            analysis['worst_negative_price_eur_mwh'] = 0
            analysis['worst_negative_price_production'] = 0
            analysis['worst_negative_price_cost'] = 0
        
        # Total export value
        analysis['total_export_value_sek'] = merged_df['export_value_sek'].sum()
        analysis['positive_export_value_sek'] = merged_df[merged_df['price_eur_per_mwh'] > 0]['export_value_sek'].sum()
        
        # Correlation analysis
        if merged_df['production_kwh'].var() > 0 and merged_df['price_sek_per_kwh'].var() > 0:
            analysis['price_production_correlation'] = merged_df['production_kwh'].corr(merged_df['price_sek_per_kwh'])
        else:
            analysis['price_production_correlation'] = 0
        
        # Volatility metrics
        analysis['price_volatility_std'] = merged_df['price_sek_per_kwh'].std()
        analysis['price_volatility_cv'] = analysis['price_volatility_std'] / analysis['price_mean_sek_kwh'] if analysis['price_mean_sek_kwh'] != 0 else 0
        
        return analysis
    
    @staticmethod
    def print_analysis(analysis: Dict[str, Any]):
        """Print analysis results in a formatted way."""
        print("\n" + "="*60)
        print("PRICE-PRODUCTION ANALYSIS RESULTS")
        print("="*60)
        
        print(f"\nPERIOD OVERVIEW:")
        print(f"  Period covered: {analysis['period_days']} days")
        print(f"  Total hours of data: {analysis['total_hours']}")
        
        print(f"\nPRICE STATISTICS (SEK/kWh):")
        print(f"  Min price: {analysis['price_min_sek_kwh']:.4f} SEK/kWh ({analysis['price_min_eur_mwh']:.2f} EUR/MWh)")
        print(f"  Max price: {analysis['price_max_sek_kwh']:.4f} SEK/kWh ({analysis['price_max_eur_mwh']:.2f} EUR/MWh)")
        print(f"  Mean price: {analysis['price_mean_sek_kwh']:.4f} SEK/kWh ({analysis['price_mean_eur_mwh']:.2f} EUR/MWh)")
        print(f"  Median price: {analysis['price_median_sek_kwh']:.4f} SEK/kWh ({analysis['price_median_eur_mwh']:.2f} EUR/MWh)")
        print(f"  Price volatility (std): {analysis['price_volatility_std']:.4f} SEK/kWh")
        print(f"  Price volatility (CV): {analysis['price_volatility_cv']:.2%}")
        
        print(f"\nPRODUCTION STATISTICS:")
        print(f"  Total production: {analysis['production_total']:.2f} kWh")
        print(f"  Average hourly production: {analysis['production_mean']:.3f} kWh")
        print(f"  Max hourly production: {analysis['production_max']:.3f} kWh")
        print(f"  Hours with production > 0: {analysis['hours_with_production']}")
        
        print(f"\nCORRELATION ANALYSIS:")
        print(f"  Price-Production correlation: {analysis['price_production_correlation']:.3f}")
        
        print(f"\nNEGATIVE PRICE ANALYSIS:")
        print(f"  Hours with negative prices: {analysis['negative_price_hours']}")
        if analysis['negative_price_hours'] > 0:
            print(f"  Production during negative prices: {analysis['production_during_negative_prices']:.2f} kWh")
            print(f"  Average production during negative prices: {analysis['avg_production_during_negative_prices']:.3f} kWh")
            print(f"  Lowest negative price: {analysis['min_negative_price_sek_per_kwh']:.4f} SEK/kWh")
            print(f"  Average negative price: {analysis['avg_negative_price_sek_per_kwh']:.4f} SEK/kWh")
            print(f"  COST of negative price exports: {analysis['negative_export_cost_abs_sek']:.2f} SEK")
        else:
            print(f"  No negative price periods found")
        
        print(f"\nEXPORT VALUE ANALYSIS:")
        print(f"  Total export value: {analysis['total_export_value_sek']:.2f} SEK")
        print(f"  Positive price export value: {analysis['positive_export_value_sek']:.2f} SEK")
        print(f"  Net export value (after negative costs): {analysis['total_export_value_sek']:.2f} SEK")
        
        print("\n" + "="*60)
    
    @staticmethod
    def get_daily_summary(merged_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate daily summary statistics.
        
        Args:
            merged_df (pd.DataFrame): Merged hourly data
            
        Returns:
            pd.DataFrame: Daily summary with aggregated metrics
        """
        daily_summary = merged_df.groupby(merged_df.index.date).agg({
            'production_kwh': ['sum', 'mean', 'max'],
            'price_eur_per_mwh': ['mean', 'min', 'max'],
            'price_sek_per_kwh': ['mean', 'min', 'max'],
            'export_value_sek': 'sum'
        }).round(3)
        
        # Flatten column names
        daily_summary.columns = ['_'.join(col).strip() for col in daily_summary.columns]
        
        return daily_summary
