"""
agents/market_agent.py
Main orchestration agent: collects → deduplicates → classifies →
scores → filters → outputs watchlist and alerts.
"""

import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# Guarantee the project root is on sys.path so every sibling package
# (collector/, core/, storage/) is importable regardless of:
#   - current working directory
#   - how Python was invoked (python main.py / python agents/market_agent.py
#                             / systemd / import from another module)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Import DIRECTLY from each submodule — bypasses __init__.py so a single
# missing optional dependency (e.g. feedparser) never hides every class.
# ---------------------------------------------------------------------------
from collector.yahoo_collector       import YahooCollector        # noqa: E402
from collector.globenews_collector   import GlobeNewsCollector    # noqa: E402
from collector.prnews_collector      import PRNewsCollector       # noqa: E402
from collector.businesswire_collector import BusinessWireCollector # noqa: E402
from collector.sedar_collector       import SedarCollector        # noqa: E402
from collector.macro_collector       import MacroCollector        # noqa: E402

from core.symbol_resolver   import SymbolResolver   # noqa: E402
from core.event_classifier  import EventClassifier  # noqa: E402
from core.sentiment_analyzer import SentimentAnalyzer # noqa: E402
from core.event_scorer      import EventScorer      # noqa: E402
from core.liquidity_filter  import LiquidityFilter  # noqa: E402
from core.deduplicator      import Deduplicator     # noqa: E402
from core.email_notifier    import EmailNotifier    # noqa: E402

from storage.database import Database               # noqa: E402

logger = logging.getLogger(__name__)


class MarketAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self._setup_dirs()
        self.db = Database(self.config["database"]["path"])
        self._init_components()
        self._init_collectors()
        logger.info("MarketAgent initialised")

    # ------------------------------------------------------------------ #
    #  Initialisation                                                      #
    # ------------------------------------------------------------------ #

    def _load_config(self, path: str) -> Dict:
        with open(path) as f:
            return yaml.safe_load(f)

    def _setup_dirs(self):
        for key in ("alerts_path", "watchlist_path"):
            p = Path(self.config["output"][key])
            p.parent.mkdir(parents=True, exist_ok=True)

    def _init_components(self):
        self.resolver   = SymbolResolver(self.db)
        self.classifier = EventClassifier()
        self.sentiment  = SentimentAnalyzer()
        self.scorer     = EventScorer(self.config, self.db)
        self.liq_filter = LiquidityFilter(self.config)
        self.dedup      = Deduplicator(self.db)
        self.notifier   = EmailNotifier(self.config)

    def _init_collectors(self):
        cfg = self.config.get("collectors", {})
        self.collectors = []

        def add(cls, key):
            c = cfg.get(key, {})
            if c.get("enabled", True):
                self.collectors.append(cls(c))

        add(YahooCollector,        "yahoo_finance")
        add(GlobeNewsCollector,    "globenewswire")
        add(PRNewsCollector,       "prnewswire")
        add(BusinessWireCollector, "businesswire")
        add(SedarCollector,        "sedar")

        macro_cfg = cfg.get("bank_of_canada", {})
        if macro_cfg.get("enabled", True):
            self.macro_collector = MacroCollector(macro_cfg)
        else:
            self.macro_collector = None

    # ------------------------------------------------------------------ #
    #  Main cycle                                                          #
    # ------------------------------------------------------------------ #

    def run_cycle(self) -> Dict[str, Any]:
        """Execute a single collection + processing cycle."""
        logger.info("=== Starting collection cycle ===")
        stats = {"collected": 0, "after_dedup": 0,
                 "scored": 0, "high_priority": 0, "watch": 0}

        # 1. Macro events → sector tailwinds
        if self.macro_collector:
            self._process_macro()

        # 2. Collect from all news / filing sources
        raw_items: List[Dict] = []
        for collector in self.collectors:
            try:
                items = collector.collect()
                raw_items.extend(items)
                logger.info("[%s] %d items collected",
                            collector.SOURCE_NAME, len(items))
            except Exception as exc:
                logger.error("[%s] Collection error: %s",
                             collector.SOURCE_NAME, exc)

        stats["collected"] = len(raw_items)

        # 3. Deduplicate
        unique_items = self.dedup.filter_batch(raw_items)
        stats["after_dedup"] = len(unique_items)
        logger.info("After dedup: %d / %d unique events",
                    len(unique_items), len(raw_items))

        # 4. Classify + score each unique event
        processed_events: List[Dict] = []
        for item in unique_items:
            try:
                event = self._process_item(item)
                if event:
                    processed_events.append(event)
                    self.db.save_event(event)
                    stats["scored"] += 1
                    if event["label"] == "HIGH_PRIORITY":
                        stats["high_priority"] += 1
                    elif event["label"] == "WATCH":
                        stats["watch"] += 1
            except Exception as exc:
                logger.error("Error processing '%s': %s",
                             item.get("headline", "?")[:60], exc)

        # 5. Update watchlist
        self._update_watchlist(processed_events)

        # 6. Send email alerts for qualifying events
        self.notifier.notify_cycle(processed_events)

        # 7. Write output JSON files
        self._write_outputs()

        # 8. Housekeeping
        self.db.prune_old_hashes()
        self.db.clear_stale_watchlist()

        logger.info(
            "Cycle complete — collected=%d deduped=%d scored=%d "
            "high=%d watch=%d",
            stats["collected"], stats["after_dedup"], stats["scored"],
            stats["high_priority"], stats["watch"],
        )
        return stats

    # ------------------------------------------------------------------ #
    #  Per-item processing                                                 #
    # ------------------------------------------------------------------ #

    def _process_item(self, item: Dict) -> Optional[Dict]:
        headline = item.get("headline", "")
        text     = item.get("article_text", "") or ""
        if not headline:
            return None

        tickers = self.resolver.resolve(text, headline)
        if not tickers:
            logger.debug("No tickers found: %s", headline[:60])
            return None

        classification  = self.classifier.classify(headline, text)
        sentiment_score = self.sentiment.score(headline, text)

        ticker_data   = self.db.get_ticker(tickers[0]) if tickers else None
        liq_score     = self.liq_filter.liquidity_score(ticker_data)
        passes_liq    = self.liq_filter.passes(ticker_data)
        novelty_score = 1.0
        sector        = ticker_data.get("sector") if ticker_data else None

        score_result = self.scorer.score(
            item, classification, sentiment_score,
            liq_score, novelty_score, sector,
        )

        event_id = item.get("id") or str(uuid.uuid4())[:16]
        event = {
            "id":                 event_id,
            "timestamp":          item.get("publication_time",
                                           datetime.now(timezone.utc).isoformat()),
            "source":             item.get("source", "Unknown"),
            "headline":           headline,
            "text":               text[:500] if text else None,
            "url":                item.get("article_url", ""),
            "tickers":            tickers,
            "event_type":         classification["event_type"],
            "sentiment_score":    round(sentiment_score, 3),
            "catalyst_score":     round(classification["catalyst_score"], 3),
            "source_reliability": item.get("source_reliability", 0.5),
            "final_score":        score_result["final_score"],
            "label":              score_result["label"],
            "risk_flags":         classification["risk_flags"],
            "headline_hash":      _hash(headline),
            "url_hash":           _hash(item.get("article_url", "")),
            "liquidity_ok":       passes_liq,
        }
        logger.info(
            "[%s] %-13s %5.1f  %-28s  %s",
            event["source"][:12],
            event["label"],
            event["final_score"],
            ", ".join(event["tickers"][:3]),
            headline[:50],
        )
        return event

    # ------------------------------------------------------------------ #
    #  Macro / sector tailwind processing                                  #
    # ------------------------------------------------------------------ #

    def _process_macro(self):
        try:
            macro_items = self.macro_collector.collect()
            for item in macro_items:
                self.db.save_macro_event({
                    "id":           item.get("id", str(uuid.uuid4())[:16]),
                    "timestamp":    item.get("publication_time",
                                             datetime.now(timezone.utc).isoformat()),
                    "source":       item.get("source", "BankOfCanada"),
                    "title":        item.get("headline", ""),
                    "url":          item.get("article_url", ""),
                    "category":     item.get("category", "general_macro"),
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                })
                for sector, delta in item.get("sector_impacts", {}).items():
                    current = self.db.get_sector_tailwind(sector)
                    new_val = max(-1.0, min(1.0, current + delta))
                    self.db.set_sector_tailwind(
                        sector, new_val,
                        reason=item.get("headline", "")[:80],
                    )
        except Exception as exc:
            logger.error("Macro processing error: %s", exc)

    # ------------------------------------------------------------------ #
    #  Output                                                              #
    # ------------------------------------------------------------------ #

    def _update_watchlist(self, events: List[Dict]):
        for event in events:
            if event["label"] == "IGNORE":
                continue
            for ticker in event["tickers"][:3]:
                self.db.upsert_watchlist({
                    "ticker":     ticker,
                    "score":      event["final_score"],
                    "label":      event["label"],
                    "reason":     event["event_type"].replace("_", " "),
                    "source":     event["source"],
                    "event_id":   event["id"],
                    "timestamp":  event["timestamp"],
                    "link":       event["url"],
                    "risk_flags": event["risk_flags"],
                })

    def _write_outputs(self):
        cfg       = self.config["output"]
        max_items = cfg.get("max_output_items", 50)

        watchlist = self.db.get_watchlist()[:max_items]
        Path(cfg["watchlist_path"]).write_text(
            json.dumps(watchlist, indent=2, default=str)
        )

        alerts     = self.db.get_recent_events(hours=6, min_score=75)
        alerts_out = []
        for e in alerts[:max_items]:
            for ticker in e.get("tickers", []):
                alerts_out.append({
                    "ticker":     ticker,
                    "score":      e["final_score"],
                    "label":      e["label"],
                    "reason":     e.get("event_type", "").replace("_", " "),
                    "source":     e["source"],
                    "timestamp":  e["timestamp"],
                    "link":       e.get("url", ""),
                    "risk_flags": e.get("risk_flags", []),
                })
        Path(cfg["alerts_path"]).write_text(
            json.dumps(alerts_out, indent=2, default=str)
        )
        logger.info("Output written: %d watchlist, %d alerts",
                    len(watchlist), len(alerts_out))


def _hash(s: str) -> str:
    import hashlib
    return hashlib.md5((s or "").encode()).hexdigest()
