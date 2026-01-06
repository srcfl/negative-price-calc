import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from utils.csv_format_detector_fallback import CSVFormatDetectorFallback
from utils.ai_table_reader import AITableReader

logger = logging.getLogger(__name__)


class ProductionLoader:
    """Load and standardize solar production tables, auto-detect hourly vs daily."""

    def __init__(self):
        self.fallback_reader = CSVFormatDetectorFallback()
        self.ai_reader = AITableReader()

    def load_production(self, file_path: str, use_llm: bool = False) -> Tuple[pd.DataFrame, str]:
        # reset parse format trace
        self.last_parse_format = None
        is_excel = str(file_path).lower().endswith((".xlsx", ".xls", ".xlsm"))
        # 1) Base case: read normally and accept only if the header looks standard
        try:
            if is_excel:
                df_raw = pd.read_excel(file_path, engine="openpyxl")
            else:
                df_raw = self.fallback_reader.read(file_path)
            logger.info("Loaded %d rows, columns: %s", len(df_raw), list(df_raw.columns)[:5])
            if self._looks_like_standard_schema(df_raw):
                logger.info("Standard schema detected, processing...")
                return self._process_auto(df_raw)
            logger.info("Schema not standard (missing required columns)")
        except Exception as e:
            logger.warning("Initial read failed: %s", e)

        # 2) Non-standard schema (or read failed): ask AI to infer header/columns
        if use_llm:
            try:
                logger.info("Schema not standard or read failed; invoking AI-assisted parser for: %s", file_path)
                df_ai = self.ai_reader.read(file_path)
                logger.info("AI parsed %d rows, columns: %s", len(df_ai), list(df_ai.columns)[:5])
                return self._process_auto(df_ai)
            except Exception as e:
                logger.warning("AI parsing failed: %s", e)
        else:
            logger.info("LLM parsing disabled, skipping AI-assisted parser")

        # 3) Last-chance Excel fallbacks (no AI or AI failed)
        if is_excel:
            try:
                df0 = pd.read_excel(file_path, engine="openpyxl", header=None)
                df_promoted = self._promote_header_if_present(df0)
                return self._process_auto(df_promoted)
            except Exception:
                pass
            try:
                df_grid = pd.read_excel(file_path, engine="openpyxl", header=None)
                df_table = self._extract_table_from_grid(df_grid)
                return self._process_auto(df_table)
            except Exception:
                pass

        # 4) Give up with a clear error message
        raise ValueError("Unrecognized production file format. Expected headers with Date/Datum and a kWh production column, or enable AI parsing via OPENAI_API_KEY.")

    def _process_auto(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
        df = df.rename(columns={c: str(c).strip() for c in df.columns})
        date_candidates = ["Datum", "Date", "date", "DATUM"]
        time_candidates = ["Tid", "Time", "time", "Timme", "Hour", "hour"]
        prod_candidates = [
            "Produktion kWh", "production_kwh", "Production kWh", "Produktion", "Production", "kWh", "Value"
        ]
        date_col = self._first_present(df, date_candidates) or self._infer_date_col(df)
        time_col = self._first_present(df, time_candidates)
        prod_col = self._first_present(df, prod_candidates) or self._infer_prod_col(df)
        if not date_col or not prod_col:
            raise ValueError(f"Could not detect date/production columns. Columns: {list(df.columns)}")
        ts = self._parse_datetime_series(df[date_col], time_series=df[time_col] if time_col else None)
        # If nothing parsed to a datetime, fail clearly
        if pd.Series(ts).notna().sum() == 0:
            raise ValueError("No date/datetime values could be parsed; ensure the file contains a Date/Datum column.")
        prod_series = df[prod_col]
        if prod_series.dtype == object:
            prod_series = self._normalize_numeric_string(prod_series)
        prod = pd.to_numeric(prod_series, errors="coerce")
        data = pd.DataFrame({"ts": ts, "production_kwh": prod}).dropna(subset=["ts"]).copy()
        data = data[~data["production_kwh"].isna()]
        data = data[data["production_kwh"] >= 0]
        norm_days = data["ts"].dt.normalize()
        rows_per_day = data.groupby(norm_days).size() if not data.empty else pd.Series(dtype=int)
        avg_rows_per_day = rows_per_day.mean() if not rows_per_day.empty else 0
        median_rows_per_day = rows_per_day.median() if not rows_per_day.empty else 0
        p75_rows_per_day = rows_per_day.quantile(0.75) if not rows_per_day.empty else 0
        multi_row_days_ratio = (rows_per_day >= 2).mean() if not rows_per_day.empty else 0
        is_hourly = (
            (median_rows_per_day >= 2) or
            (avg_rows_per_day >= 2.0) or
            (p75_rows_per_day >= 2) or
            (multi_row_days_ratio >= 0.25)
        )
        if is_hourly:
            idx = data["ts"].dt.floor('h')
            out = pd.DataFrame({"dt": idx, "production_kwh": data["production_kwh"].values}).groupby("dt").agg({"production_kwh": "sum"}).sort_index()
            gran = "hourly"
            logger.info("Loaded %d production hours from %s to %s", len(out), out.index.min() if len(out) else None, out.index.max() if len(out) else None)
            return out, gran
        else:
            idx = data["ts"].dt.normalize()
            out = pd.DataFrame({"date": idx, "production_kwh": data["production_kwh"].values}).groupby("date").agg({"production_kwh": "sum"}).sort_index()
            gran = "daily"
            logger.info("Loaded %d production days from %s to %s", len(out), out.index.min().date() if len(out) else None, out.index.max().date() if len(out) else None)
            return out, gran

    def _first_present(self, df: pd.DataFrame, candidates: list) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _looks_like_standard_schema(self, df: pd.DataFrame) -> bool:
        cols = [str(c).strip().lower() for c in df.columns]
        has_date = any(("datum" in c) or ("date" in c) for c in cols)
        has_prod_kwh = any((any(w in c for w in ["produktion", "production", "export"])) and ("kwh" in c) for c in cols)
        return has_date and has_prod_kwh

    def _infer_date_col(self, df: pd.DataFrame) -> Optional[str]:
        for c in df.columns:
            cl = str(c).lower()
            if any(k in cl for k in ["datum", "date", "tid", "time"]):
                return c
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                return c
        best_col = None
        best_ratio = 0.0
        sample_n = 200
        for c in df.columns:
            s = df[c].dropna().head(sample_n)
            if s.empty:
                continue
            parsed = pd.to_datetime(s, errors="coerce", dayfirst=True)
            ratio = parsed.notna().mean()
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
        # Name hints (broad, language-agnostic)
        for c in df.columns:
            cl = str(c).lower()
            if any(k in cl for k in ["produktion", "production", "prod", "kwh", "mwh", "energi", "energy", "power", "utmatning", "export"]):
                return c
        # Data-based: try to detect a column that looks numeric after light normalization
        best_col = None
        best_ratio = 0.0
        sample_n = 200
        for c in df.columns:
            col = df[c]
            if col.dtype == object:
                norm = self._normalize_numeric_string(col)
                s = pd.to_numeric(norm, errors="coerce").dropna().head(sample_n)
            else:
                s = pd.to_numeric(col, errors="coerce").dropna().head(sample_n)
            ratio = len(s) / max(1, min(sample_n, len(df[c])))
            if ratio > best_ratio:
                best_ratio = ratio
                best_col = c
        if best_ratio >= 0.3:
            return best_col
        # Fallback to first numeric dtype
        num_cols = df.select_dtypes(include=["number"]).columns
        if len(num_cols) > 0:
            return num_cols[0]
        return None

    def _normalize_numeric_string(self, s: pd.Series) -> pd.Series:
        """Normalize numeric text to parseable form.
        - Convert NBSP and thin spaces to regular nothing
        - Remove regular spaces
        - Convert decimal comma to dot
        - Strip any unit text (e.g., 'kWh') and other non-numeric chars, keeping digits, sign, and dot
        """
        ss = s.astype(str)
        ss = ss.str.replace("\u00A0", "", regex=False)  # NBSP
        ss = ss.str.replace("\u202F", "", regex=False)  # thin space
        ss = ss.str.replace(" ", "", regex=False)
        ss = ss.str.replace(",", ".", regex=False)
        ss = ss.str.replace(r"[^0-9+\-\.]", "", regex=True)
        return ss

    def _promote_header_if_present(self, df: pd.DataFrame) -> pd.DataFrame:
        max_scan = min(30, len(df))
        for i in range(max_scan):
            header_vals = [str(v).strip() if pd.notna(v) else "" for v in list(df.iloc[i].values)]
            non_empty = [v for v in header_vals if v]
            if len(non_empty) < 2:
                continue
            data = df.iloc[i + 1 :].copy()
            data.columns = header_vals[: data.shape[1]]
            date_col = self._infer_date_col(data)
            prod_col = self._infer_prod_col(data)
            if date_col and prod_col:
                return data
        return df

    def _extract_table_from_grid(self, df: pd.DataFrame) -> pd.DataFrame:
        """Given a header=None Excel grid, infer the likely date and production columns and return a 2-col frame."""
        # Search for a column with many parseable dates
        best_ci = None
        best_ratio = 0.0
        for ci in range(df.shape[1]):
            col = df.iloc[:, ci]
            parsed = pd.to_datetime(col, errors='coerce', dayfirst=True)
            ratio = parsed.notna().mean()
            if ratio < 0.5 and np.issubdtype(col.dtype, np.number):
                parsed2 = pd.to_datetime(col, unit='D', origin='1899-12-30', errors='coerce')
                ratio = max(ratio, parsed2.notna().mean())
            if ratio > best_ratio:
                best_ratio = ratio
                best_ci = ci
        if best_ci is None or best_ratio < 0.3:
            raise ValueError("Could not infer date column from grid")
        dates = pd.to_datetime(df.iloc[:, best_ci], errors='coerce', dayfirst=True)
        # Pick a production column: prefer numeric with good coverage
        prod_ci = None
        prod_best = 0.0
        for ci in range(df.shape[1]):
            if ci == best_ci:
                continue
            s = pd.to_numeric(df.iloc[:, ci], errors='coerce')
            coverage = s.notna().mean()
            if coverage > prod_best:
                prod_best = coverage
                prod_ci = ci
        if prod_ci is None or prod_best < 0.3:
            raise ValueError("Could not infer production column from grid")
        prod = pd.to_numeric(df.iloc[:, prod_ci], errors='coerce')
        out = pd.DataFrame({"Date": dates, "Production kWh": prod}).dropna(subset=["Date"]).rename(columns={"Date": "date", "Production kWh": "production_kwh"})
        return out

    def _parse_datetime_series(self, date_series: pd.Series, time_series: Optional[pd.Series] = None) -> pd.Series:
        # 1) Parse date component
        s = date_series
        if pd.api.types.is_datetime64_any_dtype(s):
            ts_date = pd.to_datetime(s, errors='coerce')
        else:
            if np.issubdtype(getattr(s, 'dtype', object), np.number):
                ts_date = pd.to_datetime(s, unit='D', origin='1899-12-30', errors='coerce')
                self.last_parse_format = self.last_parse_format or 'excel_serial'
            else:
                s_str = s.astype(str).str.strip()
                ts_date = pd.to_datetime(s_str, format='%Y-%m-%d', errors='coerce', utc=False)
                if ts_date.notna().mean() < 0.8:
                    ts_dt_try = pd.to_datetime(s_str, format='%Y-%m-%d %H:%M', errors='coerce', utc=False)
                    if ts_dt_try.notna().mean() >= 0.5:
                        ts_date = ts_dt_try
                        self.last_parse_format = 'YYYY-MM-DD HH:MM'
                    else:
                        ts_date = pd.to_datetime(s_str, errors='coerce', dayfirst=False)
                        self.last_parse_format = self.last_parse_format or 'auto_no_dayfirst'
                else:
                    self.last_parse_format = self.last_parse_format or 'YYYY-MM-DD'
        try:
            if isinstance(ts_date.dtype, pd.DatetimeTZDtype):
                ts_date = ts_date.dt.tz_convert(None)
        except Exception:
            pass
        if not pd.api.types.is_datetime64_any_dtype(ts_date):
            ts_date = pd.to_datetime(ts_date.astype(str), errors='coerce', dayfirst=False)
        # 2) No time column
        if time_series is None or ts_date.isna().all():
            return ts_date
        # 3) Derive hour
        t = time_series
        hours_series = None
        if np.issubdtype(getattr(t, 'dtype', object), np.number):
            tnum = pd.to_numeric(t, errors='coerce')
            hours = np.where((tnum >= 0) & (tnum <= 1), (tnum * 24), (tnum % 24))
            hours_series = pd.Series(np.clip(np.round(hours), 0, 23), index=tnum.index).astype('Int64')
        else:
            t_str = t.astype(str).str.strip()
            t_dt = pd.to_datetime('2000-01-01 ' + t_str, errors='coerce', utc=True)
            try:
                hours_series = t_dt.dt.hour.astype('Int64')
            except Exception:
                hh = t_str.str.extract(r'(\d{1,2})')[0]
                hours_series = pd.to_numeric(hh, errors='coerce').round().clip(0, 23).astype('Int64')
        if not pd.api.types.is_datetime64_any_dtype(ts_date):
            ts_date = pd.to_datetime(ts_date.astype(str), errors='coerce', dayfirst=False)
        base_dates = ts_date.dt.floor('D')
        hours_td = pd.to_timedelta(hours_series.fillna(0).astype('Int64'), unit='h')
        ts = base_dates + hours_td
        ts = ts.where(ts.notna(), ts_date)
        return ts

    def get_last_parse_format(self) -> Optional[str]:
        return getattr(self, 'last_parse_format', None)
