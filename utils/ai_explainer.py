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
        scenarios = (payload.get('scenarios') or {})
        battery = scenarios.get('battery_shift') or {}
        batt_sizes = battery.get('sizes_kwh', []) if battery else []
        best_batt = max(batt_sizes, key=lambda x: x.get('delta_revenue_sek', 0)) if batt_sizes else None

        # --- Extract metrics ---
        prod = float(hero.get('production_kwh') or 0)
        rev = float(hero.get('revenue_sek') or 0)
        neg_val = float(hero.get('negative_value_sek') or 0)
        neg_share = float(hero.get('share_non_positive_during_production_pct') or 0)
        timing_disc = float(hero.get('timing_discount_pct') or 0)
        delta_if_floor = float(counterfactuals.get('delta_sek') or 0)
        lost_energy_at_floor0 = counterfactuals.get('lost_energy_kwh_at_floor_0')

        facts: Dict[str, Any] = {
            'produktion_kwh': round(prod, 1),
            'intakter_sek': round(rev, 0),
        }
        if neg_val > 0:
            facts['negativt_varde_sek'] = round(neg_val, 0)
        if neg_share > 0:
            facts['andel_neg_timmar_pct'] = round(neg_share, 1)
        if timing_disc != 0:
            facts['timing_rabatt_pct'] = round(timing_disc, 1)
        if delta_if_floor > 0:
            facts['prisgolv_potential_sek'] = round(delta_if_floor, 0)
        if best_batt and (best_batt.get('delta_revenue_sek') or 0) > 0:
            facts['batt_delta_sek'] = round(best_batt.get('delta_revenue_sek'), 0)
            size_kwh = best_batt.get('size_kwh') or best_batt.get('size')
            if size_kwh:
                facts['batt_size_kwh'] = size_kwh
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
        bits = [f"produktion {fmt(facts['produktion_kwh'])} kWh", f"intäkter {fmt(facts['intakter_sek'])} SEK"]
        if 'negativt_varde_sek' in facts:
            bits.append(f"negativt värde {fmt(facts['negativt_varde_sek'])} SEK")
        if 'andel_neg_timmar_pct' in facts:
            bits.append(f"{fmt(facts['andel_neg_timmar_pct'])}% timmar ≤0 SEK")
        if 'timing_rabatt_pct' in facts:
            bits.append(f"timingrabatt {fmt(facts['timing_rabatt_pct'])}%")
        if 'prisgolv_potential_sek' in facts:
            bits.append(f"prisgolv potential +{fmt(facts['prisgolv_potential_sek'])} SEK")
        if 'batt_delta_sek' in facts:
            maybe_size = facts.get('batt_size_kwh')
            size_str = f" ({maybe_size}kWh)" if maybe_size else ''
            bits.append(f"batteri{size_str} +{fmt(facts['batt_delta_sek'])} SEK")
        if 'energi_vid_golv0_kwh' in facts:
            bits.append(f"energi vid golv 0 paus {fmt(facts['energi_vid_golv0_kwh'])} kWh")
        return '; '.join(bits)

    def _build_prompt(self, bullet_line: str, facts: Dict[str, Any]) -> str:
        # Keep prompt compact to lower latency while retaining instructions
        return (
            "Skriv en kort engagerande svensk sammanfattning (1–2 stycken, max 220 ord) för en villaägare. "
            "Vi är Sourceful Energy (tjänsten Zap) som automatiskt pausar export vid ≤0 SEK/kWh och kan styra mot egenanvändning, laddning eller batteri. "
            f"Data: {bullet_line}. "
            "Förklara värdet i kronor, lyft hur många timmar som låg vid 0/negativa priser om siffran finns, och hur prisgolv/batteri minskar tappet (använd endast givna siffror). "
            "Inga nya siffror. Ingen lista eller rubrik. Avsluta med tydlig CTA att aktivera Zap nu för att undvika noll/negativtpris-timmar. Ton: professionell och trygg, lätt sälj." )

    def _short_prompt(self, bullet_line: str) -> str:
        return (
            f"Sammanfatta kort (1 stycke, max 90 ord) på svenska för villaägare baserat på: {bullet_line}. "
            "Förklara effekten av negativa timmar och uppmana att aktivera Zap. Endast givna siffror." )

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
            neg = facts.get('negativt_varde_sek')
            negshare = facts.get('andel_neg_timmar_pct')
            timing = facts.get('timing_rabatt_pct')
            batt = facts.get('batt_delta_sek')
            golv = facts.get('rekommenderat_golv')
            parts = [f"Produktion {prod} kWh gav ca {rev} SEK."]
            if neg:
                parts.append(f"Negativa priser kostade ~{neg} SEK")
            if negshare:
                parts.append(f"({negshare}% av produktionstimmarna var ≤0 SEK)")
            if timing is not None:
                parts.append(f"Timing-rabatt: {timing}% mot enkelt snitt")
            if golv is not None:
                parts.append(f"Möjligt golv: {golv} SEK/kWh")
            if batt:
                parts.append(f"Batteriscenario +{batt} SEK")
            parts.append(f"(AI fallback – {reason})")
            return ' '.join(parts)
        except Exception:
            return f"AI-förklaring fallback misslyckades ({reason})."
