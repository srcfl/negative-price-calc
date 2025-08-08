# Sourceful Energy - Core Functionality Setup Guide

## Project Overview
A Python application for analyzing electricity prices and solar production data, focusing on negative price detection and cost analysis.

## Core Components & Dependencies

### 1. Project Structure
```
price-negative-comparison/
├── core/
│   ├── __init__.py
│   ├── price_fetcher.py      # ENTSO-E API integration
│   ├── production_loader.py  # CSV production data loader
│   ├── price_analyzer.py     # Analysis engine
│   └── db_manager.py         # SQLite database management
├── utils/
│   ├── __init__.py
│   ├── csv_format_detector_fallback.py  # Traditional CSV detection
│   ├── csv_format_module.py            # LLM-powered CSV detection
│   └── ai_explainer.py                 # AI analysis explanation
├── data/
│   ├── price_data.db         # SQLite database (auto-created)
│   └── cache/               # Temporary cache directory
├── requirements.txt
├── .env                     # Environment variables
└── main.py                  # CLI entry point
```

### 2. Dependencies (requirements.txt)
```
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
python-dotenv>=1.0.0
openai>=1.0.0
sqlite3
pathlib
```

### 3. Environment Configuration (.env)
```
# Required for ENTSO-E price data fetching
ENTSOE_API_KEY=your_entso_e_api_key_here

# Required for AI features (OpenAI)
OPENAI_API_KEY=your_openai_api_key_here

# Optional: Database configuration
DATABASE_PATH=data/price_data.db
```

## Core Modules Implementation

### 4. core/db_manager.py
```python
import sqlite3
import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class PriceDatabaseManager:
    def __init__(self, db_path='data/price_data.db'):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._create_tables()
    
    def _create_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS price_data (
                    datetime TEXT,
                    area_code TEXT,
                    price_eur_per_mwh REAL,
                    PRIMARY KEY (datetime, area_code)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_datetime ON price_data(datetime)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_area ON price_data(area_code)')
    
    def store_price_data(self, df, area_code):
        """Store price data in database."""
        df_copy = df.copy()
        df_copy['area_code'] = area_code
        df_copy['datetime'] = df_copy.index.strftime('%Y-%m-%d %H:%M:%S')
        
        with sqlite3.connect(self.db_path) as conn:
            df_copy[['datetime', 'area_code', 'price_eur_per_mwh']].to_sql(
                'price_data', conn, if_exists='replace', index=False, method='multi'
            )
        logger.info(f"Stored {len(df_copy)} price records for {area_code}")
    
    def get_price_data(self, area_code, start_date, end_date):
        """Retrieve price data from database."""
        query = '''
            SELECT datetime, price_eur_per_mwh 
            FROM price_data 
            WHERE area_code = ? AND datetime BETWEEN ? AND ?
            ORDER BY datetime
        '''
        
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                query, conn, 
                params=[area_code, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')],
                parse_dates=['datetime'],
                index_col='datetime'
            )
        
        return df
    
    def has_data_for_period(self, area_code, start_date, end_date):
        """Check if database has data for the specified period."""
        query = '''
            SELECT COUNT(*) FROM price_data 
            WHERE area_code = ? AND datetime BETWEEN ? AND ?
        '''
        
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                query, 
                [area_code, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')]
            ).fetchone()[0]
        
        expected_hours = (end_date - start_date).total_seconds() / 3600
        return count >= expected_hours * 0.8  # Allow 20% missing data
```

