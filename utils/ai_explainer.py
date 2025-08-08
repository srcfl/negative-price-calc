import openai
import os
import json
import logging

logger = logging.getLogger(__name__)

class AIExplainer:
    def __init__(self):
        self.client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    def explain_analysis(self, analysis_data, metadata):
        """Generate AI explanation of the analysis results."""
        if not os.getenv('OPENAI_API_KEY'):
            return "AI explanation requires OpenAI API key."
        
        # Prepare summary data for the prompt
        summary = {
            'period_days': analysis_data.get('period_days', 0),
            'total_production_kwh': analysis_data.get('production_total', 0),
            'negative_price_hours': analysis_data.get('negative_price_hours', 0),
            'negative_cost_sek': analysis_data.get('negative_export_cost_abs_sek', 0),
            'total_export_value_sek': analysis_data.get('total_export_value_sek', 0),
            'area_code': metadata.get('area_code', 'Unknown'),
            'currency': metadata.get('currency', 'SEK')
        }
        
        prompt = f"""
        You are an energy market analyst. Explain this solar production analysis in simple Swedish:

        Analysis Summary:
        - Period: {summary['period_days']} days
        - Total production: {summary['total_production_kwh']:.1f} kWh
        - Hours with negative prices: {summary['negative_price_hours']}
        - Cost from negative prices: {summary['negative_cost_sek']:.2f} {summary['currency']}
        - Total export value: {summary['total_export_value_sek']:.2f} {summary['currency']}
        - Area: {summary['area_code']}

        Provide:
        1. A brief summary of the results
        2. What negative prices mean for solar owners
        3. Practical recommendations

        Keep it under 300 words, in Swedish, and avoid technical jargon.
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500
            )
            
            explanation = response.choices[0].message.content.strip()
            logger.info("Generated AI explanation successfully")
            return explanation
            
        except Exception as e:
            logger.error(f"AI explanation generation failed: {e}")
            return "AI-förklaring kunde inte genereras för tillfället. Analysresultaten visar din solproduktions prestanda och kostnader under negativa prispriser."
