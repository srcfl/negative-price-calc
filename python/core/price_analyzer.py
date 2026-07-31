#!/usr/bin/env python3
import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from .intervals import infer_step_hours, interval_hours_series

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Standard Swedish main-fuse ratings (amperes), ascending. Mirrors FUSE_LADDER in analyze.ts.
FUSE_LADDER = [16, 20, 25, 35, 50, 63, 80, 100, 125, 160, 200, 250]


def next_fuse_step(amps: float) -> Optional[int]:
    """The next standard fuse rating strictly larger than ``amps`` (None if at the top)."""
    for a in FUSE_LADDER:
        if a > amps:
            return a
    return None


def prev_fuse_step(amps: float) -> Optional[int]:
    """The next standard fuse rating strictly smaller than ``amps`` (None if the smallest)."""
    prev = None
    for a in FUSE_LADDER:
        if a < amps:
            prev = a
        else:
            break
    return prev


class PriceAnalyzer:
    """Core analysis engine for price and production data.

    Interval-aware: production and prices may differ in resolution (hourly,
    15-minute from 2025-10-01, or daily). Prices are aligned onto the production
    timeline without dropping rows, and every "hours" metric is derived from each
    row's actual interval length rather than assuming one row equals one hour.
    """

    @staticmethod
    def merge_data(prices_df: pd.DataFrame, production_df: pd.DataFrame, eur_sek_rate: float = 11.5) -> pd.DataFrame:
        """
        Align prices onto the production timeline and compute derived columns.

        Unlike a plain inner join (which silently discards rows when production and
        prices have different cadences), this resamples the price series to the
        production resolution so no production interval is lost:
          * finer prices (e.g. 15-min prices vs. hourly production) are averaged
            down to the production grid;
          * coarser prices (e.g. hourly prices vs. 15-min production) are
            forward-filled onto the production grid.

        Args:
            prices_df: Price data with datetime index and 'price_eur_per_mwh'.
            production_df: Production data with datetime index and 'production_kwh'.
            eur_sek_rate: EUR to SEK exchange rate.

        Returns:
            pd.DataFrame: One row per production interval, with price, SEK price,
            export value and per-row 'interval_hours'.
        """
        logger.info("Merging price and production data")

        if not isinstance(prices_df.index, pd.DatetimeIndex):
            prices_df = prices_df.copy()
            prices_df.index = pd.to_datetime(prices_df.index)
        if not isinstance(production_df.index, pd.DatetimeIndex):
            production_df = production_df.copy()
            production_df.index = pd.to_datetime(production_df.index)

        prices_df = prices_df.sort_index()
        production_df = production_df.sort_index()

        prod_step = infer_step_hours(production_df.index)
        price_step = infer_step_hours(prices_df.index)

        if prices_df.index.equals(production_df.index):
            # Same cadence: no resampling needed.
            merged_df = production_df.copy()
            merged_df['price_eur_per_mwh'] = prices_df['price_eur_per_mwh']
            merged_df = merged_df.dropna(subset=['price_eur_per_mwh'])
        else:
            # Different cadence: project both onto a regular grid at the FINER of the
            # two resolutions over their overlapping span. Production energy is split
            # evenly across the finer cells (so 15-minute negative-price spikes are
            # surfaced even when production is only hourly); prices are held constant
            # within their interval (forward-filled). This mirrors the browser engine.
            step_hours = min(prod_step, price_step)
            target = pd.Timedelta(hours=step_hours)

            cov_start = max(production_df.index.min(), prices_df.index.min())
            cov_end = min(
                production_df.index.max() + pd.Timedelta(hours=prod_step),
                prices_df.index.max() + pd.Timedelta(hours=price_step),
            )
            if cov_end <= cov_start:
                raise ValueError("Price and production data do not overlap in time.")

            grid = pd.date_range(cov_start, cov_end, freq=target, inclusive='left')
            prod_on_grid = production_df['production_kwh'].reindex(grid, method='ffill') * (step_hours / prod_step)
            price_on_grid = prices_df['price_eur_per_mwh'].reindex(grid, method='ffill')

            merged_df = pd.DataFrame(
                {'production_kwh': prod_on_grid, 'price_eur_per_mwh': price_on_grid},
                index=grid,
            ).dropna(subset=['price_eur_per_mwh', 'production_kwh'])

        # Per-row interval length in hours (drives all "hours" metrics).
        merged_df['interval_hours'] = interval_hours_series(merged_df.index).reindex(merged_df.index).values

        # SEK pricing (convert from EUR/MWh to SEK/kWh). Energy is already per-interval
        # kWh, so export value = energy * price is correct at any resolution.
        merged_df['price_sek_per_kwh'] = (merged_df['price_eur_per_mwh'] * eur_sek_rate) / 1000
        merged_df['export_value_sek'] = merged_df['production_kwh'] * merged_df['price_sek_per_kwh']

        # Daily aggregations
        merged_df['production_daily'] = merged_df.groupby(merged_df.index.date)['production_kwh'].transform('sum')
        merged_df['price_daily_avg'] = merged_df.groupby(merged_df.index.date)['price_eur_per_mwh'].transform('mean')
        merged_df['export_value_daily_sek'] = merged_df.groupby(merged_df.index.date)['export_value_sek'].transform('sum')

        logger.info(f"Merged data: {len(merged_df)} rows from {merged_df.index.min()} to {merged_df.index.max()}")

        return merged_df

    @staticmethod
    def analyze_data(
        merged_df: pd.DataFrame,
        fuse_amps: float = None,
        voltage: float = 400.0,
        vat_rate: float = None,
        vat_registered: bool = False,
        grid_fixed: float = None,
        grid_pct: float = None,
        trader_fixed: float = None,
        trader_pct: float = None,
        grid_monthly_fee: float = None,
        trader_monthly_fee: float = None,
        next_fuse_monthly_fee: float = None,
        lower_fuse_monthly_fee: float = None,
        installed_kwp: float = None,
        self_energy_tax: float = None,
        self_grid_fee: float = None,
        self_quarter_price: bool = True,
    ) -> Dict[str, Any]:
        """
        Perform comprehensive analysis on merged price and production data.

        Args:
            merged_df (pd.DataFrame): Merged price and production data
            fuse_amps (float, optional): Main fuse rating (A). If given, adds a
                grid-connection "flat peak" analysis (time export power was maxed out).
            voltage (float): Line voltage for the 3-phase power calc (default 400 V).
            vat_rate (float, optional): VAT, fraction (0.25) or percent (25). Used by both
                valuations below.
            vat_registered (bool): If True, VAT is added to the EXPORT (sales) side; otherwise
                export is paid ex-moms. The self-consumption (buy) side always includes VAT, as
                a consumer always pays moms on purchased electricity. Default False.
            grid_fixed (float, optional): Elnätsbolag fixed förlustersättning in SEK/kWh.
            grid_pct (float, optional): Elnätsbolag variable förlustersättning, % of spot.
            trader_fixed (float, optional): Elhandelsbolag fixed påslag/avdrag in SEK/kWh
                (may be negative).
            trader_pct (float, optional): Elhandelsbolag variable påslag/avdrag, % of spot.
            grid_monthly_fee (float, optional): Elnät fixed monthly fee in SEK/month
                (varies by fuse class). Used by the monthly_forecast block.
            trader_monthly_fee (float, optional): Elhandel fixed monthly fee in SEK/month.
            next_fuse_monthly_fee (float, optional): Elnät monthly fee for the NEXT fuse size up.
                With fuse_amps, adds the ``fuse_upgrade`` worthiness block.
            lower_fuse_monthly_fee (float, optional): Elnät monthly fee for the NEXT fuse size
                DOWN. With fuse_amps, adds the ``fuse_downgrade`` block (fee saving vs clipped peaks).
            installed_kwp (float, optional): Installed PV capacity (kWp). Bounds the upgrade
                estimate — a bigger fuse only unlocks export up to what the panels can produce.
            self_energy_tax (float, optional): Energy tax in SEK/kWh. Adds the
                self-consumption block.
            self_grid_fee (float, optional): Grid/transmission fee in SEK/kWh. Adds the
                self-consumption block.
            self_quarter_price (bool): True if consumption is priced per quarter (15-min) —
                values self-use at the per-quarter spot; else at the period average. Default True.

        Returns:
            Dict[str, Any]: Analysis results with statistics and insights. Mirrors the
            TypeScript engine's export-compensation, self-consumption and export-at-loss
            model.
        """
        analysis = {}

        # Per-row interval length in hours. Falls back to 1.0 if merge_data wasn't used.
        if 'interval_hours' in merged_df.columns:
            interval_hours = merged_df['interval_hours']
        else:
            interval_hours = interval_hours_series(merged_df.index).reindex(merged_df.index)

        # Basic statistics
        analysis['period_days'] = (merged_df.index.max() - merged_df.index.min()).days
        analysis['total_intervals'] = len(merged_df)
        analysis['total_hours'] = float(interval_hours.sum())  # duration, not row count
        
        # Time series data for charts (limit to prevent large payloads)
        time_series_limit = min(len(merged_df), 720)  # Max 30 days of hourly data
        sample_df = merged_df.head(time_series_limit) if len(merged_df) > time_series_limit else merged_df
        
        analysis['time_series'] = {
            'timestamps': [dt.isoformat() for dt in sample_df.index],
            'production': sample_df['production_kwh'].tolist(),
            'prices_eur_mwh': sample_df['price_eur_per_mwh'].tolist(),
            'prices_sek_kwh': sample_df['price_sek_per_kwh'].tolist(),
            'export_values': sample_df['export_value_sek'].tolist(),
            'negative_price_mask': (sample_df['price_eur_per_mwh'] < 0).tolist()
        }
        
        # Daily aggregations for monthly/weekly views
        daily_data = merged_df.groupby(merged_df.index.date).agg({
            'production_kwh': 'sum',
            'price_eur_per_mwh': 'mean',
            'export_value_sek': 'sum'
        }).reset_index()
        
        analysis['daily_series'] = {
            'dates': [d.isoformat() for d in daily_data['index']],
            'daily_production': daily_data['production_kwh'].tolist(),
            'daily_avg_price': daily_data['price_eur_per_mwh'].tolist(),
            'daily_export_value': daily_data['export_value_sek'].tolist()
        }
        
        # Negative pricing insights
        negative_periods = merged_df[merged_df['price_eur_per_mwh'] < 0]
        if len(negative_periods) > 0:
            analysis['negative_price_timeline'] = {
                'timestamps': [dt.isoformat() for dt in negative_periods.index],
                'production_kwh': negative_periods['production_kwh'].tolist(),
                'prices_eur_mwh': negative_periods['price_eur_per_mwh'].tolist(),
                'cost_sek': negative_periods['export_value_sek'].tolist()
            }
        else:
            analysis['negative_price_timeline'] = None
        
        # Price statistics in SEK/kWh (user-friendly format)
        analysis['price_min_sek_kwh'] = merged_df['price_sek_per_kwh'].min()
        analysis['price_max_sek_kwh'] = merged_df['price_sek_per_kwh'].max()
        analysis['price_mean_sek_kwh'] = merged_df['price_sek_per_kwh'].mean()
        analysis['price_median_sek_kwh'] = merged_df['price_sek_per_kwh'].median()
        
        # Keep EUR/MWh for reference (internal use)
        analysis['price_min_eur_mwh'] = merged_df['price_eur_per_mwh'].min()
        analysis['price_max_eur_mwh'] = merged_df['price_eur_per_mwh'].max()
        analysis['price_mean_eur_mwh'] = merged_df['price_eur_per_mwh'].mean()
        analysis['price_median_eur_mwh'] = merged_df['price_eur_per_mwh'].median()
        
        # Production statistics
        analysis['production_total'] = merged_df['production_kwh'].sum()
        analysis['production_mean'] = merged_df['production_kwh'].mean()
        analysis['production_max'] = merged_df['production_kwh'].max()
        analysis['hours_with_production'] = float(interval_hours[merged_df['production_kwh'] > 0].sum())

        # Negative price analysis (Enhanced)
        negative_mask = merged_df['price_eur_per_mwh'] < 0
        negative_prices = merged_df[negative_mask]
        analysis['negative_price_intervals'] = len(negative_prices)
        # Counts of producing intervals (≈ quarters for 15-min data); mirrors the web hero card.
        producing_mask = merged_df['production_kwh'] > 0
        analysis['producing_intervals'] = int(producing_mask.sum())
        analysis['negative_producing_intervals'] = int((producing_mask & negative_mask).sum())
        analysis['negative_price_hours'] = float(interval_hours[negative_mask].sum())  # duration
        analysis['production_during_negative_prices'] = negative_prices['production_kwh'].sum()
        analysis['negative_export_cost_sek'] = negative_prices['export_value_sek'].sum()  # This will be negative
        analysis['negative_export_cost_abs_sek'] = abs(negative_prices['export_value_sek'].sum())  # Absolute cost

        # Enhanced negative pricing metrics (share of time, by duration)
        analysis['negative_price_percentage'] = (analysis['negative_price_hours'] / analysis['total_hours']) * 100 if analysis['total_hours'] > 0 else 0
        analysis['production_percentage_negative_prices'] = (analysis['production_during_negative_prices'] / analysis['production_total']) * 100 if analysis['production_total'] > 0 else 0
        
        if len(negative_prices) > 0:
            analysis['avg_production_during_negative_prices'] = negative_prices['production_kwh'].mean()
            analysis['avg_negative_price_sek_per_kwh'] = negative_prices['price_sek_per_kwh'].mean()
            analysis['min_negative_price_sek_per_kwh'] = negative_prices['price_sek_per_kwh'].min()
            
            # Find the worst negative price period
            worst_negative_idx = negative_prices['price_eur_per_mwh'].idxmin()
            analysis['worst_negative_price_datetime'] = worst_negative_idx.isoformat()
            analysis['worst_negative_price_eur_mwh'] = negative_prices.loc[worst_negative_idx, 'price_eur_per_mwh']
            analysis['worst_negative_price_production'] = negative_prices.loc[worst_negative_idx, 'production_kwh']
            analysis['worst_negative_price_cost'] = abs(negative_prices.loc[worst_negative_idx, 'export_value_sek'])
        else:
            analysis['avg_production_during_negative_prices'] = 0
            analysis['avg_negative_price_sek_per_kwh'] = 0
            analysis['min_negative_price_sek_per_kwh'] = 0
            analysis['worst_negative_price_datetime'] = None
            analysis['worst_negative_price_eur_mwh'] = 0
            analysis['worst_negative_price_production'] = 0
            analysis['worst_negative_price_cost'] = 0
        
        # Total export value
        analysis['total_export_value_sek'] = merged_df['export_value_sek'].sum()
        analysis['positive_export_value_sek'] = merged_df[merged_df['price_eur_per_mwh'] > 0]['export_value_sek'].sum()
        
        # Correlation analysis
        if merged_df['production_kwh'].var() > 0 and merged_df['price_sek_per_kwh'].var() > 0:
            analysis['price_production_correlation'] = merged_df['production_kwh'].corr(merged_df['price_sek_per_kwh'])
        else:
            analysis['price_production_correlation'] = 0
        
        # Volatility metrics
        analysis['price_volatility_std'] = merged_df['price_sek_per_kwh'].std()
        analysis['price_volatility_cv'] = analysis['price_volatility_std'] / analysis['price_mean_sek_kwh'] if analysis['price_mean_sek_kwh'] != 0 else 0

        # Grid-connection (main fuse) flat-peak analysis. Average power per interval =
        # energy / duration, so 15-minute data catches short clipping peaks that hourly
        # data averages away. Mirrors the browser engine's analyzeFusePeaks().
        if fuse_amps:
            limit_kw = (3 ** 0.5) * voltage * fuse_amps / 1000.0
            threshold = limit_kw * 0.98  # within 2% of the limit counts as "maxed out"
            power_kw = merged_df['production_kwh'] / interval_hours
            maxed = power_kw >= threshold
            hours_at_max = float(interval_hours[maxed].sum())
            # Share is measured against the time you can actually export (the hours you were
            # producing), not all 24 h — counting the night understates the bottleneck. (The
            # browser app additionally narrows this to STRÅNG sunlit hours when a location is
            # set; STRÅNG is browser-only, so here the basis is producing time.)
            producing_hours = float(interval_hours[merged_df['production_kwh'] > 0].sum())
            analysis['grid_connection'] = {
                'fuse_amp': fuse_amps,
                'fuse_limit_kw': round(limit_kw, 2),
                'peak_power_kw': round(float(power_kw.max()), 2),
                'hours_at_max': round(hours_at_max, 2),
                'share_time_at_max_pct': round(hours_at_max / producing_hours * 100, 1) if producing_hours else 0.0,
                'share_basis': 'producing',
                'energy_at_max_kwh': round(float(merged_df.loc[maxed, 'production_kwh'].sum()), 2),
                'peaks': int(maxed.sum()),
            }

        # Export-compensation + self-consumption valuations, split per company (elnät /
        # elhandel), each with a fixed (SEK/kWh) and variable (% of spot) part. Uses the
        # energy-weighted average spot (affine, so equals a per-interval result). Mirrors
        # analyze.ts.
        total_kwh = float(analysis['production_total'])
        spot_total = float(analysis['total_export_value_sek'])
        realized_spot = spot_total / total_kwh if total_kwh else 0.0
        # Duration-weighted average spot over the covered intervals (the "period average").
        ih_sum = float(interval_hours.sum())
        avg_spot = (
            float((merged_df['price_sek_per_kwh'] * interval_hours).sum() / ih_sum)
            if ih_sum > 0 else realized_spot
        )

        def _norm_vat(v):
            if v is None:
                return 0.0
            return v / 100.0 if v > 1 else v

        vat = _norm_vat(vat_rate)
        # VAT on the EXPORT (sales) side applies only when the producer is VAT-registered;
        # the BUY side (self-consumption / cost of bought electricity) always includes VAT.
        sales_vat = vat if vat_registered else 0.0
        g_fixed = grid_fixed or 0.0
        g_pct = grid_pct or 0.0
        t_fixed = trader_fixed or 0.0
        t_pct = trader_pct or 0.0

        def _effective(spot):
            before = spot + g_fixed + spot * (g_pct / 100.0) + t_fixed + spot * (t_pct / 100.0)
            return before * (1 + sales_vat)

        if total_kwh > 0 and any(x is not None for x in (vat_rate, grid_fixed, grid_pct, trader_fixed, trader_pct)):
            elnat_var = realized_spot * (g_pct / 100.0)
            elnat_total = g_fixed + elnat_var
            elhandel_var = realized_spot * (t_pct / 100.0)
            elhandel_total = t_fixed + elhandel_var
            before_vat = realized_spot + elnat_total + elhandel_total
            effective = before_vat * (1 + sales_vat)
            effective_total = effective * total_kwh
            analysis['export_compensation'] = {
                'vat_pct': round(sales_vat * 100, 1),
                'vat_on_sales': bool(vat_registered),
                'spot_sek_per_kwh': round(realized_spot, 4),
                'elnat_fixed_sek_per_kwh': round(g_fixed, 4),
                'elnat_pct': round(g_pct, 2),
                'elnat_variable_sek_per_kwh': round(elnat_var, 4),
                'elnat_total_sek_per_kwh': round(elnat_total, 4),
                'elhandel_fixed_sek_per_kwh': round(t_fixed, 4),
                'elhandel_pct': round(t_pct, 2),
                'elhandel_variable_sek_per_kwh': round(elhandel_var, 4),
                'elhandel_total_sek_per_kwh': round(elhandel_total, 4),
                'price_before_vat_sek_per_kwh': round(before_vat, 4),
                'effective_price_sek_per_kwh': round(effective, 4),
                'spot_total_sek': round(spot_total, 2),
                'effective_total_sek': round(effective_total, 2),
                'uplift_vs_spot_sek': round(effective_total - spot_total, 2),
            }

        if total_kwh > 0 and any(x is not None for x in (self_energy_tax, self_grid_fee)):
            tax = self_energy_tax or 0.0
            fee = self_grid_fee or 0.0
            # Quarter pricing -> avoided purchase at the per-quarter (production-weighted) spot;
            # otherwise at the period's average spot. Export is always realized at production time.
            self_spot = realized_spot if self_quarter_price else avg_spot
            value_self = (self_spot + tax + fee) * (1 + vat)
            export_value = _effective(realized_spot)

            # Per-month breakdown on the actual production: saving from self-using vs exporting.
            df_sc = merged_df.copy()
            df_sc['interval_hours'] = interval_hours.values
            sc_months = []
            for period, grp in df_sc.groupby(df_sc.index.to_period('M')):
                kwh = float(grp['production_kwh'].sum())
                if kwh <= 0:
                    continue
                m_realized = float(grp['export_value_sek'].sum()) / kwh
                ih = float(grp['interval_hours'].sum())
                m_avg = (
                    float((grp['price_sek_per_kwh'] * grp['interval_hours']).sum() / ih)
                    if ih > 0 else m_realized
                )
                m_self_spot = m_realized if self_quarter_price else m_avg
                m_value_self = (m_self_spot + tax + fee) * (1 + vat)
                m_export = _effective(m_realized)
                sc_months.append({
                    'period': str(period),
                    'production_kwh': round(kwh, 1),
                    'value_self_sek_per_kwh': round(m_value_self, 4),
                    'export_value_sek_per_kwh': round(m_export, 4),
                    'saving_sek': round(kwh * (m_value_self - m_export), 2),
                })

            analysis['self_consumption'] = {
                'vat_pct': round(vat * 100, 1),
                'quarter_price': self_quarter_price,
                'spot_sek_per_kwh': round(self_spot, 4),
                'energy_tax_sek_per_kwh': round(tax, 4),
                'grid_fee_sek_per_kwh': round(fee, 4),
                'value_self_sek_per_kwh': round(value_self, 4),
                'export_value_sek_per_kwh': round(export_value, 4),
                'increment_vs_export_sek_per_kwh': round(value_self - export_value, 4),
                'months': sc_months,
                'total_saving_sek': round(sum(x['saving_sek'] for x in sc_months), 2),
            }

        # Quarters exported at a loss: effective export price below zero while exporting.
        if total_kwh > 0:
            price_sek = merged_df['price_sek_per_kwh']
            prod_kwh = merged_df['production_kwh']
            eff_price = (price_sek + g_fixed + price_sek * (g_pct / 100.0)
                         + t_fixed + price_sek * (t_pct / 100.0)) * (1 + sales_vat)
            loss_mask = (eff_price < 0) & (prod_kwh > 0)
            loss_count = int(loss_mask.sum())
            if loss_count > 0:
                loss_df = merged_df[loss_mask].copy()
                loss_df['eff_price'] = eff_price[loss_mask]
                loss_df['loss_sek'] = -(loss_df['production_kwh'] * loss_df['eff_price'])
                total_pct_frac = (g_pct + t_pct) / 100.0
                total_fixed = g_fixed + t_fixed
                break_even = -total_fixed / (1 + total_pct_frac) if (1 + total_pct_frac) != 0 else 0.0
                step_min = float(interval_hours.median()) * 60 if len(interval_hours) else 60.0
                worst = loss_df.sort_values('loss_sek', ascending=False).head(50)
                rows = [{
                    'start': idx.isoformat(),
                    'spot_sek_per_kwh': round(float(row['price_sek_per_kwh']), 4),
                    'effective_price_sek_per_kwh': round(float(row['eff_price']), 4),
                    'kwh': round(float(row['production_kwh']), 3),
                    'loss_sek': round(float(row['loss_sek']), 2),
                } for idx, row in worst.iterrows()]
                daily_loss = loss_df.groupby(loss_df.index.date)['loss_sek'].sum()
                series = [{'date': d.isoformat(), 'loss_sek': round(float(v), 2)} for d, v in daily_loss.items()]
                analysis['export_at_loss'] = {
                    'count': loss_count,
                    'interval_minutes': round(step_min, 1),
                    'break_even_spot_sek_per_kwh': round(break_even, 4),
                    'total_kwh': round(float(loss_df['production_kwh'].sum()), 3),
                    'total_loss_sek': round(float(loss_df['loss_sek'].sum()), 2),
                    'rows': rows,
                    'series': series,
                }

        # Monthly forecast — always per FULL month so the fixed monthly fees apply
        # consistently. Partial months (start/end of the data) are scaled up by their
        # coverage and flagged. Mirrors analyze.ts.
        if total_kwh > 0:
            # Fixed monthly fees are optional. Without any, report production and effective
            # compensation but omit the net-after-fees figures rather than silently treating
            # an unfilled fee as 0 kr (which would overstate the net). Mirrors analyze.ts.
            g_month = grid_monthly_fee or 0.0
            t_month = trader_monthly_fee or 0.0
            has_fixed_monthly = grid_monthly_fee is not None or trader_monthly_fee is not None
            fixed_monthly = g_month + t_month
            pct_frac = (g_pct + t_pct) / 100.0
            tot_fixed = g_fixed + t_fixed
            prod_start = merged_df.index.min()
            step_h = float(interval_hours.median()) if len(interval_hours) else 1.0
            prod_end = merged_df.index.max() + pd.Timedelta(hours=step_h)
            forecast_months = []
            for period, grp in merged_df.groupby(merged_df.index.to_period('M')):
                month_start = period.start_time
                month_end = (period + 1).start_time  # exclusive (start of next month)
                covered_start = max(prod_start, month_start)
                covered_end = min(prod_end, month_end)
                covered_days = max((covered_end - covered_start).total_seconds() / 86400.0, 0.0)
                days_in_month = (month_end - month_start).total_seconds() / 86400.0
                complete = (prod_start <= month_start) and (prod_end >= month_end)
                scale = 1.0 if (complete or covered_days <= 0) else days_in_month / covered_days
                revenue_month = float(grp['export_value_sek'].sum())
                kwh_month = float(grp['production_kwh'].sum())
                effective = (1 + sales_vat) * ((1 + pct_frac) * revenue_month + tot_fixed * kwh_month)
                forecast_months.append({
                    'period': str(period),
                    'complete': complete,
                    'days_with_data': round(covered_days, 1),
                    'days_in_month': round(days_in_month),
                    'production_kwh': round(kwh_month * scale, 1),
                    'effective_sek': round(effective * scale, 2),
                    'fixed_fees_sek': round(fixed_monthly, 2) if has_fixed_monthly else None,
                    'net_sek': round(effective * scale - fixed_monthly, 2) if has_fixed_monthly else None,
                })
            if forecast_months:
                n = len(forecast_months)
                analysis['monthly_forecast'] = {
                    'months_count': n,
                    'full_months': sum(1 for m in forecast_months if m['complete']),
                    'has_fixed_fees': has_fixed_monthly,
                    'grid_monthly_fee_sek': round(g_month, 2) if grid_monthly_fee is not None else None,
                    'trader_monthly_fee_sek': round(t_month, 2) if trader_monthly_fee is not None else None,
                    'fixed_monthly_sek': round(fixed_monthly, 2) if has_fixed_monthly else None,
                    'months': forecast_months,
                    'avg_production_kwh': round(sum(m['production_kwh'] for m in forecast_months) / n, 1),
                    'avg_effective_sek': round(sum(m['effective_sek'] for m in forecast_months) / n, 2),
                    'avg_net_sek': (
                        round(sum(m['net_sek'] for m in forecast_months) / n, 2)
                        if has_fixed_monthly
                        else None
                    ),
                }

        # Fuse upgrade ("is a bigger main fuse worth it?"). Mirrors analyze.ts
        # sakringsuppgradering: weigh the extra annual grid subscription against the
        # (best-case) value of export a bigger fuse would unlock during the quarters that hit
        # the cap — counting only sustained clipping (≥2 consecutive intervals) and bounded by
        # the installed kWp (a bigger fuse only helps up to what the panels can produce).
        # Both fuse verdicts compare the *current* subscription fee against the alternative,
        # so they need both numbers; without the current fee the comparison would run against
        # 0 kr/month and read as a confident answer while being meaningless. Mirrors analyze.ts.
        next_amp = (
            next_fuse_step(fuse_amps)
            if (fuse_amps and next_fuse_monthly_fee is not None and grid_monthly_fee is not None)
            else None
        )
        if next_amp is not None:
            cur_limit_kw = (3 ** 0.5) * voltage * fuse_amps / 1000.0
            next_limit_kw = (3 ** 0.5) * voltage * next_amp / 1000.0
            up_threshold = cur_limit_kw * 0.98
            achievable_kw = min(next_limit_kw, installed_kwp) if installed_kwp is not None else next_limit_kw
            headroom_kw = max(0.0, achievable_kw - cur_limit_kw)

            power = (merged_df['production_kwh'] / interval_hours).values
            clipped = power >= up_threshold
            ih_arr = interval_hours.values
            # Gaps to the previous / next row, in hours (unit-safe via Timedelta).
            ts = merged_df.index.to_series()
            gap_prev_h = (ts - ts.shift(1)).dt.total_seconds().values / 3600.0
            gap_next_h = (ts.shift(-1) - ts).dt.total_seconds().values / 3600.0
            n = len(clipped)
            sustained = np.zeros(n, dtype=bool)
            tol_h = 1.0 / 3600.0  # 1-second tolerance on interval contiguity
            for i in range(n):
                if not clipped[i]:
                    continue
                prev_adj = i > 0 and clipped[i - 1] and abs(gap_prev_h[i] - ih_arr[i - 1]) <= tol_h
                next_adj = i < n - 1 and clipped[i + 1] and abs(gap_next_h[i] - ih_arr[i]) <= tol_h
                if prev_adj or next_adj:
                    sustained[i] = True

            eff_all = _effective(merged_df['price_sek_per_kwh']).values
            unlocked_kwh_per = headroom_kw * interval_hours.values
            unlocked_kwh = float(unlocked_kwh_per[sustained].sum())
            unlocked_value = float((unlocked_kwh_per * eff_all)[sustained].sum())

            step_h = float(interval_hours.median()) if len(interval_hours) else 1.0
            prod_start = merged_df.index.min()
            prod_end = merged_df.index.max() + pd.Timedelta(hours=step_h)
            period_days = (prod_end - prod_start).total_seconds() / 86400.0
            annual_factor = 365.0 / period_days if period_days > 0 else 0.0

            period_months = period_days / 30.437
            cur_fee = grid_monthly_fee or 0.0
            next_fee = next_fuse_monthly_fee or 0.0
            extra_fee_month = next_fee - cur_fee
            extra_fee_year = extra_fee_month * 12.0
            extra_fee_period = extra_fee_month * period_months
            unlocked_value_year = unlocked_value * annual_factor
            net_period = unlocked_value - extra_fee_period
            net_year = unlocked_value_year - extra_fee_year
            analysis['fuse_upgrade'] = {
                'current_fuse_amp': fuse_amps,
                'current_fuse_kw': round(cur_limit_kw, 2),
                'next_fuse_amp': next_amp,
                'next_fuse_kw': round(next_limit_kw, 2),
                'current_fee_sek_per_month': round(cur_fee, 2),
                'next_fee_sek_per_month': round(next_fee, 2),
                'extra_fee_sek_per_month': round(extra_fee_month, 2),
                'extra_fee_sek_per_year': round(extra_fee_year, 2),
                'extra_fee_over_period_sek': round(extra_fee_period, 2),
                'sustained_clip_intervals': int(sustained.sum()),
                'installed_kwp': round(installed_kwp, 2) if installed_kwp is not None else None,
                'limited_by_kwp': bool(installed_kwp is not None and installed_kwp < next_limit_kw),
                'period_days': round(period_days, 1),
                'estimated_extra_export_kwh': round(unlocked_kwh, 1),
                'estimated_extra_value_sek': round(unlocked_value, 2),
                'estimated_extra_export_kwh_per_year': round(unlocked_kwh * annual_factor, 1),
                'estimated_extra_value_per_year_sek': round(unlocked_value_year, 2),
                'net_over_period_sek': round(net_period, 2),
                'net_per_year_sek': round(net_year, 2),
                'worth_upgrading': bool(net_period > 0),
            }

        # Fuse downgrade ("would a smaller fuse pay off?"). Mirrors analyze.ts
        # sakringsnedgradering: weigh the annual subscription saving against the export a lower
        # fuse would clip (power above the lower limit). Concrete, from the actual production.
        prev_amp = (
            prev_fuse_step(fuse_amps)
            if (fuse_amps and lower_fuse_monthly_fee is not None and grid_monthly_fee is not None)
            else None
        )
        if prev_amp is not None:
            cur_limit_kw = (3 ** 0.5) * voltage * fuse_amps / 1000.0
            prev_limit_kw = (3 ** 0.5) * voltage * prev_amp / 1000.0
            power = (merged_df['production_kwh'] / interval_hours).values
            eff_all = _effective(merged_df['price_sek_per_kwh']).values
            ih = interval_hours.values
            over = power > prev_limit_kw
            lost_kwh_arr = np.maximum(0.0, power - prev_limit_kw) * ih
            lost_kwh = float(lost_kwh_arr.sum())
            lost_value = float((lost_kwh_arr * eff_all).sum())

            step_h = float(interval_hours.median()) if len(interval_hours) else 1.0
            prod_start = merged_df.index.min()
            prod_end = merged_df.index.max() + pd.Timedelta(hours=step_h)
            period_days = (prod_end - prod_start).total_seconds() / 86400.0
            annual_factor = 365.0 / period_days if period_days > 0 else 0.0

            period_months = period_days / 30.437
            cur_fee = grid_monthly_fee or 0.0
            lower_fee = lower_fuse_monthly_fee or 0.0
            saving_month = cur_fee - lower_fee
            saving_year = saving_month * 12.0
            saving_period = saving_month * period_months
            lost_value_year = lost_value * annual_factor
            net_period = saving_period - lost_value
            net_year = saving_year - lost_value_year
            analysis['fuse_downgrade'] = {
                'current_fuse_amp': fuse_amps,
                'current_fuse_kw': round(cur_limit_kw, 2),
                'lower_fuse_amp': prev_amp,
                'lower_fuse_kw': round(prev_limit_kw, 2),
                'current_fee_sek_per_month': round(cur_fee, 2),
                'lower_fee_sek_per_month': round(lower_fee, 2),
                'saved_fee_sek_per_month': round(saving_month, 2),
                'saved_fee_sek_per_year': round(saving_year, 2),
                'saved_fee_over_period_sek': round(saving_period, 2),
                'intervals_over_lower_limit': int(over.sum()),
                'period_days': round(period_days, 1),
                'clipped_export_kwh': round(lost_kwh, 1),
                'clipped_value_sek': round(lost_value, 2),
                'clipped_export_kwh_per_year': round(lost_kwh * annual_factor, 1),
                'clipped_value_per_year_sek': round(lost_value_year, 2),
                'net_over_period_sek': round(net_period, 2),
                'net_per_year_sek': round(net_year, 2),
                'worth_downgrading': bool(net_period > 0),
            }

        # Echo the inputs used (SEK units), for traceability / export. Mirrors the web
        # app's `parametrar` block.
        analysis['parameters'] = {
            'vat_rate': vat_rate,
            'vat_registered': vat_registered,
            'grid_fixed_sek_per_kwh': grid_fixed,
            'grid_pct': grid_pct,
            'trader_fixed_sek_per_kwh': trader_fixed,
            'trader_pct': trader_pct,
            'grid_monthly_fee_sek': grid_monthly_fee,
            'trader_monthly_fee_sek': trader_monthly_fee,
            'next_fuse_monthly_fee_sek': next_fuse_monthly_fee,
            'lower_fuse_monthly_fee_sek': lower_fuse_monthly_fee,
            'installed_kwp': installed_kwp,
            'self_energy_tax_sek_per_kwh': self_energy_tax,
            'self_grid_fee_sek_per_kwh': self_grid_fee,
            'self_quarter_price': self_quarter_price,
            'fuse_amps': fuse_amps,
        }

        return analysis
    
    @staticmethod
    def print_analysis(analysis: Dict[str, Any]):
        """Print analysis results in a formatted way."""
        print("\n" + "="*60)
        print("PRICE-PRODUCTION ANALYSIS RESULTS")
        print("="*60)
        
        print(f"\nPERIOD OVERVIEW:")
        print(f"  Period covered: {analysis['period_days']} days")
        print(f"  Total hours of data: {analysis['total_hours']}")
        
        print(f"\nPRICE STATISTICS (SEK/kWh):")
        print(f"  Min price: {analysis['price_min_sek_kwh']:.4f} SEK/kWh ({analysis['price_min_eur_mwh']:.2f} EUR/MWh)")
        print(f"  Max price: {analysis['price_max_sek_kwh']:.4f} SEK/kWh ({analysis['price_max_eur_mwh']:.2f} EUR/MWh)")
        print(f"  Mean price: {analysis['price_mean_sek_kwh']:.4f} SEK/kWh ({analysis['price_mean_eur_mwh']:.2f} EUR/MWh)")
        print(f"  Median price: {analysis['price_median_sek_kwh']:.4f} SEK/kWh ({analysis['price_median_eur_mwh']:.2f} EUR/MWh)")
        print(f"  Price volatility (std): {analysis['price_volatility_std']:.4f} SEK/kWh")
        print(f"  Price volatility (CV): {analysis['price_volatility_cv']:.2%}")
        
        print(f"\nPRODUCTION STATISTICS:")
        print(f"  Total production: {analysis['production_total']:.2f} kWh")
        print(f"  Average hourly production: {analysis['production_mean']:.3f} kWh")
        print(f"  Max hourly production: {analysis['production_max']:.3f} kWh")
        print(f"  Hours with production > 0: {analysis['hours_with_production']}")
        
        print(f"\nCORRELATION ANALYSIS:")
        print(f"  Price-Production correlation: {analysis['price_production_correlation']:.3f}")
        
        print(f"\nNEGATIVE PRICE ANALYSIS:")
        print(f"  Hours with negative prices: {analysis['negative_price_hours']}")
        if analysis['negative_price_hours'] > 0:
            print(f"  Production during negative prices: {analysis['production_during_negative_prices']:.2f} kWh")
            print(f"  Average production during negative prices: {analysis['avg_production_during_negative_prices']:.3f} kWh")
            print(f"  Lowest negative price: {analysis['min_negative_price_sek_per_kwh']:.4f} SEK/kWh")
            print(f"  Average negative price: {analysis['avg_negative_price_sek_per_kwh']:.4f} SEK/kWh")
            print(f"  COST of negative price exports: {analysis['negative_export_cost_abs_sek']:.2f} SEK")
        else:
            print(f"  No negative price periods found")
        
        print(f"\nEXPORT VALUE ANALYSIS:")
        print(f"  Total export value: {analysis['total_export_value_sek']:.2f} SEK")
        print(f"  Positive price export value: {analysis['positive_export_value_sek']:.2f} SEK")
        print(f"  Net export value (after negative costs): {analysis['total_export_value_sek']:.2f} SEK")
        
        print("\n" + "="*60)
    
    @staticmethod
    def get_daily_summary(merged_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate daily summary statistics.
        
        Args:
            merged_df (pd.DataFrame): Merged hourly data
            
        Returns:
            pd.DataFrame: Daily summary with aggregated metrics
        """
        daily_summary = merged_df.groupby(merged_df.index.date).agg({
            'production_kwh': ['sum', 'mean', 'max'],
            'price_eur_per_mwh': ['mean', 'min', 'max'],
            'price_sek_per_kwh': ['mean', 'min', 'max'],
            'export_value_sek': 'sum'
        }).round(3)
        
        # Flatten column names
        daily_summary.columns = ['_'.join(col).strip() for col in daily_summary.columns]
        
        return daily_summary