### 5. core/price_fetcher.py
```python
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import os
from .db_manager import PriceDatabaseManager
import logging

logger = logging.getLogger(__name__)

class PriceFetcher:
    def __init__(self, db_path='data/price_data.db'):
        self.api_key = os.getenv('ENTSOE_API_KEY')
        self.base_url = 'https://web-api.tp.entsoe.eu/api'
        self.db_manager = PriceDatabaseManager(db_path)
        
        if not self.api_key:
            logger.warning("No ENTSO-E API key found. Using existing database data only.")
    
    def get_price_data(self, area_code, start_date, end_date):
        """Get price data for area and date range, fetching from API if needed."""
        # Try to get data from database first
        if self.db_manager.has_data_for_period(area_code, start_date, end_date):
            logger.info(f"Using cached data for {area_code} from {start_date} to {end_date}")
            return self.db_manager.get_price_data(area_code, start_date, end_date)
        
        # Fetch from API if we have a key
        if self.api_key:
            logger.info(f"Fetching price data from ENTSO-E API for {area_code}")
            df = self._fetch_from_api(area_code, start_date, end_date)
            if df is not None and not df.empty:
                self.db_manager.store_price_data(df, area_code)
                return df
        
        # Fallback to partial database data
        logger.warning(f"Incomplete data available for {area_code} from {start_date} to {end_date}")
        return self.db_manager.get_price_data(area_code, start_date, end_date)
    
    def _fetch_from_api(self, area_code, start_date, end_date):
        """Fetch price data from ENTSO-E API."""
        try:
            # Convert dates to UTC and format for API
            start_str = start_date.strftime('%Y%m%d%H%M')
            end_str = end_date.strftime('%Y%m%d%H%M')
            
            params = {
                'securityToken': self.api_key,
                'documentType': 'A44',  # Price document
                'in_Domain': area_code,
                'out_Domain': area_code,
                'periodStart': start_str,
                'periodEnd': end_str
            }
            
            response = requests.get(self.base_url, params=params, timeout=30)
            
            if response.status_code == 200:
                return self._parse_xml_response(response.text)
            else:
                logger.error(f"API request failed with status {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching price data: {e}")
            return None
    
    def _parse_xml_response(self, xml_text):
        """Parse XML response from ENTSO-E API."""
        try:
            root = ET.fromstring(xml_text)
            
            # Handle namespaces
            namespaces = {'ns': 'urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3'}
            
            time_series = root.findall('.//ns:TimeSeries', namespaces)
            
            prices = []
            timestamps = []
            
            for ts in time_series:
                # Get time period
                period = ts.find('ns:Period', namespaces)
                start_time = period.find('ns:timeInterval/ns:start', namespaces).text
                
                # Parse start time
                start_dt = pd.to_datetime(start_time, utc=True).tz_convert('Europe/Stockholm')
                
                # Get price points
                points = period.findall('ns:Point', namespaces)
                
                for point in points:
                    position = int(point.find('ns:position', namespaces).text)
                    price = float(point.find('ns:price.amount', namespaces).text)
                    
                    # Calculate timestamp (position is 1-based)
                    timestamp = start_dt + timedelta(hours=position - 1)
                    
                    timestamps.append(timestamp)
                    prices.append(price)
            
            if timestamps and prices:
                df = pd.DataFrame({'price_eur_per_mwh': prices}, index=timestamps)
                df.index = df.index.tz_localize(None)  # Remove timezone for consistency
                df = df.sort_index()
                
                # Remove duplicates
                df = df[~df.index.duplicated(keep='last')]
                
                return df
            else:
                logger.warning("No price data found in API response")
                return None
                
        except Exception as e:
            logger.error(f"Error parsing XML response: {e}")
            return None
```

