"""
storage/database.py
SQLite-backed persistence layer for the CA Market Agent.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- Ticker universe
CREATE TABLE IF NOT EXISTS tickers (
    ticker          TEXT PRIMARY KEY,
    exchange        TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    aliases         TEXT DEFAULT '[]',   -- JSON array
    sector          TEXT,
    average_volume  REAL DEFAULT 0,
    market_cap      REAL DEFAULT 0,
    last_price      REAL DEFAULT 0,
    spread_estimate REAL DEFAULT 0,
    updated_at      TEXT
);

-- Processed events
CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    source          TEXT NOT NULL,
    headline        TEXT NOT NULL,
    text            TEXT,
    url             TEXT,
    tickers         TEXT DEFAULT '[]',   -- JSON array
    event_type      TEXT,
    sentiment_score REAL DEFAULT 0,
    catalyst_score  REAL DEFAULT 0,
    source_reliability REAL DEFAULT 0.5,
    final_score     REAL DEFAULT 0,
    label           TEXT DEFAULT 'IGNORE',
    risk_flags      TEXT DEFAULT '[]',   -- JSON array
    processed_at    TEXT NOT NULL,
    headline_hash   TEXT,
    url_hash        TEXT
);

-- Watchlist (current active opportunities)
CREATE TABLE IF NOT EXISTS watchlist (
    ticker          TEXT PRIMARY KEY,
    score           REAL NOT NULL,
    label           TEXT NOT NULL,
    reason          TEXT,
    source          TEXT,
    event_id        TEXT,
    timestamp       TEXT NOT NULL,
    link            TEXT,
    risk_flags      TEXT DEFAULT '[]'
);

-- Seen URL/headline hashes for deduplication
CREATE TABLE IF NOT EXISTS seen_hashes (
    hash        TEXT PRIMARY KEY,
    hash_type   TEXT NOT NULL,   -- 'url' or 'headline'
    first_seen  TEXT NOT NULL
);

-- Macro events
CREATE TABLE IF NOT EXISTS macro_events (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT,
    category    TEXT,
    processed_at TEXT NOT NULL
);

-- Sector tailwind scores (updated by macro events)
CREATE TABLE IF NOT EXISTS sector_tailwinds (
    sector      TEXT PRIMARY KEY,
    score       REAL DEFAULT 0,
    reason      TEXT,
    updated_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_label     ON events(label);
CREATE INDEX IF NOT EXISTS idx_events_tickers   ON events(tickers);
CREATE INDEX IF NOT EXISTS idx_seen_hashes      ON seen_hashes(hash);
"""


