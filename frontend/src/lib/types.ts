// Shared types for the in-browser electricity price / production analysis.
// Everything runs client-side so the tool can be served statically (GitHub Pages).

/** A single price interval. Times are local Europe/Stockholm wall-clock. */
export interface PriceInterval {
  /** Local wall-clock start (ms since epoch, treated as naive local time). */
  start: number;
  /** Local wall-clock end (exclusive). */
  end: number;
  /** Price in SEK per kWh. */
  sekPerKwh: number;
  /** Price in EUR per kWh (kept for reference). */
  eurPerKwh: number;
}

/** A single production interval read from the user's file. */
export interface ProductionInterval {
  /** Local wall-clock start (ms since epoch, treated as naive local time). */
  start: number;
  /** Local wall-clock end (exclusive). */
  end: number;
  /** Exported / produced energy in kWh during this interval. */
  kwh: number;
}

export type Granularity = "15min" | "hourly" | "daily" | "unknown";

export interface ParsedProduction {
  rows: ProductionInterval[];
  granularity: Granularity;
  /** Median interval length in minutes (used to detect granularity). */
  stepMinutes: number;
  /** % of consecutive intervals whose spacing equals the dominant step (data regularity). */
  stepConsistencyPct: number;
  datetimeColumn: string;
  productionColumn: string;
}

