"""Tests for interval-aware (15-minute / hourly / daily) price-production analysis.

These lock in the behaviour added when the Swedish market moved to 15-minute
resolution: production and prices may have different cadences, and "hours" metrics
must reflect real durations rather than row counts.
"""

import pandas as pd
import pytest

from core.intervals import (assess_resolution, combine_production,
                            filter_production_direction, granularity_from_hours,
                            infer_step_hours, interval_hours_series,
                            step_consistency_pct)
from core.price_analyzer import PriceAnalyzer, next_fuse_step, prev_fuse_step


def test_infer_step_hours_hourly_and_quarterly():
    hourly = pd.date_range("2025-01-01", periods=10, freq="h")
    quarterly = pd.date_range("2025-01-01", periods=10, freq="15min")
    assert infer_step_hours(hourly) == pytest.approx(1.0)
    assert infer_step_hours(quarterly) == pytest.approx(0.25)
    assert infer_step_hours(hourly[:1]) == pytest.approx(1.0)  # single row -> default


def test_interval_hours_series_sums_to_span():
    idx = pd.date_range("2025-01-01", periods=4, freq="15min")
    hours = interval_hours_series(idx)
    assert hours.sum() == pytest.approx(1.0)  # 4 x 15 min == 1 hour


def test_hourly_x_hourly_matches_simple_multiplication():
    idx = pd.date_range("2025-01-01 00:00", periods=2, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, -50.0]}, index=idx)
    production = pd.DataFrame({"production_kwh": [2.0, 3.0]}, index=idx)

    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)
    a = PriceAnalyzer.analyze_data(merged)

    # sek/kwh = eur_mwh * 10 / 1000 -> [1.0, -0.5]
    assert a["total_hours"] == pytest.approx(2.0)
    assert a["production_total"] == pytest.approx(5.0)
    assert a["total_export_value_sek"] == pytest.approx(2 * 1.0 + 3 * -0.5)  # 0.5
    assert a["negative_price_hours"] == pytest.approx(1.0)
    assert a["hours_with_production"] == pytest.approx(2.0)
    assert a["negative_export_cost_abs_sek"] == pytest.approx(1.5)
    assert a["producing_intervals"] == 2
    assert a["negative_producing_intervals"] == 1  # the negative-price hour produces


def test_hourly_production_x_15min_prices_surfaces_negative_quarter():
    # Hourly production, but prices at 15-minute resolution with one negative quarter.
    prod_idx = pd.date_range("2025-11-03 00:00", periods=2, freq="h")
    production = pd.DataFrame({"production_kwh": [4.0, 8.0]}, index=prod_idx)

    price_idx = pd.date_range("2025-11-03 00:00", periods=8, freq="15min")
    # First hour has a negative third quarter; second hour all positive.
    eur = [100, 100, -200, 100, 100, 100, 100, 100]
    prices = pd.DataFrame({"price_eur_per_mwh": [float(x) for x in eur]}, index=price_idx)

    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)
    a = PriceAnalyzer.analyze_data(merged)

    # Production is split evenly across the 4 quarters of each hour: [1,1,1,1, 2,2,2,2].
    assert a["production_total"] == pytest.approx(12.0)
    assert a["total_hours"] == pytest.approx(2.0)
    # Revenue: 1*1 + 1*1 + 1*(-2) + 1*1 + 2*1*4 = 1 + 8 = 9
    assert a["total_export_value_sek"] == pytest.approx(9.0)
    # Exactly one negative 15-min quarter, carrying 1 kWh.
    assert a["negative_price_hours"] == pytest.approx(0.25)
    assert a["production_during_negative_prices"] == pytest.approx(1.0)
    assert a["negative_export_cost_abs_sek"] == pytest.approx(2.0)


