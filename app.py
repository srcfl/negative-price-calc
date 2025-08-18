#!/usr/bin/env python3
"""
Sourceful Energy - Web Application
Flask-based web interface for negative price analysis
"""

import os
import tempfile
import json
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import pandas as pd
from dotenv import load_dotenv

from core.price_fetcher import PriceFetcher
from core.production_loader import ProductionLoader
from cli.main import build_storytelling_payload
from utils.ai_explainer import AIExplainer

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    """Serve the main web interface"""
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    """Handle file upload and analysis"""
    try:
        # Check if file was uploaded
        if 'production_file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'})
        
        file = request.files['production_file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Invalid file type. Please upload CSV or Excel files.'})
        
        # Get form parameters
        area = request.form.get('area', 'SE_4')
        email = request.form.get('email', '')
        
        # Log the analysis request
        log_analysis_request(request, file.filename, area, email)
        
        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            # Initialize components
            price_fetcher = PriceFetcher()
            production_loader = ProductionLoader()
            
            # Load production data
            production_df, granularity = production_loader.load_production(filepath)
            
            if production_df.empty:
                return jsonify({'success': False, 'error': 'No production data found in file'})
            
            # Determine date range from production data
            production_start = pd.Timestamp(production_df.index.min(), tz='Europe/Stockholm')
            production_end = pd.Timestamp(production_df.index.max(), tz='Europe/Stockholm')
            
            # Get price data
            prices_df = price_fetcher.get_price_data(area, production_start, production_end)
            
            if prices_df.empty:
                return jsonify({'success': False, 'error': f'No price data available for {area} in the specified period'})
            
            # Currency configuration
            currency = 'SEK'
            currency_rate = 11.5  # EUR to SEK conversion rate
            
            # Merge data and create analysis
            merged_df = pd.DataFrame({'prod_kwh': production_df['production_kwh']}).join(
                (prices_df['price_eur_per_mwh'] * currency_rate / 1000).to_frame('sek_per_kwh'), 
                how='left'
            )
            
            # Build storytelling payload
            payload = build_storytelling_payload(merged_df, currency, currency_rate, granularity)
            
            # Add AI explanation if available
            if email and os.getenv('OPENAI_API_KEY'):
                try:
                    explainer = AIExplainer()
                    metadata = {
                        'area_code': area,
                        'currency': currency,
                        'filename': filename,
                        'email': email
                    }
                    ai_explanation = explainer.explain_analysis(payload, metadata)
                    payload['ai_explanation_sv'] = ai_explanation
                except Exception as e:
                    print(f"AI explanation failed: {e}")
                    # Continue without AI explanation
            
            # Add metadata
            metadata = {
                'filename': filename,
                'area': area,
                'currency': currency,
                'granularity': granularity,
                'analyzed_at': datetime.now().isoformat(),
                'total_hours': len(merged_df),
                'date_range': {
                    'start': production_start.isoformat(),
                    'end': production_end.isoformat()
                }
            }
            
            # Clean up temporary file
            os.unlink(filepath)
            
            return jsonify({
                'success': True,
                'analysis': payload,
                'metadata': metadata
            })
            
        except Exception as e:
            # Clean up temporary file on error
            if os.path.exists(filepath):
                os.unlink(filepath)
            raise e
            
    except Exception as e:
        return jsonify({'success': False, 'error': f'Analysis failed: {str(e)}'})

def log_analysis_request(request, filename, area, email):
    """Log analysis requests for debugging and analytics"""
    try:
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'filename': filename,
            'area': area,
            'email': email,
            'ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', ''),
            'file_size': request.content_length
        }
        
        # Add geolocation if provided
        if request.form.get('latitude'):
            log_entry['location'] = {
                'latitude': request.form.get('latitude'),
                'longitude': request.form.get('longitude'),
                'accuracy': request.form.get('location_accuracy')
            }
        
        # Add browser info if provided
        if request.form.get('browser_info'):
            try:
                log_entry['browser_info'] = json.loads(request.form.get('browser_info'))
            except:
                pass
        
        # Write to log file
        log_file = Path('data/email_logs.txt')
        log_file.parent.mkdir(exist_ok=True)
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            
    except Exception as e:
        print(f"Failed to log analysis request: {e}")

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': 'File too large. Maximum size is 16MB.'}), 413

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({'success': False, 'error': f'Server error: {str(e)}'}), 500

if __name__ == '__main__':
    # Development server
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    print(f"Starting Sourceful Energy web application on port {port}")
    print(f"Debug mode: {debug}")
    print(f"Environment: {os.environ.get('FLASK_ENV', 'development')}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
