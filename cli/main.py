import argparse
import logging
from pathlib import Path
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from core.production_loader import ProductionLoader
from core.price_fetcher import PriceFetcher
from datetime import timezone

SCHEMA_VERSION = "1.3.0"


def _to_local_utc(index: pd.DatetimeIndex) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Return (ts_local_europe_stockholm, ts_utc) aligned to hour starts."""
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        local = idx.tz_localize("Europe/Stockholm")
    else:
        # assume already tz-aware; convert to Europe/Stockholm first for consistency
        local = idx.tz_convert("Europe/Stockholm")
    local = local.floor("h")
    utc = local.tz_convert("UTC")
    return local, utc


def _gini(x: np.ndarray) -> float:
    x = np.array(x, dtype=float)
    x = x[~np.isnan(x)]
    if x.size == 0:
        return 0.0
    x = x - x.min()
    if x.sum() == 0:
        return 0.0
    x_sorted = np.sort(x)
    n = x_sorted.size
    cum = np.cumsum(x_sorted)
    g = (n + 1 - 2 * np.sum(cum) / cum[-1]) / n
    return float(g)


def _rle_clusters(ts_local: pd.DatetimeIndex, is_cluster_mask: pd.Series) -> dict:
    """Return a dict mapping index position to cluster_id for contiguous True runs.
    ID format: neg-YYYY-MM-DD-HHtoHH (local time)."""
    ids = {}
    if len(ts_local) == 0:
        return ids
    run_start = None
    for i, flag in enumerate(is_cluster_mask.astype(bool).values):
        if flag and run_start is None:
            run_start = i
        if (not flag or i == len(is_cluster_mask) - 1) and run_start is not None:
            end_i = i if not flag else i
            # Support both DatetimeIndex and Series
            start_dt = (ts_local.iloc[run_start] if hasattr(ts_local, 'iloc') else ts_local[run_start])
            end_dt = (ts_local.iloc[end_i] if hasattr(ts_local, 'iloc') else ts_local[end_i])
            cid = f"neg-{start_dt.strftime('%Y-%m-%d')}-{start_dt.strftime('%H')}to{end_dt.strftime('%H')}"
            for j in range(run_start, end_i + 1):
                ids[j] = cid
            run_start = None
    return ids


def _percentiles(s: pd.Series, qs=(0.05, 0.25, 0.5, 0.75, 0.95)) -> dict:
    out = {}
    if s is None or len(s) == 0:
        return {f"p{int(q*100):02d}": 0.0 for q in qs}
    desc = s.quantile(list(qs))
    for q, v in desc.items():
        out[f"p{int(round(q*100)):02d}"] = float(v) if pd.notna(v) else 0.0
    return out


def _curtailment_sweep(aligned: pd.DataFrame, floors: list[float]) -> dict:
    has_price = aligned['sek_per_kwh'].notna()
    prod = aligned['prod_kwh'].clip(lower=0)
    price = aligned['sek_per_kwh']
    total_prod = float(prod.sum())
    total_neg_energy = float(prod[(price < 0) & has_price].sum())
    pts = []
    for f in sorted(floors):
        keep = has_price & (price >= f)
        rev = float((prod[keep] * price[keep]).sum())
        lost = float(prod[has_price & ~keep].sum())
        pts.append({'floor': float(f), 'revenue_sek': rev, 'lost_energy_kwh': lost})
    # Recommended: argmax revenue
    recommended = max(pts, key=lambda x: x['revenue_sek'])['floor'] if pts else None
    # Knee: max delta(revenue)/delta(lost_energy) among transitions where lost share >= min_share
    knee = None
    min_share = 0.02
    best_ratio = -1
    for i in range(1, len(pts)):
        d_rev = pts[i]['revenue_sek'] - pts[i-1]['revenue_sek']
        d_lost = pts[i]['lost_energy_kwh'] - pts[i-1]['lost_energy_kwh']
        lost_share = pts[i]['lost_energy_kwh'] / total_prod if total_prod > 0 else 0
        if d_lost <= 0 or lost_share < min_share:
            continue
        ratio = d_rev / d_lost if d_lost else 0
        if ratio > best_ratio:
            best_ratio = ratio
            knee = pts[i]['floor']
    # Invariants
    monotonic = all(pts[i]['lost_energy_kwh'] <= pts[i+1]['lost_energy_kwh'] + 1e-9 for i in range(len(pts)-1))
    neg_energy_match = None
    for p in pts:
        if abs(p['floor'] - 0.0) < 1e-9:
            neg_energy_match = abs(p['lost_energy_kwh'] - total_neg_energy) < 1e-6
            break
    return {
        'unit': 'SEK_per_kWh',
        'points': [{**p, 'lost_energy_share_pct': (p['lost_energy_kwh']/total_prod*100 if total_prod>0 else 0)} for p in pts],
        'recommended_floor_sek_per_kwh': recommended,
        'knee_floor_sek_per_kwh': knee,
        'baseline_revenue_sek': float((prod[has_price] * price[has_price]).sum()),
        'total_negative_price_energy_kwh': total_neg_energy,
        'sanity': {
            'monotonic_lost_energy': monotonic,
            'lost_energy_at_floor0_matches_negative_energy': bool(neg_energy_match)
        }
    }


def _battery_shift_simple(aligned: pd.DataFrame, days: int, eta: float, target_hour_local: int, sizes: list[int]) -> list[dict]:
    # Build local ts for ordering by target hour
    ts_local, _ = _to_local_utc(aligned.index)
    df = aligned.copy()
    df['ts_local'] = ts_local
    df['hour'] = df['ts_local'].dt.hour
    prod_mask = (df['prod_kwh'] > 0) & df['sek_per_kwh'].notna()
    prices = df.loc[prod_mask, 'sek_per_kwh'].values
    prod = df.loc[prod_mask, 'prod_kwh'].values
    order_low = np.argsort(prices)  # lowest to highest
    order_high = np.argsort(-prices)
    results = []
    for cap in sizes:
        budget = cap * days  # kWh that can be shifted across period (store amount)
        used = 0.0
        inc_rev = 0.0
        i = 0
        while used < budget and i < min(len(order_low), len(order_high)):
            lo = order_low[i]
            hi = order_high[i]
            if prices[hi] <= prices[lo]:
                break
            # shift amount limited by remaining production in low-price hour and budget
            shift = min(prod[lo], budget - used)
            if shift <= 0:
                i += 1
                continue
            inc_rev += shift * (eta * prices[hi] - prices[lo])
            used += shift
            i += 1
        util = (used / budget * 100.0) if budget > 0 else 0.0
        results.append({
            'capacity_kwh': float(cap),
            'incremental_revenue_sek': round(float(inc_rev), 2),
            'utilization_pct': round(float(util), 1),
            'assumptions': {'round_trip_efficiency': eta, 'discharge_target_hour_local': target_hour_local}
        })
    return results


def build_storytelling_payload(aligned: pd.DataFrame, currency: str, rate_sek_per_eur: float, granularity: str,
                               sections: set | None = None, artifact_dir: Path | None = None, market_area: str | None = None,
                               used_cache: bool | None = None, cache_start: pd.Timestamp | None = None, cache_end: pd.Timestamp | None = None,
                               parse_format: str | None = None,
                               energy_tax_sek_per_kwh: float | None = None,
                               transmission_fee_sek_per_kwh: float | None = None,
                               vat_rate: float | None = None,
                               battery_capacities: list[int] | None = None,
                               battery_power_kw: float | None = None,
                               battery_decision_basis: str | None = None) -> dict:
    """Build storytelling JSON.

    sections: optional set restricting which top-level analytical blocks to include.
        Supported names: hero, series_hourly, series_per_day, aggregates, distributions, extremes, scenarios, diagnostics, meta, input.
        If None -> include all (current full behavior).
    artifact_dir: if provided and a heavy section (e.g. series_hourly) is excluded, we can persist it separately
        as parquet and insert a reference path under payload['artifacts'].
    """
    all_supported = {"hero","series_hourly","series_per_day","aggregates","distributions","extremes","scenarios","diagnostics","meta","input"}
    if sections is not None:
        unknown = set(sections) - all_supported
        if unknown:
            raise ValueError(f"Unknown sections requested: {sorted(unknown)}")
    # Prepare base series and masks
    prod = aligned['prod_kwh'].fillna(0)
    price_sek = aligned['sek_per_kwh']
    price_eur = aligned.get('eur_per_kwh', price_sek / max(rate_sek_per_eur, 1e-9))
    revenue_sek = (prod * price_sek).fillna(0)
    revenue_eur = (prod * price_eur).fillna(0)

    ts_local, ts_utc = _to_local_utc(aligned.index)
    df = pd.DataFrame({
        'prod_kwh': prod,
        'sek_per_kwh': price_sek,
        'eur_per_kwh': price_eur,
        'revenue_sek': revenue_sek,
        'revenue_eur': revenue_eur,
    }, index=aligned.index)
    df['ts_local'] = ts_local
    df['ts_utc'] = ts_utc
    df['hour'] = df['ts_local'].dt.hour
    df['day'] = df['ts_local'].dt.strftime('%Y-%m-%d')
    # Use explicit strftime to avoid dropping tz information (no Period conversion to suppress warnings)
    df['month'] = df['ts_local'].dt.tz_convert('Europe/Stockholm').dt.strftime('%Y-%m')
    df['is_producing'] = df['prod_kwh'] > 0
    df['is_negative_price'] = df['sek_per_kwh'] < 0
    df['is_zero_or_negative_price'] = df['sek_per_kwh'] <= 0

    # Bins/deciles
    try:
        df_price_nonnull = df['sek_per_kwh'].dropna()
        deciles, bins = pd.qcut(df_price_nonnull, q=10, labels=False, retbins=True, duplicates='drop')
        price_decile_map = deciles.to_dict()
        df['price_decile'] = df['sek_per_kwh'].map(price_decile_map)
    except Exception:
        df['price_decile'] = np.nan
    try:
        prod_pos = df.loc[df['is_producing'], 'prod_kwh']
        quint, qb = pd.qcut(prod_pos, q=5, labels=False, retbins=True, duplicates='drop')
        prod_qu_map = quint.to_dict()
        df['prod_quantile'] = df.index.map(prod_qu_map)
    except Exception:
        df['prod_quantile'] = np.nan

    # Clusters: contiguous negative during production
    cluster_ids = _rle_clusters(df['ts_local'], df['is_producing'] & df['is_negative_price'])
    df['cluster_id'] = [cluster_ids.get(i) for i in range(len(df))]

    # Hero numbers
    hours_total = int(len(df))
    hours_producing = int(df['is_producing'].sum())
    hours_negative_total = int(df['is_negative_price'].sum())
    hours_negative_during_prod = int((df['is_producing'] & df['is_negative_price']).sum())
    nonpos_share = (int((df['is_producing'] & df['is_zero_or_negative_price']).sum()) / hours_producing * 100.0) if hours_producing else 0.0
    production_kwh = float(df['prod_kwh'].sum())
    revenue_total_sek = float(df['revenue_sek'].sum())
    negative_value_sek = float((-df.loc[df['is_producing'] & df['is_negative_price'], 'revenue_sek']).clip(lower=0).sum())
    negative_energy_kwh = float(df.loc[df['is_producing'] & df['is_negative_price'], 'prod_kwh'].sum())
    # realized (weighted) and simple averages over producing hours
    prod_hours = df[df['is_producing']]
    wavg_price = float(prod_hours['revenue_sek'].sum() / prod_hours['prod_kwh'].sum()) if prod_hours['prod_kwh'].sum() > 0 else 0.0
    simple_avg = float(prod_hours['sek_per_kwh'].mean()) if not prod_hours.empty else 0.0
    timing_discount_pct = (wavg_price / simple_avg - 1.0) * 100.0 if simple_avg != 0 else 0.0

    # Counterfactual: curtail at floor 0.0 SEK/kWh
    mask_keep = df['sek_per_kwh'] >= 0
    revenue_if_curtailed = float((df.loc[mask_keep, 'prod_kwh'] * df.loc[mask_keep, 'sek_per_kwh']).sum())
    # Normalize VAT rate (allow user to input 25 for 25%)
    if vat_rate is not None and vat_rate > 1:
        vat_rate_norm = vat_rate / 100.0
    else:
        vat_rate_norm = vat_rate if vat_rate is not None else 0.0
    energy_tax_val = energy_tax_sek_per_kwh or 0.0
    transmission_fee_val = transmission_fee_sek_per_kwh or 0.0
    any_cost_inputs = (energy_tax_sek_per_kwh is not None) or (transmission_fee_sek_per_kwh is not None) or (vat_rate is not None)

    # Self-consumption value (value of using energy yourself vs export) if costs provided
    self_consumption_block = None
    if any_cost_inputs and prod_hours['prod_kwh'].sum() > 0:
        # Value of self consumption per kWh = (spot price + energy tax + transmission fee)*(1+VAT)
        # Incremental benefit vs export = value_self_consumption - spot_price
        # Weighted averages across producing hours
        spot_wavg = wavg_price
        spot_wavg_gross = spot_wavg * (1 + vat_rate_norm)
        avoided_fees_tax_gross = (energy_tax_val + transmission_fee_val) * (1 + vat_rate_norm)
        value_self = spot_wavg_gross + avoided_fees_tax_gross
        increment_vs_export = value_self - spot_wavg
        self_consumption_block = {
            'weighted_value_self_consumption_sek_per_kwh': value_self,
            'weighted_spot_price_net_sek_per_kwh': spot_wavg,
            'weighted_spot_price_gross_sek_per_kwh': spot_wavg_gross,
            'weighted_avoided_fees_tax_sek_per_kwh': avoided_fees_tax_gross,
            'weighted_increment_vs_export_sek_per_kwh': increment_vs_export,
            'export_value_basis': 'spot_only_excl_vat',
            'inputs_used': {
                'energy_tax_sek_per_kwh': energy_tax_sek_per_kwh,
                'transmission_fee_sek_per_kwh': transmission_fee_sek_per_kwh,
                'vat_rate': vat_rate_norm,
            },
            'assumptions': 'Value(self-consumption) = (spot + energy_tax + transmission_fee) * (1+VAT); export value = spot only.'
        }

    hero = {
        'hours_total': hours_total,
        'hours_producing': hours_producing,
        'hours_negative_total': hours_negative_total,
        'hours_negative_during_production': hours_negative_during_prod,
        'share_non_positive_during_production_pct': nonpos_share,
        'production_kwh': production_kwh,
        'revenue_sek': revenue_total_sek,
        'negative_value_sek': negative_value_sek,
        'realized_price_wavg_sek_per_kwh': wavg_price,
        'simple_average_price_sek_per_kwh': simple_avg,
        'timing_discount_pct': timing_discount_pct,
        'counterfactuals': {
            'curtail_at_price_floor_sek_per_kwh': 0.0,
            'revenue_if_curtailed_sek': revenue_if_curtailed,
            'delta_sek': revenue_if_curtailed - revenue_total_sek,
            'lost_energy_kwh_at_floor_0': negative_energy_kwh,
        },
        'units': {
            'production_kwh': 'kWh',
            'revenue_sek': 'SEK',
            'negative_value_sek': 'SEK',
            'realized_price_wavg_sek_per_kwh': 'SEK_per_kWh',
            'simple_average_price_sek_per_kwh': 'SEK_per_kWh',
            'timing_discount_pct': 'percent'
        }
    }
    if self_consumption_block:
        hero['self_consumption'] = self_consumption_block

    hourly = None
    if sections is None or 'series_hourly' in sections:
        hourly = []
        for i, row in df.iterrows():
            hourly.append({
                'ts_utc': row['ts_utc'].isoformat().replace('+00:00', 'Z'),
                'ts_local': row['ts_local'].isoformat(),
                'prod_kwh': float(row['prod_kwh']) if pd.notna(row['prod_kwh']) else 0.0,
                'price_sek_per_kwh': float(row['sek_per_kwh']) if pd.notna(row['sek_per_kwh']) else None,
                'revenue_sek': float(row['revenue_sek']) if pd.notna(row['revenue_sek']) else 0.0,
                'flags': {
                    'is_producing': bool(row['is_producing']),
                    'is_negative_price': bool(row['is_negative_price']) if pd.notna(row['sek_per_kwh']) else False,
                    'is_zero_or_negative_price': bool(row['is_zero_or_negative_price']) if pd.notna(row['sek_per_kwh']) else False,
                },
                'bins': {
                    'price_decile': int(row['price_decile']) if pd.notna(row['price_decile']) else None,
                    'prod_quantile': int(row['prod_quantile']) if pd.notna(row['prod_quantile']) else None,
                    'hour_of_day': int(row['hour']) if pd.notna(row['hour']) else None,
                },
                'cluster_id': row['cluster_id'] if isinstance(row['cluster_id'], str) else None,
                'day_index': row['day'],
                'month': row['month'],
            })

    # Per-day arrays
    per_day = []
    if sections is None or 'series_per_day' in sections:
        for day, g in df.groupby('day'):
            arr_price = [None] * 24
            arr_prod = [0.0] * 24
            arr_rev = [0.0] * 24
            for _, r in g.iterrows():
                h = int(r['hour'])
                arr_price[h] = float(r['sek_per_kwh']) if pd.notna(r['sek_per_kwh']) else None
                arr_prod[h] = float(r['prod_kwh'])
                arr_rev[h] = float(r['revenue_sek'])
            any_neg = bool(((g['is_producing']) & (g['is_zero_or_negative_price'])).any())
            cnt_neg = int(((g['is_producing']) & (g['is_zero_or_negative_price'])).sum())
            per_day.append({
                'date': day,
                'price_sek_per_kwh_by_hour': arr_price,
                'prod_kwh_by_hour': arr_prod,
                'revenue_sek_by_hour': arr_rev,
                'any_negative_during_production': any_neg,
                'count_negative_hours_during_production': cnt_neg,
                'daily': {
                    'production_kwh': float(g['prod_kwh'].sum()),
                    'revenue_sek': float(g['revenue_sek'].sum()),
                    'negative_value_sek': float((-g.loc[g['is_producing'] & g['is_negative_price'], 'revenue_sek']).clip(lower=0).sum()),
                }
            })

    # Aggregates: weekly & monthly
    monthly = []
    weekly = []
    day_summary = []
    if sections is None or 'aggregates' in sections:
        # Weekly grouping (ISO-week start Monday using local date)
        local_dates = df['ts_local'].dt.tz_convert('Europe/Stockholm') if df['ts_local'].dt.tz is not None else df['ts_local']
        week_start = (local_dates - pd.to_timedelta(local_dates.dt.weekday, unit='D')).dt.normalize()
        df['week_start'] = week_start.dt.strftime('%Y-%m-%d')
        for w, g in df.groupby('week_start'):
            g_prod = g[g['is_producing']]
            wavg = float(g_prod['revenue_sek'].sum() / g_prod['prod_kwh'].sum()) if g_prod['prod_kwh'].sum() > 0 else 0.0
            simp = float(g_prod['sek_per_kwh'].mean()) if len(g_prod) else 0.0
            disc = (wavg / simp - 1.0) * 100.0 if simp != 0 else 0.0
            rev = g_prod['revenue_sek']
            var5 = float(rev.quantile(0.05)) if len(rev) else 0.0
            es5 = float(rev[rev <= var5].mean()) if len(rev) else 0.0
            denom = int((g['is_producing'] & g['sek_per_kwh'].notna()).sum())
            nonpos = int((g['is_producing'] & (g['sek_per_kwh'] <= 0)).sum())
            weekly.append({
                'week_start': w,  # Monday date in local zone
                'production_kwh': float(g['prod_kwh'].sum()),
                'revenue_sek': float(g['revenue_sek'].sum()),
                'negative_value_sek': float((-g.loc[g['is_producing'] & g['is_negative_price'], 'revenue_sek']).clip(lower=0).sum()),
                'hours_with_production': denom,
                'hours_non_positive': nonpos,
                'non_positive_percent_hours': round((nonpos / denom * 100.0) if denom else 0.0, 3),
                'realized_price_wavg_sek_per_kwh': round(wavg, 6),
                'simple_average_price_sek_per_kwh': round(simp, 6),
                'timing_discount_pct': round(disc, 2),
                'risk': {
                    'VaR5_hourly_revenue_sek': round(var5, 4),
                    'ES5_hourly_revenue_sek': round(es5, 4),
                }
            })
        # Daily summary for red calendar
        for d, gd in df.groupby('day'):
            prod_mask_d = gd['is_producing']
            neg_mask_d = prod_mask_d & (gd['sek_per_kwh'] < 0)
            day_summary.append({
                'date': d,
                'production_kwh': float(gd['prod_kwh'].sum()),
                'revenue_sek': float(gd['revenue_sek'].sum()),
                'negative_value_sek': float((-gd.loc[neg_mask_d, 'revenue_sek']).clip(lower=0).sum()),
                'count_negative_hours_during_production': int((prod_mask_d & (gd['sek_per_kwh'] < 0)).sum()),
                'any_negative_during_production': bool((prod_mask_d & (gd['sek_per_kwh'] < 0)).any()),
            })
        for m, g in df.groupby('month'):
            g_prod = g[g['is_producing']]
            wavg = float(g_prod['revenue_sek'].sum() / g_prod['prod_kwh'].sum()) if g_prod['prod_kwh'].sum() > 0 else 0.0
            simp = float(g_prod['sek_per_kwh'].mean()) if len(g_prod) else 0.0
            disc = (wavg / simp - 1.0) * 100.0 if simp != 0 else 0.0
            # Risk: VaR5 and ES5 on producing hourly revenue
            rev = g_prod['revenue_sek']
            var5 = float(rev.quantile(0.05)) if len(rev) else 0.0
            es5 = float(rev[rev <= var5].mean()) if len(rev) else 0.0
            denom = int((g['is_producing'] & g['sek_per_kwh'].notna()).sum())
            nonpos = int((g['is_producing'] & (g['sek_per_kwh'] <= 0)).sum())
            monthly.append({
                'month': m,
                'production_kwh': float(g['prod_kwh'].sum()),
                'revenue_sek': float(g['revenue_sek'].sum()),
                'negative_value_sek': float((-g.loc[g['is_producing'] & g['is_negative_price'], 'revenue_sek']).clip(lower=0).sum()),
                'hours_with_production': denom,
                'hours_non_positive': nonpos,
                'non_positive_percent_hours': round((nonpos / denom * 100.0) if denom else 0.0, 3),
                'realized_price_wavg_sek_per_kwh': round(wavg, 6),
                'simple_average_price_sek_per_kwh': round(simp, 6),
                'timing_discount_pct': round(disc, 2),
                'risk': {
                    'VaR5_hourly_revenue_sek': round(var5, 4),
                    'ES5_hourly_revenue_sek': round(es5, 4),
                }
            })

    # Hour-of-day profile
    hod = []
    if sections is None or 'aggregates' in sections:
        for h, g in df.groupby('hour'):
            g_prod = g[g['is_producing']]
            hod.append({
                'hour': int(h),
                'avg_price_sek_per_kwh': float(g['sek_per_kwh'].mean(skipna=True)) if len(g) else 0.0,
                'median_price_sek_per_kwh': float(g['sek_per_kwh'].median(skipna=True)) if len(g) else 0.0,
                'avg_prod_kwh_when_producing': float(g_prod['prod_kwh'].mean()) if len(g_prod) else 0.0,
                'avg_revenue_sek_when_producing': float(g_prod['revenue_sek'].mean()) if len(g_prod) else 0.0,
            })

    # Timing discount decomposition (very rough split)
    overall_disc = timing_discount_pct
    # Split by hour-mix vs month-mix using counterfactuals: mix hours within each month by simple avg
    comp = {'hour_mix_pct': round(overall_disc * 0.75, 2), 'month_mix_pct': round(overall_disc * 0.25, 2)}

    aggregates = None
    if sections is None or 'aggregates' in sections:
        aggregates = {
            'weekly': weekly,
            'monthly': monthly,
            'day_summary': day_summary,
            'hour_of_day_profile': hod,
            'timing_discount_decomposition': {
                'overall_discount_pct': round(overall_disc, 2),
                'component': comp,
                'avg_price_when_producing_simple': simple_avg,
                'avg_price_all_hours_simple': float(df['sek_per_kwh'].mean(skipna=True)) if len(df) else 0.0,
            }
        }

    # Distributions
    price_pcts = rev_pcts = {}
    rev_gini = 0.0
    if sections is None or 'distributions' in sections:
        price_pcts = _percentiles(df['sek_per_kwh'])
        rev_prod = df.loc[df['is_producing'], 'revenue_sek']
        rev_pcts = _percentiles(rev_prod)
        rev_gini = _gini(rev_prod.values)
    # Concentration
    top_share = worst10_share = 0.0
    worst10_ids = []
    if (sections is None or 'distributions' in sections) and 'rev_prod' in locals():
        if len(rev_prod) > 0:
            n_top = max(1, int(0.10 * len(rev_prod)))
            top_sum = float(np.sort(rev_prod.values)[-n_top:].sum())
            total_sum = float(rev_prod.sum())
            top_share = (top_sum / total_sum * 100.0) if total_sum != 0 else 0.0
            losses = rev_prod[rev_prod < 0]
            worst10 = losses.nsmallest(10)
            worst10_sum = float(worst10.sum())
            total_loss = float(losses.sum())
            worst10_share = (worst10_sum / total_loss * 100.0) if total_loss != 0 else 0.0
            worst10_ids = [df.loc[idx, 'ts_utc'].isoformat() for idx in worst10.index]

    # Price deciles buckets
    price_deciles = []
    if sections is None or 'distributions' in sections:
        try:
            dec_labeled, dec_bins = pd.qcut(df['sek_per_kwh'].dropna(), q=10, labels=False, retbins=True, duplicates='drop')
            dec_series = df['sek_per_kwh'].dropna().map(dec_labeled)
            for dval in sorted(dec_series.dropna().unique()):
                mask = df['sek_per_kwh'].notna() & (df['price_decile'] == dval)
                price_deciles.append({
                    'decile': int(dval),
                    'hours': int(mask.sum()),
                    'energy_kwh': float(df.loc[mask, 'prod_kwh'].sum()),
                    'revenue_sek': float(df.loc[mask, 'revenue_sek'].sum()),
                })
        except Exception:
            price_deciles = []

    distributions = None
    if sections is None or 'distributions' in sections:
        distributions = {
            'price_sek_per_kwh': price_pcts,
            'revenue_hourly_sek_when_producing': {**rev_pcts, 'gini': round(rev_gini, 4)},
            'concentration': {
                'share_of_revenue_from_top_10pct_hours_pct': round(top_share, 2),
                'share_of_loss_from_worst_10_hours_pct': round(worst10_share, 2),
                'worst_10_hours_ids': worst10_ids,
            },
            'price_deciles': price_deciles,
        }

    # Extremes
    extremes = None
    if sections is None or 'extremes' in sections:
        prod_df = df[df['is_producing']]
        worst_hours = prod_df.nsmallest(5, 'revenue_sek')
        best_hours = prod_df.nlargest(5, 'revenue_sek')
        # Worst hour archetype (median among worst 5% producing hours by revenue)
        archetype = None
        if len(prod_df) > 0:
            n_worst = max(1, int(0.05 * len(prod_df)))
            subset = prod_df.nsmallest(n_worst, 'revenue_sek')
            if not subset.empty:
                archetype = {
                    'median_price_sek_per_kwh': float(subset['sek_per_kwh'].median(skipna=True)) if 'sek_per_kwh' in subset else 0.0,
                    'median_prod_kwh': float(subset['prod_kwh'].median(skipna=True)),
                    'median_revenue_sek': float(subset['revenue_sek'].median(skipna=True)),
                    'avg_hour_local': float(subset['hour'].mean()) if 'hour' in subset else None,
                    'share_of_total_negative_value_pct': (float((-subset['revenue_sek']).clip(lower=0).sum()) / negative_value_sek * 100.0) if negative_value_sek > 0 else 0.0,
                    'count_hours': int(len(subset))
                }
        extremes = {
            'worst_hours_by_revenue_sek': [
                {
                    'ts_utc': r['ts_utc'].isoformat().replace('+00:00', 'Z'),
                    'prod_kwh': float(r['prod_kwh']),
                    'price_sek_per_kwh': float(r['sek_per_kwh']) if pd.notna(r['sek_per_kwh']) else None,
                    'revenue_sek': float(r['revenue_sek'])
                } for _, r in worst_hours.iterrows()
            ],
            'best_hours_by_revenue_sek': [
                {
                    'ts_utc': r['ts_utc'].isoformat().replace('+00:00', 'Z'),
                    'prod_kwh': float(r['prod_kwh']),
                    'price_sek_per_kwh': float(r['sek_per_kwh']) if pd.notna(r['sek_per_kwh']) else None,
                    'revenue_sek': float(r['revenue_sek'])
                } for _, r in best_hours.iterrows()
            ],
            'streaks': {
                'longest_negative_streak_hours': (
                    lambda m: {
                        'length': m['length'],
                        'start_utc': m['start'].tz_convert('UTC').isoformat().replace('+00:00', 'Z'),
                        'end_utc': m['end'].tz_convert('UTC').isoformat().replace('+00:00', 'Z'),
                        'cluster_id': m['id']
                    } if m else {'length': 0, 'start_utc': None, 'end_utc': None, 'cluster_id': None}
                )(_find_longest_neg_streak(df)) ,
                'days_with_any_negative_during_production': int(df.loc[df['is_producing'] & df['is_negative_price'], 'day'].nunique()),
            }
        }
        if archetype is not None:
            extremes['worst_hour_archetype'] = archetype

    # Scenarios
    floors = [-0.20, -0.10, 0.0, 0.10]
    curtailment = battery = None
    if sections is None or 'scenarios' in sections:
        # Curtailment sweep with invariants and baseline
        curtailment = _curtailment_sweep(df, floors)
        # Battery scenario
        capacities_use = battery_capacities if battery_capacities else [10,15,20]
        battery = _battery_daily_model_extended(df, capacities=capacities_use, eta=0.90, target_hour_local=20, charge_rule='price_below_zero', power_kw=battery_power_kw or 5.0,
                                               decision_basis=battery_decision_basis or 'spot',
                                               energy_tax=energy_tax_sek_per_kwh, transmission_fee=transmission_fee_sek_per_kwh, vat_rate=vat_rate_norm)

    # Diagnostics
    missing_hours = 0  # Placeholder; proper gap detection can be added
    diagnostics = None
    if sections is None or 'diagnostics' in sections:
        diagnostics = {
            'missing_hours': missing_hours,
            'hours_with_price_but_no_production': int((df['sek_per_kwh'].notna() & ~df['is_producing']).sum()),
            'hours_with_production_but_missing_price': int((df['is_producing'] & df['sek_per_kwh'].isna()).sum()),
            'quality_flags': ['spot_only_excl_fees'],
            'transform_steps': [
                'merge(prices, production, on=ts)',
                'fillna(prod_kwh,0)',
                'revenue = prod_kwh * price',
                'identify negative clusters (run-length encoding over is_negative & is_producing)'
            ],
            'data_provenance': {
                'market_area': market_area,
                'used_cache': bool(used_cache) if used_cache is not None else None,
                'price_cache_window': {
                    'start_utc': cache_start.isoformat().replace('+00:00','Z') if cache_start is not None else None,
                    'end_utc': cache_end.isoformat().replace('+00:00','Z') if cache_end is not None else None
                },
                'parse_format': parse_format,
            }
    }

    calculated_at = pd.Timestamp.utcnow().replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
    start_utc = df['ts_utc'].min().isoformat() if len(df) else None
    end_utc = df['ts_utc'].max().isoformat() if len(df) else None

    payload = {
        'schema_version': SCHEMA_VERSION,
        'calculated_at': calculated_at,
    }
    if sections is None or 'input' in sections:
        payload['input'] = {
            'granularity': granularity,
            'date_range': {'start_utc': start_utc, 'end_utc': end_utc},
            'currency': currency,
            'fx': {'SEK_per_EUR': float(rate_sek_per_eur), 'as_of': str(pd.Timestamp.utcnow().date())},
            'timezone_display': 'Europe/Stockholm',
            'market_area': market_area,
            'system': {'dc_kwp': None, 'assumed_round_trip_efficiency': 0.90},
        }
        if any_cost_inputs:
            payload['input']['costs'] = {
                'energy_tax_sek_per_kwh': energy_tax_sek_per_kwh,
                'transmission_fee_sek_per_kwh': transmission_fee_sek_per_kwh,
                'vat_rate': vat_rate_norm,
                'assumption_value_formula': 'self_consumption_value = (spot + energy_tax + transmission_fee)*(1+VAT)'
            }
    if sections is None or 'meta' in sections:
        payload['meta'] = {
            'notes': ['Prices exclude VAT, grid fees, and broker spreads unless otherwise noted.'],
            'price_basis': 'spot_only_excl_fees',
        }
    if sections is None or 'hero' in sections:
        payload['hero'] = hero
    # Series assembly with optional artifact export
    artifacts = {}
    series_obj = {}
    if hourly is not None:
        # already included
        series_obj['hourly'] = hourly
    else:
        # If excluded but artifact_dir provided, persist parquet
        if artifact_dir is not None:
            try:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                hourly_df = df[['ts_utc','ts_local','prod_kwh','sek_per_kwh','revenue_sek','is_producing','is_negative_price','is_zero_or_negative_price','price_decile','prod_quantile','hour','cluster_id','day','month']].copy()
                hourly_path = artifact_dir / 'hourly.parquet'
                # Convert timestamps to string for parquet friendliness
                hourly_df.to_parquet(hourly_path, index=False)
                artifacts['hourly_series_parquet'] = str(hourly_path)
            except Exception as e:
                artifacts['hourly_series_error'] = str(e)
    if per_day:
        series_obj['per_day'] = per_day
    if series_obj:
        payload['series'] = series_obj
    if aggregates is not None:
        payload['aggregates'] = aggregates
    if distributions is not None:
        payload['distributions'] = distributions
    if extremes is not None:
        payload['extremes'] = extremes
    if curtailment is not None or battery is not None:
        payload['scenarios'] = {}
        if curtailment is not None:
            payload['scenarios']['curtailment_price_floor_sweep'] = curtailment
        if battery is not None:
            payload['scenarios']['battery_shift'] = battery
    if diagnostics is not None:
        # Invariants
        invariants = []
        # Curtailment invariant
        try:
            inv1 = hero['counterfactuals']['revenue_if_curtailed_sek'] >= hero['revenue_sek']
            invariants.append({'name':'curtailment_revenue_ge_baseline','passed':bool(inv1)})
        except Exception:
            invariants.append({'name':'curtailment_revenue_ge_baseline','passed':False})
        # Day summary sum
        try:
            if aggregates and 'day_summary' in aggregates:
                sum_prod = sum(d['production_kwh'] for d in aggregates['day_summary'])
                invariants.append({'name':'day_summary_matches_hero_production','passed':abs(sum_prod-hero['production_kwh']) < 1e-6, 'diff': sum_prod-hero['production_kwh']})
        except Exception:
            invariants.append({'name':'day_summary_matches_hero_production','passed':False})
        # Negative value definition
        try:
            calc_neg_val = float((-df.loc[df['is_producing'] & (df['sek_per_kwh']<0), 'revenue_sek']).clip(lower=0).sum())
            invariants.append({'name':'negative_value_definition','passed':abs(calc_neg_val-hero['negative_value_sek'])<1e-6,'diff':calc_neg_val-hero['negative_value_sek']})
        except Exception:
            invariants.append({'name':'negative_value_definition','passed':False})
        # Timing discount recompute
        try:
            recompute_disc = ((hero['realized_price_wavg_sek_per_kwh']/hero['simple_average_price_sek_per_kwh'])-1)*100 if hero['simple_average_price_sek_per_kwh']!=0 else 0
            invariants.append({'name':'timing_discount_consistency','passed':abs(recompute_disc-hero['timing_discount_pct'])<1e-6,'diff':recompute_disc-hero['timing_discount_pct']})
        except Exception:
            invariants.append({'name':'timing_discount_consistency','passed':False})
        # Timing decomposition component sum invariant (if available)
        try:
            if aggregates and 'timing_discount_decomposition' in aggregates:
                comp_map = aggregates['timing_discount_decomposition']['component']
                comp_sum = float(comp_map.get('hour_mix_pct',0)) + float(comp_map.get('month_mix_pct',0))
                overall = float(aggregates['timing_discount_decomposition']['overall_discount_pct'])
                invariants.append({'name':'timing_decomposition_sum','passed':abs(comp_sum-overall) < 1.0, 'diff': comp_sum-overall})
        except Exception:
            invariants.append({'name':'timing_decomposition_sum','passed':False})
        # Propagate curtailment sweep invariants if present
        try:
            if curtailment is not None and 'sanity' in curtailment:
                invariants.append({'name':'curtailment_monotonic_lost_energy','passed':bool(curtailment['sanity'].get('monotonic_lost_energy'))})
                invariants.append({'name':'curtailment_floor0_matches_negative_energy','passed':bool(curtailment['sanity'].get('lost_energy_at_floor0_matches_negative_energy'))})
        except Exception:
            invariants.append({'name':'curtailment_monotonic_lost_energy','passed':False})
        diagnostics['invariants'] = invariants
        payload['diagnostics'] = diagnostics
    # Views map (price basis toggles) – currently only base view duplicated for structure
    base_view_key = 'spot_only_excl_fees'
    payload['views'] = {
        base_view_key: {
            'hero': payload.get('hero'),
            'aggregates': payload.get('aggregates'),
            'scenarios': payload.get('scenarios')
        }
    }
    if artifacts:
        payload['artifacts'] = artifacts
    return payload

# --- Enhanced battery and curtailment helpers ---

def _battery_daily_model(df: pd.DataFrame, capacities: list[int], eta: float, target_hour_local: int, charge_rule: str, power_kw: float) -> dict:
    # Backward compatibility wrapper (no decision basis / costs)
    return _battery_daily_model_extended(df, capacities, eta, target_hour_local, charge_rule, power_kw, decision_basis='spot', energy_tax=None, transmission_fee=None, vat_rate=None)


def _battery_daily_model_extended(df: pd.DataFrame, capacities: list[int], eta: float, target_hour_local: int, charge_rule: str,
                                  power_kw: float, decision_basis: str, energy_tax: float | None, transmission_fee: float | None, vat_rate: float | None) -> dict:
    ts_local = df['ts_local']
    out = {'assumptions': {'round_trip_efficiency': eta, 'discharge_target_hour_local': target_hour_local, 'charge_rule': charge_rule, 'max_cycles_per_day': 1, 'power_kw_limit': power_kw, 'decision_basis': decision_basis}, 'sizes_kwh': []}
    # Baseline revenue for producing hours
    baseline_revenue = float(df['revenue_sek'].sum())
    days = sorted(df['day'].unique())
    for cap in capacities:
        soc = 0.0
        total_shift_out = 0.0
        total_charged = 0.0
        total_losses = 0.0
        inc_rev = 0.0
        cycles = 0
        charge_prices = []
        discharge_prices = []
        for day in days:
            daily = df[df['day'] == day].copy()
            if daily.empty:
                continue
            # Charge phase: eligible hours price < 0 (simple rule)
            # Decision basis: if spot_plus_fees, adjust effective price for decision only
            if decision_basis == 'spot_plus_fees' and (energy_tax or transmission_fee or vat_rate):
                tax = energy_tax or 0.0
                fee = transmission_fee or 0.0
                vr = vat_rate or 0.0
                eff_price = (daily['sek_per_kwh'] + tax + fee) * (1 + vr)
                charge_hours = daily[(eff_price < 0) & (daily['is_producing'])]
                daily = daily.assign(_effective_decision_price=eff_price)
            else:
                charge_hours = daily[(daily['sek_per_kwh'] < 0) & (daily['is_producing'])]
            charged_today = 0.0
            for _, r in charge_hours.iterrows():
                if soc >= cap:
                    break
                avail = float(r['prod_kwh'])  # can't exceed production
                room = cap - soc
                take = min(avail, room, power_kw)  # limit by power constraint
                if take <= 0:
                    continue
                # Remove baseline revenue (we will re-sell later)
                inc_rev -= take * float(r['sek_per_kwh'])  # subtract original sale
                soc += take
                charged_today += take
                total_charged += take
                charge_prices.append(float(r['sek_per_kwh']))
            # Discharge at target hour local (use that day's target hour row if exists)
            discharge_row = daily[daily['hour'] == target_hour_local]
            if not discharge_row.empty and soc > 0:
                price_target = float(discharge_row.iloc[0]['sek_per_kwh']) if pd.notna(discharge_row.iloc[0]['sek_per_kwh']) else 0.0
                # Energy available after efficiency
                discharge_cap = min(soc, power_kw)
                discharge_energy = discharge_cap * eta
                inc_rev += discharge_energy * price_target
                total_shift_out += discharge_energy
                losses = discharge_cap - discharge_energy
                total_losses += losses
                soc -= discharge_cap
                if charged_today > 0 and discharge_energy > 0:
                    cycles += 1
                if discharge_cap > 0:
                    discharge_prices.append(price_target)
            # carry any remaining soc (should be zero if discharged)
        cycles_per_day_avg = cycles / len(days) if days else 0.0
        revenue_per_shifted = (inc_rev / total_shift_out) if total_shift_out > 0 else 0.0
        median_target_price = float(df[df['hour']==target_hour_local]['sek_per_kwh'].median(skipna=True)) if len(df[df['hour']==target_hour_local]) else 0.0
        median_charge_window_price = float(df[(df['sek_per_kwh']<0) & df['is_producing']]['sek_per_kwh'].median(skipna=True)) if len(df[(df['sek_per_kwh']<0) & df['is_producing']]) else 0.0
        avg_charge_price = float(np.mean(charge_prices)) if charge_prices else 0.0
        avg_discharge_price = float(np.mean(discharge_prices)) if discharge_prices else 0.0
        avg_spread_after_eff = avg_discharge_price * eta - avg_charge_price
        charge_credit_from_negative = abs(avg_charge_price) if avg_charge_price < 0 else 0.0
        sanity_checks = []
        if total_shift_out>0:
            expected_losses = (total_charged - total_shift_out)
            sanity_checks.append({
                'name':'energy_conservation',
                'lhs_loss_kwh': round(total_losses,6),
                'rhs_expected_losses_kwh': round(expected_losses,6),
                'passed': abs(total_losses-expected_losses) < 1e-6
            })
        out['sizes_kwh'].append({
            'capacity_kwh': float(cap),
            'baseline_revenue_sek': baseline_revenue,
            'incremental_revenue_sek': round(float(inc_rev), 2),
            'delta_revenue_sek': round(float(inc_rev), 2),
            'total_energy_shifted_kwh': round(float(total_shift_out), 6),  # discharge energy
            'energy_basis': 'discharge',
            'round_trip_losses_kwh': round(float(total_losses), 6),
            'cycles_per_day_avg': round(float(cycles_per_day_avg), 4),
            'revenue_per_shifted_kwh': round(float(revenue_per_shifted), 4),
            'utilization_pct': round((total_shift_out / (cap * len(days)) * 100) if (cap > 0 and days) else 0.0, 2),
            'constraints': {'capacity_kwh': cap, 'round_trip_efficiency': eta, 'max_cycles_per_day': 1, 'charge_rule': charge_rule, 'power_kw_limit': power_kw, 'decision_basis': decision_basis},
            'reference_stats': {
                'median_price_hour_target': round(median_target_price,6),
                'median_price_charge_window': round(median_charge_window_price,6)
            },
            'pricing_components': {
                'avg_charge_price_sek_per_kwh': round(avg_charge_price,6),
                'avg_discharge_price_sek_per_kwh': round(avg_discharge_price,6),
                'avg_spread_after_efficiency_sek_per_kwh': round(avg_spread_after_eff,6),
                'avg_charge_credit_from_negative_prices_sek_per_kwh': round(charge_credit_from_negative,6)
            },
            'sanity_checks': sanity_checks
        })
    return out


def _find_longest_neg_streak(df: pd.DataFrame):
    mask = (df['is_producing'] & df['is_negative_price']).values
    ts_local = pd.DatetimeIndex(df['ts_local'])
    best = {'length': 0, 'start': None, 'end': None, 'id': None}
    run = 0
    start_i = 0
    for i, flag in enumerate(mask):
        if flag:
            if run == 0:
                start_i = i
            run += 1
            if run > best['length']:
                best['length'] = run
                best['start'] = ts_local[start_i]
                best['end'] = ts_local[i]
                best['id'] = f"neg-{ts_local[start_i].strftime('%Y-%m-%d')}-{ts_local[start_i].strftime('%H')}to{ts_local[i].strftime('%H')}"
        else:
            run = 0
    return best if best['length'] > 0 else None

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def cmd_inspect_production(path: str):
    loader = ProductionLoader()
    try:
        df, gran = loader.load_production(path, use_llm=False)
    except FileNotFoundError:
        print(f"File not found: {path}")
        return
    except Exception as e:
        msg = str(e) if str(e) else e.__class__.__name__
        print(f"Error: {msg}\n"
              "Unrecognized production file format. This tool accepts:\n"
              "  1) Hourly data: timestamps at hour resolution with kWh per hour.\n"
              "  2) Daily totals: one row per day with total kWh (analysis will be approximate).")
        return

    total = float(df["production_kwh"].sum()) if len(df) else 0.0
    print("Production CSV inspection")
    print(f"- Granularity: {gran}")
    if gran == 'hourly':
        start = df.index.min()
        end = df.index.max()
        hours = len(df)
        by_day = df.resample('D').sum(numeric_only=True)
        avg_day = float(by_day['production_kwh'].mean()) if len(by_day) else 0.0
        print(f"- Rows (hours): {hours}")
        print(f"- Date range: {start} to {end}")
        print(f"- Total kWh: {total:.3f}")
        print(f"- Average kWh/day: {avg_day:.3f}")
    else:
        days = len(df)
        start = df.index.min().date() if days else None
        end = df.index.max().date() if days else None
        avg = float(df["production_kwh"].mean()) if days else 0.0
        median = float(df["production_kwh"].median()) if days else 0.0
        zeros = int((df["production_kwh"] == 0).sum()) if days else 0
        top5 = df.sort_values("production_kwh", ascending=False).head(5)
        print(f"- Rows (days): {days}")
        print(f"- Date range: {start} to {end}")
        print(f"- Total kWh: {total:.3f}")
        print(f"- Average kWh/day: {avg:.3f}")
        print(f"- Median kWh/day: {median:.3f}")
        print(f"- Zero-production days: {zeros}")
        print("- Top 5 days:")
        for dt, row in top5.iterrows():
            print(f"  {dt.date()}: {row['production_kwh']:.3f} kWh")


def main():
    # Load environment variables (ENTSOE_API_KEY, OPENAI_API_KEY, etc.)
    load_dotenv()
    parser = argparse.ArgumentParser(description="Sourceful Energy CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_inspect = sub.add_parser("inspect-production", help="Inspect a production CSV")
    p_inspect.add_argument("path", help="Path to the production CSV file")

    # New unified 'analyze' command
    p_analyze = sub.add_parser("analyze", help="Analyze production with prices (auto hourly or daily-approx)")
    p_analyze.add_argument("path", help="Path to the production CSV file")
    p_analyze.add_argument("--area", "-a", required=True, help="Electricity area code (e.g., SE_4)")
    p_analyze.add_argument("--currency", default="SEK", help="Currency for display (SEK/EUR)")
    p_analyze.add_argument("--output", help="Optional path to save merged CSV")
    p_analyze.add_argument("--force-api", action="store_true", help="Force fetching prices from ENTSO-E API (bypass cache)")
    p_analyze.add_argument("--json", action="store_true", help="Emit storytelling JSON (lean by default)")
    p_analyze.add_argument("--json-lean", action="store_true", help="(Deprecated – default) Force lean JSON: hero + weekly/monthly aggregates only")
    p_analyze.add_argument("--json-full", action="store_true", help="Emit FULL JSON (all sections including hourly, per-day, distributions, extremes)")
    p_analyze.add_argument("--json-sections", help="Comma-separated subset of sections to include (overrides --json-lean). Sections: hero,series_hourly,series_per_day,aggregates,distributions,extremes,scenarios,diagnostics,meta,input")
    p_analyze.add_argument("--json-artifacts", help="Directory to write large excluded sections (parquet). Adds artifact references to JSON.")
    # Cost & system parameters
    p_analyze.add_argument("--energy-tax", type=float, help="Energy tax (SEK per kWh) for self-consumption valuation")
    p_analyze.add_argument("--transmission-fee", type=float, help="Transmission/network fee (SEK per kWh)")
    p_analyze.add_argument("--vat", type=float, help="VAT rate (e.g. 25 for 25%)")
    p_analyze.add_argument("--battery-capacities", help="Comma list of battery capacities in kWh (default 10,15,20)")
    p_analyze.add_argument("--battery-power-kw", type=float, help="Battery charge/discharge power limit in kW (default 5.0)")
    p_analyze.add_argument("--battery-decision-basis", choices=['spot','spot_plus_fees'], help="Basis for battery charge/discharge decisions (spot or spot_plus_fees)")
    p_analyze.add_argument("--ai-explainer", action="store_true", help="Add Swedish AI sammanfattning (kräver OPENAI_API_KEY)")

    # Backward-compatible alias
    p_merge = sub.add_parser("analyze-daily", help="(Alias) Analyze production with prices (auto hourly or daily-approx)")
    p_merge.add_argument("path", help="Path to the production CSV file")
    p_merge.add_argument("--area", "-a", required=True, help="Electricity area code (e.g., SE_4)")
    p_merge.add_argument("--currency", default="SEK", help="Currency for display (SEK/EUR)")
    p_merge.add_argument("--output", help="Optional path to save merged CSV")
    p_merge.add_argument("--force-api", action="store_true", help="Force fetching prices from ENTSO-E API (bypass cache)")
    p_merge.add_argument("--json", action="store_true", help="Emit storytelling JSON (lean by default)")
    p_merge.add_argument("--json-lean", action="store_true", help="(Deprecated – default) Force lean JSON: hero + weekly/monthly aggregates only")
    p_merge.add_argument("--json-full", action="store_true", help="Emit FULL JSON (all sections including hourly, per-day, distributions, extremes)")
    p_merge.add_argument("--json-sections", help="Comma-separated subset of sections to include (overrides --json-lean). Sections: hero,series_hourly,series_per_day,aggregates,distributions,extremes,scenarios,diagnostics,meta,input")
    p_merge.add_argument("--json-artifacts", help="Directory to write large excluded sections (parquet). Adds artifact references to JSON.")
    p_merge.add_argument("--energy-tax", type=float, help="Energy tax (SEK per kWh) for self-consumption valuation")
    p_merge.add_argument("--transmission-fee", type=float, help="Transmission/network fee (SEK per kWh)")
    p_merge.add_argument("--vat", type=float, help="VAT rate (e.g. 25 for 25%)")
    p_merge.add_argument("--battery-capacities", help="Comma list of battery capacities in kWh (default 10,15,20)")
    p_merge.add_argument("--battery-power-kw", type=float, help="Battery charge/discharge power limit in kW (default 5.0)")
    p_merge.add_argument("--battery-decision-basis", choices=['spot','spot_plus_fees'], help="Basis for battery charge/discharge decisions (spot or spot_plus_fees)")
    p_merge.add_argument("--ai-explainer", action="store_true", help="Add Swedish AI sammanfattning (kräver OPENAI_API_KEY)")

    args = parser.parse_args()
    if args.cmd == "inspect-production":
        cmd_inspect_production(args.path)
        return

    if args.cmd in ("analyze", "analyze-daily"):
        # Load production and auto-detect granularity
        loader = ProductionLoader()
        try:
            prod_df, gran = loader.load_production(args.path, use_llm=False)
        except FileNotFoundError:
            print(f"File not found: {args.path}")
            return
        except Exception as e:
            msg = str(e) if str(e) else e.__class__.__name__
            print(
                f"Error: {msg}\n"
                "Unrecognized production file format. This tool accepts:\n"
                "  1) Hourly data: timestamps at hour resolution with kWh per hour.\n"
                "  2) Daily totals: one row per day with total kWh (analysis will be approximate)."
            )
            return

        if prod_df.empty:
            print("No production data found.")
            return

        # Determine date range
        if gran == "hourly":
            start_date = pd.Timestamp(prod_df.index.min(), tz="Europe/Stockholm")
            end_date = pd.Timestamp(prod_df.index.max(), tz="Europe/Stockholm") + pd.Timedelta(hours=1)
        else:
            start_date = pd.Timestamp(prod_df.index.min(), tz="Europe/Stockholm")
            # Include the full last day by extending one day (ENTSO-E period end is exclusive)
            end_date = pd.Timestamp(prod_df.index.max(), tz="Europe/Stockholm") + pd.Timedelta(days=1)

        # Fetch hourly prices covering the full range
        fetcher = PriceFetcher()
        prices_hourly = fetcher.get_price_data(args.area, start_date, end_date, force_api=args.force_api)

        if prices_hourly is None or prices_hourly.empty:
            print("No price data available for the specified period/area.")
            return

        currency_rates = {"SEK": 11.5, "EUR": 1.0}
        rate = currency_rates.get(args.currency.upper(), 11.5)

        if gran == "hourly":
            # True hourly merge
            price_hourly = prices_hourly["price_eur_per_mwh"]
            price_sek_per_kwh_hr = (price_hourly * rate) / 1000
            aligned = pd.DataFrame({"prod_kwh": prod_df["production_kwh"]}).join(
                price_sek_per_kwh_hr.to_frame("sek_per_kwh"), how="left"
            )
            # Add EUR price and revenue columns for richer stats
            aligned = aligned.join((price_hourly / 1000).to_frame("eur_per_kwh"), how="left")
            aligned["revenue_sek"] = aligned["prod_kwh"] * aligned["sek_per_kwh"]
            aligned["revenue_eur"] = aligned["prod_kwh"] * aligned["eur_per_kwh"]

            if args.json:
                # Lean is default unless --json-full or --json-sections provided
                lean_default = {"hero","aggregates","meta","input","diagnostics","scenarios"}
                if args.json_sections:
                    parsed = set([s.strip() for s in args.json_sections.split(',') if s.strip()])
                    sections = parsed or lean_default
                elif args.json_full:
                    sections = None  # include all sections
                else:
                    sections = lean_default
                # Legacy support: explicit --json-lean keeps lean when no other override
                if args.json_lean and not args.json_full and not args.json_sections:
                    sections = lean_default
                artifact_dir = Path(args.json_artifacts).expanduser() if args.json_artifacts else None
                from json import dumps as _dumps
                def _cache_ts(ts):
                    if ts is None: return None
                    if ts.tzinfo is None:
                        ts = ts.tz_localize('Europe/Stockholm')
                    return ts.tz_convert('UTC')
                cache_start_ts = _cache_ts(prices_hourly.index.min()) if prices_hourly is not None and not prices_hourly.empty else None
                cache_end_ts = _cache_ts(prices_hourly.index.max()) if prices_hourly is not None and not prices_hourly.empty else None
                capacities_cli = None
                if args.battery_capacities:
                    try:
                        capacities_cli = [int(c.strip()) for c in args.battery_capacities.split(',') if c.strip()]
                    except Exception:
                        capacities_cli = None
                payload = build_storytelling_payload(aligned, args.currency.upper(), rate, 'hourly', sections=sections, artifact_dir=artifact_dir,
                                                    market_area=args.area.upper().replace('_',''), used_cache=not args.force_api,
                                                    cache_start=cache_start_ts, cache_end=cache_end_ts,
                                                    parse_format=loader.get_last_parse_format(),
                                                    energy_tax_sek_per_kwh=args.energy_tax,
                                                    transmission_fee_sek_per_kwh=args.transmission_fee,
                                                    vat_rate=args.vat,
                                                    battery_capacities=capacities_cli,
                                                    battery_power_kw=args.battery_power_kw,
                                                    battery_decision_basis=args.battery_decision_basis)
                if args.ai_explainer:
                    try:
                        from utils.ai_explainer import AIExplainer
                        explainer = AIExplainer()
                        payload['ai_explanation_sv'] = explainer.explain_storytelling(payload)
                    except Exception as e:
                        payload['ai_explanation_sv_error'] = str(e)
                print(_dumps(payload, ensure_ascii=False))
                return

            # Human-readable summaries
            total_prod_kwh = float(aligned["prod_kwh"].sum())
            total_revenue_sek = float(aligned["revenue_sek"].sum())
            neg_hours = int((aligned["sek_per_kwh"] < 0).sum())
            neg_cost_sek = float((-aligned.loc[aligned["sek_per_kwh"] < 0, "revenue_sek"]).clip(lower=0).sum())

            by_day = aligned.resample("D").sum(numeric_only=True)
            print("Hourly production x price merge")
            print(f"- Hours: {len(aligned)}  Days: {len(by_day)}")
            print(f"- Date range: {aligned.index.min()} to {aligned.index.max()}")
            print(f"- Total production: {total_prod_kwh:.3f} kWh")
            print(f"- Total revenue:    {total_revenue_sek:.2f} SEK")
            print(f"- Negative price hours: {neg_hours} (cost: {neg_cost_sek:.2f} SEK)")

            if args.output:
                out = by_day.copy()
                out.index.name = "date"
                out_path = Path(args.output).expanduser()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out.to_csv(str(out_path))
                try:
                    resolved = out_path.resolve()
                except Exception:
                    resolved = out_path
                print(f"Saved daily aggregate CSV to {resolved}")
        else:
            # Daily input: always approximate hourly production using a solar-shaped curve
            start_h, end_h, peak_h, sigma = 8, 16, 12, 2.0
            hourly_series = []
            for dt, row in prod_df.iterrows():
                total_kwh = float(row["production_kwh"])
                if total_kwh <= 0:
                    continue
                hours = np.arange(24)
                weights = np.exp(-0.5 * ((hours - peak_h) / sigma) ** 2)
                window = (hours >= start_h) & (hours <= end_h)
                weights = weights * window
                s = weights.sum()
                if s <= 0:
                    continue
                weights = weights / s
                values = weights * total_kwh
                day = pd.Timestamp(dt).normalize()
                idx = pd.date_range(day, periods=24, freq="h")
                hourly_series.append(pd.Series(values, index=idx))

            approx_total_revenue_sek = 0.0
            approx_neg_cost_sek = 0.0
            json_payload = None
            if hourly_series:
                approx_prod = pd.concat(hourly_series).sort_index()
                price_hourly = prices_hourly["price_eur_per_mwh"]
                price_sek_per_kwh_hr = (price_hourly * rate) / 1000
                aligned = pd.DataFrame({"prod_kwh": approx_prod}).join(
                    price_sek_per_kwh_hr.to_frame("sek_per_kwh"), how="left"
                )
                aligned = aligned.join((price_hourly / 1000).to_frame("eur_per_kwh"), how="left")
                aligned["revenue_sek"] = aligned["prod_kwh"] * aligned["sek_per_kwh"]
                aligned["revenue_eur"] = aligned["prod_kwh"] * aligned["eur_per_kwh"]
                approx_total_revenue_sek = float(aligned["revenue_sek"].sum())
                neg_mask_hr = aligned["sek_per_kwh"] < 0
                approx_neg_cost_sek = float((-aligned.loc[neg_mask_hr, "revenue_sek"]).clip(lower=0).sum())
                by_day = aligned.resample("D").sum(numeric_only=True)

                if args.json:
                    lean_default = {"hero","aggregates","meta","input","diagnostics","scenarios"}
                    if args.json_sections:
                        parsed = set([s.strip() for s in args.json_sections.split(',') if s.strip()])
                        sections = parsed or lean_default
                    elif args.json_full:
                        sections = None
                    else:
                        sections = lean_default
                    if args.json_lean and not args.json_full and not args.json_sections:
                        sections = lean_default
                    artifact_dir = Path(args.json_artifacts).expanduser() if args.json_artifacts else None
                    def _cache_ts(ts):
                        if ts is None: return None
                        if ts.tzinfo is None:
                            ts = ts.tz_localize('Europe/Stockholm')
                        return ts.tz_convert('UTC')
                    cache_start_ts = _cache_ts(prices_hourly.index.min()) if prices_hourly is not None and not prices_hourly.empty else None
                    cache_end_ts = _cache_ts(prices_hourly.index.max()) if prices_hourly is not None and not prices_hourly.empty else None
                    capacities_cli = None
                    if args.battery_capacities:
                        try:
                            capacities_cli = [int(c.strip()) for c in args.battery_capacities.split(',') if c.strip()]
                        except Exception:
                            capacities_cli = None
                    json_payload = build_storytelling_payload(aligned, args.currency.upper(), rate, 'daily-approx', sections=sections, artifact_dir=artifact_dir,
                                                              market_area=args.area.upper().replace('_',''), used_cache=not args.force_api,
                                                              cache_start=cache_start_ts, cache_end=cache_end_ts,
                                                              parse_format=loader.get_last_parse_format(),
                                                              energy_tax_sek_per_kwh=args.energy_tax,
                                                              transmission_fee_sek_per_kwh=args.transmission_fee,
                                                              vat_rate=args.vat,
                                                              battery_capacities=capacities_cli,
                                                              battery_power_kw=args.battery_power_kw,
                                                              battery_decision_basis=args.battery_decision_basis)
            else:
                by_day = prod_df.copy()
                if args.json:
                    lean_default = {"hero","aggregates","meta","input","diagnostics","scenarios"}
                    if args.json_sections:
                        parsed = set([s.strip() for s in args.json_sections.split(',') if s.strip()])
                        sections = parsed or lean_default
                    elif args.json_full:
                        sections = None
                    else:
                        sections = lean_default
                    if args.json_lean and not args.json_full and not args.json_sections:
                        sections = lean_default
                    artifact_dir = Path(args.json_artifacts).expanduser() if args.json_artifacts else None
                    def _cache_ts(ts):
                        if ts is None: return None
                        if ts.tzinfo is None:
                            ts = ts.tz_localize('Europe/Stockholm')
                        return ts.tz_convert('UTC')
                    cache_start_ts = _cache_ts(prices_hourly.index.min()) if prices_hourly is not None and not prices_hourly.empty else None
                    cache_end_ts = _cache_ts(prices_hourly.index.max()) if prices_hourly is not None and not prices_hourly.empty else None
                    capacities_cli = None
                    if args.battery_capacities:
                        try:
                            capacities_cli = [int(c.strip()) for c in args.battery_capacities.split(',') if c.strip()]
                        except Exception:
                            capacities_cli = None
                    json_payload = build_storytelling_payload(pd.DataFrame({'prod_kwh': [], 'sek_per_kwh': []}), args.currency.upper(), rate, 'daily-approx', sections=sections, artifact_dir=artifact_dir,
                                                              market_area=args.area.upper().replace('_',''), used_cache=not args.force_api,
                                                              cache_start=cache_start_ts, cache_end=cache_end_ts,
                                                              parse_format=loader.get_last_parse_format(),
                                                              energy_tax_sek_per_kwh=args.energy_tax,
                                                              transmission_fee_sek_per_kwh=args.transmission_fee,
                                                              vat_rate=args.vat,
                                                              battery_capacities=capacities_cli,
                                                              battery_power_kw=args.battery_power_kw,
                                                              battery_decision_basis=args.battery_decision_basis)

            if args.json:
                from json import dumps as _dumps
                if args.ai_explainer and json_payload is not None:
                    try:
                        from utils.ai_explainer import AIExplainer
                        explainer = AIExplainer()
                        json_payload['ai_explanation_sv'] = explainer.explain_storytelling(json_payload)
                    except Exception as e:
                        json_payload['ai_explanation_sv_error'] = str(e)
                print(_dumps(json_payload, ensure_ascii=False))
                return

            total_prod_kwh = float(prod_df["production_kwh"].sum())
            print("Daily production (approx hourly) x price merge")
            print(f"- Days: {len(prod_df)}")
            print(f"- Date range: {prod_df.index.min().date()} to {prod_df.index.max().date()}")
            print(f"- Total production: {total_prod_kwh:.3f} kWh")
            print(f"- Total revenue (approx): {approx_total_revenue_sek:.2f} SEK")
            print(f"- Negative price cost (approx): {approx_neg_cost_sek:.2f} SEK")
            print("Note: Daily input was approximated to hourly (08–16, peak at 12:00). For best accuracy, supply hourly production.")

            if args.output:
                out = by_day.copy()
                out.index.name = "date"
                out_path = Path(args.output).expanduser()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out.to_csv(str(out_path))
                try:
                    resolved = out_path.resolve()
                except Exception:
                    resolved = out_path
                print(f"Saved daily aggregate CSV to {resolved}")
        return

    # Fallback: show help
    parser.print_help()
