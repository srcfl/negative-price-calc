# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Setup and Dependencies
```bash
# Install all dependencies
uv sync

# Install with development dependencies  
uv sync --dev
```

### Testing
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest test_core.py
```

### Code Quality
```bash
# Format code
uv run black .
uv run isort .

# Run linting
uv run flake8
```

### Application Commands
```bash
# Modern CLI (preferred)
uv run se-cli analyze [file] --area [area] --json

# Legacy CLI (being phased out)
uv run python main.py

# Web application
uv run python run_webapp.py

# Web application (alternative)
uv run python app.py
```

## Architecture Overview

### Core Architecture
This is an electricity price analysis tool focused on negative price detection and solar production optimization. The system has three main entry points:

1. **CLI Interface** (`cli/main.py`) - Modern command-line interface with `se-cli` command
2. **Web Interface** (`app.py`) - Flask-based web application with drag-and-drop file upload
3. **Legacy CLI** (`main.py`) - Original CLI being phased out

### Key Components

**Data Layer:**
- `core/price_fetcher.py` - ENTSO-E API integration with SQLite caching
- `core/production_loader.py` - CSV/Excel production data loader with AI-assisted parsing
- `core/db_manager.py` - SQLite database management for price data caching

**Analysis Engine:**
- `core/price_analyzer.py` - Core price analysis algorithms
- `core/negative_price_analysis.py` - Specialized negative price detection
- `core/price_production_analyzer.py` - Combined price and production analysis

**AI Components:**
- `utils/ai_explainer.py` - OpenAI-powered Swedish explanations of analysis results
- `utils/ai_table_reader.py` - LLM-driven CSV format detection and parsing
- `utils/csv_format_detector_fallback.py` - Traditional CSV parsing fallback

### Data Flow Pattern

1. **Input**: CSV/Excel files containing solar production data (hourly or daily)
2. **Price Data**: Automatic fetching from ENTSO-E API based on date range and area
3. **Analysis**: Combined analysis of production patterns and electricity prices
4. **Output**: Structured JSON with storytelling format, AI explanations, and export options

### Key Features

- **Multi-granularity Support**: Handles both hourly and daily production data
- **Intelligent CSV Parsing**: AI-assisted format detection for various CSV schemas
- **Negative Price Analysis**: Specialized algorithms for negative electricity price scenarios
- **Battery Simulation**: Energy storage optimization calculations
- **Multi-currency Support**: EUR, SEK, USD, NOK with configurable exchange rates
- **Area Code Mapping**: Swedish electricity areas (SE_1 through SE_4) with Nordic support

### Environment Configuration

Required environment variables in `.env`:
- `ENTSOE_API_KEY` - Required for ENTSO-E price data
- `OPENAI_API_KEY` - Required for AI features
- `DATABASE_PATH` - Optional, defaults to `data/price_data.db`

### File Processing Patterns

The system expects production data in these formats:
- **Hourly data**: Timestamp + production_kwh columns
- **Daily data**: Date + production_kwh columns (automatically approximated to hourly)
- **Flexible schemas**: AI parser handles various column names and formats

### Output Schema

The CLI generates structured JSON with these main sections:
- `hero` - Key metrics and counterfactuals
- `aggregates` - Monthly/yearly summaries  
- `diagnostics` - Data quality metrics
- `scenarios` - Battery optimization results
- `distributions` - Statistical distributions
- `meta` - Analysis metadata

### API Integration Notes

- **ENTSO-E API**: Cached in SQLite to minimize API calls
- **OpenAI API**: Uses direct HTTP requests, configurable model
- **Area codes**: Normalized from various formats (SE1, SE_1, SE-1 all map to SE_1)

### Testing Strategy

- Unit tests in `test_core.py` for core functionality
- Simple OpenAI integration test in `test_openai_simple.py`
- Test data samples in `data/samples/` directory