def test_15min_production_x_hourly_prices_no_row_loss():
    # 15-minute production, hourly prices (older dates). No production interval dropped.
    prod_idx = pd.date_range("2024-06-01 00:00", periods=8, freq="15min")
    production = pd.DataFrame({"production_kwh": [1.0] * 8}, index=prod_idx)

    price_idx = pd.date_range("2024-06-01 00:00", periods=2, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, -100.0]}, index=price_idx)

    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)
    a = PriceAnalyzer.analyze_data(merged)

    assert len(merged) == 8  # all 15-min production rows kept
    assert a["total_hours"] == pytest.approx(2.0)
    assert a["production_total"] == pytest.approx(8.0)
    # First hour price +1 sek/kwh (4 kWh), second hour -1 sek/kwh (4 kWh) -> 0 net
    assert a["total_export_value_sek"] == pytest.approx(0.0)
    assert a["negative_price_hours"] == pytest.approx(1.0)  # second hour
    assert a["production_during_negative_prices"] == pytest.approx(4.0)


def test_fuse_flat_peak_analysis():
    # Hour 1: 12 kWh -> 12 kW (above 16 A limit ~11.1 kW). Hour 2: 5 kWh -> below.
    idx = pd.date_range("2025-07-01 12:00", periods=2, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, 100.0]}, index=idx)
    production = pd.DataFrame({"production_kwh": [12.0, 5.0]}, index=idx)

    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)
    a = PriceAnalyzer.analyze_data(merged, fuse_amps=16)

    gc = a["grid_connection"]
    assert gc["fuse_limit_kw"] == pytest.approx((3 ** 0.5) * 400 * 16 / 1000, abs=0.01)  # ~11.08
    assert gc["peak_power_kw"] == pytest.approx(12.0)
    assert gc["hours_at_max"] == pytest.approx(1.0)
    assert gc["peaks"] == 1
    assert gc["share_time_at_max_pct"] == pytest.approx(50.0)


def test_no_fuse_means_no_grid_connection_block():
    idx = pd.date_range("2025-07-01", periods=2, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, 100.0]}, index=idx)
    production = pd.DataFrame({"production_kwh": [1.0, 1.0]}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production)
    assert "grid_connection" not in PriceAnalyzer.analyze_data(merged)


def test_next_fuse_step():
    assert next_fuse_step(16) == 20
    assert next_fuse_step(20) == 25
    assert next_fuse_step(63) == 80
    assert next_fuse_step(250) is None


def test_prev_fuse_step():
    assert prev_fuse_step(20) == 16
    assert prev_fuse_step(25) == 20
    assert prev_fuse_step(16) is None


def test_fuse_downgrade_clips_peaks():
    # Current 20 A (~13.86 kW), lower 16 A (~11.08 kW). Hour 1 at 13 kW (clipped), hour 2 at 5.
    idx = pd.date_range("2025-07-01 12:00", periods=2, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, 100.0]}, index=idx)  # 1.0 SEK/kWh @ rate 10
    production = pd.DataFrame({"production_kwh": [13.0, 5.0]}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)
    lower_kw = (3 ** 0.5) * 400 * 16 / 1000

    d = PriceAnalyzer.analyze_data(
        merged, fuse_amps=20, vat_rate=0, grid_monthly_fee=250, lower_fuse_monthly_fee=150
    )["fuse_downgrade"]
    assert d["lower_fuse_amp"] == 16
    assert d["saved_fee_sek_per_month"] == pytest.approx(100.0)
    assert d["saved_fee_sek_per_year"] == pytest.approx(1200.0)
    assert d["intervals_over_lower_limit"] == 1
    assert d["clipped_export_kwh"] == pytest.approx(13 - lower_kw, abs=0.05)
    assert d["clipped_value_sek"] == pytest.approx((13 - lower_kw) * 1.0, abs=0.05)
    # Over-period netto = period saving − period clipped value (the primary basis).
    assert d["net_over_period_sek"] == pytest.approx(d["saved_fee_over_period_sek"] - d["clipped_value_sek"], abs=0.02)
    assert isinstance(d["worth_downgrading"], bool)

    assert "fuse_downgrade" not in PriceAnalyzer.analyze_data(merged, fuse_amps=20)