### 6. core/production_loader.py
```python
import pandas as pd
import logging
from utils.csv_format_detector_fallback import CSVFormatDetectorFallback
from utils.csv_format_module import CSVFormatDetector

logger = logging.getLogger(__name__)

class ProductionLoader:
    def __init__(self):
        self.fallback_detector = CSVFormatDetectorFallback()
        self.llm_detector = CSVFormatDetector()
    
    def load_production_data(self, file_path, use_llm=True):
        """Load production data from CSV file with automatic format detection."""
        try:
            # Try LLM detection first if enabled
            if use_llm:
                try:
                    logger.info("Attempting LLM-powered CSV format detection")
                    params = self.llm_detector.detect_format(file_path)
                    df = pd.read_csv(file_path, **params)
                    return self._process_production_dataframe(df)
                except Exception as e:
                    logger.warning(f"LLM detection failed: {e}. Falling back to traditional method.")
            
            # Fallback to traditional detection
            logger.info("Using traditional CSV format detection")
            params = self.fallback_detector.detect_format(file_path)
            df = pd.read_csv(file_path, **params)
            return self._process_production_dataframe(df)
            
        except Exception as e:
            logger.error(f"Failed to load production data: {e}")
            raise
    
    def _process_production_dataframe(self, df):
        """Process and standardize production dataframe."""
        # Find datetime and production columns
        datetime_col = self._find_datetime_column(df)
        production_col = self._find_production_column(df)
        
        if not datetime_col:
            raise ValueError("No datetime column found in CSV")
        if not production_col:
            raise ValueError("No production column found in CSV")
        
        # Create processed dataframe
        processed_df = pd.DataFrame()
        processed_df['datetime'] = pd.to_datetime(df[datetime_col])
        processed_df['production_kwh'] = pd.to_numeric(df[production_col], errors='coerce')
        
        # Set datetime as index
        processed_df.set_index('datetime', inplace=True)
        
        # Remove rows with invalid data
        processed_df = processed_df.dropna()
        
        # Ensure positive production values
        processed_df = processed_df[processed_df['production_kwh'] >= 0]
        
        # Sort by datetime
        processed_df = processed_df.sort_index()
        
        logger.info(f"Loaded {len(processed_df)} production records from {processed_df.index.min()} to {processed_df.index.max()}")
        
        return processed_df
    
    def _find_datetime_column(self, df):
        """Find the datetime column in the dataframe."""
        datetime_keywords = ['datetime', 'date', 'time', 'timestamp', 'datum', 'tid']
        
        for col in df.columns:
            col_lower = str(col).lower()
            if any(keyword in col_lower for keyword in datetime_keywords):
                return col
        
        # Try first column if it looks like a date
        first_col = df.columns[0]
        try:
            pd.to_datetime(df[first_col].iloc[0])
            return first_col
        except:
            pass
        
        return None
    
    def _find_production_column(self, df):
        """Find the production column in the dataframe."""
        production_keywords = ['production', 'produktion', 'kwh', 'energy', 'output', 'generation']
        
        for col in df.columns:
            col_lower = str(col).lower()
            if any(keyword in col_lower for keyword in production_keywords):
                return col
        
        # Try numeric columns
        numeric_cols = df.select_dtypes(include=['number']).columns
        if len(numeric_cols) > 0:
            return numeric_cols[0]
        
        return None
```

### 7. core/price_analyzer.py
```python
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
```

### 8. utils/csv_format_detector_fallback.py
```python
import pandas as pd
import csv
import chardet
import logging

logger = logging.getLogger(__name__)

class CSVFormatDetectorFallback:
    def __init__(self):
        self.common_separators = [',', ';', '\t', '|']
        self.common_encodings = ['utf-8', 'iso-8859-1', 'cp1252', 'utf-16']
    
    def detect_format(self, file_path):
        """Detect CSV format using traditional methods."""
        # Detect encoding
        encoding = self._detect_encoding(file_path)
        
        # Detect separator
        separator = self._detect_separator(file_path, encoding)
        
        # Test the detected parameters
        test_params = {
            'sep': separator,
            'encoding': encoding,
            'na_values': ['', 'NA', 'N/A', 'null', 'NULL', 'None', '-'],
            'thousands': None,
            'decimal': '.',
            'skipinitialspace': True
        }
        
        # Verify by loading a few rows
        try:
            df_test = pd.read_csv(file_path, nrows=5, **test_params)
            logger.info(f"Detected format: {test_params}")
            return test_params
        except Exception as e:
            logger.error(f"Format detection failed: {e}")
            raise
    
    def _detect_encoding(self, file_path):
        """Detect file encoding."""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(10000)  # Read first 10KB
                result = chardet.detect(raw_data)
                encoding = result['encoding']
                
                if encoding and result['confidence'] > 0.7:
                    return encoding
        except Exception as e:
            logger.warning(f"Encoding detection failed: {e}")
        
        # Default to utf-8
        return 'utf-8'
    
    def _detect_separator(self, file_path, encoding):
        """Detect CSV separator."""
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                # Read first few lines
                lines = [f.readline() for _ in range(5)]
                sample = ''.join(lines)
            
            # Use csv.Sniffer
            sniffer = csv.Sniffer()
            try:
                dialect = sniffer.sniff(sample, delimiters=',;|\t')
                return dialect.delimiter
            except:
                pass
            
            # Fallback: count occurrences of common separators
            separator_counts = {}
            for sep in self.common_separators:
                separator_counts[sep] = sample.count(sep)
            
            # Return separator with highest count
            best_separator = max(separator_counts, key=separator_counts.get)
            if separator_counts[best_separator] > 0:
                return best_separator
            
        except Exception as e:
            logger.warning(f"Separator detection failed: {e}")
        
        # Default to comma
        return ','
```

