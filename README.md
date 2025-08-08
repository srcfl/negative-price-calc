# Negative Price Calculator

A Python application for analyzing electricity prices and solar production data, focusing on negative price detection and cost analysis.

## Features

- **Price Data Fetching**: Automatic retrieval from ENTSO-E API with local caching
- **CSV Format Detection**: Both traditional and AI-powered CSV parsing
- **Negative Price Analysis**: Detailed cost analysis for negative price periods  
- **Multi-currency Support**: EUR, SEK, USD, NOK, etc.
- **AI Explanations**: OpenAI-powered analysis summaries in Swedish
- **Database Management**: SQLite storage with automatic schema creation

## Installation

This project uses [uv](https://docs.astral.sh/uv/) for dependency management:

```bash
# Clone the repository
git clone <repository-url>
cd negative-price-calc

# Install dependencies
uv sync

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

## Configuration

Create a `.env` file with your API keys:

```bash
# Required for ENTSO-E price data fetching
ENTSOE_API_KEY=your_entso_e_api_key_here

# Required for AI features (OpenAI)
OPENAI_API_KEY=your_openai_api_key_here

# Optional: Database configuration
DATABASE_PATH=data/price_data.db
```

## Usage

### Command Line Interface

```bash
# Basic analysis
uv run python main.py --production-file data/production.csv --area SE_4

# Specific date range
uv run python main.py --production-file data/production.csv --area SE_4 --start-date 2024-06-01 --end-date 2024-06-30

# With AI explanation
uv run python main.py --production-file data/production.csv --area SE_4 --ai-explain

# Save results to JSON
uv run python main.py --production-file data/production.csv --area SE_4 --output results.json
```

### Python API

```python
from core.price_fetcher import PriceFetcher
from core.production_loader import ProductionLoader
from core.price_analyzer import PriceAnalyzer

# Initialize components
fetcher = PriceFetcher()
loader = ProductionLoader()
analyzer = PriceAnalyzer()

# Load data
production_df = loader.load_production_data('your_file.csv')
prices_df = fetcher.get_price_data('SE_4', start_date, end_date)

# Analyze
merged_df = analyzer.merge_data(prices_df, production_df)
results = analyzer.analyze_data(merged_df)
```

## Project Structure

```
negative-price-calc/
├── core/                     # Core business logic
│   ├── price_fetcher.py      # ENTSO-E API integration
│   ├── production_loader.py  # CSV production data loader
│   ├── price_analyzer.py     # Analysis engine
│   └── db_manager.py         # SQLite database management
├── utils/                    # Utility modules
│   ├── csv_format_detector_fallback.py  # Traditional CSV detection
│   ├── csv_format_module.py             # LLM-powered CSV detection
│   └── ai_explainer.py                  # AI analysis explanation
├── data/                     # Data directory
│   ├── price_data.db         # SQLite database (auto-created)
│   └── cache/               # Temporary cache directory
├── main.py                   # CLI entry point
├── pyproject.toml           # Project configuration
└── .env.example             # Environment template
```

## Dependencies

- **pandas>=2.0.0**: Data manipulation and analysis
- **numpy>=1.24.0**: Numerical computing
- **requests>=2.31.0**: HTTP requests for API calls
- **python-dotenv>=1.0.0**: Environment variable management
- **openai>=1.0.0**: AI-powered features
- **chardet>=5.0.0**: Character encoding detection

## Development

Install development dependencies:

```bash
uv sync --dev
```

Run code formatting:

```bash
uv run black .
uv run isort .
```

Run linting:

```bash
uv run flake8
```

Run tests:

```bash
uv run pytest
```

## Area Codes

Common electricity area codes for Nordic countries:

- **SE_1**: Northern Sweden (Luleå)
- **SE_2**: Central Sweden (Sundsvall)  
- **SE_3**: Central Sweden (Stockholm)
- **SE_4**: Southern Sweden (Malmö)
- **NO_1**: Eastern Norway (Oslo)
- **NO_2**: Southern Norway (Kristiansand)
- **DK_1**: Western Denmark (Jutland)
- **DK_2**: Eastern Denmark (Copenhagen)

## Data Sources

- **Price Data**: ENTSO-E Transparency Platform API
- **Production Data**: CSV files from solar monitoring systems
- **AI Features**: OpenAI GPT models for explanations

## License

This project is licensed under the MIT License.

## Support

For questions or issues, please open an issue on the repository.