def test_share_at_max_uses_producing_time():
    # 4 hourly rows; only 2 produce. Hour 1 = 12 kWh (>16A ~11.08), hour 2 = 5, then two zeros.
    idx = pd.date_range("2025-07-01 12:00", periods=4, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0] * 4}, index=idx)
    production = pd.DataFrame({"production_kwh": [12.0, 5.0, 0.0, 0.0]}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)
    gc = PriceAnalyzer.analyze_data(merged, fuse_amps=16)["grid_connection"]
    # 1 h at max over 2 producing hours -> 50% (not 25% over all 4 h).
    assert gc["share_basis"] == "producing"
    assert gc["share_time_at_max_pct"] == pytest.approx(50.0)


def test_fuse_upgrade_sustained_and_kwp_bound():
    # 8 consecutive quarters at the 16 A cap (~11.08 kW), priced positively. Next step = 20 A.
    idx = pd.date_range("2025-07-01 11:00", periods=8, freq="15min")
    cap_kw = (3 ** 0.5) * 400 * 16 / 1000
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0] * 8}, index=idx)  # -> 1.0 SEK/kWh @ rate 10
    production = pd.DataFrame({"production_kwh": [cap_kw * 0.25] * 8}, index=idx)  # power == cap
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)

    u = PriceAnalyzer.analyze_data(
        merged, fuse_amps=16, vat_rate=0, grid_monthly_fee=200, next_fuse_monthly_fee=275
    )["fuse_upgrade"]
    assert u["next_fuse_amp"] == 20
    assert u["sustained_clip_intervals"] == 8
    assert u["extra_fee_sek_per_month"] == pytest.approx(75.0)
    assert u["extra_fee_sek_per_year"] == pytest.approx(900.0)
    assert u["estimated_extra_value_sek"] > 0
    assert u["estimated_extra_value_per_year_sek"] > u["estimated_extra_value_sek"]  # annualized up

    # Installed kWp just above the current cap shrinks the headroom drastically and flags it.
    u2 = PriceAnalyzer.analyze_data(
        merged, fuse_amps=16, vat_rate=0, grid_monthly_fee=200, next_fuse_monthly_fee=275, installed_kwp=11.2
    )["fuse_upgrade"]
    assert u2["limited_by_kwp"] is True
    assert u2["estimated_extra_value_sek"] < u["estimated_extra_value_sek"]


def test_fuse_upgrade_isolated_peaks_dont_count():
    # Alternating cap / near-zero quarters -> never two at the cap in a row.
    idx = pd.date_range("2025-07-01 11:00", periods=8, freq="15min")
    cap_kw = (3 ** 0.5) * 400 * 16 / 1000
    prod = [cap_kw * 0.25 if i % 2 == 0 else 0.001 for i in range(8)]
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0] * 8}, index=idx)
    production = pd.DataFrame({"production_kwh": prod}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)
    u = PriceAnalyzer.analyze_data(
        merged, fuse_amps=16, vat_rate=0, grid_monthly_fee=200, next_fuse_monthly_fee=275
    )["fuse_upgrade"]
    assert u["sustained_clip_intervals"] == 0
    assert u["estimated_extra_value_sek"] == pytest.approx(0.0)


def test_no_next_fuse_fee_means_no_upgrade_block():
    idx = pd.date_range("2025-07-01", periods=2, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, 100.0]}, index=idx)
    production = pd.DataFrame({"production_kwh": [1.0, 1.0]}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production)
    assert "fuse_upgrade" not in PriceAnalyzer.analyze_data(merged, fuse_amps=16)


def test_combine_production_dedup_and_sort():
    a = pd.DataFrame(
        {"production_kwh": [1.0, 2.0]},
        index=pd.date_range("2025-01-01 00:00", periods=2, freq="15min"),
    )
    # Second chunk repeats the last row of the first (overlapping boundary), then continues.
    b = pd.DataFrame(
        {"production_kwh": [2.0, 3.0]},
        index=pd.date_range("2025-01-01 00:15", periods=2, freq="15min"),
    )
    combined, info = combine_production([b, a])  # passed out of order on purpose
    assert info["files_combined"] == 2
    assert info["duplicates_removed"] == 1
    assert info["granularities_match"] is True
    assert list(combined["production_kwh"]) == [1.0, 2.0, 3.0]
    assert combined.index.is_monotonic_increasing

    single, info1 = combine_production([a])
    assert info1["files_combined"] == 1 and info1["duplicates_removed"] == 0


