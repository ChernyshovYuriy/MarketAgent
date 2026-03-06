"""
core/sentiment_analyzer.py
Financial sentiment analysis for Canadian market news.
Uses a keyword/phrase dictionary approach (no GPU needed, runs on Jetson Nano).
Score range: -1.0 to +1.0
"""

import re
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentiment lexicons
# ---------------------------------------------------------------------------

STRONG_POSITIVE: List[Tuple[str, float]] = [
    ("record high", 0.9), ("record revenue", 0.9), ("record earnings", 0.9),
    ("all-time high", 0.85), ("best ever", 0.85), ("blowout", 0.8),
    ("exceeds expectations", 0.8), ("beat expectations", 0.8),
    ("raises guidance", 0.8), ("upgrades to buy", 0.75),
    ("significant discovery", 0.8), ("major discovery", 0.85),
    ("regulatory approval", 0.8), ("health canada approval", 0.85),
    ("transformative", 0.7), ("strategic acquisition", 0.7),
    ("accretive", 0.65), ("high-grade", 0.65),
]

MODERATE_POSITIVE: List[Tuple[str, float]] = [
    ("increases", 0.3), ("growth", 0.3), ("improved", 0.35),
    ("strong", 0.3), ("positive", 0.3), ("gains", 0.3),
    ("outperforms", 0.45), ("outperform", 0.4), ("beats", 0.45),
    ("above", 0.25), ("higher", 0.25), ("expands", 0.3),
    ("advances", 0.3), ("progress", 0.3), ("contract", 0.25),
    ("partnership", 0.3), ("agreement", 0.2), ("milestone", 0.35),
    ("profitable", 0.4), ("profit", 0.3), ("revenue growth", 0.4),
    ("cash flow positive", 0.5), ("free cash flow", 0.35),
]

STRONG_NEGATIVE: List[Tuple[str, float]] = [
    ("going concern", -0.9), ("bankruptcy", -0.95), ("insolvency", -0.9),
    ("ccaa protection", -0.9), ("receivership", -0.9),
    ("cease trade order", -0.85), ("regulatory sanction", -0.85),
    ("defaults", -0.8), ("defaulted", -0.8), ("missed payment", -0.8),
    ("wider loss", -0.7), ("significant loss", -0.7),
    ("earnings miss", -0.7), ("below expectations", -0.6),
    ("guidance cut", -0.75), ("lowers guidance", -0.75),
    ("cuts guidance", -0.75),
]

MODERATE_NEGATIVE: List[Tuple[str, float]] = [
    ("loss", -0.3), ("decline", -0.3), ("decreases", -0.25),
    ("lower", -0.2), ("below", -0.2), ("miss", -0.35),
    ("disappointing", -0.45), ("concern", -0.25), ("risk", -0.15),
    ("challenges", -0.2), ("uncertainty", -0.25), ("delay", -0.3),
    ("delayed", -0.3), ("weakness", -0.3), ("downturn", -0.35),
    ("restructuring", -0.3), ("dilution", -0.4), ("placement", -0.3),
    ("private placement", -0.35), ("warrant", -0.15),
]

# Negation words that flip sentiment
NEGATORS = {"not", "no", "never", "neither", "nor", "without",
            "hardly", "barely", "scarcely", "fails", "failed"}

# Intensifiers
INTENSIFIERS = {"very", "extremely", "significantly", "substantially",
                "materially", "greatly", "highly", "severely"}

WINDOW_SIZE = 4  # words to look back for negation


class SentimentAnalyzer:
    def __init__(self):
        # Compile all phrases sorted by length desc (longer phrases first)
        self._phrases: List[Tuple[str, float]] = sorted(
            STRONG_POSITIVE + MODERATE_POSITIVE +
            STRONG_NEGATIVE + MODERATE_NEGATIVE,
            key=lambda x: len(x[0]), reverse=True
        )

    def score(self, headline: str, text: str = "") -> float:
        """
        Returns sentiment score in [-1.0, +1.0].
        Headline is weighted 2x vs body text.
        """
        headline_score = self._score_text(headline) * 2.0
        text_score = self._score_text(text) if text else 0.0
        weight = 3.0 if text else 2.0
        raw = (headline_score + text_score) / weight
        return max(-1.0, min(1.0, raw))

    def _score_text(self, text: str) -> float:
        if not text:
            return 0.0
        lower = text.lower()
        # Remove matched spans to avoid double-counting
        remaining = lower
        total_score = 0.0
        hit_count = 0

        for phrase, base_score in self._phrases:
            if phrase not in remaining:
                continue
            # Check for negation in a window before the phrase
            idx = remaining.find(phrase)
            window_text = remaining[max(0, idx - 40):idx]
            window_words = set(window_text.split())
            negated = bool(window_words & NEGATORS)
            intensified = bool(window_words & INTENSIFIERS)

            score = base_score
            if negated:
                score = -score * 0.8
            if intensified:
                score *= 1.2

            total_score += score
            hit_count += 1
            # Remove matched phrase to avoid overlap
            remaining = remaining.replace(phrase, " " * len(phrase), 1)

        if hit_count == 0:
            return 0.0
        # Dampen large accumulations
        return max(-1.0, min(1.0, total_score / max(hit_count, 2)))
