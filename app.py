#!/usr/bin/env python3
"""
Simple web frontend for the Negative Price Calculator
"""
import os
import json
import tempfile
import subprocess
from datetime import datetime
from pathlib import Path
import pandas as pd
from io import BytesIO

from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()

ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}
AREA_CODES = {
    'SE_1': 'Norra Sverige (Luleå)',
    'SE_2': 'Mellersta Sverige (Sundsvall)',
    'SE_3': 'Mellersta Sverige (Stockholm)',
    'SE_4': 'Södra Sverige (Malmö)',
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html', area_codes=AREA_CODES)

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        # Check if file was uploaded
        if 'production_file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['production_file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload CSV or Excel files.'}), 400

        # Get parameters
        area = request.form.get('area', 'SE_4')
        currency = 'SEK'  # Always use SEK

        # Check if OpenAI key is available for AI explanations
        has_openai_key = bool(os.getenv('OPENAI_API_KEY'))

        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        try:
            # Build CLI command
            cmd = [
                'uv', 'run', 'se-cli', 'analyze',
                file_path,
                '--area', area,
                '--currency', currency,
                '--json'
            ]

            # Add AI explainer only if OpenAI key is available
            if has_openai_key:
                cmd.append('--ai-explainer')

            # Run the CLI command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or 'Analysis failed'
                return jsonify({'error': f'Analysis error: {error_msg}'}), 500

            # Parse JSON output from CLI
            try:
                analysis_data = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                return jsonify({'error': f'Failed to parse analysis results: {str(e)}'}), 500

            # Format response
            response = {
                'success': True,
                'analysis': analysis_data,
                'metadata': {
                    'filename': filename,
                    'granularity': analysis_data.get('input', {}).get('granularity', 'unknown'),
                    'area': area,
                    'currency': currency,
                    'analyzed_at': datetime.now().isoformat(),
                    'ai_enabled': has_openai_key
                }
            }

            return jsonify(response)

        finally:
            # Clean up temporary file
            if os.path.exists(file_path):
                os.remove(file_path)

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Analysis timed out. Please try with a smaller file.'}), 500
    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500

@app.route('/download_xlsx', methods=['POST'])
def download_xlsx():
    try:
        # Get the analysis data from the request
        data = request.get_json()
        if not data or 'analysis' not in data:
            return jsonify({'error': 'No analysis data provided'}), 400

        analysis = data['analysis']
        metadata = data.get('metadata', {})

        # Create Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:

            # Hero metrics sheet
            hero_data = []
            if 'hero' in analysis:
                hero = analysis['hero']
                for key, value in hero.items():
                    if isinstance(value, dict) and 'units' in hero and key in hero['units']:
                        unit = hero['units'][key]
                        hero_data.append({'Metric': key.replace('_', ' ').title(), 'Value': value, 'Unit': unit})
                    else:
                        hero_data.append({'Metric': key.replace('_', ' ').title(), 'Value': value, 'Unit': ''})

            if hero_data:
                pd.DataFrame(hero_data).to_excel(writer, sheet_name='Hero Metrics', index=False)

            # Weekly aggregates sheet
            if 'aggregates' in analysis and 'weekly' in analysis['aggregates']:
                weekly_df = pd.DataFrame(analysis['aggregates']['weekly'])
                weekly_df.to_excel(writer, sheet_name='Weekly Analysis', index=False)

            # Monthly aggregates sheet
            if 'aggregates' in analysis and 'monthly' in analysis['aggregates']:
                monthly_df = pd.DataFrame(analysis['aggregates']['monthly'])
                monthly_df.to_excel(writer, sheet_name='Monthly Analysis', index=False)

            # AI Analysis sheet (if available)
            if 'ai_explanation_sv' in analysis:
                ai_df = pd.DataFrame([{
                    'AI Analysis (Swedish)': analysis['ai_explanation_sv'],
                    'Generated At': analysis.get('calculated_at', ''),
                    'Schema Version': analysis.get('schema_version', '')
                }])
                ai_df.to_excel(writer, sheet_name='AI Analysis', index=False)

            # Metadata sheet
            meta_data = []
            for key, value in metadata.items():
                meta_data.append({'Property': key.replace('_', ' ').title(), 'Value': str(value)})
            if meta_data:
                pd.DataFrame(meta_data).to_excel(writer, sheet_name='Metadata', index=False)

        output.seek(0)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"analysis_report_{timestamp}.xlsx"

        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
        return jsonify({'error': f'Failed to generate XLSX: {str(e)}'}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
