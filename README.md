# BodaccScrap

A Python data pipeline that tracks **French court-ordered liquidations** published in the BODACC
(the official bulletin of civil and commercial notices) and the **vehicles put up for sale** by the
court-appointed liquidators handling them. A second collector does the same for Spain (BORME and the
eactivos.com judicial auction platform).

Everything is collected from public, open sources, stored in SQLite with its history, and re-runs
only report what is new.

> Code comments and command-line messages are in French.

## Pipeline

```
BODACC open-data API                     Liquidators' websites (Gemweb RSS feeds)
  daily liquidation notices                       assets for sale
        │                                               │
        ▼                                               ▼
  extract the liquidator   ──►   registry of firms   ◄──   free-text description:
  from the court's free text     (config/cabinets.json)    make, registration, mileage, year, fuel
        │                                               │
        └───────────────► SQLite database ◄────────────┘
                        first_seen / last_seen
                                │
              python -m bodacc.update   → what's new today
              python -m bodacc.report   → filtered tables, CSV / Excel exports
```

1. **Liquidations** are read day by day from the BODACC open-data API.
2. **The liquidator** is extracted from the court's free text (regular expressions handling many
   real-world wordings and typos), then matched against a registry of firms with a known website.
3. **Assets for sale** are read from those firms' RSS feeds.
4. **Vehicles** are detected, then make, model, registration, mileage, year and fuel are parsed from
   the free-text description.
5. Every record keeps `first_seen` (never modified) and `last_seen`. Re-running never creates
   duplicates (idempotent upserts) and only reports new items.

## Features

- **French collector** (`bodacc`): BODACC API client, liquidator extraction, cabinet matching with
  normalisation (legal forms, accents, initials, aliases), Gemweb RSS scraper, vehicle parser.
- **Registry discovery** (`bodacc.find_cabinets`): finds the website of unknown liquidators through the
  official directory, and only adds it once its RSS feed is verified.
- **Reporting** (`bodacc.report`): multi-criteria filters (make, year, price, mileage, fuel, place,
  firm), multi-key sorting, CSV and Excel (`openpyxl`) exports.
- **Market price enrichment** (`--market`): median asking price of comparable listings through a
  third-party API (key in a git-ignored `.env`).
- **Spanish collector** (`es`): BORME insolvency acts via the BOE open-data API (court, judge,
  procedure, insolvency administrator), vehicle lots from eactivos.com read from its sitemap, and
  links between lots and BORME acts.
- **Polite scraping**: `robots.txt` checked before requests, one request per second, only extracted
  facts are stored (no images, no copies of pages).
- **Tests**: 500+ `pytest` tests, network calls mocked.

## Installation

Python 3.11+ (tested with 3.14), Windows / PowerShell shown.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . pytest beautifulsoup4
copy .env.example .env   # optional: only needed for --market
```

## Usage

```powershell
# France
.\.venv\Scripts\python.exe -m bodacc.update --period last_7_days
.\.venv\Scripts\python.exe -m bodacc.report vehicles --max-price 20000 --max-km 50000 --sort km
.\.venv\Scripts\python.exe -m bodacc.report vehicles --marque renault --min-year 2018 --xlsx data\exports\vehicles.xlsx
.\.venv\Scripts\python.exe -m bodacc.report unmatched          # liquidators not yet in the registry
.\.venv\Scripts\python.exe -m bodacc.find_cabinets --top 40    # look for their websites

# Spain
.\.venv\Scripts\python.exe -m es.update --period last_7_days
.\.venv\Scripts\python.exe -m es.report vehicles --lieu madrid --sort price
.\.venv\Scripts\python.exe -m es.report liquidations --type liquidation
```

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Project layout

```
config/cabinets.json      registry of liquidator firms with a Gemweb site (name, domain, aliases)
src/bodacc/               French pipeline: collectors, parsing, storage, reporting
src/es/                   Spanish pipeline: BORME, eactivos, storage, reporting
tests/                    pytest suite (fixtures are anonymised)
data/                     local database and exports (git-ignored)
```

## Data and privacy

Only public data is collected. The database, exports and API keys stay local and are excluded from
git. Names, addresses, identifiers and registration plates in the test fixtures are fictional.
