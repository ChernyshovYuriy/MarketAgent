"""
tests/test_agent.py
Unit tests for core components of the CA Market Opportunity Agent.
Run: pytest tests/ -v
"""

import sys
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

# ---- Storage ----------------------------------------------------------------

class TestDatabase:
    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        from storage import Database
        self.db = Database(self.tmp.name)

    def test_upsert_and_get_ticker(self):
        self.db.upsert_ticker({
            "ticker": "RY.TO", "exchange": "TSX",
            "company_name": "Royal Bank", "aliases": ["RY"],
            "sector": "Financials", "average_volume": 4000000,
            "market_cap": 180e9, "last_price": 132.0,
            "spread_estimate": 0.02,
        })
        t = self.db.get_ticker("RY.TO")
        assert t is not None
        assert t["company_name"] == "Royal Bank"
        assert "RY" in t["aliases"]

    def test_hash_dedup(self):
        self.db.add_hash("abc123", "url")
        assert self.db.has_hash("abc123")
        assert not self.db.has_hash("nope")

    def test_save_and_retrieve_event(self):
        self.db.save_event({
            "id": "ev001",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "Yahoo",
            "headline": "Test headline",
            "tickers": ["RY.TO"],
            "event_type": "earnings_beat",
            "sentiment_score": 0.7,
            "catalyst_score": 0.85,
            "source_reliability": 0.6,
            "final_score": 80.0,
            "label": "HIGH_PRIORITY",
            "risk_flags": [],
        })
        events = self.db.get_recent_events(hours=24, min_score=0)
        assert any(e["id"] == "ev001" for e in events)

    def test_watchlist_upsert(self):
        self.db.upsert_watchlist({
            "ticker": "ABX.TO", "score": 82.0, "label": "HIGH_PRIORITY",
            "reason": "earnings beat", "source": "Reuters",
            "event_id": "ev001",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "link": "https://example.com",
            "risk_flags": [],
        })
        wl = self.db.get_watchlist(label="HIGH_PRIORITY")
        assert any(w["ticker"] == "ABX.TO" for w in wl)


# ---- Event Classifier -------------------------------------------------------

class TestEventClassifier:
    def setup_method(self):
        from core.event_classifier import EventClassifier
        self.clf = EventClassifier()

    def test_earnings_beat(self):
        r = self.clf.classify("Company beats quarterly earnings expectations")
        assert r["event_type"] == "earnings_beat"
        assert r["catalyst_score"] > 0

    def test_guidance_increase(self):
        r = self.clf.classify("Acme Corp raises guidance for full year")
        assert r["event_type"] == "guidance_increase"

    def test_equity_dilution(self):
        r = self.clf.classify("Company announces non-brokered private placement")
        assert r["event_type"] == "equity_dilution"
        assert "dilution" in r["risk_flags"]
        assert r["catalyst_score"] == 0.0

    def test_going_concern(self):
        r = self.clf.classify("Auditors note going concern uncertainty in annual report")
        assert r["event_type"] == "going_concern"
        assert "high_risk" in r["risk_flags"]

    def test_regulatory_approval(self):
        r = self.clf.classify("Health Canada approval received for new drug")
        assert r["event_type"] == "regulatory_approval"

    def test_general_fallback(self):
        r = self.clf.classify("Company provides corporate update")
        assert r["event_type"] in ("corporate_update", "general_news")


# ---- Sentiment Analyzer -----------------------------------------------------

class TestSentimentAnalyzer:
    def setup_method(self):
        from core.sentiment_analyzer import SentimentAnalyzer
        self.sa = SentimentAnalyzer()

    def test_positive_headline(self):
        score = self.sa.score("Company beats quarterly earnings, raises guidance")
        assert score > 0.3

    def test_negative_headline(self):
        score = self.sa.score("Company misses earnings, cuts guidance for next year")
        assert score < 0

    def test_neutral(self):
        score = self.sa.score("Company provides monthly corporate update")
        assert -0.3 < score < 0.3

    def test_negation(self):
        score_pos = self.sa.score("Company beats expectations")
        score_neg = self.sa.score("Company does not beat expectations")
        assert score_pos > score_neg

    def test_range(self):
        texts = [
            "Record high revenue, record earnings beat, raises guidance",
            "Bankruptcy filing, going concern doubt, missed payment, default",
            "Today is a day",
        ]
        for t in texts:
            s = self.sa.score(t)
            assert -1.0 <= s <= 1.0


