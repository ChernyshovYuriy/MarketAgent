"""
core/event_scorer.py
Applies the multi-factor scoring formula to produce a final 0-100 score.

Formula:
  final_score =
      0.30 * catalyst_score
    + 0.20 * sentiment_score
    + 0.20 * source_score
    + 0.15 * liquidity_score
    + 0.10 * novelty_score
    + 0.05 * sector_tailwind_score
    - dilution_penalty
    - promotion_penalty
  × freshness_factor
"""

import math
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Score thresholds
HIGH_PRIORITY_THRESHOLD = 75
WATCH_THRESHOLD = 60


class EventScorer:
    def __init__(self, config: Dict[str, Any], db=None):
        scoring = config.get("scoring", {})
        weights = scoring.get("weights", {})
        penalties = scoring.get("penalties", {})
        freshness_cfg = config.get("freshness", {})
        src_cfg = config.get("source_reliability", {})

        self.w_catalyst = weights.get("catalyst", 0.30)
        self.w_sentiment = weights.get("sentiment", 0.20)
        self.w_source = weights.get("source", 0.20)
        self.w_liquidity = weights.get("liquidity", 0.15)
        self.w_novelty = weights.get("novelty", 0.10)
        self.w_tailwind = weights.get("sector_tailwind", 0.05)

        self.dilution_penalty = penalties.get("dilution", 15)
        self.promotion_penalty = penalties.get("promotion", 20)

        self.decay_half_life = freshness_cfg.get("decay_half_life_hours", 6)
        self.max_age_hours = freshness_cfg.get("max_age_hours", 24)

        self.source_reliability_map = {
            k.lower(): v for k, v in src_cfg.items()
        }
        self.db = db

        self.high_priority_threshold = (
            config.get("scoring", {}).get("thresholds", {}).get("high_priority", 75)
        )
        self.watch_threshold = (
            config.get("scoring", {}).get("thresholds", {}).get("watch", 60)
        )

    def score(
        self,
        event: Dict[str, Any],
        classification: Dict[str, Any],
        sentiment_score: float,
        liquidity_score: float,
        novelty_score: float,
        ticker_sector: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compute final score (0-100) and label.

        Parameters
        ----------
        event           : raw event dict (must have 'source', 'timestamp')
        classification  : output of EventClassifier.classify()
        sentiment_score : float in [-1, +1] from SentimentAnalyzer
        liquidity_score : float in [0, 1] from LiquidityFilter
        novelty_score   : float in [0, 1] (1 = never seen before)
        ticker_sector   : sector string for tailwind lookup
        """
        # --- Component scores (all normalised to 0..1) ---
        catalyst = classification.get("catalyst_score", 0.0)

        # Sentiment: convert [-1,+1] to [0,1]
        sent_normalised = (sentiment_score + 1.0) / 2.0

        source_name = event.get("source", "Unknown").lower()
        source_rel = self.source_reliability_map.get(
            source_name,
            event.get("source_reliability", 0.5)
        )

        tailwind = 0.0
        if ticker_sector and self.db:
            raw_tw = self.db.get_sector_tailwind(ticker_sector)
            # Tailwind in [-1,+1] -> normalise to [0,1]
            tailwind = (raw_tw + 1.0) / 2.0

        # --- Raw weighted sum ---
        raw = (
            self.w_catalyst  * catalyst +
            self.w_sentiment * sent_normalised +
            self.w_source    * source_rel +
            self.w_liquidity * liquidity_score +
            self.w_novelty   * novelty_score +
            self.w_tailwind  * tailwind
        ) * 100  # scale to 0-100

        # --- Penalties ---
        risk_flags = classification.get("risk_flags", [])
        if "dilution" in risk_flags:
            raw -= self.dilution_penalty
        if "promotion_flag" in risk_flags:
            raw -= self.promotion_penalty
        if "high_risk" in risk_flags:
            raw -= 25

        # --- Freshness decay ---
        raw *= self._freshness_factor(event.get("timestamp", ""))

        # --- Clamp to 0-100 ---
        final = max(0.0, min(100.0, raw))

        label = self._label(final)
        logger.debug(
            "Score breakdown: catalyst=%.2f sent=%.2f src=%.2f "
            "liq=%.2f nov=%.2f tail=%.2f → raw=%.1f final=%.1f [%s]",
            catalyst, sent_normalised, source_rel,
            liquidity_score, novelty_score, tailwind,
            raw, final, label
        )
        return {
            "final_score": round(final, 1),
            "label": label,
            "components": {
                "catalyst": round(catalyst, 3),
                "sentiment_normalised": round(sent_normalised, 3),
                "source_reliability": round(source_rel, 3),
                "liquidity": round(liquidity_score, 3),
                "novelty": round(novelty_score, 3),
                "sector_tailwind": round(tailwind, 3),
            }
        }

    def _freshness_factor(self, timestamp_str: str) -> float:
        if not timestamp_str:
            return 0.5
        try:
            ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (
                datetime.now(timezone.utc) - ts
            ).total_seconds() / 3600
            if age_hours > self.max_age_hours:
                return 0.0
            return math.exp(-age_hours / self.decay_half_life)
        except (ValueError, TypeError):
            return 0.7

    def _label(self, score: float) -> str:
        if score >= self.high_priority_threshold:
            return "HIGH_PRIORITY"
        elif score >= self.watch_threshold:
            return "WATCH"
        return "IGNORE"
