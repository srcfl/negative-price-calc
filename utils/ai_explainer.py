import os
import logging
import re
import json
from typing import Any, Dict
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
        # --- Preconditions ---
        if not os.getenv('OPENAI_API_KEY'):
            return "AI-förklaring kräver OPENAI_API_KEY."

        # --- Minimal fact extraction (only high‑level numbers) ---
        hero = payload.get('hero', {})
        scenarios = (payload.get('scenarios') or {})
        curtail = scenarios.get('curtailment_price_floor_sweep') or {}
        battery = scenarios.get('battery_shift') or {}

        prod = float(hero.get('production_kwh', 0) or 0)
        rev = float(hero.get('revenue_sek', 0) or 0)
        neg_val = float(hero.get('negative_value_sek', 0) or 0)
        neg_share = float(hero.get('share_non_positive_during_production_pct', 0) or 0)
        timing_disc = float(hero.get('timing_discount_pct', 0) or 0)
        curt_reco = curtail.get('recommended_floor_sek_per_kwh')
        batt_sizes = battery.get('sizes_kwh', []) if battery else []
        best_batt = max(batt_sizes, key=lambda x: x.get('delta_revenue_sek',0)) if batt_sizes else None
        self_cons = hero.get('self_consumption')

        facts: Dict[str, Any] = {
            'produktion_kwh': round(prod,1),
            'intakter_sek': round(rev,0),
        }
        if neg_val > 0:
            facts['negativt_varde_sek'] = round(neg_val,0)
        # Human friendly formatting (svenska decimaler) for storytelling
        def fmt(v):
            if isinstance(v, (int,)):
                return f"{v:,}".replace(',', ' ')  # thousands space
            if isinstance(v, float):
                sval = ("{:.2f}".format(v)).rstrip('0').rstrip('.')
                return sval.replace('.', ',')
            return str(v)
        story_bits = []
        story_bits.append(f"produktion {fmt(facts['produktion_kwh'])} kWh")
        story_bits.append(f"intäkter {fmt(facts['intakter_sek'])} SEK")
        if 'negativt_varde_sek' in facts:
            story_bits.append(f"negativt prispåverkan {fmt(facts['negativt_varde_sek'])} SEK")
        if 'andel_neg_timmar_pct' in facts:
            story_bits.append(f"{fmt(facts['andel_neg_timmar_pct'])}% timmar ≤0 SEK")
        if 'timing_rabatt_pct' in facts:
            story_bits.append(f"timingrabatt {fmt(facts['timing_rabatt_pct'])}%")
        if 'batt_delta_sek' in facts:
            story_bits.append(f"batteripotential +{fmt(facts['batt_delta_sek'])} SEK")
        if 'rekommenderat_golv' in facts:
            story_bits.append(f"möjligt golv {fmt(facts['rekommenderat_golv'])} SEK/kWh")
        bullet_line = '; '.join(story_bits)

        prompt = (
            "Skriv ett engagerande men sakligt stycke på svenska (EN enda paragraf) som återger hur solcellsperioden gått. "
            "Utgå från dessa nycklar (rå fakta): " + bullet_line + ". "
            "Väv in siffrorna naturligt i löpande text, förklara kort vad de betyder för hushållets ekonomi och nämn effekten av negativa priser om med. "
            "Avsluta med 1 kort konkret förbättringsidé (t.ex. bättre timing, ev. liten batterilagring eller prisgolv om relevant). "
            "Ton: positivt nykter, ingen överdrift, ingen punktlista, inga rubriker. Max 110 ord."
        )
        try:
            ai_text = self._call_openai(prompt)
            if ai_text:
                return ai_text.strip()
            return self._manual_fallback(facts, reason='tomt AI-svar')
        except Exception as e:
            msg = str(e)
            if '401' in msg:
                return self._manual_fallback(facts, reason='auth')
            if '429' in msg or 'quota' in msg:
                return self._manual_fallback(facts, reason='kvot')
            if '404' in msg or 'model' in msg.lower():
                return self._manual_fallback(facts, reason='modell')
            return self._manual_fallback(facts, reason=msg[:60])
        # --- Error surface ---
        if last_err:
            msg = str(last_err)
            if 'insufficient_quota' in msg:
                return (
                    "AI-förklaring misslyckades (kvot). Kontrollera billing eller välj annan nyckel. "
                    f"Fel: {msg[:240]}"
                )
            if 'model_not_found' in msg:
                return "Modell ej hittad. Justera OPENAI_MODEL."
            # Deterministisk fallback
            return self._manual_fallback(facts, reason=msg[:120])
        # Okänt fel -> fallback
        return self._manual_fallback(facts, reason="okänt")

    def _call_openai(self, prompt: str) -> str | None:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return None
        url = f"{self.base_url.rstrip('/')}/responses"
        payload = {"model": self.model, "input": prompt}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
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