class Database:
    def __init__(self, db_path: str = "storage/market_agent.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(SCHEMA_SQL)
        logger.info("Database initialised at %s", self.db_path)

    # ------------------------------------------------------------------ #
    #  Tickers                                                             #
    # ------------------------------------------------------------------ #

    def upsert_ticker(self, ticker: Dict[str, Any]):
        sql = """
        INSERT INTO tickers (ticker, exchange, company_name, aliases, sector,
                             average_volume, market_cap, last_price,
                             spread_estimate, updated_at)
        VALUES (:ticker, :exchange, :company_name, :aliases, :sector,
                :average_volume, :market_cap, :last_price,
                :spread_estimate, :updated_at)
        ON CONFLICT(ticker) DO UPDATE SET
            exchange        = excluded.exchange,
            company_name    = excluded.company_name,
            aliases         = excluded.aliases,
            sector          = excluded.sector,
            average_volume  = excluded.average_volume,
            market_cap      = excluded.market_cap,
            last_price      = excluded.last_price,
            spread_estimate = excluded.spread_estimate,
            updated_at      = excluded.updated_at
        """
        row = {**ticker}
        row.setdefault("aliases", "[]")
        row.setdefault("sector", None)
        row.setdefault("average_volume", 0)
        row.setdefault("market_cap", 0)
        row.setdefault("last_price", 0)
        row.setdefault("spread_estimate", 0)
        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        if isinstance(row.get("aliases"), list):
            row["aliases"] = json.dumps(row["aliases"])
        with self._get_conn() as conn:
            conn.execute(sql, row)

    def get_ticker(self, ticker: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tickers WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row:
            d = dict(row)
            d["aliases"] = json.loads(d.get("aliases") or "[]")
            return d
        return None

    def get_all_tickers(self) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM tickers").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["aliases"] = json.loads(d.get("aliases") or "[]")
            result.append(d)
        return result

    def get_ticker_symbols(self) -> List[str]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT ticker FROM tickers").fetchall()
        return [r["ticker"] for r in rows]

    # ------------------------------------------------------------------ #
    #  Events                                                              #
    # ------------------------------------------------------------------ #

    def save_event(self, event: Dict[str, Any]):
        sql = """
        INSERT OR REPLACE INTO events
            (id, timestamp, source, headline, text, url, tickers,
             event_type, sentiment_score, catalyst_score,
             source_reliability, final_score, label, risk_flags,
             processed_at, headline_hash, url_hash)
        VALUES
            (:id, :timestamp, :source, :headline, :text, :url, :tickers,
             :event_type, :sentiment_score, :catalyst_score,
             :source_reliability, :final_score, :label, :risk_flags,
             :processed_at, :headline_hash, :url_hash)
        """
        row = dict(event)
        if isinstance(row.get("tickers"), list):
            row["tickers"] = json.dumps(row["tickers"])
        if isinstance(row.get("risk_flags"), list):
            row["risk_flags"] = json.dumps(row["risk_flags"])
        row.setdefault("processed_at", datetime.now(timezone.utc).isoformat())
        for f in ("text", "url", "event_type", "headline_hash", "url_hash"):
            row.setdefault(f, None)
        with self._get_conn() as conn:
            conn.execute(sql, row)

    def get_recent_events(self, hours: int = 24, min_score: float = 0) -> List[Dict]:
        sql = """
        SELECT * FROM events
        WHERE datetime(timestamp) >= datetime('now', ? || ' hours')
          AND final_score >= ?
        ORDER BY final_score DESC
        """
        with self._get_conn() as conn:
            rows = conn.execute(sql, (f"-{hours}", min_score)).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tickers"] = json.loads(d.get("tickers") or "[]")
            d["risk_flags"] = json.loads(d.get("risk_flags") or "[]")
            result.append(d)
        return result

    # ------------------------------------------------------------------ #
    #  Deduplication hashes                                                #
    # ------------------------------------------------------------------ #

    def has_hash(self, hash_value: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_hashes WHERE hash = ?", (hash_value,)
            ).fetchone()
        return row is not None

    def add_hash(self, hash_value: str, hash_type: str):
        sql = """
        INSERT OR IGNORE INTO seen_hashes (hash, hash_type, first_seen)
        VALUES (?, ?, ?)
        """
        with self._get_conn() as conn:
            conn.execute(sql, (hash_value, hash_type,
                               datetime.now(timezone.utc).isoformat()))

    def prune_old_hashes(self, older_than_hours: int = 48):
        sql = """
        DELETE FROM seen_hashes
        WHERE datetime(first_seen) < datetime('now', ? || ' hours')
        """
        with self._get_conn() as conn:
            conn.execute(sql, (f"-{older_than_hours}",))

    # ------------------------------------------------------------------ #
    #  Watchlist                                                           #
    # ------------------------------------------------------------------ #

    def upsert_watchlist(self, entry: Dict[str, Any]):
        sql = """
        INSERT OR REPLACE INTO watchlist
            (ticker, score, label, reason, source, event_id,
             timestamp, link, risk_flags)
        VALUES
            (:ticker, :score, :label, :reason, :source, :event_id,
             :timestamp, :link, :risk_flags)
        """
        row = dict(entry)
        if isinstance(row.get("risk_flags"), list):
            row["risk_flags"] = json.dumps(row["risk_flags"])
        row.setdefault("risk_flags", "[]")
        with self._get_conn() as conn:
            conn.execute(sql, row)

    def get_watchlist(self, label: Optional[str] = None) -> List[Dict]:
        if label:
            sql = "SELECT * FROM watchlist WHERE label = ? ORDER BY score DESC"
            params = (label,)
        else:
            sql = "SELECT * FROM watchlist ORDER BY score DESC"
            params = ()
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["risk_flags"] = json.loads(d.get("risk_flags") or "[]")
            result.append(d)
        return result

    def clear_stale_watchlist(self, older_than_hours: int = 24):
        sql = """
        DELETE FROM watchlist
        WHERE datetime(timestamp) < datetime('now', ? || ' hours')
        """
        with self._get_conn() as conn:
            conn.execute(sql, (f"-{older_than_hours}",))

    # ------------------------------------------------------------------ #
    #  Macro / Sector Tailwinds                                            #
    # ------------------------------------------------------------------ #

    def save_macro_event(self, event: Dict[str, Any]):
        sql = """
        INSERT OR IGNORE INTO macro_events
            (id, timestamp, source, title, url, category, processed_at)
        VALUES
            (:id, :timestamp, :source, :title, :url, :category, :processed_at)
        """
        row = dict(event)
        row.setdefault("processed_at", datetime.now(timezone.utc).isoformat())
        with self._get_conn() as conn:
            conn.execute(sql, row)

    def set_sector_tailwind(self, sector: str, score: float, reason: str = ""):
        sql = """
        INSERT OR REPLACE INTO sector_tailwinds (sector, score, reason, updated_at)
        VALUES (?, ?, ?, ?)
        """
        with self._get_conn() as conn:
            conn.execute(sql, (sector, score, reason,
                               datetime.now(timezone.utc).isoformat()))

    def get_sector_tailwind(self, sector: str) -> float:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT score FROM sector_tailwinds WHERE sector = ?", (sector,)
            ).fetchone()
        return row["score"] if row else 0.0
