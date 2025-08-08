import openai
import pandas as pd
import os
import logging

logger = logging.getLogger(__name__)

class CSVFormatDetector:
    def __init__(self):
        self.client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    def detect_format(self, file_path):
        """Detect CSV format using LLM analysis."""
        if not os.getenv('OPENAI_API_KEY'):
            raise ValueError("OpenAI API key not found")
        
        # Read first few lines of the file
        sample_lines = self._read_sample(file_path)
        
        # Ask LLM to analyze the format
        prompt = f"""
        Analyze this CSV file sample and determine the best pandas.read_csv() parameters:

        {sample_lines}

        Return only a Python dictionary with these keys:
        - sep: separator character
        - encoding: file encoding (utf-8, iso-8859-1, etc.)
        - decimal: decimal separator
        - thousands: thousands separator (or None)
        - skiprows: number of rows to skip (or 0)
        - header: header row number (or 0)

        Example: {{"sep": ",", "encoding": "utf-8", "decimal": ".", "thousands": None, "skiprows": 0, "header": 0}}
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=200
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Parse the result
            import ast
            params = ast.literal_eval(result_text)
            
            # Add standard parameters
            params.update({
                'na_values': ['', 'NA', 'N/A', 'null', 'NULL', 'None', '-'],
                'skipinitialspace': True
            })
            
            logger.info(f"LLM detected CSV format: {params}")
            return params
            
        except Exception as e:
            logger.error(f"LLM format detection failed: {e}")
            raise
    
    def _read_sample(self, file_path, lines=10):
        """Read first few lines of file for analysis."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = [f.readline().strip() for _ in range(lines)]
            return '\n'.join(lines)
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='iso-8859-1') as f:
                lines = [f.readline().strip() for _ in range(lines)]
            return '\n'.join(lines)