### 9. utils/csv_format_module.py
```python
import openai
import pandas as pd
import os
import logging

logger = logging.getLogger(__name__)

class CSVFormatDetector:
    def __init__(self):
        self.client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    def detect_format(self, file_path):
        """Detect CSV format using LLM analysis."""
        if not os.getenv('OPENAI_API_KEY'):
            raise ValueError("OpenAI API key not found")
        
        # Read first few lines of the file
        sample_lines = self._read_sample(file_path)
        
        # Ask LLM to analyze the format
        prompt = f"""
        Analyze this CSV file sample and determine the best pandas.read_csv() parameters:

        {sample_lines}

        Return only a Python dictionary with these keys:
        - sep: separator character
        - encoding: file encoding (utf-8, iso-8859-1, etc.)
        - decimal: decimal separator
        - thousands: thousands separator (or None)
        - skiprows: number of rows to skip (or 0)
        - header: header row number (or 0)

        Example: {{"sep": ",", "encoding": "utf-8", "decimal": ".", "thousands": None, "skiprows": 0, "header": 0}}
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=200
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Parse the result
            import ast
            params = ast.literal_eval(result_text)
            
            # Add standard parameters
            params.update({
                'na_values': ['', 'NA', 'N/A', 'null', 'NULL', 'None', '-'],
                'skipinitialspace': True
            })
            
            logger.info(f"LLM detected CSV format: {params}")
            return params
            
        except Exception as e:
            logger.error(f"LLM format detection failed: {e}")
            raise
    
    def _read_sample(self, file_path, lines=10):
        """Read first few lines of file for analysis."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = [f.readline().strip() for _ in range(lines)]
            return '\n'.join(lines)
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='iso-8859-1') as f:
                lines = [f.readline().strip() for _ in range(lines)]
            return '\n'.join(lines)
```

### 10. utils/ai_explainer.py
```python
import openai
import os
import json
import logging

logger = logging.getLogger(__name__)

class AIExplainer:
    def __init__(self):
        self.client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    def explain_analysis(self, analysis_data, metadata):
        """Generate AI explanation of the analysis results."""
        if not os.getenv('OPENAI_API_KEY'):
            return "AI explanation requires OpenAI API key."
        
        # Prepare summary data for the prompt
        summary = {
            'period_days': analysis_data.get('period_days', 0),
            'total_production_kwh': analysis_data.get('production_total', 0),
            'negative_price_hours': analysis_data.get('negative_price_hours', 0),
            'negative_cost_sek': analysis_data.get('negative_export_cost_abs_sek', 0),
            'total_export_value_sek': analysis_data.get('total_export_value_sek', 0),
            'area_code': metadata.get('area_code', 'Unknown'),
            'currency': metadata.get('currency', 'SEK')
        }
        
        prompt = f"""
        You are an energy market analyst. Explain this solar production analysis in simple Swedish:

        Analysis Summary:
        - Period: {summary['period_days']} days
        - Total production: {summary['total_production_kwh']:.1f} kWh
        - Hours with negative prices: {summary['negative_price_hours']}
        - Cost from negative prices: {summary['negative_cost_sek']:.2f} {summary['currency']}
        - Total export value: {summary['total_export_value_sek']:.2f} {summary['currency']}
        - Area: {summary['area_code']}

        Provide:
        1. A brief summary of the results
        2. What negative prices mean for solar owners
        3. Practical recommendations

        Keep it under 300 words, in Swedish, and avoid technical jargon.
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500
            )
            
            explanation = response.choices[0].message.content.strip()
            logger.info("Generated AI explanation successfully")
            return explanation
            
        except Exception as e:
            logger.error(f"AI explanation generation failed: {e}")
            return "AI-förklaring kunde inte genereras för tillfället. Analysresultaten visar din solproduktions prestanda och kostnader under negativa prispriser."
```