# ---- Event Scorer -----------------------------------------------------------

class TestEventScorer:
    def setup_method(self):
        from core.event_scorer import EventScorer
        config = {
            "scoring": {
                "weights": {
                    "catalyst": 0.30, "sentiment": 0.20,
                    "source": 0.20, "liquidity": 0.15,
                    "novelty": 0.10, "sector_tailwind": 0.05,
                },
                "penalties": {"dilution": 15, "promotion": 20},
                "thresholds": {"high_priority": 75, "watch": 60},
            },
            "freshness": {"decay_half_life_hours": 6, "max_age_hours": 24},
            "source_reliability": {
                "sedar": 1.0, "reuters": 0.9, "yahoo": 0.6,
            },
        }
        self.scorer = EventScorer(config)

    def test_high_priority_score(self):
        event = {
            "source": "Reuters",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        classification = {
            "catalyst_score": 0.85,
            "risk_flags": [],
        }
        result = self.scorer.score(
            event, classification,
            sentiment_score=0.7,
            liquidity_score=0.8,
            novelty_score=1.0,
        )
        assert result["label"] == "HIGH_PRIORITY"
        assert result["final_score"] >= 75

    def test_dilution_penalty(self):
        event = {
            "source": "Yahoo",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        no_dilution = self.scorer.score(
            event, {"catalyst_score": 0.5, "risk_flags": []},
            0.3, 0.5, 0.8
        )
        with_dilution = self.scorer.score(
            event, {"catalyst_score": 0.5, "risk_flags": ["dilution"]},
            0.3, 0.5, 0.8
        )
        assert no_dilution["final_score"] > with_dilution["final_score"]

    def test_old_event_decay(self):
        fresh_event = {
            "source": "Reuters",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        import datetime as dt
        old_ts = (
            datetime.now(timezone.utc) - dt.timedelta(hours=20)
        ).isoformat()
        old_event = {"source": "Reuters", "timestamp": old_ts}
        classification = {"catalyst_score": 0.85, "risk_flags": []}
        fresh = self.scorer.score(fresh_event, classification, 0.7, 0.8, 1.0)
        old = self.scorer.score(old_event, classification, 0.7, 0.8, 1.0)
        assert fresh["final_score"] > old["final_score"]


# ---- Deduplicator -----------------------------------------------------------

class TestDeduplicator:
    def setup_method(self):
        from core.deduplicator import Deduplicator
        self.dedup = Deduplicator()

    def test_url_dedup(self):
        e1 = {"article_url": "https://example.com/news/1",
              "headline": "Company beats earnings"}
        e2 = {"article_url": "https://example.com/news/1",
              "headline": "Different headline"}
        assert not self.dedup.is_duplicate(e1)
        self.dedup.mark_seen(e1)
        assert self.dedup.is_duplicate(e2)  # Same URL

    def test_headline_dedup(self):
        e1 = {"article_url": "https://a.com/1",
              "headline": "Company XYZ beats quarterly earnings"}
        e2 = {"article_url": "https://b.com/2",
              "headline": "Company XYZ beats quarterly earnings"}
        self.dedup.mark_seen(e1)
        assert self.dedup.is_duplicate(e2)

    def test_batch_filter(self):
        events = [
            {"article_url": f"https://example.com/{i}",
             "headline": f"Unique story {i}"}
            for i in range(5)
        ]
        # Add duplicate
        events.append({"article_url": "https://example.com/0",
                        "headline": "Unique story 0"})
        result = self.dedup.filter_batch(events)
        assert len(result) == 5


# ---- Symbol Resolver --------------------------------------------------------

class TestSymbolResolver:
    def setup_method(self):
        from core.symbol_resolver import SymbolResolver
        self.resolver = SymbolResolver()  # No DB – lenient mode

    def test_exchange_qualified(self):
        text = "TSX: ABC reported strong Q3 earnings"
        tickers = self.resolver.resolve(text)
        assert "ABC" in tickers

    def test_suffix_to(self):
        text = "RY.TO posted record quarterly profit"
        tickers = self.resolver.resolve(text)
        assert any("RY" in t for t in tickers)

    def test_false_positive_exclusion(self):
        text = "CEO and CFO attended the conference in the US"
        tickers = self.resolver.resolve(text)
        for t in tickers:
            assert t not in ("CEO", "CFO", "US", "THE")


# ---- Liquidity Filter -------------------------------------------------------

class TestLiquidityFilter:
    def setup_method(self):
        from core.liquidity_filter import LiquidityFilter
        config = {"liquidity": {
            "min_price_cad": 1.0,
            "min_avg_daily_volume": 200000,
            "max_spread_pct": 3.0,
        }}
        self.lf = LiquidityFilter(config)

    def test_passes(self):
        assert self.lf.passes({
            "ticker": "RY.TO", "last_price": 132.0,
            "average_volume": 4000000, "spread_estimate": 0.02,
        })

    def test_fails_price(self):
        assert not self.lf.passes({
            "ticker": "X.V", "last_price": 0.50,
            "average_volume": 500000, "spread_estimate": 1.5,
        })

    def test_fails_volume(self):
        assert not self.lf.passes({
            "ticker": "Y.V", "last_price": 2.00,
            "average_volume": 50000, "spread_estimate": 1.5,
        })

    def test_unknown_ticker_passes(self):
        # Unknown tickers are allowed through (penalised in scoring)
        assert self.lf.passes(None)


# ---- EmailNotifier ----------------------------------------------------------

class TestEmailNotifier:
    def _make_event(self, label="HIGH_PRIORITY", score=82.0, tickers=None):
        return {
            "id": "ev001",
            "label": label,
            "final_score": score,
            "tickers": tickers or ["RY.TO"],
            "headline": "Company beats quarterly earnings and raises guidance",
            "event_type": "earnings_beat",
            "source": "Reuters",
            "url": "https://example.com/news/1",
            "risk_flags": [],
            "timestamp": "2024-11-15T14:32:00+00:00",
        }

    def test_disabled_by_default(self):
        from core.email_notifier import EmailNotifier
        n = EmailNotifier({})          # no email key at all
        assert not n.enabled

    def test_no_to_addresses_disables(self):
        from core.email_notifier import EmailNotifier
        n = EmailNotifier({"email": {"enabled": True, "to_addresses": []}})
        assert not n.enabled

    def test_filter_passes_high_priority(self):
        from core.email_notifier import EmailNotifier
        n = EmailNotifier({"email": {
            "enabled": True,
            "to_addresses": ["x@x.com"],
            "notify_labels": ["HIGH_PRIORITY"],
            "min_score": 75,
            "cooldown_minutes": 0,
            "batch": True,
        }})
        qualifying = n._filter([self._make_event("HIGH_PRIORITY", 82)])
        assert len(qualifying) == 1

    def test_filter_blocks_low_score(self):
        from core.email_notifier import EmailNotifier
        n = EmailNotifier({"email": {
            "enabled": True,
            "to_addresses": ["x@x.com"],
            "notify_labels": ["HIGH_PRIORITY"],
            "min_score": 75,
            "cooldown_minutes": 0,
            "batch": True,
        }})
        qualifying = n._filter([self._make_event("HIGH_PRIORITY", 60)])
        assert len(qualifying) == 0

    def test_filter_blocks_watch_when_not_configured(self):
        from core.email_notifier import EmailNotifier
        n = EmailNotifier({"email": {
            "enabled": True,
            "to_addresses": ["x@x.com"],
            "notify_labels": ["HIGH_PRIORITY"],
            "min_score": 60,
            "cooldown_minutes": 0,
            "batch": True,
        }})
        qualifying = n._filter([self._make_event("WATCH", 65)])
        assert len(qualifying) == 0

    def test_cooldown_blocks_repeat(self):
        from core.email_notifier import EmailNotifier
        n = EmailNotifier({"email": {
            "enabled": True,
            "to_addresses": ["x@x.com"],
            "notify_labels": ["HIGH_PRIORITY"],
            "min_score": 75,
            "cooldown_minutes": 60,
            "batch": True,
        }})
        event = self._make_event()
        first  = n._filter([event])
        second = n._filter([event])   # same ticker, within cooldown
        assert len(first)  == 1
        assert len(second) == 0

    def test_digest_html_contains_ticker(self):
        from core.email_notifier import EmailNotifier
        n = EmailNotifier({"email": {
            "enabled": True,
            "to_addresses": ["x@x.com"],
            "notify_labels": ["HIGH_PRIORITY"],
            "min_score": 75,
            "cooldown_minutes": 0,
            "batch": True,
        }})
        _, html = n._build_digest_body([self._make_event()])
        assert "RY.TO" in html
        assert "HIGH_PRIORITY" in html
        assert "82" in html
