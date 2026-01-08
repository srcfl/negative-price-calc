#!/usr/bin/env python3
"""
Simple web frontend for the Negative Price Calculator

Requires environment variables:
- OPENAI_API_KEY: OpenRouter API key for AI features (required for AI explanations)
- ENTSOE_API_KEY: ENTSO-E API key for historical price data (optional fallback)
"""
import os
import json
import tempfile
import subprocess
import hashlib
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import threading
import pandas as pd
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Import AI table reader for smart file preview
from utils.ai_table_reader import AITableReader

app = Flask(__name__)

# CORS configuration - allow frontend origins from environment or defaults
cors_origins = os.environ.get('CORS_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000').split(',')
CORS(app, origins=cors_origins, supports_credentials=True)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()

# Results storage directory
RESULTS_DIR = Path(__file__).parent / 'data' / 'results'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Rate limiting: 4 analyses per hour per IP
RATE_LIMIT_MAX = 4
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds
rate_limit_store: dict[str, list[float]] = defaultdict(list)
rate_limit_lock = threading.Lock()

def get_client_ip() -> str:
    """Get client IP, handling proxies."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or 'unknown'

def check_rate_limit() -> tuple[bool, int]:
    """Check if client is within rate limit. Returns (allowed, remaining)."""
    client_ip = get_client_ip()
    current_time = time.time()

    with rate_limit_lock:
        # Clean old entries
        rate_limit_store[client_ip] = [
            t for t in rate_limit_store[client_ip]
            if current_time - t < RATE_LIMIT_WINDOW
        ]

        # Check limit
        request_count = len(rate_limit_store[client_ip])
        remaining = RATE_LIMIT_MAX - request_count

        if request_count >= RATE_LIMIT_MAX:
            return False, 0

        return True, remaining

def record_request():
    """Record a request for rate limiting."""
    client_ip = get_client_ip()
    with rate_limit_lock:
        rate_limit_store[client_ip].append(time.time())

ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}
AREA_CODES = {
    'SE_1': 'Norra Sverige (Luleå)',
    'SE_2': 'Mellersta Sverige (Sundsvall)',
    'SE_3': 'Mellersta Sverige (Stockholm)',
    'SE_4': 'Södra Sverige (Malmö)',
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_result_id(data: dict) -> str:
    """Generate a short unique ID for a result."""
    content = json.dumps(data, sort_keys=True) + str(time.time())
    return hashlib.sha256(content.encode()).hexdigest()[:8]


def save_result(result_id: str, data: dict) -> None:
    """Save result to JSON file."""
    file_path = RESULTS_DIR / f"{result_id}.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_result(result_id: str) -> dict | None:
    """Load result from JSON file."""
    file_path = RESULTS_DIR / f"{result_id}.json"
    if not file_path.exists():
        return None
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

@app.route('/')
def index():
    """API root - return service info."""
    return jsonify({
        'service': 'Negative Price Calculator API',
        'version': '2.0.0',
        'endpoints': {
            '/health': 'Health check',
            '/api/analyze/stream': 'POST - Analyze production file (SSE)',
            '/api/results/<id>': 'GET - Retrieve saved results',
        },
        'areas': AREA_CODES
    })

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

            # Save result and add ID for permalink
            result_id = generate_result_id(response)
            save_result(result_id, response)
            response['result_id'] = result_id

            return jsonify(response)

        finally:
            # Clean up temporary file
            if os.path.exists(file_path):
                os.remove(file_path)

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Analysis timed out. Please try with a smaller file.'}), 500
    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500

def analyze_file_preview(file_path: str, filename: str) -> dict:
    """Analyze file to extract preview info before full analysis.

    Uses AI-first approach: If OPENAI_API_KEY is available, use AI to intelligently
    detect file structure (including multi-section files like EON exports).
    Falls back to simple heuristics if AI unavailable.
    """
    result = {
        'file_type': 'unknown',
        'rows': 0,
        'columns': [],
        'date_column': None,
        'value_column': None,
        'date_range': None,
        'error': None,
        'ai_parsed': False
    }

    try:
        # Detect file type
        ext = filename.lower().split('.')[-1]
        if ext == 'csv':
            result['file_type'] = 'CSV'
        elif ext in ['xlsx', 'xls']:
            result['file_type'] = 'Excel'
        else:
            result['error'] = f'Okänt filformat: {ext}'
            return result

        # AI-FIRST: Try AI parsing when available
        ai_reader = AITableReader()
        if ai_reader.is_available():
            try:
                df, spec = ai_reader.read(file_path)
                result['rows'] = len(df)
                result['columns'] = list(df.columns)
                result['date_column'] = spec.get('datetime_column')
                result['value_column'] = spec.get('value_column')
                result['ai_parsed'] = True

                # Get date range from AI-parsed data
                if result['date_column'] and result['date_column'] in df.columns:
                    try:
                        dates = pd.to_datetime(df[result['date_column']], errors='coerce')
                        valid_dates = dates.dropna()
                        if len(valid_dates) > 0:
                            result['date_range'] = {
                                'start': valid_dates.min().strftime('%Y-%m-%d'),
                                'end': valid_dates.max().strftime('%Y-%m-%d')
                            }
                    except:
                        pass

                return result
            except Exception as e:
                # AI failed, fall back to heuristics
                pass

        # FALLBACK: Simple heuristic parsing (when AI unavailable)
        if ext == 'csv':
            df = None
            for sep in [';', ',', '\t']:
                try:
                    df = pd.read_csv(file_path, sep=sep, nrows=1000, encoding='utf-8-sig')
                    if len(df.columns) > 1:
                        break
                except:
                    continue
            if df is None:
                df = pd.read_csv(file_path, nrows=1000, encoding='utf-8-sig')
        else:
            df = pd.read_excel(file_path, nrows=1000)

        result['rows'] = len(df)
        result['columns'] = list(df.columns)

        # Try to find date column with keywords
        date_keywords = ['datum', 'date', 'time', 'tid', 'timestamp', 'datetime', 'starttidpunkt']
        for col in df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in date_keywords):
                result['date_column'] = col
                break

        # If no date column found, try first column
        if not result['date_column'] and len(df.columns) > 0:
            first_col = df.columns[0]
            try:
                pd.to_datetime(df[first_col].head(10))
                result['date_column'] = first_col
            except:
                pass

        # Try to find value/energy column
        value_keywords = ['kwh', 'wh', 'energi', 'energy', 'värde', 'value', 'produktion',
                         'export', 'förbrukning', 'consumption', 'kvantitet', 'mängd', 'quantity']
        for col in df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in value_keywords):
                result['value_column'] = col
                break

        # If still no value column, look for numeric columns (excluding date column)
        if not result['value_column']:
            for col in df.columns:
                if col != result['date_column'] and pd.api.types.is_numeric_dtype(df[col]):
                    result['value_column'] = col
                    break

        # Try to get date range
        if result['date_column']:
            try:
                dates = pd.to_datetime(df[result['date_column']], errors='coerce')
                valid_dates = dates.dropna()
                if len(valid_dates) > 0:
                    result['date_range'] = {
                        'start': valid_dates.min().strftime('%Y-%m-%d'),
                        'end': valid_dates.max().strftime('%Y-%m-%d')
                    }
            except:
                pass

    except Exception as e:
        result['error'] = str(e)

    return result


def parse_cli_error(stderr: str, stdout: str) -> str:
    """Parse CLI error output into a user-friendly message."""
    error_text = stderr or stdout or ''

    # Filter out UV deprecation warnings (noise)
    lines = error_text.split('\n')
    filtered_lines = [l for l in lines if not l.startswith('warning: The `tool.uv')]
    error_text = '\n'.join(filtered_lines)

    # Common error patterns - ORDER MATTERS! More specific patterns first

    # Price data issues (check before generic "no data")
    if 'no price data' in error_text.lower() or ('price' in error_text.lower() and 'available' in error_text.lower()):
        return 'Kunde inte hämta elpriser för angivet datumintervall. Sourceful API har endast prisdata för de senaste månaderna.'

    if 'price' in error_text.lower() and 'fetch' in error_text.lower():
        return 'Kunde inte hämta elpriser. Kontrollera att datumintervallet är rimligt (max 2 år).'

    if 'No date column found' in error_text or 'datum' in error_text.lower():
        return 'Kunde inte hitta datumkolumn i filen. Kontrollera att filen innehåller en kolumn med datum/tid.'

    if 'No value column' in error_text or 'numeric' in error_text.lower():
        return 'Kunde inte hitta numerisk kolumn med energivärden. Kontrollera att filen innehåller kWh-värden.'

    if 'empty' in error_text.lower() or 'no data' in error_text.lower():
        return 'Filen verkar vara tom eller sakna data.'

    if 'encoding' in error_text.lower() or 'codec' in error_text.lower():
        return 'Problem med filens teckenkodning. Försök spara filen som UTF-8.'

    if 'permission' in error_text.lower():
        return 'Kunde inte läsa filen. Kontrollera filrättigheter.'

    # Return first line of error if specific pattern not found
    first_line = error_text.strip().split('\n')[0] if error_text else 'Okänt fel'
    return f'Analysfel: {first_line[:200]}'


@app.route('/analyze/stream', methods=['POST'])
def analyze_stream():
    """SSE endpoint for streaming analysis progress."""
    def generate():
        file_path = None
        try:
            # Check rate limit first
            allowed, remaining = check_rate_limit()
            if not allowed:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Du har nått gränsen på 4 analyser per timme. Försök igen senare.'})}\n\n"
                return

            # Record this request for rate limiting
            record_request()

            # Check if file was uploaded
            if 'production_file' not in request.files:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Ingen fil uppladdad'})}\n\n"
                return

            file = request.files['production_file']
            if file.filename == '':
                yield f"data: {json.dumps({'type': 'error', 'message': 'Ingen fil vald'})}\n\n"
                return

            if not allowed_file(file.filename):
                yield f"data: {json.dumps({'type': 'error', 'message': 'Ogiltig filtyp. Använd CSV eller Excel.'})}\n\n"
                return

            # Get parameters
            area = request.form.get('area', 'SE_4')
            currency = 'SEK'
            has_openai_key = bool(os.getenv('OPENAI_API_KEY'))

            # Save file
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            # Get file size
            file_size_kb = os.path.getsize(file_path) / 1024
            yield f"data: {json.dumps({'type': 'info', 'message': f'Fil uppladdad: {filename} ({file_size_kb:.1f} KB)'})}\n\n"
            time.sleep(0.2)

            # Analyze file preview
            yield f"data: {json.dumps({'type': 'progress', 'message': 'Läser filformat...'})}\n\n"
            preview = analyze_file_preview(file_path, filename)
            time.sleep(0.2)

            if preview['error']:
                error_msg = preview['error']
                yield f"data: {json.dumps({'type': 'error', 'message': f'Filfel: {error_msg}'})}\n\n"
                return

            file_type = preview['file_type']
            row_count = preview['rows']
            ai_parsed = preview.get('ai_parsed', False)

            if ai_parsed:
                yield f"data: {json.dumps({'type': 'ai', 'message': 'AI analyserade filstrukturen'})}\n\n"
                time.sleep(0.1)

            yield f"data: {json.dumps({'type': 'info', 'message': f'Filtyp: {file_type} med {row_count} rader'})}\n\n"
            time.sleep(0.1)

            # Show columns found
            if preview['columns']:
                cols_preview = ', '.join(str(c) for c in preview['columns'][:5])
                extra_cols = len(preview['columns']) - 5
                if extra_cols > 0:
                    cols_preview += f' (+{extra_cols} till)'
                yield f"data: {json.dumps({'type': 'info', 'message': f'Kolumner: {cols_preview}'})}\n\n"
                time.sleep(0.1)

            # Show detected columns - track if we need AI parsing
            date_col = preview['date_column']
            value_col = preview['value_column']
            cols_list = ', '.join(str(c) for c in preview['columns'][:10])
            needs_ai_parsing = False

            if date_col:
                yield f"data: {json.dumps({'type': 'success', 'message': f'Datumkolumn hittad: {date_col}'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Kunde inte automatiskt hitta datumkolumn'})}\n\n"
                needs_ai_parsing = True
            time.sleep(0.1)

            if value_col:
                yield f"data: {json.dumps({'type': 'success', 'message': f'Värdekolumn hittad: {value_col}'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Kunde inte automatiskt hitta värdekolumn'})}\n\n"
                needs_ai_parsing = True
            time.sleep(0.1)

            # Show date range if found
            date_range = preview['date_range']
            if date_range:
                start_date = date_range['start']
                end_date = date_range['end']
                yield f"data: {json.dumps({'type': 'info', 'message': f'Datumintervall: {start_date} till {end_date}'})}\n\n"
                time.sleep(0.1)

            # Build CLI command
            cmd = [
                'uv', 'run', 'se-cli', 'analyze',
                file_path,
                '--area', area,
                '--currency', currency,
                '--json'
            ]

            if has_openai_key:
                cmd.append('--ai-explainer')

            # If we need AI parsing, run it first and wait for result
            if needs_ai_parsing:
                yield f"data: {json.dumps({'type': 'ai', 'message': 'Aktiverar AI-assisterad filanalys...'})}\n\n"
                yield f"data: {json.dumps({'type': 'info', 'message': f'Kolumner att analysera: {cols_list}'})}\n\n"
                time.sleep(0.2)

                # Run CLI and wait for AI parsing result
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                yield f"data: {json.dumps({'type': 'ai', 'message': 'AI försöker tolka filstrukturen...'})}\n\n"

                stdout, stderr = process.communicate(timeout=300)

                if process.returncode != 0:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'AI kunde inte tolka filen'})}\n\n"
                    # Parse and show specific error
                    if 'No date' in stderr or 'datum' in stderr.lower():
                        yield f"data: {json.dumps({'type': 'info', 'message': 'Filen saknar en kolumn som kan tolkas som datum'})}\n\n"
                    if 'No value' in stderr or 'numeric' in stderr.lower():
                        yield f"data: {json.dumps({'type': 'info', 'message': 'Filen saknar numeriska energivärden'})}\n\n"
                    yield f"data: {json.dumps({'type': 'info', 'message': 'Tips: Kontrollera att filen har en datumkolumn och en kolumn med kWh-värden'})}\n\n"
                    if stderr:
                        short_err = stderr.strip().split('\n')[0][:200]
                        yield f"data: {json.dumps({'type': 'info', 'message': f'Tekniskt: {short_err}'})}\n\n"
                    return

                # Try to parse JSON result
                try:
                    analysis_data = json.loads(stdout)
                    yield f"data: {json.dumps({'type': 'success', 'message': 'AI lyckades tolka filen!'})}\n\n"
                except json.JSONDecodeError:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'AI kunde inte tolka filens data'})}\n\n"
                    if stderr:
                        short_err = stderr.strip().split('\n')[0][:200]
                        yield f"data: {json.dumps({'type': 'info', 'message': f'Detalj: {short_err}'})}\n\n"
                    return

            else:
                # Standard parsing - show progress
                yield f"data: {json.dumps({'type': 'progress', 'message': f'Hämtar elpriser för {area}...'})}\n\n"
                time.sleep(0.2)

                # Run CLI with Popen
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                yield f"data: {json.dumps({'type': 'progress', 'message': 'Matchar produktion med elpriser...'})}\n\n"
                time.sleep(0.3)

                yield f"data: {json.dumps({'type': 'progress', 'message': 'Beräknar intäkter och förluster...'})}\n\n"

                if has_openai_key:
                    yield f"data: {json.dumps({'type': 'ai', 'message': 'AI analyserar dina mönster...'})}\n\n"

                # Wait for process to complete
                stdout, stderr = process.communicate(timeout=300)

                if process.returncode != 0:
                    error_msg = parse_cli_error(stderr, stdout)
                    yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"

                    # Show raw error for debugging
                    if stderr:
                        yield f"data: {json.dumps({'type': 'info', 'message': f'Tekniskt fel: {stderr[:300]}'})}\n\n"
                    return

                # Parse results
                try:
                    analysis_data = json.loads(stdout)
                except json.JSONDecodeError as e:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Kunde inte tolka analysresultat'})}\n\n"
                    # Show both stdout and stderr for debugging
                    if stdout:
                        yield f"data: {json.dumps({'type': 'info', 'message': f'stdout: {stdout[:500]}'})}\n\n"
                    if stderr:
                        yield f"data: {json.dumps({'type': 'info', 'message': f'stderr: {stderr[:300]}'})}\n\n"
                    return

            # Show some results in log
            hero = analysis_data.get('hero', {})
            produktion = hero.get('produktion', {})
            total_kwh = produktion.get('total_kwh')
            if total_kwh:
                yield f"data: {json.dumps({'type': 'success', 'message': f'Total produktion: {total_kwh:.0f} kWh'})}\n\n"

            # Build response
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

            # Save result
            result_id = generate_result_id(response)
            save_result(result_id, response)
            response['result_id'] = result_id

            yield f"data: {json.dumps({'type': 'success', 'message': 'Analys klar!'})}\n\n"
            yield f"data: {json.dumps({'type': 'result', 'data': response})}\n\n"

        except subprocess.TimeoutExpired:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Analysen tog för lång tid. Försök med mindre fil.'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Oväntat fel: {str(e)}'})}\n\n"
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/results/<result_id>', methods=['GET'])
def get_result(result_id):
    """Retrieve a saved result by ID."""
    # Validate ID format (8 hex chars)
    if not result_id or len(result_id) != 8 or not all(c in '0123456789abcdef' for c in result_id.lower()):
        return jsonify({'error': 'Invalid result ID'}), 400

    result = load_result(result_id.lower())
    if result is None:
        return jsonify({'error': 'Result not found'}), 404

    return jsonify(result)


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
