# Negative Price Calculator

En Python-applikation för att analysera elpriser och solcellsproduktion, med fokus på negativa priser och kostnadskalkylering.

## Features

- **🔌 Prisdata från ENTSO-E**: Automatisk hämtning med lokal cache
- **📊 CSV Format Detection**: AI-driven och traditionell CSV-parsing  
- **💸 Negativ Prisanalys**: Detaljerad kostnadskalkyl för negativa prisperioder
- **🌐 Webbgränssnitt**: Enkelt drag-and-drop interface för analys
- **💱 Multi-valuta**: EUR, SEK, USD, NOK, etc.
- **🤖 AI-förklaringar**: OpenAI-drivna sammanfattningar på svenska
- **🔋 Batterisimulering**: Analys av energilagring för optimering
- **📈 Omfattande rapportering**: JSON-export med detaljerade insikter

## Installation

Detta projekt använder [uv](https://docs.astral.sh/uv/) för dependency management:

```bash
# Klona repository
git clone https://github.com/srcfl/negative-price-calc.git
cd negative-price-calc

# Installera dependencies
uv sync

# Kopiera environment template
cp .env.example .env
# Redigera .env med dina API-nycklar
```

## Konfiguration

Skapa en `.env`-fil med dina API-nycklar:

```bash
# Krävs för ENTSO-E prisdata
ENTSOE_API_KEY=your_entso_e_api_key_here

# Krävs för AI-funktioner (OpenAI)
OPENAI_API_KEY=your_openai_api_key_here

# Valfritt: Databaskonfiguration
DATABASE_PATH=data/price_data.db
```

## Användning

### 🌐 Webbgränssnitt

För enkel analys med grafiskt interface:

```bash
# Starta webbapplikationen
uv run python run_webapp.py

# Öppna sedan din webbläsare på: http://localhost:8080
```

Funktioner:
- **📁 Drag & drop** filuppladdning (CSV/Excel)
- **⚙️ Interaktiv konfiguration** (område, valuta, inställningar)  
- **🤖 AI-driven analys** med svenska sammanfattningar
- **📊 Visuell resultatdashboard** med nyckeltal
- **💾 Excel & JSON export** för rapporter och vidare analys
- **📱 Mobilanpassad** responsiv design

Se [WEBAPP.md](WEBAPP.md) för detaljerad dokumentation.

### Kommandoradsinterface (CLI)

Modern CLI med `se-cli`-kommando (auto-detekterar timvis vs daglig data och approximerar daglig till timvis för analys):

```bash
# Grundläggande JSON-analys (standard: hero, aggregates, diagnostics, scenarios, meta, input)
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json > lean.json

# Fullständig JSON-analys (inkluderar timvis data, per-dag arrays, distributioner, extremer)
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json --json-full > full.json

# Anpassad subset (endast hero + distributioner)
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json --json-sections hero,distributions > custom.json

# Exportera tunga sektioner till parquet-filer, behåll lean JSON
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json --json-artifacts data/artifacts > lean_with_refs.json

# Inkludera svenska skatter/nätavgifter & moms för egenförbrukning
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json \
	--energy-tax 0.39 --transmission-fee 0.20 --vat 25 > with_costs.json

# Anpassad batterikonfiguration med avgifts-inkluderande beslutsgrund
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json \
	--battery-capacities 12,18 --battery-power-kw 3 --battery-decision-basis spot_plus_fees > battery_custom.json

# Inspektera produktionsfil (inga priser hämtas)
uv run se-cli inspect-production "data/samples/Produktion - Viktor hourly.csv"

# AI-förklaring på svenska (kräver OPENAI_API_KEY)
uv run se-cli analyze "data/samples/Produktion - Viktor hourly.csv" --area SE_4 --json --ai-explainer > with_ai.json
```

Legacy `main.py` finns kvar men fasas ut till förmån för `se-cli`.

### Python API

```python
from core.price_fetcher import PriceFetcher
from core.production_loader import ProductionLoader

# Initialisera komponenter
fetcher = PriceFetcher()
loader = ProductionLoader()

# Ladda data
production_df, granularity = loader.load_production('your_file.csv', use_llm=True)
prices_df = fetcher.get_price_data('SE_4', start_date, end_date)

# För storytelling JSON, använd CLI-funktionerna
from cli.main import build_storytelling_payload
import pandas as pd

# Slå ihop data och skapa payload
merged_df = pd.DataFrame({'prod_kwh': production_df['production_kwh']}).join(
    (prices_df['price_eur_per_mwh'] * 11.5 / 1000).to_frame('sek_per_kwh'), 
    how='left'
)
payload = build_storytelling_payload(merged_df, 'SEK', 11.5, granularity)
```

## Projektstruktur

```
negative-price-calc/
├── core/                           # Kärnlogik
│   ├── price_fetcher.py           # ENTSO-E API integration
│   ├── production_loader.py       # CSV produktionsdata loader
│   ├── price_analyzer.py          # Analysmotor
│   ├── db_manager.py              # SQLite databashantering
│   └── negative_price_analysis.py  # Negativ prisanalys
├── cli/                            # Kommandoradsinterface
│   └── main.py                    # Modern se-cli entrypoint
├── utils/                          # Utility-moduler
│   ├── csv_format_detector_fallback.py  # Traditionell CSV detection
│   ├── csv_format_module.py             # LLM-driven CSV detection
│   ├── ai_explainer.py                  # AI-analysförklaringar
│   └── ai_table_reader.py               # AI-tabellläsning
├── templates/                      # HTML-mallar för webbapp
│   └── index.html                 # Huvudsida för webapp
├── data/                          # Datakatalog
│   ├── price_data.db             # SQLite databas (auto-skapad)
│   ├── cache/                    # Temporär cache
│   └── samples/                  # Exempelfiler
├── app.py                         # Flask webbapplikation
├── run_webapp.py                  # Webapp launcher
├── main.py                        # Legacy CLI (fasas ut)
├── pyproject.toml                # Projektkonfiguration
└── .env.example                  # Environment template
```

## Beroenden

- **pandas>=2.0.0**: Datamanipulation och analys
- **numpy>=1.24.0**: Numeriska beräkningar
- **requests>=2.31.0**: HTTP-anrop för API:er
- **python-dotenv>=1.0.0**: Environment variable hantering
- **openai>=1.0.0**: AI-funktioner
- **chardet>=5.0.0**: Teckenkodnings-detection
- **entsoe-py>=0.6.9**: ENTSO-E API-klient
- **openpyxl>=3.1.2**: Excel-filhantering
- **flask>=3.0.0**: Webbapplikationsramverk

## Docker Deployment

För enkel deployment med Docker:

```bash
# Kopiera environment template och konfigurera API-nycklar
cp .env.example .env
# Redigera .env med dina ENTSOE_API_KEY och OPENAI_API_KEY

# Bygg och starta applikationen
docker-compose up --build

# Öppna sedan din webbläsare på: http://localhost:8080
```

Docker-containern:
- **🐳 Automatisk setup** med alla dependencies
- **💾 Persistent data** via volumes för databas och cache
- **🔄 Health checks** för tillgänglighet
- **🔒 Säker konfiguration** via environment variabler
- **📱 Produktionsredo** för deployment

## Utveckling

Installera utvecklingsberoenden:

```bash
uv sync --dev
```

Kör kodformattering:

```bash
uv run black .
uv run isort .
```

Kör linting:

```bash
uv run flake8
```

Kör tester:

```bash
uv run pytest
```

Starta development server:

```bash
# Webbapplikation
uv run python run_webapp.py

# Eller direkt via CLI
uv run se-cli analyze --help
```

## Områdeskoder

Vanliga elområdeskoder för nordiska länder:

- **SE_1**: Norra Sverige (Luleå)
- **SE_2**: Mellersta Sverige (Sundsvall)  
- **SE_3**: Mellersta Sverige (Stockholm)
- **SE_4**: Södra Sverige (Malmö)
- **NO_1**: Östra Norge (Oslo)
- **NO_2**: Södra Norge (Kristiansand)
- **DK_1**: Västra Danmark (Jylland)
- **DK_2**: Östra Danmark (Köpenhamn)

## Datakällor

- **Prisdata**: ENTSO-E Transparency Platform API
- **Produktionsdata**: CSV-filer från solcellsövervakningssystem
- **AI-funktioner**: OpenAI GPT-modeller för förklaringar
- **Cache**: Lokal SQLite-databas för prishistorik

## Licens

Detta projekt är licensierat under MIT License.

## Support

För frågor eller problem, öppna en issue på [GitHub](https://github.com/srcfl/negative-price-calc/issues).

## Changelog

- **v0.1.1**: Webbgränssnitt, AI-förklaringar, batterisimulering
- **v0.1.0**: Grundläggande CLI och prisanalys
