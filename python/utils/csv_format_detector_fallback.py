import pandas as pd
import csv
import re
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
        sep = separator or ';'

        test_params = {
            'sep': sep,
            'encoding': (encoding or 'utf-8-sig'),
            'na_values': ['', 'NA', 'N/A', 'null', 'NULL', 'None', '-'],
            'thousands': None,
            'decimal': ',' if sep == ';' else '.',
            'skipinitialspace': True,
            'quotechar': '"',
        }

        header_row = self._detect_header_row(file_path, test_params['encoding'], sep)
        if header_row > 0:
            logger.info(f"Skipping {header_row} metadata line(s) above the data header")
            test_params['skiprows'] = header_row

        try:
            pd.read_csv(file_path, nrows=5, **test_params)
            logger.info(f"Detected format: {test_params}")
            return test_params
        except Exception as e:
            logger.error(f"Format detection failed: {e}")
            raise

    def _detect_header_row(self, file_path, encoding, separator, max_preamble=25, max_probe=40):
        """Find the line that actually heads the data table.

        E.ON's "Mätvärdesexport" prefixes the table with a metadata block (plant id, export
        timestamp, unit) that has its own header/value pair, a blank line, and a different
        column count -- so reading from line 1 mis-parses or raises. Score each candidate by
        how many following lines share its column count and look like data; the real header
        is followed by thousands of them, a metadata header by one. Ties go to the earliest
        line, so ordinary single-header files are unaffected (returns 0).

        Mirrors findHeaderRow() in frontend/src/lib/parseProduction.ts.
        """
        try:
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                lines = [ln for ln in (f.readline() for _ in range(max_preamble + max_probe + 2)) if ln]
        except Exception as e:
            logger.warning(f"Header-row detection failed: {e}")
            return 0

        rows = [ln.rstrip('\r\n').split(separator) for ln in lines if ln.strip() != '']
        if len(rows) < 2:
            return 0

        def looks_like_data(cells):
            has_ts = any(self._is_timestamp(c) for c in cells)
            has_num = any(self._is_number(c) for c in cells)
            return has_ts and has_num

        best_index, best_score = 0, -1
        for h in range(min(len(rows) - 1, max_preamble)):
            width = len(rows[h])
            if width < 2:
                continue
            score = 0
            for r in range(h + 1, len(rows)):
                if score >= max_probe:
                    break
                if len(rows[r]) != width or not looks_like_data(rows[r]):
                    break
                score += 1
            if score > best_score:
                best_index, best_score = h, score
        return best_index

    # Date shapes accepted by the header probe: ISO (optionally with a time) and European
    # D.M.YYYY / D/M/YYYY. A regex keeps the probe fast over many lines and avoids pandas'
    # dayfirst parsing warnings; exact parsing happens later, on the real columns.
    _TIMESTAMP_RE = re.compile(
        r"^\s*(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[./]\d{1,2}[./]\d{4})"
        r"(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?\s*$"
    )

    @classmethod
    def _is_timestamp(cls, cell):
        return bool(cls._TIMESTAMP_RE.match(cell))

    @staticmethod
    def _is_number(cell):
        try:
            float(cell.strip().replace(' ', '').replace(',', '.'))
            return True
        except (ValueError, AttributeError):
            return False

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