def test_export_compensation_and_self_consumption():
    # spot [1.0, 2.0] SEK/kWh (eur_mwh [100,200] * 10/1000), production [2, 2] kWh.
    idx = pd.date_range("2025-01-01 00:00", periods=2, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, 200.0]}, index=idx)
    production = pd.DataFrame({"production_kwh": [2.0, 2.0]}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)

    # elnät: 5 öre fast + 10% rörlig ; elhandel: 10 öre fast + 0% rörlig
    a = PriceAnalyzer.analyze_data(
        merged,
        vat_rate=25,
        vat_registered=True,
        grid_fixed=0.05,
        grid_pct=10,
        trader_fixed=0.1,
        trader_pct=0,
        self_energy_tax=0.4,
        self_grid_fee=0.6,
    )

    # realized spot = (2*1 + 2*2)/4 = 1.5
    e = a["export_compensation"]
    assert e["spot_sek_per_kwh"] == pytest.approx(1.5)
    assert e["elnat_variable_sek_per_kwh"] == pytest.approx(0.15)  # 10% of 1.5
    assert e["elnat_total_sek_per_kwh"] == pytest.approx(0.20)  # 0.05 + 0.15
    assert e["elhandel_total_sek_per_kwh"] == pytest.approx(0.10)  # 0.10 fast
    assert e["price_before_vat_sek_per_kwh"] == pytest.approx(1.80)
    assert e["effective_price_sek_per_kwh"] == pytest.approx(2.25)  # * 1.25
    assert e["spot_total_sek"] == pytest.approx(6.0)
    assert e["effective_total_sek"] == pytest.approx(9.0)
    assert e["uplift_vs_spot_sek"] == pytest.approx(3.0)

    s = a["self_consumption"]
    assert s["value_self_sek_per_kwh"] == pytest.approx(3.125)  # (1.5+0.4+0.6)*1.25
    assert s["export_value_sek_per_kwh"] == pytest.approx(2.25)
    assert s["increment_vs_export_sek_per_kwh"] == pytest.approx(0.875)


def test_vat_is_asymmetric_sales_vs_buy():
    # Sales VAT only when momsregistrerad; the buy (self-consumption) side always has VAT.
    idx = pd.date_range("2025-11-03 00:00", periods=1, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0]}, index=idx)  # -> 1.0 SEK/kWh @ rate 10
    production = pd.DataFrame({"production_kwh": [4.0]}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)
    kw = dict(vat_rate=25, grid_fixed=0.1, self_energy_tax=0.4, self_grid_fee=0.6)

    not_reg = PriceAnalyzer.analyze_data(merged, **kw)
    assert not_reg["export_compensation"]["vat_on_sales"] is False
    assert not_reg["export_compensation"]["effective_price_sek_per_kwh"] == pytest.approx(1.1)  # ex-moms
    assert not_reg["self_consumption"]["value_self_sek_per_kwh"] == pytest.approx(2.5)  # buy side WITH moms
    assert not_reg["self_consumption"]["export_value_sek_per_kwh"] == pytest.approx(1.1)
    assert not_reg["self_consumption"]["increment_vs_export_sek_per_kwh"] == pytest.approx(1.4)

    reg = PriceAnalyzer.analyze_data(merged, vat_registered=True, **kw)
    assert reg["export_compensation"]["vat_on_sales"] is True
    assert reg["export_compensation"]["effective_price_sek_per_kwh"] == pytest.approx(1.375)  # 1.1*1.25
    assert reg["self_consumption"]["value_self_sek_per_kwh"] == pytest.approx(2.5)  # unchanged
    assert reg["self_consumption"]["export_value_sek_per_kwh"] == pytest.approx(1.375)


