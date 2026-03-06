# Canadian Market Opportunity Detection Agent

A lightweight automated monitoring agent that continuously scans public
Canadian financial news and SEDAR+ regulatory filings, detects TSX/TSXV
ticker mentions, classifies events, scores them, and outputs a ranked
watchlist of trading opportunities.

Designed to run continuously on a **Jetson Nano (4 GB RAM)** with minimal
CPU and memory usage.

---

## Architecture

```
ca_market_agent/
├── collector/
│   ├── base_collector.py        # Base class with retry/backoff
│   ├── yahoo_collector.py       # Yahoo Finance RSS
│   ├── globenews_collector.py   # GlobeNewswire RSS (Canada feed)
│   ├── prnews_collector.py      # PR Newswire (Canadian filter)
│   ├── businesswire_collector.py
│   ├── sedar_collector.py       # SEDAR+ regulatory filings
│   └── macro_collector.py       # Bank of Canada RSS
├── core/
│   ├── symbol_resolver.py       # Text → TSX/TSXV ticker mapping
│   ├── event_classifier.py      # Event type + catalyst score
│   ├── sentiment_analyzer.py    # Keyword-based [-1, +1] scorer
│   ├── event_scorer.py          # Multi-factor 0–100 scorer
│   ├── liquidity_filter.py      # Price / volume / spread filter
│   └── deduplicator.py          # URL / headline / cosine dedup
├── storage/
│   └── database.py              # SQLite persistence layer
├── agents/
│   ├── market_agent.py          # Orchestration: collect→score→output
│   └── scheduler.py             # Continuous polling loop
├── tools/
│   └── seed_tickers.py          # Ticker universe loader
├── tests/
│   └── test_agent.py            # Unit tests
├── output/
│   ├── alerts.json              # HIGH_PRIORITY (score ≥ 75) alerts
│   └── watchlist.json           # Full ranked watchlist
├── logs/
│   └── agent.log                # Rotating log file
├── config.yaml                  # All configuration
├── requirements.txt
└── main.py                      # Entry point
```

---

## Installation

### 1. Clone / copy the project

```bash
cd /opt
git clone <repo-url> ca_market_agent
cd ca_market_agent
```

### 2. Create a virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **Note for Jetson Nano ARM64:** All dependencies are pure-Python or
> have ARM64 wheels. No CUDA/GPU dependency is required. The optional
> `transformers` / `torch` lines in `requirements.txt` are commented out.

---

## Configuration

Edit `config.yaml` to:

- Set `agent.poll_interval_seconds` (default 120 s)
- Enable/disable individual collectors
- Adjust liquidity filters (`min_price_cad`, `min_avg_daily_volume`)
- Tune scoring weights and penalty values
- Change output file paths

---

## Database Schema

SQLite database at `storage/market_agent.db`:

| Table              | Description                              |
|--------------------|------------------------------------------|
| `tickers`          | TSX/TSXV ticker universe                 |
| `events`           | All processed events with scores         |
| `watchlist`        | Current top-ranked opportunities         |
| `seen_hashes`      | URL + headline hashes for deduplication  |
| `macro_events`     | Bank of Canada policy announcements      |
| `sector_tailwinds` | Sector-level score adjustments           |

---

## Usage

### First-time setup: seed tickers

```bash
python main.py --seed-tickers
```

Or load from a CSV file:

```bash
python tools/seed_tickers.py --csv my_tickers.csv
```

CSV format:
```
ticker,exchange,company_name,aliases,sector,average_volume,market_cap,last_price,spread_estimate
RY.TO,TSX,Royal Bank of Canada,RY,Financials,4000000,180000000000,132.00,0.02
```

### Run a single cycle (test / debug)

```bash
python main.py --once
```

### Run continuously (production)

```bash
python main.py
```

### View current watchlist

```bash
python main.py --print-watchlist
```

### Run as a systemd service (Jetson Nano / Ubuntu)

```ini
# /etc/systemd/system/ca-market-agent.service
[Unit]
Description=Canadian Market Opportunity Detection Agent
After=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/ca_market_agent
ExecStart=/opt/ca_market_agent/venv/bin/python main.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable ca-market-agent
sudo systemctl start ca-market-agent
journalctl -u ca-market-agent -f
```

---

## Output Format

### `output/alerts.json` (HIGH_PRIORITY events, last 6 hours)

```json
[
  {
    "ticker":     "ABX.TO",
    "score":      82.5,
    "label":      "HIGH_PRIORITY",
    "reason":     "earnings beat",
    "source":     "Reuters",
    "timestamp":  "2024-11-15T14:32:00+00:00",
    "link":       "https://...",
    "risk_flags": []
  }
]
```

### `output/watchlist.json`

All WATCH + HIGH_PRIORITY tickers ranked by score, updated every cycle.

---

## Scoring Formula

```
final_score =
    0.30 × catalyst_score         (event type quality, 0–1)
  + 0.20 × sentiment_score        (keyword sentiment, normalised 0–1)
  + 0.20 × source_reliability     (SEDAR=1.0 … Unknown=0.3)
  + 0.15 × liquidity_score        (price/volume/spread quality, 0–1)
  + 0.10 × novelty_score          (1.0 = first occurrence)
  + 0.05 × sector_tailwind_score  (macro-driven, 0–1)
  - dilution_penalty (15 pts)     (if equity_dilution event)
  - promotion_penalty (20 pts)    (if paid-promotion language detected)
  × freshness_factor              (exp(-age_hours / 6))

Clamped to [0, 100].
Labels: HIGH_PRIORITY ≥ 75 | WATCH ≥ 60 | IGNORE < 60
```

---

## Running Tests

```bash
pytest tests/ -v --tb=short
```

---

## Resource Usage (Jetson Nano)

| Metric        | Target   | Typical  |
|---------------|----------|----------|
| RAM           | < 1 GB   | ~200 MB  |
| CPU (idle)    | < 40 %   | ~5 %     |
| CPU (cycle)   | < 40 %   | ~15–25 % |
| Cycle time    | < 60 s   | ~10–20 s |
| Poll interval | 1–5 min  | 2 min    |

Memory and CPU are logged after every cycle. The scheduler applies
garbage collection if memory exceeds the configured limit.

---

## Extending the Agent

| Feature                | File to modify                          |
|------------------------|-----------------------------------------|
| New data source        | Add `collector/new_collector.py`        |
| New event type         | `core/event_classifier.py` keyword list |
| Price anomaly detector | New `core/price_anomaly.py` module      |
| Volume spike detector  | New `core/volume_detector.py` module    |
| Social sentiment       | New `collector/social_collector.py`     |
| LLM classification     | Replace `SentimentAnalyzer.score()`     |

---

## Security & Compliance

- Uses **only public data sources** (no authentication required)
- Respects source terms of service via configurable polling intervals
- No personal data is stored
- All network requests use exponential backoff to avoid hammering sources
