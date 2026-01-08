import pandas as pd
import csv
import chardet
import logging

logger = logging.getLogger(__name__)


class CSVFormatDetectorFallback:
    """Simple CSV format detector - used as fallback when AI parsing is unavailable."""

    def __init__(self):
        self.common_separators = [',', ';', '\t', '|']
        self.common_encodings = ['utf-8', 'iso-8859-1', 'cp1252', 'utf-16']

    def detect_format(self, file_path):
        """Detect CSV format using traditional methods."""
        encoding = self._detect_encoding(file_path)
        separator = self._detect_separator(file_path, encoding)

        test_params = {
            'sep': separator or ';',
            'encoding': (encoding or 'utf-8-sig'),
            'na_values': ['', 'NA', 'N/A', 'null', 'NULL', 'None', '-'],
            'thousands': None,
            'decimal': ',' if separator == ';' else '.',
            'skipinitialspace': True,
            'quotechar': '"',
        }

        try:
            df_test = pd.read_csv(file_path, nrows=5, **test_params)
            logger.info(f"Detected format: {test_params}")
            return test_params
        except Exception as e:
            logger.error(f"Format detection failed: {e}")
            raise

    def read(self, file_path):
        """Read CSV with detected format parameters."""
        params = self.detect_format(file_path)
        return pd.read_csv(file_path, **params)

    def _detect_encoding(self, file_path):
        """Detect file encoding."""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(10000)
                result = chardet.detect(raw_data)
                encoding = result['encoding']

                if encoding and result['confidence'] > 0.7:
                    return encoding
        except Exception as e:
            logger.warning(f"Encoding detection failed: {e}")

        return 'utf-8'

    def _detect_separator(self, file_path, encoding):
        """Detect CSV separator."""
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                lines = [f.readline() for _ in range(5)]
                sample = ''.join(lines)

            sniffer = csv.Sniffer()
            try:
                dialect = sniffer.sniff(sample, delimiters=',;|\t')
                return dialect.delimiter
            except Exception:
                pass

            separator_counts = {}
            for sep in self.common_separators:
                separator_counts[sep] = sample.count(sep)

            best_separator = max(separator_counts, key=separator_counts.get)
            if separator_counts[best_separator] > 0:
                return best_separator

        except Exception as e:
            logger.warning(f"Separator detection failed: {e}")

        return ','
