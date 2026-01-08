import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from utils.csv_format_detector_fallback import CSVFormatDetectorFallback
from utils.ai_table_reader import AITableReader

logger = logging.getLogger(__name__)


class ProductionLoader:
    """Load and standardize solar production data.

    Uses AI-first approach: When OPENAI_API_KEY is available, uses LLM to
    intelligently parse any file format. Falls back to heuristic parsing
    when AI is unavailable.
    """

    def __init__(self):
        self.fallback_reader = CSVFormatDetectorFallback()
        self.ai_reader = AITableReader()
        self.last_parse_format = None
        self.last_ai_spec = None

    def load_production(self, file_path: str, use_llm: bool = True) -> Tuple[pd.DataFrame, str]:
        """Load production data from CSV/Excel file.

        Args:
            file_path: Path to the data file
            use_llm: If True and OPENAI_API_KEY is set, use AI parsing (default: True)

        Returns:
            Tuple of (DataFrame with production_kwh column, granularity string)
        """
        self.last_parse_format = None
        self.last_ai_spec = None

        # AI-FIRST: Try AI parsing when available
        if use_llm and self.ai_reader.is_available():
            try:
                logger.info(f"Using AI parser for: {file_path}")
                df, spec = self.ai_reader.read(file_path)
                self.last_ai_spec = spec

                # AI provides column names directly
                datetime_col = spec.get("datetime_column")
                value_col = spec.get("value_column")

                if datetime_col and value_col:
                    logger.info(f"AI identified columns: datetime={datetime_col}, value={value_col}")
                    return self._process_with_columns(df, datetime_col, value_col)
                else:
                    # AI parsed but didn't identify columns - try auto-detection on the parsed data
                    logger.info("AI parsed file but columns need auto-detection")
                    return self._process_auto(df)

            except Exception as e:
                logger.warning(f"AI parsing failed: {e}, falling back to heuristics")

        # FALLBACK: Heuristic parsing when AI unavailable or failed
        logger.info(f"Using heuristic parser for: {file_path}")
        return self._load_with_heuristics(file_path)

    def _load_with_heuristics(self, file_path: str) -> Tuple[pd.DataFrame, str]:
        """Load file using traditional heuristics (fallback when AI unavailable)."""
        is_excel = str(file_path).lower().endswith((".xlsx", ".xls", ".xlsm"))

        try:
            if is_excel:
                df = pd.read_excel(file_path, engine="openpyxl")
            else:
                df = self.fallback_reader.read(file_path)

            logger.info(f"Heuristic loaded {len(df)} rows, columns: {list(df.columns)[:5]}")
            return self._process_auto(df)

        except Exception as e:
            logger.error(f"Heuristic parsing failed: {e}")
            raise ValueError(
                f"Could not parse file. Set OPENAI_API_KEY to enable AI-assisted parsing. Error: {e}"
            )

    def _process_with_columns(
        self, df: pd.DataFrame, datetime_col: str, value_col: str
    ) -> Tuple[pd.DataFrame, str]:
        """Process DataFrame when column names are known (from AI)."""
        df = df.rename(columns={c: str(c).strip() for c in df.columns})

        # Validate columns exist
        if datetime_col not in df.columns:
            # Try case-insensitive match
            for c in df.columns:
                if c.lower() == datetime_col.lower():
                    datetime_col = c
                    break
            else:
                raise ValueError(f"Datetime column '{datetime_col}' not found. Available: {list(df.columns)}")

        if value_col not in df.columns:
            for c in df.columns:
                if c.lower() == value_col.lower():
                    value_col = c
                    break
            else:
                raise ValueError(f"Value column '{value_col}' not found. Available: {list(df.columns)}")

        # Parse datetime
        ts = self._parse_datetime_series(df[datetime_col])

        # Parse production values
        prod_series = df[value_col]
        if prod_series.dtype == object:
            prod_series = self._normalize_numeric_string(prod_series)
        prod = pd.to_numeric(prod_series, errors="coerce")

        # Build output
        data = pd.DataFrame({"ts": ts, "production_kwh": prod}).dropna(subset=["ts"]).copy()
        data = data[~data["production_kwh"].isna()]
        data = data[data["production_kwh"] >= 0]

        return self._determine_granularity_and_aggregate(data)

    def _process_auto(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
        """Process DataFrame with auto-detected columns (fallback path)."""
        df = df.rename(columns={c: str(c).strip() for c in df.columns})

        date_col = self._infer_date_col(df)
        prod_col = self._infer_prod_col(df)

        if not date_col or not prod_col:
            raise ValueError(f"Could not detect date/production columns. Columns: {list(df.columns)}")

        logger.info(f"Auto-detected columns: datetime={date_col}, value={prod_col}")

        ts = self._parse_datetime_series(df[date_col])

        if pd.Series(ts).notna().sum() == 0:
            raise ValueError("No date/datetime values could be parsed")

        prod_series = df[prod_col]
        if prod_series.dtype == object:
            prod_series = self._normalize_numeric_string(prod_series)
        prod = pd.to_numeric(prod_series, errors="coerce")

        data = pd.DataFrame({"ts": ts, "production_kwh": prod}).dropna(subset=["ts"]).copy()
        data = data[~data["production_kwh"].isna()]
        data = data[data["production_kwh"] >= 0]

        return self._determine_granularity_and_aggregate(data)

    def _determine_granularity_and_aggregate(self, data: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
        """Determine data granularity and aggregate to hourly or daily."""
        if data.empty:
            return pd.DataFrame(columns=["production_kwh"]), "unknown"

        norm_days = data["ts"].dt.normalize()
        rows_per_day = data.groupby(norm_days).size()
        median_rows_per_day = rows_per_day.median() if not rows_per_day.empty else 0

        # Detect granularity: >1 row per day = sub-daily data
        is_sub_daily = median_rows_per_day >= 2

        if is_sub_daily:
            # Aggregate to hourly
            idx = data["ts"].dt.floor('h')
            out = (
                pd.DataFrame({"dt": idx, "production_kwh": data["production_kwh"].values})
                .groupby("dt")
                .agg({"production_kwh": "sum"})
                .sort_index()
            )
            gran = "hourly"
            logger.info(f"Loaded {len(out)} production hours from {out.index.min()} to {out.index.max()}")
        else:
            # Daily data
            idx = data["ts"].dt.normalize()
            out = (
                pd.DataFrame({"date": idx, "production_kwh": data["production_kwh"].values})
                .groupby("date")
                .agg({"production_kwh": "sum"})
                .sort_index()
            )
            gran = "daily"
            logger.info(f"Loaded {len(out)} production days from {out.index.min().date()} to {out.index.max().date()}")

        return out, gran

    def _infer_date_col(self, df: pd.DataFrame) -> Optional[str]:
        """Infer which column contains date/time data."""
        # First: check for datetime dtype
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                return c

        # Second: try parsing each column and find best match
        best_col = None
        best_ratio = 0.0

        for c in df.columns:
            s = df[c].dropna().head(100)
            if s.empty:
                continue

            # Try parsing as datetime
            parsed = pd.to_datetime(s, errors="coerce", dayfirst=True)
            ratio = parsed.notna().mean()

            # Also try Excel serial dates
            if ratio < 0.5 and np.issubdtype(s.dtype, np.number):
                parsed2 = pd.to_datetime(s, unit='D', origin='1899-12-30', errors='coerce')
                ratio = max(ratio, parsed2.notna().mean())

            if ratio > best_ratio:
                best_ratio = ratio
                best_col = c

        if best_ratio >= 0.3:
            return best_col
        return None

    def _infer_prod_col(self, df: pd.DataFrame) -> Optional[str]:
        """Infer which column contains production values."""
        # Find numeric column with best coverage (excluding date-like columns)
        best_col = None
        best_ratio = 0.0

        for c in df.columns:
            col = df[c]

            # Normalize strings if needed
            if col.dtype == object:
                norm = self._normalize_numeric_string(col)
                s = pd.to_numeric(norm, errors="coerce").dropna().head(100)
            else:
                s = pd.to_numeric(col, errors="coerce").dropna().head(100)

            if len(s) == 0:
                continue

            ratio = len(s) / max(1, min(100, len(df[c])))

            # Skip columns that look like dates
            if self._column_looks_like_date(df[c]):
                continue

            if ratio > best_ratio:
                best_ratio = ratio
                best_col = c

        if best_ratio >= 0.3:
            return best_col

        # Fallback: first numeric column
        num_cols = df.select_dtypes(include=["number"]).columns
        if len(num_cols) > 0:
            return num_cols[0]
        return None

    def _column_looks_like_date(self, col: pd.Series) -> bool:
        """Check if column values look like dates."""
        sample = col.dropna().head(20)
        if sample.empty:
            return False

        parsed = pd.to_datetime(sample, errors="coerce", dayfirst=True)
        return parsed.notna().mean() > 0.5

    def _normalize_numeric_string(self, s: pd.Series) -> pd.Series:
        """Normalize numeric text to parseable form."""
        ss = s.astype(str)
        ss = ss.str.replace("\u00A0", "", regex=False)  # NBSP
        ss = ss.str.replace("\u202F", "", regex=False)  # Thin space
        ss = ss.str.replace(" ", "", regex=False)
        ss = ss.str.replace(",", ".", regex=False)  # European decimal
        ss = ss.str.replace(r"[^0-9+\-\.]", "", regex=True)
        return ss

    def _parse_datetime_series(self, date_series: pd.Series) -> pd.Series:
        """Parse a series to datetime."""
        s = date_series

        if pd.api.types.is_datetime64_any_dtype(s):
            ts = pd.to_datetime(s, errors='coerce')
        elif np.issubdtype(getattr(s, 'dtype', object), np.number):
            # Excel serial dates
            ts = pd.to_datetime(s, unit='D', origin='1899-12-30', errors='coerce')
            self.last_parse_format = 'excel_serial'
        else:
            s_str = s.astype(str).str.strip()

            # Try ISO format first
            ts = pd.to_datetime(s_str, format='%Y-%m-%d %H:%M:%S', errors='coerce')

            if ts.notna().mean() < 0.5:
                # Try without seconds
                ts2 = pd.to_datetime(s_str, format='%Y-%m-%d %H:%M', errors='coerce')
                if ts2.notna().mean() > ts.notna().mean():
                    ts = ts2

            if ts.notna().mean() < 0.5:
                # Try date only
                ts2 = pd.to_datetime(s_str, format='%Y-%m-%d', errors='coerce')
                if ts2.notna().mean() > ts.notna().mean():
                    ts = ts2

            if ts.notna().mean() < 0.5:
                # Generic fallback
                ts = pd.to_datetime(s_str, errors='coerce', dayfirst=False)

        # Remove timezone if present
        try:
            if isinstance(ts.dtype, pd.DatetimeTZDtype):
                ts = ts.dt.tz_convert(None)
        except Exception:
            pass

        return ts

    def get_last_ai_spec(self) -> Optional[dict]:
        """Return the AI analysis spec from the last parsing, if available."""
        return self.last_ai_spec
