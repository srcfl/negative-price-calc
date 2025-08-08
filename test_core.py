#!/usr/bin/env python3
"""
Test script to verify core functionality works.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all core modules can be imported."""
    print("Testing imports...")
    
    try:
        from core.db_manager import PriceDatabaseManager
        print("✓ Database manager imported")
    except ImportError as e:
        print(f"✗ Database manager import failed: {e}")
        return False
    
    try:
        from core.price_fetcher import PriceFetcher
        print("✓ Price fetcher imported")
    except ImportError as e:
        print(f"✗ Price fetcher import failed: {e}")
        return False
    
    try:
        from core.production_loader import ProductionLoader
        print("✓ Production loader imported")
    except ImportError as e:
        print(f"✗ Production loader import failed: {e}")
        return False
    
    try:
        from core.price_analyzer import PriceAnalyzer
        print("✓ Price analyzer imported")
    except ImportError as e:
        print(f"✗ Price analyzer import failed: {e}")
        return False
    
    try:
        from utils.csv_format_detector_fallback import CSVFormatDetectorFallback
        print("✓ CSV format detector imported")
    except ImportError as e:
        print(f"✗ CSV format detector import failed: {e}")
        return False
    
    return True

def test_database():
    """Test database functionality."""
    print("\nTesting database...")
    
    try:
        from core.db_manager import PriceDatabaseManager
        
        # Test database creation
        db_path = "test_price_data.db"
        db_manager = PriceDatabaseManager(db_path)
        print("✓ Database created successfully")
        
        # Clean up
        if os.path.exists(db_path):
            os.remove(db_path)
        
        return True
    except Exception as e:
        print(f"✗ Database test failed: {e}")
        return False

def test_price_analyzer():
    """Test price analyzer with sample data."""
    print("\nTesting price analyzer...")
    
    try:
        import pandas as pd
        from core.price_analyzer import PriceAnalyzer
        
        # Create sample data
        dates = pd.date_range('2024-01-01', periods=24, freq='H')
        prices_df = pd.DataFrame({
            'price_eur_per_mwh': [50, -10, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120,
                                  130, 120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20]
        }, index=dates)
        
        production_df = pd.DataFrame({
            'production_kwh': [0, 0, 0, 0, 0, 0.5, 1, 2, 3, 4, 5, 6,
                               7, 6, 5, 4, 3, 2, 1, 0.5, 0, 0, 0, 0]
        }, index=dates)
        
        analyzer = PriceAnalyzer()
        merged_df = analyzer.merge_data(prices_df, production_df)
        analysis = analyzer.analyze_data(merged_df)
        
        print("✓ Price analysis completed successfully")
        print(f"  - Total hours: {analysis['total_hours']}")
        print(f"  - Negative price hours: {analysis['negative_price_hours']}")
        print(f"  - Total production: {analysis['production_total']:.2f} kWh")
        
        return True
    except Exception as e:
        print(f"✗ Price analyzer test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("=== Negative Price Calculator - Core Test ===\n")
    
    tests = [
        test_imports,
        test_database,
        test_price_analyzer
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
    
    print(f"\n=== Test Results ===")
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("✓ All tests passed! Core functionality is working.")
        return 0
    else:
        print("✗ Some tests failed. Check the output above.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
