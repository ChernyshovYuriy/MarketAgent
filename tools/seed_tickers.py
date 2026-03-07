"""
tools/seed_tickers.py
Seeds the local ticker database from a CSV file or fetches a basic
list from Yahoo Finance for TSX/TSXV symbols.

Usage:
    python tools/seed_tickers.py [--csv tickers.csv] [--fetch]
"""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from storage import Database

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Sample seed tickers for testing (major TSX stocks)
SAMPLE_TICKERS = [
    {"ticker": "RY.TO", "exchange": "TSX", "company_name": "Royal Bank of Canada",
     "sector": "Financials", "average_volume": 4000000, "market_cap": 180e9,
     "last_price": 132.0, "spread_estimate": 0.02},
    {"ticker": "TD.TO", "exchange": "TSX", "company_name": "Toronto-Dominion Bank",
     "sector": "Financials", "average_volume": 3500000, "market_cap": 150e9,
     "last_price": 82.0, "spread_estimate": 0.02},
    {"ticker": "BNS.TO", "exchange": "TSX", "company_name": "Bank of Nova Scotia",
     "sector": "Financials", "average_volume": 3000000, "market_cap": 80e9,
     "last_price": 66.0, "spread_estimate": 0.03},
    {"ticker": "CNR.TO", "exchange": "TSX", "company_name": "Canadian National Railway",
     "sector": "Industrials", "average_volume": 1500000, "market_cap": 100e9,
     "last_price": 157.0, "spread_estimate": 0.02},
    {"ticker": "SU.TO", "exchange": "TSX", "company_name": "Suncor Energy",
     "sector": "Energy", "average_volume": 6000000, "market_cap": 55e9,
     "last_price": 53.0, "spread_estimate": 0.02},
    {"ticker": "ABX.TO", "exchange": "TSX", "company_name": "Barrick Gold",
     "sector": "Materials", "average_volume": 5000000, "market_cap": 34e9,
     "last_price": 23.0, "spread_estimate": 0.03},
    {"ticker": "ENB.TO", "exchange": "TSX", "company_name": "Enbridge",
     "sector": "Energy", "average_volume": 4500000, "market_cap": 95e9,
     "last_price": 56.0, "spread_estimate": 0.02},
    {"ticker": "CP.TO", "exchange": "TSX", "company_name": "Canadian Pacific Kansas City",
     "sector": "Industrials", "average_volume": 1200000, "market_cap": 86e9,
     "last_price": 97.0, "spread_estimate": 0.02},
    {"ticker": "BAM.TO", "exchange": "TSX", "company_name": "Brookfield Asset Management",
     "sector": "Financials", "average_volume": 2000000, "market_cap": 80e9,
     "last_price": 60.0, "spread_estimate": 0.02},
    {"ticker": "WPM.TO", "exchange": "TSX", "company_name": "Wheaton Precious Metals",
     "sector": "Materials", "average_volume": 1800000, "market_cap": 30e9,
     "last_price": 65.0, "spread_estimate": 0.03},
    # TSXV samples
    {"ticker": "TELO.V", "exchange": "TSXV", "company_name": "Telo Genomics",
     "sector": "Health Care", "average_volume": 250000, "market_cap": 50e6,
     "last_price": 1.50, "spread_estimate": 1.5},
    {"ticker": "VCI.V", "exchange": "TSXV", "company_name": "Vaccinex",
     "sector": "Health Care", "average_volume": 220000, "market_cap": 30e6,
     "last_price": 2.10, "spread_estimate": 1.8},
]


def _normalise_aliases(raw: str, ticker: str) -> str:
    """
    Convert whatever the CSV supplies in the 'aliases' column into a
    valid JSON array string that database.py can store and read back.

    Handles:
      - empty / missing value  → derive base symbol from ticker
      - already valid JSON     → use as-is
      - plain string "RY"      → wrap in a list: ["RY"]
      - comma-separated "RY,RY.TO" → split and wrap: ["RY", "RY.TO"]
    """
    raw = (raw or "").strip()

    if not raw:
        base = ticker.split(".")[0]
        return json.dumps([base])

    # Already a JSON array?
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return json.dumps([str(a).strip() for a in parsed if str(a).strip()])
        # JSON scalar (e.g. "\"RY\"") — wrap it
        return json.dumps([str(parsed).strip()])
    except (json.JSONDecodeError, ValueError):
        pass

    # Plain text — may be comma-separated
    items = [a.strip() for a in raw.split(",") if a.strip()]
    return json.dumps(items)


def seed_from_sample(db: Database):
    logger.info("Seeding %d sample tickers...", len(SAMPLE_TICKERS))
    for ticker in SAMPLE_TICKERS:
        ticker["aliases"] = json.dumps([ticker["ticker"].split(".")[0]])
        db.upsert_ticker(ticker)
    logger.info("Sample tickers loaded.")


def seed_from_csv(db: Database, csv_path: str):
    """
    Expected CSV columns:
    ticker, exchange, company_name, aliases, sector,
    average_volume, market_cap, last_price, spread_estimate
    """
    loaded = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalise numeric fields
            for field in ("average_volume", "market_cap",
                          "last_price", "spread_estimate"):
                try:
                    row[field] = float(row.get(field, 0) or 0)
                except ValueError:
                    row[field] = 0.0

            # Always store aliases as a valid JSON array string
            row["aliases"] = _normalise_aliases(
                row.get("aliases", ""), row.get("ticker", "")
            )

            db.upsert_ticker(row)
            loaded += 1
    logger.info("Loaded %d tickers from %s", loaded, csv_path)


def main():
    parser = argparse.ArgumentParser(description="Seed ticker universe")
    parser.add_argument("--csv", help="Path to ticker CSV file")
    parser.add_argument("--sample", action="store_true",
                        help="Load built-in sample TSX tickers")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    db = Database(config["database"]["path"])

    if args.csv:
        seed_from_csv(db, args.csv)
    else:
        seed_from_sample(db)

    count = len(db.get_ticker_symbols())
    logger.info("Ticker universe now contains %d symbols.", count)


if __name__ == "__main__":
    main()
