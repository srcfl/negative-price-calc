# Quick Start Guide

Get the Negative Price Calculator webapp running in 3 easy steps!

## Prerequisites

- Python 3.12 or higher
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/srcfl/negative-price-calc.git
cd negative-price-calc
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Start the webapp

```bash
uv run python app.py
```

That's it! Open your browser and navigate to:

```
http://localhost:8080
```

## Using the Webapp

1. **Upload your production data**: Drag and drop or click to select your CSV or Excel file containing solar production data
2. **Select your electricity area**: Choose your Swedish electricity area (SE_1 to SE_4)
3. **Click "Analysera"**: The tool will analyze your data and show results

## Features

- ✅ **No API keys required** for basic analysis
- ✅ **Automatic price data fetching** from Sourceful API
- ✅ **Negative price detection** and cost analysis
- ✅ **Visual charts** and metrics
- ✅ **Excel export** for detailed analysis

## Optional: Enable AI Explanations

Want AI-powered Swedish explanations of your analysis? Just add an OpenAI API key:

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your OpenAI API key:
   ```
   OPENAI_API_KEY=your_key_here
   ```

3. Restart the webapp

That's it! The AI explanations will automatically appear in your analysis results.

## Supported File Formats

### CSV Format
Your CSV should have columns for:
- Date/timestamp
- Production (kWh)

The tool is smart and can handle various column names and formats!

### Excel Format
Both `.xlsx` and `.xls` files are supported.

## Electricity Areas

- **SE_1**: Northern Sweden (Luleå)
- **SE_2**: Central Sweden (Sundsvall)
- **SE_3**: Central Sweden (Stockholm)
- **SE_4**: Southern Sweden (Malmö)

## Troubleshooting

**Port 8080 already in use?**
```bash
# Use a different port
uv run python -c "from app import app; app.run(host='0.0.0.0', port=5000)"
```

**File upload fails?**
- Make sure your file is under 16MB
- Check that it's a valid CSV or Excel file

**Analysis takes too long?**
- Large files may take a few minutes to process
- The tool supports files with up to several years of data

## Need Help?

Check out the full [README.md](README.md) for more detailed information, or open an issue on GitHub.

## Example Data

Want to try it out? Sample files are included in `data/samples/` directory.

## What's Next?

- View your negative price analysis
- Export results to Excel
- Understand your timing losses
- See AI-powered insights (if OpenAI key is configured)

---

Made with ❤️ for the solar energy community
