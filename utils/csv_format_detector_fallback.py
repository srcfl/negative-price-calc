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
            'sep': separator or ';',
            'encoding': (encoding or 'utf-8-sig'),
            'na_values': ['', 'NA', 'N/A', 'null', 'NULL', 'None', '-'],
            'thousands': None,
            'decimal': ',' if separator == ';' else '.',
            'skipinitialspace': True,
            'quotechar': '"',
        }
        
        # Verify by loading a few rows
        try:
            df_test = pd.read_csv(file_path, nrows=5, **test_params)
            logger.info(f"Detected format: {test_params}")
            return test_params
        except Exception as e:
            logger.error(f"Format detection failed: {e}")
            raise

    def read(self, file_path):
        """Convenience method to read with detected or Swedish-friendly defaults."""
        params = self.detect_format(file_path)
        return pd.read_csv(file_path, **params)
    
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
