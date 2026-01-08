import os
import json
import logging
from typing import Optional, Dict, Any, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class AITableReader:
    """AI-first CSV/Excel reader that uses LLM to understand file structure.

    This reader analyzes the raw file content and determines:
    - File structure (single table, multi-section with metadata, etc.)
    - Which row contains the actual data headers
    - Which column contains timestamps/dates
    - Which column contains the production/energy values
    - Separator and decimal format

    The AI approach allows handling arbitrary file formats without hardcoded rules.
    """

    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

    SYSTEM_PROMPT = """You are a data parsing assistant. Your job is to analyze CSV/tabular file previews and identify their structure.

You will receive the first 30-50 lines of a file containing energy production data (solar panels, etc).

Common file patterns you may encounter:
1. Simple CSV: Header row followed by data rows
2. Multi-section files: Metadata section, empty line(s), then data header and data rows
3. Files with extra header rows before the actual column names
4. Various languages (Swedish, English, German, etc.)
5. Different date/time formats and column naming conventions

Your task: Analyze the preview and return a JSON object with these fields:

{
  "file_structure": "simple" | "multi_section" | "complex",
  "data_header_row": <0-indexed row number where the DATA column headers are>,
  "separator": ";" | "," | "\\t" | "|",
  "decimal": "," | ".",
  "datetime_column": "<exact column name for the timestamp/date column>",
  "value_column": "<exact column name for the production/energy/quantity column>",
  "datetime_format": "<optional: detected format like 'YYYY-MM-DD HH:MM:SS'>",
  "notes": "<brief explanation of your analysis>"
}

IMPORTANT RULES:
1. For multi-section files: The data_header_row is where the ACTUAL DATA columns are defined, not metadata headers
2. Look for patterns: empty lines often separate metadata from data sections
3. The datetime column often contains words like: date, time, datum, tid, timestamp, start, end, period
4. The value column often contains words like: production, energy, kwh, mwh, quantity, value, amount, export, produktion, kvantitet, mängd
5. Return EXACT column names as they appear in the file (case-sensitive)
6. If the file uses European format (semicolon separator), decimal is likely comma
7. Always return valid JSON - no markdown, no explanation outside the JSON"""

    def __init__(self, max_preview_lines: int = 50):
        self.max_preview_lines = max_preview_lines
        self.client = None
        self.model = os.getenv("OPENAI_PARSER_MODEL", self.DEFAULT_MODEL)
        self.base_url = os.getenv("OPENAI_BASE_URL", self.DEFAULT_BASE_URL)
        api_key = os.getenv("OPENAI_API_KEY")

        if api_key and OpenAI is not None:
            try:
                self.client = OpenAI(api_key=api_key, base_url=self.base_url)
                logger.info(f"AI table reader initialized with model: {self.model}")
            except Exception as e:
                logger.warning(f"Failed to init OpenAI client: {e}")

    def is_available(self) -> bool:
        """Check if AI parsing is available."""
        return self.client is not None

    def analyze_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Analyze file structure using AI.

        Returns dict with parsing instructions, or None if AI unavailable/failed.
        """
        if not self.client:
            logger.debug("AI client not available")
            return None

        preview = self._read_preview(file_path)
        if not preview:
            logger.warning(f"Could not read preview from {file_path}")
            return None

        user_prompt = f"""Analyze this file and return JSON with parsing instructions.

FILE PREVIEW (first {self.max_preview_lines} lines):
---
{preview}
---

Return only valid JSON, no other text."""

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,  # Deterministic output
                max_tokens=500,
            )

            content = resp.choices[0].message.content if resp.choices else None
            if not content:
                logger.error("AI response empty")
                return None

            # Parse JSON from response
            spec = json.loads(self._extract_json(content))
            logger.info(f"AI analysis result: {spec}")
            return spec

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.debug(f"Raw response: {content}")
            return None
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return None

    def read(self, file_path: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Read file using AI-detected structure.

        Returns:
            Tuple of (DataFrame, spec_dict) where spec_dict contains the AI analysis
        """
        spec = self.analyze_file(file_path)
        if not spec:
            raise RuntimeError("AI analysis failed or unavailable")

        # Extract parsing parameters
        header_row = int(spec.get("data_header_row", 0))
        separator = spec.get("separator", ";")
        decimal = spec.get("decimal", ",")

        # Handle escape sequences
        if separator == "\\t":
            separator = "\t"

        # Determine file type and read
        is_excel = file_path.lower().endswith(('.xlsx', '.xls', '.xlsm'))

        try:
            if is_excel:
                df = pd.read_excel(
                    file_path,
                    engine='openpyxl',
                    header=header_row
                )
            else:
                # Build skiprows list for rows before header
                skiprows = list(range(header_row)) if header_row > 0 else None

                df = pd.read_csv(
                    file_path,
                    sep=separator,
                    decimal=decimal,
                    encoding='utf-8-sig',
                    skiprows=skiprows,
                    skip_blank_lines=False,  # We handle blank lines via skiprows
                    on_bad_lines='skip',
                    engine='python',
                )

            # Clean up column names
            df.columns = [str(c).strip() for c in df.columns]

            # Drop completely empty rows that might remain
            df = df.dropna(how='all')

            logger.info(f"AI-parsed {len(df)} rows, columns: {list(df.columns)}")
            return df, spec

        except Exception as e:
            logger.error(f"Failed to read file with AI-detected params: {e}")
            raise

    def _read_preview(self, file_path: str) -> str:
        """Read first N lines of file for AI analysis."""
        try:
            # Try multiple encodings
            for enc in ("utf-8-sig", "utf-8", "cp1252", "iso-8859-1", "utf-16"):
                try:
                    with open(file_path, 'r', encoding=enc, errors='ignore') as f:
                        lines = []
                        for i, line in enumerate(f):
                            if i >= self.max_preview_lines:
                                break
                            lines.append(f"[{i}] {line.rstrip()}")
                        return "\n".join(lines)
                except Exception:
                    continue

            # Fallback: read as bytes and decode
            with open(file_path, 'rb') as f:
                data = f.read(64 * 1024)  # 64KB
            return data.decode('utf-8', errors='ignore')

        except Exception as e:
            logger.warning(f"Preview read failed: {e}")
            return ""

    def _extract_json(self, text: str) -> str:
        """Extract JSON object from text (handles markdown code blocks)."""
        # Remove markdown code blocks if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Find JSON object
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]
        return text
