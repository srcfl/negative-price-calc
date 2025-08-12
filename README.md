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

The modern entrypoint is the `se-cli` analyze command (auto-detects hourly vs daily totals and approximates daily to an hourly shape for analysis):

```bash
# Lean storytelling JSON (default sections: hero, aggregates (weekly+monthly), diagnostics, scenarios, meta, input)
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json > lean.json

# Full storytelling JSON (includes hourly series, per-day arrays, distributions, extremes)
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json --json-full > full.json

# Custom subset (only hero + distributions)
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json --json-sections hero,distributions > custom.json

# Export excluded heavy sections (e.g. hourly) to parquet artifacts directory while keeping lean JSON
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json --json-artifacts data/artifacts > lean_with_refs.json

# Include Swedish energy tax / grid fees & VAT for self-consumption valuation
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json \
	--energy-tax 0.39 --transmission-fee 0.20 --vat 25 > with_costs.json

# Override battery capacities and power & use fee-inclusive decision basis
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json \
	--battery-capacities 12,18 --battery-power-kw 3 --battery-decision-basis spot_plus_fees > battery_custom.json

# Inspect a production file format (no prices fetched)
uv run se-cli inspect-production "data/samples/Produktion - Viktor hourly.csv"
```

Legacy `main.py` options still exist but are being phased out in favor of `se-cli`.

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