/** Result object shaped to match the existing <AnalysisResults> component. */
export interface AnalysisResult {
  hero: {
    produktion: {
      total_kwh: number;
      totala_intakter_sek: number;
      genomsnittspris_erhållet_sek_per_kwh: number;
      enkelt_snitt_pris_sek_per_kwh: number;
      timing_förlust_pct: number;
    };
    export_förluster: {
      /** Count of producing intervals (≈ quarters) where exporting cost you (price < 0). */
      intervaller_som_kostat_dig: number;
      kwh_exporterat_med_förlust: number;
      andel_olönsam_export_pct: number;
      kostnad_negativ_export_sek: number;
    };
    tidsanalys: {
      /** Nominal interval length in minutes (15 = quarters). */
      intervall_minuter: number;
      /** Count of all covered intervals (≈ quarters for 15-min data). */
      totala_intervaller: number;
      /** Count of producing intervals. */
      produktionsintervaller: number;
      /** Count of intervals where the spot price was negative across the range. */
      negativa_intervaller_totalt: number;
      /** Count of producing intervals where the spot price was negative. */
      negativa_intervaller: number;
    };
  };
  input: {
    date_range: { start: string; end: string };
    granularity: Granularity;
  };
  /** Per-interval (15-minute) producing series, for CSV/JSON export. */
  series: Array<{
    start: string;
    production_kwh: number;
    spot_sek_per_kwh: number;
    effektivt_pris_sek_per_kwh: number;
    varde_sek: number;
  }>;
  /**
   * SMHI STRÅNG solar context for the period (attached by the UI when a position is set):
   * total global horizontal irradiance and a rough potential PV production estimate.
   */
  solinstralning?: {
    kwh_per_m2: number;
    /** ≈ irradiation × kWp × 0.82; present only when installed kWp is given. */
    potentiell_produktion_kwh?: number;
    kwp?: number;
    from?: string;
    to?: string;
  };
  /** Echo of the settings used (display units), attached by the UI for export/display. */
  parametrar?: {
    elomrade?: string;
    huvudsakring_a?: string;
    moms_pct?: string;
    momsregistrerad?: boolean;
    elnat_fast_ore_per_kwh?: string;
    elnat_rorlig_pct?: string;
    elhandel_fast_ore_per_kwh?: string;
    elhandel_rorlig_pct?: string;
    elnat_manadsavgift_kr?: string;
    elnat_manadsavgift_nasta_sakring_kr?: string;
    elnat_manadsavgift_lagre_sakring_kr?: string;
    installerad_kwp?: string;
    elhandel_manadsavgift_kr?: string;
    energiskatt_ore_per_kwh?: string;
    natavgift_ore_per_kwh?: string;
    kvartspris_elhandel?: boolean;
  };
  aggregates: {
    monthly: Array<{
      period: string;
      production_kwh: number;
      revenue_sek: number;
      avg_price_sek_per_kwh: number;
      negative_intervaller: number;
      negative_kwh: number;
      negative_value_sek: number;
    }>;
    /** Per-day aggregation (higher-resolution chart). */
    daily: Array<{
      date: string;
      production_kwh: number;
      revenue_sek: number;
      negative_kwh: number;
      negative_value_sek: number;
      /** Mean spot over "exportable" (sunlit) hours that day, from SMHI STRÅNG (if available). */
      spot_sunlit_sek_per_kwh?: number;
    }>;
  };
  /**
   * Monthly forecast over months with full data coverage — "what to expect" per month:
   * effective export compensation minus the fixed monthly fees, plus averages.
   */
  manads_prognos?: {
    antal_manader: number;
    fullstandiga_manader: number;
    /**
     * True when at least one fixed monthly fee was supplied. When false the net-after-fees
     * fields below are omitted (an unfilled fee is "unknown", not 0 kr), and the forecast
     * reports production and effective compensation only.
     */
    har_fasta_avgifter: boolean;
    elnat_avgift_sek_per_man?: number;
    elhandel_avgift_sek_per_man?: number;
    fasta_avgifter_sek_per_man?: number;
    manader: Array<{
      period: string;
      /** True if the month had full data; false if scaled up from a partial month. */
      complete: boolean;
      dagar_med_data: number;
      dagar_i_manad: number;
      production_kwh: number;
      effektiv_ersattning_sek: number;
      fasta_avgifter_sek?: number;
      netto_sek?: number;
    }>;
    snitt_production_kwh: number;
    snitt_effektiv_ersattning_sek: number;
    snitt_netto_sek?: number;
  };
  /**
   * Effective export compensation: what you actually get paid for exported energy.
   * Model: (spot + förlustersättning[% av spot] + fast påslag/avdrag) × (1 + moms).
   * Present when any export-compensation setting (fixed / loss% / VAT) is given.
   */
  exportersattning?: {
    moms_pct: number;
    /** True if VAT was added to the export price (only when momsregistrerad). */
    moms_pa_forsaljning: boolean;
    spot_sek_per_kwh: number;
    /** Elnätsbolag (grid): fixed + variable (% of spot) förlustersättning. */
    elnat_fast_sek_per_kwh: number;
    elnat_pct: number;
    elnat_rorlig_sek_per_kwh: number;
    elnat_total_sek_per_kwh: number;
    /** Elhandelsbolag (trader): fixed + variable (% of spot) påslag/avdrag. */
    elhandel_fast_sek_per_kwh: number;
    elhandel_pct: number;
    elhandel_rorlig_sek_per_kwh: number;
    elhandel_total_sek_per_kwh: number;
    pris_innan_moms_sek_per_kwh: number;
    effektivt_pris_sek_per_kwh: number;
    /** Spot price (SEK/kWh) below which export becomes a loss, given the offsets. */
    brytpunkt_spot_sek_per_kwh: number;
    spot_total_sek: number;
    effektiv_total_sek: number;
    skillnad_mot_spot_sek: number;
  };
  /**
   * Self-consumption valuation: what a kWh is worth if you use it yourself instead of
   * exporting it. value_self = (spot + energiskatt + nätavgift) × (1 + moms); compared
   * to the effective export compensation. Present when energy tax / grid fee is given.
   */
  sjalvkonsumtion?: {
    moms_pct: number;
    /** True if valued at the per-quarter spot; false if at the period's average spot. */
    kvartpris: boolean;
    spot_sek_per_kwh: number;
    energiskatt_sek_per_kwh: number;
    natavgift_sek_per_kwh: number;
    varde_self_sek_per_kwh: number;
    export_varde_sek_per_kwh: number;
    okning_vs_export_sek_per_kwh: number;
    /** Per-month saving from self-consuming vs exporting, on the actual production. */
    manader: Array<{
      period: string;
      production_kwh: number;
      varde_self_sek_per_kwh: number;
      export_varde_sek_per_kwh: number;
      besparing_sek: number;
    }>;
    total_besparing_sek: number;
  };
  /**
   * Quarters exported "at a loss": the effective export price (after offsets + VAT) was
   * below zero, i.e. you paid to export. Present when any such interval exists.
   */
  forlust_export?: {
    /** Number of intervals (quarters) exported at a loss. */
    antal: number;
    /** Nominal interval length in minutes (15 = quarters). */
    intervall_minuter: number;
    /** Spot price (SEK/kWh) below which export becomes a loss, given the offsets. */
    troskel_spot_sek_per_kwh: number;
    total_kwh: number;
    total_forlust_sek: number;
    /** Worst occasions (up to 50), for the table. */
    poster: Array<{
      start: string;
      spot_sek_per_kwh: number;
      effektivt_pris_sek_per_kwh: number;
      kwh: number;
      forlust_sek: number;
    }>;
    /** Daily total loss (SEK), for the chart. */
    serie: Array<{ date: string; forlust_sek: number }>;
  };
  /** Grid-connection (main fuse) peak analysis. Only present when a fuse size is given. */
  natanslutning?: {
    sakring_amp: number;
    sakring_kw: number;
    hogsta_effekt_kw: number;
    /** Count of intervals (≈ quarters) at/above the fuse limit. */
    intervaller_vid_max: number;
    /** Share of *exportable* quarters spent at the cap (see andel_bas_soltimmar / namnare_kvartar). */
    andel_tid_vid_max_pct: number;
    /** True if the share is measured over STRÅNG sunlit quarters; false = over producing quarters. */
    andel_bas_soltimmar: boolean;
    /** Denominator used for the share (sunlit or producing quarters). */
    namnare_kvartar: number;
    energi_vid_max_kwh: number;
    /** Daily peak export power (kW), for charting against the fuse limit. */
    serie: Array<{ date: string; peak_kw: number }>;
  };
  /**
   * Fuse-upgrade analysis: is paying the higher grid subscription for the next fuse size up
   * worth the extra export it would unlock? Present when a fuse size and the next-step monthly
   * fee are both given. The unlocked-export figures are optimistic upper bounds (the energy is
   * produced at midday peaks when spot is lowest, so its marginal value is small).
   */
  sakringsuppgradering?: {
    nuvarande_sakring_amp: number;
    nuvarande_sakring_kw: number;
    nasta_sakring_amp: number;
    nasta_sakring_kw: number;
    nuvarande_avgift_kr_per_man: number;
    nasta_avgift_kr_per_man: number;
    extra_avgift_kr_per_man: number;
    extra_avgift_kr_per_ar: number;
    /** Extra fee over the loaded data period (the primary basis shown in the UI). */
    extra_avgift_over_period_sek: number;
    /** Sustained clipped quarters (≥2 consecutive at the cap) the estimate is based on. */
    kvartar_vid_max: number;
    /** Installed PV capacity (kWp) if given — bounds the estimate. */
    installerad_kwp?: number;
    /** True if installed kWp is below the next fuse limit (panels, not fuse, are the cap). */
    begransas_av_kwp?: boolean;
    period_dagar: number;
    uppskattad_extra_export_kwh: number;
    uppskattat_extra_varde_sek: number;
    uppskattad_extra_export_kwh_per_ar: number;
    uppskattat_extra_varde_per_ar_sek: number;
    /** Unlocked export value minus the extra fee, over the loaded period (primary). */
    netto_over_period_sek: number;
    /** Same, annualized (≈, secondary). */
    netto_per_ar_sek: number;
    vart_att_uppgradera: boolean;
  };
  /**
   * Fuse-downgrade analysis: would a SMALLER fuse pay off? Weighs the annual subscription
   * saving against the export it would clip (power above the lower limit). Concrete (from the
   * actual production), not a best-case estimate. Present when a fuse size and the lower-step
   * monthly fee are both given.
   */
  sakringsnedgradering?: {
    nuvarande_sakring_amp: number;
    nuvarande_sakring_kw: number;
    lagre_sakring_amp: number;
    lagre_sakring_kw: number;
    nuvarande_avgift_kr_per_man: number;
    lagre_avgift_kr_per_man: number;
    sparad_avgift_kr_per_man: number;
    sparad_avgift_kr_per_ar: number;
    /** Subscription saving over the loaded data period (the primary basis shown in the UI). */
    sparad_avgift_over_period_sek: number;
    /** Producing quarters whose average power exceeds the lower fuse limit (would be clipped). */
    kvartar_over_lagre_tak: number;
    period_dagar: number;
    kapad_export_kwh: number;
    kapat_varde_sek: number;
    kapad_export_kwh_per_ar: number;
    kapat_varde_per_ar_sek: number;
    /** Subscription saving over the period minus the clipped export value (primary). */
    netto_over_period_sek: number;
    /** Same, annualized (≈, secondary). */
    netto_per_ar_sek: number;
    vart_att_sanka: boolean;
  };
  meta: {
    price_granularity: Granularity;
    price_intervals: number;
    production_intervals: number;
    matched_kwh_pct: number;
  };
}
