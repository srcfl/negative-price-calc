# 🌐 Web Application Interface

A simple web frontend for the Negative Price Calculator that provides an easy-to-use interface for analyzing electricity prices and solar production data.

## 🚀 Quick Start

### Option 1: Direct Python
```bash
cd negative-price-calc
uv run python run_webapp.py
```

### Option 2: Using the CLI script
```bash
cd negative-price-calc
uv run webapp
```

Then open your browser to: **http://localhost:8080**

## ✨ Features

### 📁 File Upload
- **Supported formats**: CSV, Excel (.xlsx, .xls)
- **File size limit**: 16MB
- **Data types**: Hourly or daily production data
- **Drag & drop** or click to browse

### ⚙️ Configuration Options
- **Electricity Area**: Choose from Nordic countries (SE_1-4, NO_1-2, DK_1-2)
- **Currency**: SEK, EUR, NOK, DKK  
- **Smart File Processing**: Automatically handles various CSV and Excel formats with AI-powered parsing
- **AI Analysis**: Always-on educational Swedish explanations (requires OpenAI API key)
- **Real-time feedback** on file selection and processing

### 📊 Analysis Results
- **Key Metrics Dashboard**:
  - Total production (kWh)
  - Revenue and negative value losses
  - Average realized vs market prices
  - Timing discount percentage
  - Hours with negative prices

- **AI Analysis Summary** (always included):
  - Educational Swedish explanations of complex statistics
  - Neutral, objective analysis without product marketing
  - Practical investment advice based on your data
  - Clear explanations of timing discount, curtailment potential, and battery scenarios

- **Insights & Recommendations**:
  - Production efficiency analysis
  - Curtailment potential calculations
  - Price realization performance
  - Historical context

- **Data Export**:
  - **Excel Report**: Multi-sheet XLSX with hero metrics, weekly/monthly data, and AI analysis
  - **JSON Data**: Complete analysis data for external tools
  - **Timestamped files** for easy organization
  - **Professional formatting** ready for stakeholder reports

## 🏗️ Architecture

### Backend (Flask)
- **Framework**: Flask 3.0+
- **Analysis Engine**: Uses the same CLI pipeline (`se-cli analyze`)
- **File Handling**: Secure temporary file processing
- **Error Handling**: Comprehensive error reporting with user-friendly messages
- **Timeout Protection**: 5-minute analysis timeout

### Frontend (Pure HTML/CSS/JS)
- **Responsive Design**: Works on desktop and mobile
- **Modern UI**: Clean, professional interface
- **Real-time Updates**: Progress indicators and status feedback
- **No Build Process**: Pure HTML/CSS/JavaScript (no bundling required)

### Integration
- **CLI Wrapper**: Leverages existing `se-cli analyze` command
- **JSON API**: RESTful endpoints for analysis
- **File Security**: Sanitized uploads with extension validation

## 🔧 Configuration

### Environment Variables
The webapp uses the same `.env` file as the CLI:

```bash
# Required for price data
ENTSOE_API_KEY=your_entso_e_api_key_here

# Optional for AI features
OPENAI_API_KEY=your_openai_api_key_here

# Database (auto-created)
DATABASE_PATH=data/price_data.db
```

### Flask Settings
- **Max file size**: 16MB
- **Upload directory**: System temp directory
- **Debug mode**: Enabled in development
- **Host**: 0.0.0.0 (accessible from other devices on network)
- **Port**: 8080

## 📡 API Endpoints

### `GET /`
Renders the main web interface.

### `POST /analyze`
Performs production data analysis.

**Parameters** (form-data):
- `production_file`: CSV/Excel file (required)
- `area`: Electricity area code (default: SE_4)
- `currency`: Currency code (default: SEK)
- `force_api`: Boolean string for forcing API fetch (default: false)
- `ai_explainer`: Boolean string for AI analysis summary (default: false)

**Response**:
```json
{
  "success": true,
  "analysis": { ... },  // Full analysis results
  "metadata": {
    "filename": "production.csv",
    "granularity": "hourly",
    "area": "SE_4",
    "currency": "SEK",
    "analyzed_at": "2025-08-12T16:45:00.123456"
  }
}
```

### `GET /health`
Health check endpoint.

## 🐛 Troubleshooting

### Common Issues

1. **"No file uploaded" error**
   - Ensure file is selected before clicking analyze
   - Check file size is under 16MB

2. **"Analysis failed" error**
   - Verify ENTSOE_API_KEY is set in .env
   - Check if the production file format is supported
   - Try with `force_api` option if cached data seems stale

3. **"Analysis timed out" error**
   - Try with a smaller date range in your production file
   - The analysis has a 5-minute timeout limit

4. **"Invalid file type" error**
   - Only CSV and Excel files (.xlsx, .xls) are supported
   - Check the file extension

### Performance Tips
- **Caching**: The first analysis for a date range will be slower (API fetch)
- **Subsequent analyses**: Much faster due to price data caching
- **File size**: Smaller files process faster, but 16MB limit is generous
- **Network**: Ensure stable internet for ENTSO-E API access

## 🔒 Security

### File Upload Security
- **Extension validation**: Only allows CSV/Excel files
- **Filename sanitization**: Uses werkzeug secure_filename
- **Temporary storage**: Files are deleted immediately after processing
- **Size limits**: 16MB maximum upload size

### Process Security
- **Subprocess isolation**: CLI runs in separate process
- **Timeout protection**: Prevents runaway analyses
- **Error isolation**: Backend errors don't crash the webapp

## 🎯 Use Cases

### ☀️ Solar Producers
- Upload solar production data from monitoring systems
- Understand revenue impact of negative pricing
- Identify optimal curtailment strategies
- Track performance vs market prices

### ⚡ Energy Traders
- Analyze production timing vs price patterns
- Calculate opportunity costs of current strategies
- Evaluate battery storage scenarios
- Generate reports for stakeholders

### 🏢 Portfolio Managers
- Batch analyze multiple production sites
- Compare performance across different areas
- Export data for further analysis
- Monitor negative price exposure

## 🚧 Development

### Adding Features
The webapp is designed to be simple and extensible:
- **Backend**: Add new routes in `app.py`
- **Frontend**: Modify `templates/index.html`
- **CLI Integration**: Extend the subprocess calls to use new CLI features

### Testing
```bash
# Test imports
python -c "import app; print('✅ App imports OK')"

# Test CLI integration
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json

# Test web server (manual)
uv run python run_webapp.py
# Then visit http://localhost:5000
```