def test_self_consumption_quarter_price_toggle():
    # More production in the cheap hour: realized=1.5, average=2.0 SEK/kWh.
    idx = pd.date_range("2025-11-03 00:00", periods=2, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, 300.0]}, index=idx)  # 1.0, 3.0 SEK/kWh
    production = pd.DataFrame({"production_kwh": [3.0, 1.0]}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)

    on = PriceAnalyzer.analyze_data(
        merged, vat_rate=25, vat_registered=True, self_energy_tax=0.4, self_grid_fee=0.6, self_quarter_price=True
    )["self_consumption"]
    assert on["quarter_price"] is True
    assert on["spot_sek_per_kwh"] == pytest.approx(1.5)  # realized
    assert on["value_self_sek_per_kwh"] == pytest.approx(3.125)
    assert len(on["months"]) == 1
    assert on["total_saving_sek"] == pytest.approx(5.0)  # 4 kWh × (3.125 − 1.875)

    off = PriceAnalyzer.analyze_data(
        merged, vat_rate=25, vat_registered=True, self_energy_tax=0.4, self_grid_fee=0.6, self_quarter_price=False
    )["self_consumption"]
    assert off["quarter_price"] is False
    assert off["spot_sek_per_kwh"] == pytest.approx(2.0)  # period average
    assert off["value_self_sek_per_kwh"] == pytest.approx(3.75)
    assert off["export_value_sek_per_kwh"] == pytest.approx(1.875)  # export realized at 1.5
    assert off["total_saving_sek"] == pytest.approx(7.5)  # 4 kWh × (3.75 − 1.875)


def test_export_at_loss_quarters():
    # 15-min prices [1.0, -0.5, 0.05, 1.0] SEK/kWh (eur_mwh /100 * 10), 1 kWh each quarter.
    idx = pd.date_range("2025-11-03 00:00", periods=4, freq="15min")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, -50.0, 5.0, 100.0]}, index=idx)
    production = pd.DataFrame({"production_kwh": [1.0, 1.0, 1.0, 1.0]}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)

    # 10 öre avdrag from the trader -> effective = spot - 0.10 ; break-even spot = 0.10.
    a = PriceAnalyzer.analyze_data(merged, trader_fixed=-0.1)
    f = a["export_at_loss"]
    assert f["count"] == 2  # q2 (-0.5) and q3 (0.05) fall below break-even
    assert f["break_even_spot_sek_per_kwh"] == pytest.approx(0.10)
    assert f["total_kwh"] == pytest.approx(2.0)
    assert f["total_loss_sek"] == pytest.approx(0.65)  # 0.60 + 0.05
    assert f["interval_minutes"] == pytest.approx(15.0)
    assert len(f["rows"]) == 2
    assert f["rows"][0]["loss_sek"] == pytest.approx(0.60)  # worst first


def test_monthly_forecast_full_months():
    # Continuous hourly data covering all of Nov + Dec 2025 (both full months).
    idx = pd.date_range("2025-11-01 00:00", "2025-12-31 23:00", freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0] * len(idx)}, index=idx)  # 1.0 SEK/kWh
    production = pd.DataFrame({"production_kwh": [1.0] * len(idx)}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)

    a = PriceAnalyzer.analyze_data(merged, vat_rate=25, vat_registered=True, grid_monthly_fee=100, trader_monthly_fee=20)
    f = a["monthly_forecast"]
    assert f["full_months"] == 2
    assert f["fixed_monthly_sek"] == pytest.approx(120.0)
    # Nov 720 kWh -> rev 720 -> eff 900 ; Dec 744 -> rev 744 -> eff 930
    assert f["avg_production_kwh"] == pytest.approx(732.0)
    assert f["avg_effective_sek"] == pytest.approx(915.0)
    assert f["avg_net_sek"] == pytest.approx(795.0)  # (780 + 810) / 2


