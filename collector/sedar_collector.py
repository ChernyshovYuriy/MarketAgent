"""
collector/sedar_collector.py
Collects regulatory filings from SEDAR+ (Canadian securities regulator).
Parses public RSS / search endpoints for recent filings.
"""

import re
import logging
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any

from .base_collector import BaseCollector

logger = logging.getLogger(__name__)


class SedarCollector(BaseCollector):
    SOURCE_NAME = "SEDAR"
    RELIABILITY = 1.0   # Highest - regulatory source

    # SEDAR+ public RSS/search endpoints
    BASE_URL = "https://www.sedarplus.ca"

    # Document types of interest
    DOCUMENT_TYPES_OF_INTEREST = {
        "annual financial statements":      "financial_statements",
        "interim financial statements":     "financial_statements",
        "management discussion":            "MD&A",
        "md&a":                             "MD&A",
        "material change report":           "material_change",
        "press release":                    "press_release",
        "news release":                     "press_release",
        "financing":                        "financing",
        "prospectus":                       "financing",
        "private placement":                "financing",
        "acquisition":                      "acquisition",
        "business combination":             "acquisition",
        "arrangement":                      "acquisition",
    }

    # Regex to extract TSX/TSXV tickers from filing text
    TICKER_RE = re.compile(
        r"\b([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\s*"
        r"(?:\((?:TSX|TSXV|TSX-?V|TSX Venture)[:\s]*([A-Z.]+)\))?",
        re.IGNORECASE
    )

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.rss_url = config.get(
            "rss_url",
            "https://www.sedarplus.ca/csa-party/party/document.html"
        )

    def collect(self) -> List[Dict[str, Any]]:
        """
        Attempt to fetch SEDAR+ public filing feeds.
        Falls back gracefully if unavailable.
        """
        filings = []

        # Try RSS feed first
        try:
            rss_filings = self._collect_rss()
            filings.extend(rss_filings)
        except Exception as exc:
            logger.warning("[SEDAR] RSS collection failed: %s", exc)

        # Try the public search API as fallback
        if not filings:
            try:
                api_filings = self._collect_search_api()
                filings.extend(api_filings)
            except Exception as exc:
                logger.warning("[SEDAR] API collection failed: %s", exc)

        logger.info("[SEDAR] Collected %d filings", len(filings))
        return filings

    def _collect_rss(self) -> List[Dict]:
        """Parse SEDAR+ RSS feed."""
        entries = self._parse_rss(self.rss_url)
        result = []
        for entry in entries:
            filing = self._normalize_filing(entry)
            if filing:
                result.append(filing)
        return result

    def _collect_search_api(self) -> List[Dict]:
        """
        SEDAR+ public document search - returns recent filings.
        This hits the public search endpoint with no authentication.
        """
        search_url = (
            f"{self.BASE_URL}/csa-party/party/document.html"
            "?search=&type=&language=E&sortField=FILINGDATE&sortOrder=DESC"
        )
        resp = self._get(search_url)
        if resp is None:
            return []

        # Parse the HTML response to extract filing info
        filings = self._parse_sedar_html(resp.text)
        return filings

    def _parse_sedar_html(self, html: str) -> List[Dict]:
        """Basic HTML parsing for SEDAR+ filing tables."""
        results = []

        # Look for company names, tickers, document types
        rows = re.findall(
            r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE
        )
        for row in rows:
            cells = re.findall(
                r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE
            )
            if len(cells) < 3:
                continue
            text_cells = [re.sub(r'<[^>]+>', ' ', c).strip() for c in cells]
            headline = " | ".join(c for c in text_cells if c)
            if not headline:
                continue

            link_match = re.search(r'href="([^"]+)"', row, re.IGNORECASE)
            url = ""
            if link_match:
                href = link_match.group(1)
                url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            doc_type = self._classify_document_type(headline)
            uid = hashlib.sha256(f"{url}||{headline}".encode()).hexdigest()[:16]
            results.append({
                "id": uid,
                "headline": headline,
                "publication_time": datetime.now(timezone.utc).isoformat(),
                "source": self.SOURCE_NAME,
                "article_url": url,
                "article_text": headline,
                "document_type": doc_type,
                "source_reliability": self.RELIABILITY,
            })
        return results

    def _normalize_filing(self, raw: Dict) -> Dict:
        """Normalize an RSS entry to the filing format."""
        headline = raw.get("headline", "")
        if not headline:
            return None
        doc_type = self._classify_document_type(headline)
        uid = self.make_id(raw.get("article_url", ""), headline)
        return {
            "id": uid,
            "headline": headline,
            "publication_time": raw.get("publication_time",
                                        datetime.now(timezone.utc).isoformat()),
            "source": self.SOURCE_NAME,
            "article_url": raw.get("article_url", ""),
            "article_text": raw.get("article_text", ""),
            "document_type": doc_type,
            "source_reliability": self.RELIABILITY,
        }

    def _classify_document_type(self, text: str) -> str:
        lower = text.lower()
        for keyword, doc_type in self.DOCUMENT_TYPES_OF_INTEREST.items():
            if keyword in lower:
                return doc_type
        return "general_filing"
