# ⚡ Negative Price Calculator

A simple web application to analyze electricity prices and solar production data, with focus on negative price detection and cost analysis for solar producers in Sweden.

**[Quick Start →](QUICKSTART.md)** | **[Live Demo](http://localhost:8080)** (after running locally)

<img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+">
<img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License">
<img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome">

---

## 🎯 What is this?

When you have solar panels, you often sell excess electricity back to the grid. But sometimes electricity prices go **negative** - meaning you actually pay to export your energy! This tool helps you:

- 📊 **Analyze your production data** - Upload your solar production CSV/Excel file
- 💸 **Detect negative price periods** - See when your export cost you money
- 📈 **Visualize the impact** - Interactive charts showing monthly patterns
- 🤖 **Get AI insights** (optional) - Swedish-language explanations of your analysis
- 💾 **Export results** - Download detailed Excel reports

## ✨ Key Features

- **🔌 No API keys required** - Uses free [Sourceful Price API](https://docs.sourceful.energy/developer/price-api)
- **🌍 Webapp interface** - Simple drag-and-drop file upload
- **🇸🇪 Swedish electricity areas** - Supports SE_1 through SE_4
- **🤖 Optional AI explanations** - Add OpenAI key for AI-powered insights
- **📊 Visual analytics** - Charts and metrics at a glance
- **💾 Excel export** - Detailed analysis export
- **🚀 Easy deployment** - Docker support included

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### Install & Run (3 steps!)

```bash
# 1. Clone the repository
git clone https://github.com/srcfl/negative-price-calc.git
cd negative-price-calc

# 2. Install dependencies
uv sync

# 3. Start the webapp
uv run python app.py
```

Open your browser and go to `http://localhost:8080` 🎉

**That's it!** No API keys needed for basic analysis.

### Optional: Enable AI Explanations

Want AI-powered insights? Just add your OpenAI API key:

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add: OPENAI_API_KEY=your_key_here
```

Restart the webapp and AI explanations will appear automatically!

## 🐳 Docker Deployment

```bash
# Build and run with docker-compose
docker-compose up --build

# Open http://localhost:8080
```

## 📖 How to Use

1. **Upload your data**: CSV or Excel file with solar production (hourly or daily)
2. **Select electricity area**: SE_1, SE_2, SE_3, or SE_4
3. **Click "Analysera"**: Results appear in seconds
4. **Review insights**: See negative price impact, timing losses, and more
5. **Export if needed**: Download Excel report for deeper analysis

### Supported File Formats

The tool intelligently handles various CSV/Excel formats. Your file should have:
- **Timestamp/Date column**: DateTime or date values
- **Production column**: Energy produced in kWh

Common column names are automatically detected (timestamp, date, production, kwh, etc.)

### Example Files

Try it out with sample files in `data/samples/` directory!

## 🏗️ Architecture

### Simple Structure

```
negative-price-calc/
├── app.py                      # Flask webapp (start here!)
├── cli/                        # Command-line interface
│   └── main.py                # CLI entrypoint
├── core/                       # Analysis engine
│   ├── price_fetcher.py       # Sourceful API integration
│   ├── production_loader.py   # CSV/Excel parser
│   └── price_analyzer.py      # Core analysis logic
├── templates/                  # HTML templates
│   └── index.html             # Main webapp UI
└── data/                       # Data storage
    ├── price_data.db          # SQLite price cache
    └── samples/               # Example files
```

### Technology Stack

- **Backend**: Flask + Python 3.12
- **Price Data**: [Sourceful API](https://docs.sourceful.energy/developer/price-api) (free, no key required)
- **AI**: OpenAI GPT (optional)
- **Storage**: SQLite for price caching
- **Frontend**: Modern HTML/CSS/JS with drag-and-drop

## 🇸🇪 Swedish Electricity Areas

- **SE_1**: Northern Sweden (Luleå) - Typically lowest prices
- **SE_2**: Central Sweden (Sundsvall)
- **SE_3**: Central Sweden (Stockholm)
- **SE_4**: Southern Sweden (Malmö) - Highest price volatility

## 📊 What Analysis is Provided?

### Key Metrics

- **Total Production**: Your solar output (kWh)
- **Total Revenue**: Income from electricity export
- **Negative Price Hours**: When export cost money
- **Timing Loss**: How much below market average you received
- **Monthly Breakdown**: Visual charts showing patterns

### AI Insights (Optional)

With OpenAI API key configured:
- Swedish-language explanation of your results
- Key recommendations
- Problem areas highlighted

## 🛠️ Development

### CLI Usage

Want command-line access instead of webapp?

```bash
# Analyze with CLI
uv run se-cli analyze your_file.csv --area SE_4 --json

# With AI explanations
uv run se-cli analyze your_file.csv --area SE_4 --json --ai-explainer

# Inspect file format
uv run se-cli inspect-production your_file.csv
```

### Run Tests

```bash
uv run pytest
```

### Code Formatting

```bash
uv run black .
uv run isort .
```

## 🤝 Contributing

Contributions are welcome! This is an open source project for the solar community.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Optional | Enables AI-powered explanations |
| `DATABASE_PATH` | Optional | Custom SQLite database path (default: `data/price_data.db`) |

**Note**: Electricity price data comes from Sourceful API which requires no API key!

## 🐛 Troubleshooting

### Port 8080 in use?
```bash
# Run on different port
uv run python -c "from app import app; app.run(host='0.0.0.0', port=5000)"
```

### File upload fails?
- Check file size (max 16MB)
- Ensure valid CSV or Excel format
- Try with sample files in `data/samples/`

### Analysis seems wrong?
- Verify your electricity area is correct
- Check that your file has proper date/production columns
- Use `se-cli inspect-production` to validate file format

## 📚 Resources

- **Sourceful Price API**: https://docs.sourceful.energy/developer/price-api
- **Nordic Energy Markets**: https://www.nordpoolgroup.com/
- **Swedish Energy Agency**: https://www.energimyndigheten.se/

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Price data powered by [Sourceful Energy API](https://sourceful.energy)
- Built for the solar producer community in Sweden
- Inspired by real challenges facing solar panel owners

## 📮 Support

- 🐛 **Bug reports**: [Open an issue](https://github.com/srcfl/negative-price-calc/issues)
- 💡 **Feature requests**: [Start a discussion](https://github.com/srcfl/negative-price-calc/discussions)
- 📖 **Questions**: Check [QUICKSTART.md](QUICKSTART.md) or open an issue

---

**Made with ❤️ for the solar energy community** | [GitHub](https://github.com/srcfl/negative-price-calc)
