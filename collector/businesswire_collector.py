"""
collector/businesswire_collector.py
Collects Canadian press releases from BusinessWire.
"""

import logging
from typing import List, Dict, Any

from .base_collector import BaseCollector

logger = logging.getLogger(__name__)


class BusinessWireCollector(BaseCollector):
    SOURCE_NAME = "BusinessWire"
    RELIABILITY = 0.8

    FEEDS = [
        "https://feed.businesswire.com/rss/home/?rss=G1&rtype=Rtopic&topic=FIN",
        "https://feed.businesswire.com/rss/home/?rss=G1&rtype=Rcat&cat=CAD",
        "https://feed.businesswire.com/rss/home/?rss=G1",
    ]

    CANADIAN_KEYWORDS = [
        "TSX", "TSXV", "Toronto Stock", "Canada", "Canadian",
        "Ontario", "British Columbia", "Alberta", "Quebec",
        "Vancouver", "Calgary", "Toronto", "Ottawa",
    ]

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        extra = config.get("rss_url")
        if extra and extra not in self.FEEDS:
            self.FEEDS = [extra] + self.FEEDS

    def _is_canadian(self, item: Dict) -> bool:
        text = (item.get("headline", "") + " " +
                item.get("article_text", "")).lower()
        return any(kw.lower() in text for kw in self.CANADIAN_KEYWORDS)

    def collect(self) -> List[Dict[str, Any]]:
        items = []
        for feed_url in self.FEEDS:
            try:
                entries = self._parse_rss(feed_url)
                canadian = [e for e in entries if self._is_canadian(e)]
                for e in canadian:
                    e["source"] = self.SOURCE_NAME
                    e["source_reliability"] = self.RELIABILITY
                items.extend(canadian)
            except Exception as exc:
                logger.error("[BusinessWire] Error: %s", exc)

        seen = set()
        unique = []
        for item in items:
            key = item.get("article_url", "")
            if key not in seen:
                seen.add(key)
                unique.append(item)
        logger.info("[BusinessWire] Collected %d unique items", len(unique))
        return unique
