"""
collector/macro_collector.py
Collects Bank of Canada policy/rate announcements via RSS.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from .base_collector import BaseCollector

logger = logging.getLogger(__name__)


# Sector impact mappings for BOC announcements
RATE_SECTOR_IMPACT = {
    "rate cut":   {"Financials": -0.3, "Real Estate": +0.4, "Utilities": +0.3,
                   "Energy": +0.1, "Materials": +0.1},
    "rate hike":  {"Financials": +0.3, "Real Estate": -0.4, "Utilities": -0.3,
                   "Energy": -0.1, "Materials": -0.1},
    "hold":       {},
    "inflation":  {"Consumer Discretionary": -0.2, "Industrials": -0.1},
    "gdp growth": {"Industrials": +0.2, "Materials": +0.1, "Energy": +0.15},
}


class MacroCollector(BaseCollector):
    SOURCE_NAME = "BankOfCanada"
    RELIABILITY = 0.95

    FEEDS = [
        "https://www.bankofcanada.ca/feed/",
        "https://www.bankofcanada.ca/rates/interest-rates/feed/",
        "https://www.bankofcanada.ca/press/announcements/feed/",
    ]

    MACRO_KEYWORDS = [
        "interest rate", "policy rate", "overnight rate",
        "inflation", "gdp", "employment", "economic",
        "monetary policy", "quantitative", "basis points",
    ]

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        extra = config.get("rss_url")
        if extra and extra not in self.FEEDS:
            self.FEEDS = [extra] + self.FEEDS

    def collect(self) -> List[Dict[str, Any]]:
        items = []
        for feed_url in self.FEEDS:
            try:
                entries = self._parse_rss(feed_url)
                for e in entries:
                    e["source"] = self.SOURCE_NAME
                    e["source_reliability"] = self.RELIABILITY
                    e["is_macro"] = True
                    e["sector_impacts"] = self._derive_sector_impacts(
                        e.get("headline", "") + " " + e.get("article_text", "")
                    )
                    uid = hashlib.sha256(
                        (e.get("article_url", "") + e.get("headline", "")).encode()
                    ).hexdigest()[:16]
                    e["id"] = uid
                    e["category"] = self._classify(
                        e.get("headline", "") + " " + e.get("article_text", "")
                    )
                items.extend(entries)
            except Exception as exc:
                logger.error("[MacroCollector] Error collecting %s: %s", feed_url, exc)

        seen = set()
        unique = []
        for item in items:
            key = item.get("article_url", "")
            if key not in seen:
                seen.add(key)
                unique.append(item)
        logger.info("[MacroCollector] Collected %d macro items", len(unique))
        return unique

    def _classify(self, text: str) -> str:
        lower = text.lower()
        if any(k in lower for k in ["interest rate", "overnight rate",
                                     "policy rate", "basis points"]):
            return "interest_rate"
        if "inflation" in lower or "cpi" in lower:
            return "inflation"
        if "gdp" in lower or "economic growth" in lower:
            return "gdp"
        if "employment" in lower or "unemployment" in lower:
            return "employment"
        return "general_macro"

    def _derive_sector_impacts(self, text: str) -> Dict[str, float]:
        lower = text.lower()
        impacts = {}
        for keyword, sector_map in RATE_SECTOR_IMPACT.items():
            if keyword in lower:
                for sector, delta in sector_map.items():
                    impacts[sector] = impacts.get(sector, 0) + delta
        return impacts