### 11. main.py (CLI Entry Point)
```python
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
    
    parser = argparse.ArgumentParser(description='Sourceful Energy Analysis Tool')
    parser.add_argument('--production-file', required=True, help='CSV file with production data')
    parser.add_argument('--area', required=True, help='Electricity area code (e.g., SE_4)')
    parser.add_argument('--start-date', help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', help='End date YYYY-MM-DD')
    parser.add_argument('--currency', default='SEK', help='Currency for output (default: SEK)')
    parser.add_argument('--output', help='Output file for results (JSON)')
    parser.add_argument('--ai-explain', action='store_true', help='Generate AI explanation')
    
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
        production_start = pd.Timestamp(production_df.index.min(), tz='Europe/Stockholm')
        production_end = pd.Timestamp(production_df.index.max(), tz='Europe/Stockholm')
        
        start_date = pd.Timestamp(args.start_date, tz='Europe/Stockholm') if args.start_date else production_start
        end_date = pd.Timestamp(args.end_date, tz='Europe/Stockholm') if args.end_date else production_end
        
        # Get price data
        print(f"Fetching price data for {args.area} from {start_date.date()} to {end_date.date()}...")
        prices_df = price_fetcher.get_price_data(args.area, start_date, end_date)
        
        if prices_df.empty:
            print("No price data available for the specified period.")
            sys.exit(1)
        
        # Currency conversion rate (simplified)
        currency_rates = {'SEK': 11.5, 'EUR': 1.0, 'USD': 1.1, 'NOK': 12.0}
        currency_rate = currency_rates.get(args.currency.upper(), 11.5)
        
        # Merge and analyze
        print("Analyzing data...")
        merged_df = analyzer.merge_data(prices_df, production_df, currency_rate)
        analysis = analyzer.analyze_data(merged_df)
        
        # Print summary
        print("\n=== ANALYSIS RESULTS ===")
        print(f"Period: {analysis['period_days']} days ({analysis['total_hours']} hours)")
        print(f"Total production: {analysis['production_total']:.2f} kWh")
        print(f"Hours with negative prices: {analysis['negative_price_hours']}")
        print(f"Production during negative prices: {analysis['production_during_negative_prices']:.2f} kWh")
        print(f"Cost from negative prices: {analysis['negative_export_cost_abs_sek']:.2f} {args.currency}")
        print(f"Total export value: {analysis['total_export_value_sek']:.2f} {args.currency}")
        
        # AI explanation
        if args.ai_explain:
            print("\n=== AI EXPLANATION ===")
            explainer = AIExplainer()
            metadata = {
                'area_code': args.area,
                'currency': args.currency,
                'file_name': Path(args.production_file).name
            }
            explanation = explainer.explain_analysis(analysis, metadata)
            print(explanation)
        
        # Save results
        if args.output:
            import json
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump({
                    'analysis': analysis,
                    'metadata': metadata
                }, f, indent=2, default=str)
            print(f"\nResults saved to {args.output}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
```

## Setup Instructions

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create `.env` file with your API keys:
```bash
ENTSOE_API_KEY=your_entso_e_api_key
OPENAI_API_KEY=your_openai_api_key
```

### 3. Test Core Functionality
```bash
# Test with your production CSV file
python main.py --production-file data/production.csv --area SE_4 --ai-explain

# Test specific date range
python main.py --production-file data/production.csv --area SE_4 --start-date 2024-06-01 --end-date 2024-06-30
```

### 4. Usage Examples
```python
# Direct usage in Python
from core.price_fetcher import PriceFetcher
from core.production_loader import ProductionLoader
from core.price_analyzer import PriceAnalyzer

# Initialize
fetcher = PriceFetcher()
loader = ProductionLoader()
analyzer = PriceAnalyzer()

# Load data
production_df = loader.load_production_data('your_file.csv')
prices_df = fetcher.get_price_data('SE_4', start_date, end_date)

# Analyze
merged_df = analyzer.merge_data(prices_df, production_df)
results = analyzer.analyze_data(merged_df)
```

## Key Features

1. **CSV Format Detection**: Both traditional and AI-powered methods
2. **Price Data Management**: SQLite database with ENTSO-E API integration
3. **Negative Price Analysis**: Detailed cost analysis for negative price periods
4. **Multi-currency Support**: EUR, SEK, USD, NOK, etc.
5. **AI Explanations**: OpenAI-powered analysis summaries
6. **Robust Error Handling**: Graceful fallbacks for missing data or API failures

This core system provides all the functionality for price analysis without any web interface