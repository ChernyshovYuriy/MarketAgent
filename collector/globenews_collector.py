"""
collector/globenews_collector.py
Collects Canadian press releases from GlobeNewswire RSS feeds.
"""

import logging
from typing import List, Dict, Any

from .base_collector import BaseCollector

logger = logging.getLogger(__name__)


class GlobeNewsCollector(BaseCollector):
    SOURCE_NAME = "GlobeNewswire"
    RELIABILITY = 0.75

    FEEDS = [
        "https://www.globenewswire.com/RssFeed/country/Canada",
        "https://www.globenewswire.com/RssFeed/subjectcode/20-Financial%20Releases/country/Canada",
        "https://www.globenewswire.com/RssFeed/subjectcode/28-Mergers%20Acquisitions/country/Canada",
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
                items.extend(entries)
                logger.debug("[GlobeNewswire] %d items from %s",
                             len(entries), feed_url)
            except Exception as exc:
                logger.error("[GlobeNewswire] Error: %s", exc)

        seen = set()
        unique = []
        for item in items:
            key = item.get("article_url", "")
            if key not in seen:
                seen.add(key)
                unique.append(item)
        logger.info("[GlobeNewswire] Collected %d unique items", len(unique))
        return unique
