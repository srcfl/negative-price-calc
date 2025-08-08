#!/usr/bin/env python3
"""
Price Database Management Utility

Utility to manage the price database - view contents, clear data, etc.

Usage:
    python db_manager.py --info                           # Show database info
    python db_manager.py --list-areas                     # List all areas
    python db_manager.py --area SE_4 --info               # Show info for specific area
    python db_manager.py --area SE_4 --clear              # Clear data for specific area
    python db_manager.py --export prices_export.csv       # Export all data to CSV
"""

import argparse
import pandas as pd
import sqlite3
from pathlib import Path

class PriceDatabaseManager:
    def __init__(self, db_path='price_data.db'):
        self.db_path = db_path
    
    def show_database_info(self):
        """Show general database information."""
        if not Path(self.db_path).exists():
            print(f"Database {self.db_path} does not exist.")
            return
        
        with sqlite3.connect(self.db_path) as conn:
            # Get total records
            total_records = conn.execute('SELECT COUNT(*) FROM price_data').fetchone()[0]
            
            # Get areas
            areas = conn.execute('SELECT DISTINCT area_code FROM price_data ORDER BY area_code').fetchall()
            
            # Get date range
            date_range = conn.execute('SELECT MIN(datetime), MAX(datetime) FROM price_data').fetchone()
            
            print(f"Database: {self.db_path}")
            print(f"Total records: {total_records:,}")
            print(f"Areas: {len(areas)}")
            if date_range[0]:
                print(f"Date range: {date_range[0]} to {date_range[1]}")
            print()
            
            # Show per-area statistics
            if areas:
                print("Per-area statistics:")
                for (area,) in areas:
                    area_info = conn.execute('''
                        SELECT COUNT(*), MIN(datetime), MAX(datetime)
                        FROM price_data 
                        WHERE area_code = ?
                    ''', (area,)).fetchone()
                    print(f"  {area}: {area_info[0]:,} records from {area_info[1]} to {area_info[2]}")
    
    def list_areas(self):
        """List all areas in the database."""
        if not Path(self.db_path).exists():
            print(f"Database {self.db_path} does not exist.")
            return
        
        with sqlite3.connect(self.db_path) as conn:
            areas = conn.execute('SELECT DISTINCT area_code FROM price_data ORDER BY area_code').fetchall()
            
        if areas:
            print("Areas in database:")
            for (area,) in areas:
                print(f"  {area}")
        else:
            print("No areas found in database.")
    
    def show_area_info(self, area_code, eur_sek_rate=11.5):
        """Show detailed information for a specific area."""
        if not Path(self.db_path).exists():
            print(f"Database {self.db_path} does not exist.")
            return
        
        with sqlite3.connect(self.db_path) as conn:
            # Check if area exists
            count = conn.execute('SELECT COUNT(*) FROM price_data WHERE area_code = ?', (area_code,)).fetchone()[0]
            
            if count == 0:
                print(f"No data found for area {area_code}")
                return
            
            # Get detailed statistics
            stats = conn.execute('''
                SELECT 
                    COUNT(*) as record_count,
                    MIN(datetime) as min_date,
                    MAX(datetime) as max_date,
                    MIN(price_eur_per_mwh) as min_price,
                    MAX(price_eur_per_mwh) as max_price,
                    AVG(price_eur_per_mwh) as avg_price
                FROM price_data 
                WHERE area_code = ?
            ''', (area_code,)).fetchone()
            
            # Convert to SEK/kWh for display
            min_price_sek = (stats[3] * eur_sek_rate) / 1000
            max_price_sek = (stats[4] * eur_sek_rate) / 1000
            avg_price_sek = (stats[5] * eur_sek_rate) / 1000
            
            print(f"Area: {area_code}")
            print(f"Records: {stats[0]:,}")
            print(f"Date range: {stats[1]} to {stats[2]}")
            print(f"Price range: {min_price_sek:.4f} to {max_price_sek:.4f} SEK/kWh ({stats[3]:.2f} to {stats[4]:.2f} EUR/MWh)")
            print(f"Average price: {avg_price_sek:.4f} SEK/kWh ({stats[5]:.2f} EUR/MWh)")
            
            # Show monthly breakdown
            monthly_data = conn.execute('''
                SELECT 
                    strftime('%Y-%m', datetime) as month,
                    COUNT(*) as records,
                    AVG(price_eur_per_mwh) as avg_price
                FROM price_data 
                WHERE area_code = ?
                GROUP BY strftime('%Y-%m', datetime)
                ORDER BY month
            ''', (area_code,)).fetchall()
            
            if monthly_data:
                print(f"\nMonthly breakdown:")
                for month, records, avg_price in monthly_data:
                    avg_price_sek = (avg_price * eur_sek_rate) / 1000
                    print(f"  {month}: {records:,} records, avg price: {avg_price_sek:.4f} SEK/kWh ({avg_price:.2f} EUR/MWh)")
    
    def clear_area_data(self, area_code):
        """Clear all data for a specific area."""
        if not Path(self.db_path).exists():
            print(f"Database {self.db_path} does not exist.")
            return
        
        with sqlite3.connect(self.db_path) as conn:
            # Check current count
            count = conn.execute('SELECT COUNT(*) FROM price_data WHERE area_code = ?', (area_code,)).fetchone()[0]
            
            if count == 0:
                print(f"No data found for area {area_code}")
                return
            
            # Confirm deletion
            response = input(f"This will delete {count:,} records for area {area_code}. Continue? (y/N): ")
            if response.lower() != 'y':
                print("Cancelled.")
                return
            
            # Delete data
            conn.execute('DELETE FROM price_data WHERE area_code = ?', (area_code,))
            print(f"Deleted {count:,} records for area {area_code}")
    
    def export_data(self, output_file, area_code=None):
        """Export data to CSV file."""
        if not Path(self.db_path).exists():
            print(f"Database {self.db_path} does not exist.")
            return
        
        with sqlite3.connect(self.db_path) as conn:
            if area_code:
                query = 'SELECT * FROM price_data WHERE area_code = ? ORDER BY area_code, datetime'
                params = (area_code,)
                print(f"Exporting data for area {area_code}...")
            else:
                query = 'SELECT * FROM price_data ORDER BY area_code, datetime'
                params = ()
                print("Exporting all data...")
            
            df = pd.read_sql_query(query, conn, params=params)
            
        if len(df) == 0:
            print("No data to export.")
            return
        
        df.to_csv(output_file, index=False)
        print(f"Exported {len(df):,} records to {output_file}")

def main():
    parser = argparse.ArgumentParser(description='Manage the price database')
    parser.add_argument('--db-path', default='price_data.db', help='Path to the database file')
    parser.add_argument('--info', action='store_true', help='Show database information')
    parser.add_argument('--list-areas', action='store_true', help='List all areas')
    parser.add_argument('--area', help='Specific area to operate on')
    parser.add_argument('--clear', action='store_true', help='Clear data for specified area')
    parser.add_argument('--export', help='Export data to CSV file')
    parser.add_argument('--eur-sek-rate', type=float, default=11.5, help='EUR to SEK exchange rate for display (default: 11.5)')
    
    args = parser.parse_args()
    
    manager = PriceDatabaseManager(args.db_path)
    
    if args.info:
        if args.area:
            manager.show_area_info(args.area, args.eur_sek_rate)
        else:
            manager.show_database_info()
    elif args.list_areas:
        manager.list_areas()
    elif args.clear and args.area:
        manager.clear_area_data(args.area)
    elif args.export:
        manager.export_data(args.export, args.area)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