def test_monthly_forecast_normalizes_partial_month():
    # First 15 of April's 30 days -> scaled up x2 to a full month.
    idx = pd.date_range("2025-04-01 00:00", periods=15 * 24, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0] * len(idx)}, index=idx)  # 1.0 SEK/kWh
    production = pd.DataFrame({"production_kwh": [1.0] * len(idx)}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)

    f = PriceAnalyzer.analyze_data(merged, grid_monthly_fee=100)["monthly_forecast"]
    assert f["months_count"] == 1
    assert f["full_months"] == 0
    m = f["months"][0]
    assert m["complete"] is False
    assert m["days_with_data"] == pytest.approx(15.0, abs=0.2)
    assert m["days_in_month"] == 30
    assert m["production_kwh"] == pytest.approx(720.0)  # 360 * 2
    assert m["net_sek"] == pytest.approx(620.0)  # 720 - 100 fixed


def test_valuation_blocks_omitted_without_inputs():
    idx = pd.date_range("2025-01-01 00:00", periods=2, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0, 200.0]}, index=idx)
    production = pd.DataFrame({"production_kwh": [2.0, 2.0]}, index=idx)
    merged = PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)
    a = PriceAnalyzer.analyze_data(merged)  # no valuation inputs
    assert "export_compensation" not in a
    assert "self_consumption" not in a


def test_granularity_from_hours():
    assert granularity_from_hours(0.25) == "15min"
    assert granularity_from_hours(1.0) == "hourly"
    assert granularity_from_hours(24.0) == "daily"
    assert granularity_from_hours(0) == "unknown"


def test_assess_resolution_accepts_quarter_hour():
    idx = pd.date_range("2026-05-01", periods=12, freq="15min")
    assert step_consistency_pct(idx) == pytest.approx(100.0)
    a = assess_resolution(idx)
    assert a.granularity == "15min"
    assert a.step_minutes == pytest.approx(15.0)
    assert a.is_quarter_hour is True
    assert a.level == "ok"


def test_assess_resolution_flags_hourly_data():
    idx = pd.date_range("2026-05-01", periods=6, freq="h")
    a = assess_resolution(idx)
    assert a.granularity == "hourly"
    assert a.is_quarter_hour is False
    assert a.level == "warning"
    assert "15-minute" in a.message


def test_db_has_data_for_period_is_resolution_aware(tmp_path):
    from core.db_manager import PriceDatabaseManager

    db = PriceDatabaseManager(str(tmp_path / "p.db"))
    idx = pd.date_range("2025-11-01 00:00", periods=96, freq="15min")  # one full day
    df = pd.DataFrame({"price_eur_per_mwh": [10.0] * 96}, index=idx)
    db.store_price_data(df, "SE3")

    start = pd.Timestamp("2025-11-01 00:00")
    end = pd.Timestamp("2025-11-01 23:45")
    # 96 quarter-hour points cover the day; the hourly-only heuristic would also pass,
    # but this confirms 15-min density is accepted as complete.
    assert db.has_data_for_period("SE3", start, end) is True


# --- E.ON "Mätvärdesexport" format + optional fixed monthly fees -------------------


EON_CSV = """\ufeffAnläggnings-id;Tidpunkt för export;Energiprodukt;Starttidpunkt;Sluttidpunkt;Måttenhet
735999114013307011;2026-07-30 12:57:06;Aktiv energi;2025-10-01 00:00:00;2025-10-01 01:00:00;kWh

Starttidpunkt;Sluttidpunkt;Energiriktning;Kvalitet;Kvantitet
2025-10-01 00:00:00;2025-10-01 00:15:00;Produktion;Uppmätt;0,100
2025-10-01 00:15:00;2025-10-01 00:30:00;Produktion;Uppmätt;0,200
2025-10-01 00:30:00;2025-10-01 00:45:00;Produktion;Uppmätt;0,300
2025-10-01 00:45:00;2025-10-01 01:00:00;Produktion;Uppmätt;0,400
"""


