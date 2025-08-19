import os
import io
import json
import logging
from typing import Optional, Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except Exception:  # openai v1+ import path
    OpenAI = None


class AITableReader:
    """AI-assisted reader that tries classical parsing, then asks an LLM to infer schema.

    Contract:
      - input: file_path (csv/xlsx), first_k_bytes=64KB used for prompt if needed
      - output: pandas DataFrame with best-effort header/rows; may raise if no date column exists
    """

    def __init__(self, max_preview_bytes: int = 64 * 1024):
        self.max_preview_bytes = max_preview_bytes
        self.client = None
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key and OpenAI is not None:
            try:
                self.client = OpenAI()
            except Exception as e:
                logger.warning(f"Failed to init OpenAI client: {e}")

    def read(self, file_path: str) -> pd.DataFrame:
        """Read CSV/XLSX. Try pandas with a few heuristics. If it fails, use AI to infer schema."""
        # Quick path: try known-good CSV/XLSX patterns
        try:
            if file_path.lower().endswith((".xlsx", ".xlsm", ".xls")):
                # Try header=None, then auto promote first non-empty row
                df = pd.read_excel(file_path, engine="openpyxl", header=None)
                df = self._promote_header_if_present(df)
                return df
            else:
                # CSV heuristics: try semicolon then comma
                for sep, decimal in [(";", ","), (",", "."), ("\t", ".")]:
                    try:
                        df = pd.read_csv(
                            file_path,
                            sep=sep,
                            decimal=decimal,
                            encoding="utf-8-sig",
                            engine="python",
                            skip_blank_lines=True,
                            on_bad_lines="skip",
                        )
                        if df.shape[1] >= 1:
                            return df
                    except Exception:
                        continue
        except Exception as e:
            logger.info(f"Heuristic read failed: {e}")

        # AI fallback
        if not self.client:
            raise RuntimeError(
                "AI fallback unavailable: set OPENAI_API_KEY to enable AI-assisted parsing"
            )

        preview = self._read_preview(file_path)
        instruction = (
            "Du är en dataassistent. Filerna innehåller solelproduktion över tid.\n"
            "Identifiera radnumret där tabellhuvudet börjar och returnera en JSON med:\n"
            "{ 'header_row_index': <0-baserad rad>, 'columns': [<kolumnnamn...>], 'date_column': '<namn eller index>', 'production_column': '<namn eller index>' }.\n"
            "Om ingen datumkolumn finns, svara exakt: { 'error': 'no_date_column' }.\n"
            "Förhandsgranskning:\n" + preview
        )

        try:
            resp = self.client.responses.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                input=instruction,
            )
            content = getattr(resp, "output_text", None)
            if not content and hasattr(resp, "choices"):
                # compatibility fallback
                try:
                    content = resp.choices[0].message.content
                except Exception:
                    content = None
            if not content:
                raise RuntimeError("AI response empty")
            spec = json.loads(self._extract_json(content))
        except Exception as e:
            logger.error(f"AI schema inference failed: {e}")
            raise

        if spec.get("error") == "no_date_column":
            raise ValueError("No date column found in file (AI inference)")

        header_row = int(spec.get("header_row_index", 0))
        # Re-read with header at inferred row
        if file_path.lower().endswith((".xlsx", ".xlsm", ".xls")):
            df = pd.read_excel(file_path, engine="openpyxl", header=header_row)
        else:
            # Try both sep assumptions again with header
            df = None
            for sep, decimal in [(";", ","), (",", "."), ("\t", ".")]:
                try:
                    df = pd.read_csv(
                        file_path,
                        sep=sep,
                        decimal=decimal,
                        encoding="utf-8-sig",
                        engine="python",
                        header=header_row,
                        skip_blank_lines=True,
                        on_bad_lines="skip",
                    )
                    break
                except Exception:
                    continue
            if df is None:
                # last resort
                df = pd.read_csv(
                    file_path, header=header_row, engine="python", on_bad_lines="skip"
                )

        # If AI specified names, apply
        cols = spec.get("columns")
        if isinstance(cols, list) and len(cols) == df.shape[1]:
            df.columns = cols

        return df

    def _read_preview(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                data = f.read(self.max_preview_bytes)
            # Try decode variants
            for enc in ("utf-8-sig", "utf-8", "cp1252", "iso-8859-1", "utf-16"):
                try:
                    return data.decode(enc, errors="ignore")
                except Exception:
                    continue
            return data.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"Preview read failed: {e}")
            return ""

    def _promote_header_if_present(self, df: pd.DataFrame) -> pd.DataFrame:
        # Find first row with at least two non-null cells and non-numeric patterns
        for i in range(min(10, len(df))):
            row = df.iloc[i]
            non_null = row.dropna()
            if len(non_null) >= 2 and any(isinstance(v, str) for v in non_null):
                df2 = df.iloc[i + 1 :].copy()
                df2.columns = [str(c).strip() for c in row.values]
                return df2
        return df

    def _extract_json(self, text: str) -> str:
        # extract first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text
