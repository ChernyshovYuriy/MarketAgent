#!/usr/bin/env python3
"""
main.py
Entry point for the Canadian Market Opportunity Detection Agent.

Usage:
    python main.py                   # Continuous polling mode
    python main.py --once            # Run a single cycle then exit
    python main.py --config path.yaml
    python main.py --seed-tickers    # Seed sample tickers and exit
    python main.py --print-watchlist # Print current watchlist
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Project root on path
sys.path.insert(0, str(Path(__file__).parent))


def setup_logging(level: str = "INFO", log_file: str = "logs/agent.log"):
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5
        ),
    ]
    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format=fmt, handlers=handlers)


def main():
    import logging.handlers  # noqa: needed for RotatingFileHandler

    parser = argparse.ArgumentParser(
        description="Canadian Market Opportunity Detection Agent"
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to config.yaml (default: config.yaml)"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single collection cycle then exit"
    )
    parser.add_argument(
        "--seed-tickers", action="store_true",
        help="Seed the ticker universe with sample data then exit"
    )
    parser.add_argument(
        "--print-watchlist", action="store_true",
        help="Print the current watchlist JSON and exit"
    )
    parser.add_argument(
        "--log-level", default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level from config"
    )
    args = parser.parse_args()

    # Load config to get log level
    import yaml
    with open(args.config) as f:
        config = yaml.safe_load(f)

    log_level = args.log_level or config.get("agent", {}).get("log_level", "INFO")
    setup_logging(log_level)

    # ---- Commands --------------------------------------------------------

    if args.seed_tickers:
        from tools.seed_tickers import seed_from_sample
        from storage import Database
        db = Database(config["database"]["path"])
        seed_from_sample(db)
        print(f"Seeded {len(db.get_ticker_symbols())} tickers.")
        return

    if args.print_watchlist:
        from storage import Database
        db = Database(config["database"]["path"])
        watchlist = db.get_watchlist()
        print(json.dumps(watchlist, indent=2, default=str))
        return

    if args.once:
        from agents.market_agent import MarketAgent
        agent = MarketAgent(args.config)
        stats = agent.run_cycle()
        print("\n=== Cycle complete ===")
        print(json.dumps(stats, indent=2))
        # Print top watchlist entries
        from storage import Database
        db = Database(config["database"]["path"])
        top = db.get_watchlist(label="HIGH_PRIORITY")[:10]
        if top:
            print("\n=== HIGH PRIORITY ===")
            for entry in top:
                print(f"  {entry['ticker']:10s}  {entry['score']:5.1f}  {entry['reason']}")
        return

    # ---- Continuous mode -------------------------------------------------
    from agents.scheduler import run as run_scheduler
    run_scheduler(args.config)


if __name__ == "__main__":
    import logging.handlers

    main()