def test_eon_export_skips_metadata_preamble(tmp_path):
    """E.ON prefixes the table with a metadata block; the real header is further down."""
    from utils.csv_format_detector_fallback import CSVFormatDetectorFallback

    path = tmp_path / "Mätvärdesexport.CSV"
    path.write_text(EON_CSV, encoding="utf-8")

    df = CSVFormatDetectorFallback().read(str(path))
    assert list(df.columns) == [
        "Starttidpunkt",
        "Sluttidpunkt",
        "Energiriktning",
        "Kvalitet",
        "Kvantitet",
    ]
    assert len(df) == 4
    assert df["Kvantitet"].sum() == pytest.approx(1.0)


def test_ordinary_csv_header_row_unaffected(tmp_path):
    """A normal single-header file must still be read from line 1."""
    from utils.csv_format_detector_fallback import CSVFormatDetectorFallback

    path = tmp_path / "plain.csv"
    path.write_text(
        "Datum;Produktion kWh\n2025-10-01 00:00;1,5\n2025-10-01 01:00;2,5\n", encoding="utf-8"
    )
    df = CSVFormatDetectorFallback().read(str(path))
    assert list(df.columns) == ["Datum", "Produktion kWh"]
    assert len(df) == 2


def test_energiriktning_filters_out_consumption_rows():
    """A mixed export must not sum Förbrukning into production."""
    df = pd.DataFrame(
        {
            "Starttidpunkt": ["2025-10-01 00:00", "2025-10-01 00:00", "2025-10-01 00:15"],
            "Energiriktning": ["Produktion", "Förbrukning", "Produktion"],
            "Kvantitet": [1.0, 9.0, 2.0],
        }
    )
    out = filter_production_direction(df)
    assert len(out) == 2
    assert out["Kvantitet"].sum() == pytest.approx(3.0)

    # No direction column -> untouched.
    plain = pd.DataFrame({"Datum": ["2025-10-01 00:00"], "kWh": [1.0]})
    assert len(filter_production_direction(plain)) == 1


def _one_month_merged():
    idx = pd.date_range("2025-10-01 00:00", periods=24 * 31, freq="h")
    prices = pd.DataFrame({"price_eur_per_mwh": [100.0] * len(idx)}, index=idx)
    production = pd.DataFrame({"production_kwh": [1.0] * len(idx)}, index=idx)
    return PriceAnalyzer.merge_data(prices, production, eur_sek_rate=10.0)


def test_monthly_forecast_omits_net_without_fixed_fees():
    """An unfilled monthly fee means 'unknown', not 0 kr — so no net is reported."""
    merged = _one_month_merged()
    a = PriceAnalyzer.analyze_data(merged, fuse_amps=20, next_fuse_monthly_fee=500,
                                   lower_fuse_monthly_fee=300)
    f = a["monthly_forecast"]
    assert f["has_fixed_fees"] is False
    assert f["avg_net_sek"] is None
    assert f["fixed_monthly_sek"] is None
    assert f["months"][0]["net_sek"] is None
    # Production and compensation are still known, so they are still reported.
    assert f["avg_production_kwh"] > 0
    assert f["avg_effective_sek"] > 0
    # Both fuse verdicts compare against the current fee, so they need it.
    assert "fuse_upgrade" not in a
    assert "fuse_downgrade" not in a


def test_monthly_forecast_reports_net_with_fixed_fees():
    merged = _one_month_merged()
    a = PriceAnalyzer.analyze_data(merged, fuse_amps=20, grid_monthly_fee=400,
                                   next_fuse_monthly_fee=500, lower_fuse_monthly_fee=300)
    f = a["monthly_forecast"]
    assert f["has_fixed_fees"] is True
    assert f["fixed_monthly_sek"] == pytest.approx(400)
    assert f["avg_net_sek"] is not None
    assert a["fuse_upgrade"]["extra_fee_sek_per_month"] == pytest.approx(100)
    assert a["fuse_downgrade"]["saved_fee_sek_per_month"] == pytest.approx(100)

    # Trader fee alone is enough to report a net.
    only_trader = PriceAnalyzer.analyze_data(merged, trader_monthly_fee=59)["monthly_forecast"]
    assert only_trader["has_fixed_fees"] is True
    assert only_trader["fixed_monthly_sek"] == pytest.approx(59)
    assert only_trader["grid_monthly_fee_sek"] is None
