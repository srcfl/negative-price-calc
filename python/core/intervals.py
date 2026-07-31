"""Helpers for interval-aware (granularity-agnostic) analysis.

Electricity prices and production data can be hourly, 15-minute (the Swedish market
resolution from 2025-10-01), or daily. Code must therefore never assume "one row ==
one hour". These helpers infer the per-row interval length so energy/cost sums and
"hours" metrics stay correct at any resolution.
"""

import re
from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd


def combine_production(parts: List[pd.DataFrame]) -> Tuple[pd.DataFrame, dict]:
    """Combine several production DataFrames into one continuous, de-duplicated series.

    Swedish grid companies often cap 15-minute export downloads at ~3 months at a time, so a
    full year arrives as several files. Rows are concatenated, sorted by timestamp, and
    de-duplicated by index (chunk boundaries may overlap by a row or two; the first is kept).
    Mirrors ``combineProduction`` in the TypeScript ``parseProduction.ts``.

    Args:
        parts: production DataFrames, each indexed by datetime with a ``production_kwh`` column.

    Returns:
        (combined_df, info) where info has ``files_combined``, ``duplicates_removed`` and
        ``granularities_match`` (whether every part had the same inferred step).
    """
    parts = [p for p in parts if p is not None and len(p) > 0]
    if not parts:
        raise ValueError("Inga produktionsdata att kombinera.")
    if len(parts) == 1:
        return parts[0], {"files_combined": 1, "duplicates_removed": 0, "granularities_match": True}

    steps = [round(infer_step_hours(p.index), 6) for p in parts]
    granularities_match = all(s == steps[0] for s in steps)

    combined = pd.concat(parts).sort_index()
    before = len(combined)
    combined = combined[~combined.index.duplicated(keep="first")]
    duplicates_removed = before - len(combined)

    return combined, {
        "files_combined": len(parts),
        "duplicates_removed": duplicates_removed,
        "granularities_match": granularities_match,
    }


def infer_step_hours(index: pd.DatetimeIndex, default: float = 1.0) -> float:
    """Return the dominant spacing of a datetime index, in hours.

    Uses the median of consecutive differences so occasional gaps (DST, missing
    rows) don't skew the result. Falls back to ``default`` for a single row.
    """
    if index is None or len(index) < 2:
        return default
    diffs = pd.Series(index).sort_values().diff().dropna()
    if diffs.empty:
        return default
    step = diffs.median().total_seconds() / 3600
    return step if step > 0 else default


def interval_hours_series(index: pd.DatetimeIndex) -> pd.Series:
    """Per-row interval length in hours.

    Each row's duration is the gap to the next timestamp; the final row reuses the
    median step. This makes ``(series * hours).sum()`` correct for mixed cadences.
    """
    if len(index) == 0:
        return pd.Series([], dtype=float)
    if len(index) == 1:
        return pd.Series([infer_step_hours(index)], index=index)

    ordered = pd.DatetimeIndex(index).sort_values()
    deltas = ordered[1:] - ordered[:-1]
    hours = [d.total_seconds() / 3600 for d in deltas]
    median = pd.Series(hours).median()
    hours.append(median)  # last row: assume one more median-length step
    return pd.Series(hours, index=ordered)


def granularity_from_hours(step_hours: float) -> str:
    """Map a per-row step (in hours) to a granularity label.

    Mirrors the TypeScript engine's ``granularityFromMinutes`` so both stay in
    parity: <=20 min -> "15min", <=90 min -> "hourly", else "daily".
    """
    if step_hours <= 0:
        return "unknown"
    minutes = step_hours * 60
    if minutes <= 20:
        return "15min"
    if minutes <= 90:
        return "hourly"
    return "daily"


def step_consistency_pct(index: pd.DatetimeIndex) -> float:
    """Share (%) of consecutive gaps equal to the dominant step (within 10%)."""
    if index is None or len(index) < 2:
        return 100.0
    ordered = pd.Series(pd.DatetimeIndex(index).sort_values())
    minutes = (ordered.diff().dropna().dt.total_seconds() / 60)
    if minutes.empty:
        return 100.0
    step = minutes.median()
    tol = max(1.0, step * 0.1)
    matching = int((minutes.sub(step).abs() <= tol).sum())
    return round(matching / len(minutes) * 100, 1)


@dataclass
class ResolutionAssessment:
    """Outcome of validating that data is in 15-minute (quarter-hour) resolution."""

    granularity: str
    step_minutes: float
    consistency_pct: float
    is_quarter_hour: bool
    level: str  # "ok" | "warning"
    message: str


def assess_resolution(index: pd.DatetimeIndex) -> ResolutionAssessment:
    """Validate that a datetime index is in 15-minute (quarter-hour) resolution.

    The analysis is interval-aware and still works for hourly/daily input, but the
    Swedish market moved to 15-minute settlement on 2025-10-01 and quarter-hour data
    is required to see negative-price quarters and short export peaks. This mirrors the
    TypeScript ``assessResolution`` so the CLI and the web app warn consistently.
    """
    step_hours = infer_step_hours(index)
    step_minutes = round(step_hours * 60, 2)
    granularity = granularity_from_hours(step_hours)
    consistency = step_consistency_pct(index)
    base = dict(
        granularity=granularity,
        step_minutes=step_minutes,
        consistency_pct=consistency,
    )

    if granularity == "15min":
        if consistency < 90:
            return ResolutionAssessment(
                **base,
                is_quarter_hour=True,
                level="warning",
                message=(
                    f"Data looks like 15-minute resolution, but only {consistency}% of "
                    "intervals are exactly 15 minutes (irregular timestamps). "
                    "Check the file if results look off."
                ),
            )
        return ResolutionAssessment(
            **base,
            is_quarter_hour=True,
            level="ok",
            message="Resolution confirmed: 15-minute (quarter-hour) data.",
        )

    what = {
        "hourly": "hourly (60-minute)",
        "daily": "daily",
    }.get(granularity, f"unknown (~{step_minutes} min between rows)")
    return ResolutionAssessment(
        **base,
        is_quarter_hour=False,
        level="warning",
        message=(
            f"Input is {what} resolution, not 15-minute data. Analysis still runs "
            "(interval-aware), but 15-minute data is recommended to capture negative "
            "quarters and short export peaks."
        ),
    )


# Column naming each row's energy direction, and the values meaning "fed to the grid".
DIRECTION_HINTS = re.compile(r"(?:riktning|direction)", re.I)
# Non-capturing: pandas' str.contains warns when a pattern has match groups.
PRODUCTION_DIRECTION = re.compile(
    r"(?:produktion|production|export|inmatning|inmatad|utmatad|levererad)", re.I
)


def filter_production_direction(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only production rows when the export tags each row's energy direction.

    E.ON's "Mätvärdesexport" carries an "Energiriktning" column; a file holding both
    Produktion and Förbrukning would otherwise sum consumption into production. This is a
    no-op when there is no such column, or when every row already has the same direction.

    Mirrors the Energiriktning filter in frontend/src/lib/parseProduction.ts.
    """
    for c in df.columns:
        if not DIRECTION_HINTS.search(str(c)):
            continue
        is_production = df[c].astype(str).str.contains(PRODUCTION_DIRECTION)
        if is_production.any() and not is_production.all():
            return df[is_production].copy()
        return df
    return df
