"""
collector/prnews_collector.py
Collects Canadian financial press releases from PR Newswire.
"""

import logging
from typing import List, Dict, Any

from .base_collector import BaseCollector

logger = logging.getLogger(__name__)


class PRNewsCollector(BaseCollector):
    SOURCE_NAME = "PRNewswire"
    RELIABILITY = 0.7

    FEEDS = [
        "https://www.prnewswire.com/rss/news-releases-list.rss?category=FIN",
        "https://www.prnewswire.com/rss/news-releases-list.rss?category=OIL",
        "https://www.prnewswire.com/rss/news-releases-list.rss?category=MIN",
        "https://www.prnewswire.com/rss/news-releases-list.rss",
    ]

    # Keywords to filter for Canadian content
    CANADIAN_KEYWORDS = [
        "TSX", "TSXV", "Toronto Stock Exchange", "TSX Venture",
        "Canada", "Canadian", "Ontario", "British Columbia",
        "Alberta", "Quebec", "Vancouver", "Calgary", "Toronto",
        ".TO", ":TSX", ":TSXV",
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
                logger.debug("[PRNewswire] %d Canadian items from %s",
                             len(canadian), feed_url)
            except Exception as exc:
                logger.error("[PRNewswire] Error: %s", exc)

        seen = set()
        unique = []
        for item in items:
            key = item.get("article_url", "")
            if key not in seen:
                seen.add(key)
                unique.append(item)
        logger.info("[PRNewswire] Collected %d unique items", len(unique))
        return unique
