import os
import logging
import json
import time
from typing import Any, Dict, Optional
from dotenv import load_dotenv
import requests

logger = logging.getLogger(__name__)

class AIExplainer:
    """Generate Swedish explanation using direct HTTP (requests) instead of OpenAI SDK."""

    def __init__(self):
        if not os.getenv('OPENAI_API_KEY'):
            try:
                load_dotenv()
            except Exception:
                pass
        override = os.getenv('OPENAI_MODEL')
        self.model = override if override else 'gpt-5-mini'
        self.base_url = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')

    def explain_storytelling(self, payload: Dict[str, Any]) -> str:
        if not os.getenv('OPENAI_API_KEY'):
            return "AI-förklaring kräver OPENAI_API_KEY."

        hero = payload.get('hero', {}) or {}
        counterfactuals = hero.get('counterfactuals') or {}
        # Focus only on export optimization, no battery calculations

        # --- Extract metrics with focus on pain points ---
        # Traditional metrics
        prod = float(hero.get('production_kwh') or 0)
        rev = float(hero.get('revenue_sek') or 0)
        neg_val = float(hero.get('negative_value_sek') or 0)
        neg_share = float(hero.get('share_non_positive_during_production_pct') or 0)
        timing_disc = float(hero.get('timing_discount_pct') or 0)
        delta_if_floor = float(counterfactuals.get('delta_sek') or 0)
        lost_energy_at_floor0 = counterfactuals.get('lost_energy_kwh_at_floor_0')
        
        # NEW: Extract Swedish pain-focused metrics
        export_förluster = hero.get('export_förluster', {})
        zap_lösning = hero.get('zap_lösning', {})
        timmar_kostat = export_förluster.get('timmar_som_kostat_dig', 0)
        kwh_förlust = export_förluster.get('kwh_exporterat_med_förlust', 0)
        procent_olönsam = export_förluster.get('andel_olönsam_export_pct', 0)
        kostnad_export = export_förluster.get('kostnad_negativ_export_sek', 0)
        zap_besparing = zap_lösning.get('besparing_per_år_sek', 0)
        zap_månader = zap_lösning.get('återbetalningstid', {}).get('månader', 0)

        # Prioritize emotional impact facts
        facts: Dict[str, Any] = {
            'produktion_kwh': round(prod, 1),
            'intakter_sek': round(rev, 0),
        }
        
        # LEAD WITH PAIN POINTS - updated for export focus
        if timmar_kostat > 0:
            facts['timmar_som_kostat_dig'] = int(timmar_kostat)
        if kwh_förlust > 0:
            facts['kwh_exporterat_med_förlust'] = round(kwh_förlust, 1)
        if procent_olönsam > 0:
            facts['andel_olönsam_export_pct'] = round(procent_olönsam, 1)
        if kostnad_export > 0:
            facts['kostnad_negativ_export_sek'] = round(kostnad_export, 0)
        
        # ZAP SOLUTION FACTS - Focus on export optimization
        zap_export = zap_lösning.get('export_under_negativa_priser', {})
        if zap_export.get('timmar', 0) > 0:
            facts['zap_negativa_timmar'] = zap_export.get('timmar', 0)
        if zap_export.get('kwh', 0) > 0:
            facts['zap_export_optimerad_kwh'] = round(zap_export.get('kwh', 0), 1)
        if zap_export.get('dagar_drabbade', 0) > 0:
            facts['zap_dagar_drabbade'] = zap_export.get('dagar_drabbade', 0)
            
        # Traditional metrics (lower priority)
        if neg_share > 0:
            facts['andel_neg_timmar_pct'] = round(neg_share, 1)
        if timing_disc != 0:
            facts['timing_rabatt_pct'] = round(timing_disc, 1)
        if lost_energy_at_floor0:
            facts['energi_vid_golv0_kwh'] = round(float(lost_energy_at_floor0), 1)

        bullet_line = self._facts_to_bullet_line(facts)
        prompt = self._build_prompt(bullet_line, facts)

        # --- Attempt with retries (handles transient timeouts/connection resets) ---
        max_attempts = 2
        backoff = 2.0
        last_error: Optional[str] = None
        for attempt in range(1, max_attempts + 1):
            try:
                ai_text = self._call_openai(prompt)
                if ai_text:
                    return ai_text.strip()
                last_error = 'tomt AI-svar'
            except Exception as e:
                msg = str(e)
                last_error = msg
                # If timeout, shorten prompt and retry quickly
                if 'Read timed out' in msg or 'Timeout' in msg:
                    prompt = self._short_prompt(bullet_line)
                else:
                    # For auth/model/quota errors, break early
                    if any(k in msg for k in ('401', 'auth', 'quota', 'model_not_found', '429')):
                        break
            if attempt < max_attempts:
                time.sleep(backoff)
        # Fallback
        reason = (last_error or 'okänt')[:80]
        mapped = self._map_reason(reason)
        return self._manual_fallback(facts, reason=mapped)

    # ---------------- Internal helpers ----------------
    def _facts_to_bullet_line(self, facts: Dict[str, Any]) -> str:
        def fmt(v):
            if isinstance(v, int):
                return f"{v:,}".replace(',', ' ')
            if isinstance(v, float):
                sval = f"{v:.2f}".rstrip('0').rstrip('.')
                return sval.replace('.', ',')
            return str(v)
        
        # Make totals absolutely clear and never say zero if there are problems
        prod_val = facts.get('produktion_kwh', 0)
        rev_val = facts.get('intakter_sek', 0) 
        
        # Only show totals if they make sense with the negative data
        if prod_val > 0 and 'timmar_som_kostat_dig' in facts:
            bits = [f"Årsproduktion {fmt(prod_val)} kWh", f"totala intäkter {fmt(rev_val)} SEK"]
        else:
            bits = [f"Anläggning med produktion och intäkter enligt data"]
        
        # EXPORT FOCUS - clearly mark these as export-specific
        if 'timmar_som_kostat_dig' in facts:
            bits.append(f"{fmt(facts['timmar_som_kostat_dig'])} timmar då export kostade pengar")
        if 'kwh_exporterat_med_förlust' in facts:
            bits.append(f"{fmt(facts['kwh_exporterat_med_förlust'])} kWh exporterat vid negativa priser")
        if 'andel_olönsam_export_pct' in facts:
            bits.append(f"{fmt(facts['andel_olönsam_export_pct'])}% av exporten var olönsam")
            
        # OPTIMIZATION POTENTIAL
        if 'zap_negativa_timmar' in facts:
            bits.append(f"Exportstyrning kan optimera {fmt(facts['zap_negativa_timmar'])} timmar")
        if 'zap_export_optimerad_kwh' in facts:
            bits.append(f"Styrning kan optimera {fmt(facts['zap_export_optimerad_kwh'])} kWh export")
        if 'zap_dagar_drabbade' in facts:
            bits.append(f"Påverkan kan minskas {fmt(facts['zap_dagar_drabbade'])} dagar")
            
        # Traditional metrics (lower priority)
        if 'andel_neg_timmar_pct' in facts:
            bits.append(f"{fmt(facts['andel_neg_timmar_pct'])}% timmar ≤0 SEK")
        if 'timing_rabatt_pct' in facts:
            bits.append(f"marknadstiming {fmt(facts['timing_rabatt_pct'])}% avvikelse")
        return '; '.join(bits)

    def _build_prompt(self, bullet_line: str, facts: Dict[str, Any]) -> str:
        # Significantly shortened prompt as requested
        has_zap_data = 'zap_negativa_timmar' in facts or 'zap_export_optimerad_kwh' in facts
        
        base_prompt = (
            f"Skriv kortfattad svensk analys (max 120 ord) om export vid negativa spotpriser. Data: {bullet_line}. "
            "Viktigt: Detta baseras på spotpris exklusive moms och påslag - faktiskt resultat varierar med elbolag. "
            "Fokusera på: Hur stor andel av exporten skedde vid negativa priser. "
            "Förklara att negativa priser = systemöverskott av förnybar energi där export kostar pengar. "
            "60-öringens bortfall 2025/2026 förvärrar detta. "
            "Lösning: Exportstyrning när priserna är negativa. "
            "Skriv som löpande text, inga listor eller bullets."
        )
        
        return base_prompt

    def _short_prompt(self, bullet_line: str) -> str:
        return (
            f"Kort teknisk analys (1 stycke, max 120 ord) av solcellsanläggning: {bullet_line}. "
            "Tolkning: 'produktion' och 'intäkter' = totala värden, 'timmar som kostade' = negativa exportperioder. "
            "Fokus: marknadsvillkor, systemöverskott, exportkostnader. "
            "Nämn 60-öringens bortfall 2025/2026. Endast faktiska siffror."
        )

    def _map_reason(self, reason: str) -> str:
        if 'auth' in reason or '401' in reason:
            return 'auth'
        if '429' in reason or 'quota' in reason:
            return 'kvot'
        if 'model' in reason:
            return 'modell'
        if 'timeout' in reason.lower() or 'timed out' in reason.lower():
            return 'timeout'
        return reason

    def _call_openai(self, prompt: str) -> str | None:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return None
        url = f"{self.base_url.rstrip('/')}/responses"
        # Keep payload minimal for maximum compatibility (some deployments reject extra params)
        payload = {"model": self.model, "input": prompt}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        timeout_s = float(os.getenv('OPENAI_TIMEOUT', '40'))
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout_s)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:180]}")
        try:
            data = r.json()
        except Exception as e:
            raise RuntimeError(f"JSON decode misslyckades: {e}")
        if os.getenv('OPENAI_DEBUG_EXPLAINER') == '1':
            logger.debug('HTTP JSON keys: %s', list(data.keys()))
        output = data.get('output') or []
        pieces: list[str] = []
        for item in output:
            if isinstance(item, dict) and item.get('type') == 'message':
                for block in item.get('content', []) or []:
                    if isinstance(block, dict):
                        t = block.get('text')
                        if isinstance(t, str):
                            pieces.append(t)
                        elif isinstance(t, dict):
                            val = t.get('value') or t.get('text')
                            if isinstance(val, str):
                                pieces.append(val)
            elif isinstance(item, dict) and item.get('type') in ('text','output_text'):
                t = item.get('text')
                if isinstance(t, str):
                    pieces.append(t)
        if not pieces and isinstance(data.get('output_text'), str):
            pieces.append(data['output_text'])
        text = '\n'.join(p.strip() for p in pieces if p and p.strip())
        return text or None

    def _manual_fallback(self, facts: Dict[str, Any], reason: str) -> str:
        """Produce a simple deterministic Swedish summary if AI fails."""
        try:
            prod = facts.get('produktion_kwh')
            rev = facts.get('intakter_sek')
            timmar_kostat = facts.get('timmar_som_kostat_dig')
            kwh_förlust = facts.get('kwh_exporterat_med_förlust')
            kostnad = facts.get('kostnad_negativ_export_sek')
            zap_timmar = facts.get('zap_negativa_timmar')
            zap_kwh = facts.get('zap_export_optimerad_kwh')
            
            parts = [f"Anläggningen producerade {prod} kWh med totala intäkter {rev} SEK."]
            
            if timmar_kostat:
                parts.append(f"Under {timmar_kostat} timmar kostade exporten pengar.")
            if kwh_förlust:
                parts.append(f"{kwh_förlust} kWh exporterades vid negativa priser.")
            if kostnad:
                parts.append(f"Exportkostnad: -{kostnad} SEK.")
                
            if zap_timmar or zap_kwh:
                if zap_timmar:
                    parts.append(f"Exportstyrning kan optimera {zap_timmar} timmar.")
                if zap_kwh:
                    parts.append(f"Potential att optimera {zap_kwh} kWh export.")
            else:
                parts.append("Intelligent exportstyrning kan förbättra resultatet.")
                
            parts.append(f"(Reservförklaring – {reason})")
            return ' '.join(parts)
        except Exception:
            return f"Förklaring misslyckades ({reason})."