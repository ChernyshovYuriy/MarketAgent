"""
core/symbol_resolver.py
Resolves ticker mentions in news/filing text to known TSX/TSXV symbols.
Uses a local ticker database + pattern matching.
"""

import logging
import re
from typing import List, Set, Dict

logger = logging.getLogger(__name__)

# Common false-positive symbols to exclude
FALSE_POSITIVES = {
    "A", "I", "IT", "US", "AM", "PM", "CEO", "CFO", "COO",
    "CTO", "ESG", "GDP", "IPO", "ETF", "AUM", "NAV", "EPS",
    "PE", "PB", "ROE", "ROA", "TSX", "NYSE", "NASDAQ", "OTC",
    "USD", "CAD", "EUR", "GBP", "TBD", "TBA", "N/A", "NA",
    "Q1", "Q2", "Q3", "Q4", "H1", "H2", "YTD", "YOY", "QOQ",
    "AI", "ML", "API", "SaaS", "B2B", "B2C", "IPO", "SPV",
}

# TSX suffix patterns
TSX_SUFFIX_RE = re.compile(
    r"\b([A-Z]{1,6})\s*"
    r"(?:\."
    r"(?:TO|V|TSX|TSXV)"
    r")?\b"
)

# Exchange-qualified pattern: e.g. "TSX: ABC" or "(TSX-V: XYZ)"
EXCHANGE_QUALIFIED_RE = re.compile(
    r"(?:TSX(?:-?V(?:enture)?)?|TSXV)[:\s–-]+([A-Z]{1,6}(?:\.[A-Z]{1,2})?)",
    re.IGNORECASE
)

# Suffix .TO or .V pattern
SUFFIX_RE = re.compile(
    r"\b([A-Z]{1,6})\.(?:TO|V)\b"
)


class SymbolResolver:
    def __init__(self, db=None):
        """
        db: Database instance (optional). When provided, lookups are
        validated against the local ticker universe.
        """
        self.db = db
        self._ticker_set: Set[str] = set()
        self._alias_map: Dict[str, str] = {}  # alias -> canonical ticker
        if db:
            self._load_universe()

    def _load_universe(self):
        tickers = self.db.get_all_tickers()
        for t in tickers:
            sym = t["ticker"].upper()
            self._ticker_set.add(sym)
            # Add base symbol without exchange suffix
            base = sym.split(".")[0]
            self._ticker_set.add(base)
            self._alias_map[base] = sym
            for alias in t.get("aliases", []):
                self._alias_map[alias.upper()] = sym

    def refresh(self):
        """Reload ticker universe from DB."""
        self._ticker_set.clear()
        self._alias_map.clear()
        if self.db:
            self._load_universe()

    def resolve(self, text: str, headline: str = "") -> List[str]:
        """
        Extract and resolve ticker symbols from a news headline + body text.
        Returns list of resolved canonical tickers.
        """
        combined = f"{headline} {text}"
        candidates: Set[str] = set()

        # 1. Exchange-qualified mentions (highest confidence)
        for m in EXCHANGE_QUALIFIED_RE.finditer(combined):
            sym = m.group(1).upper().strip()
            candidates.add(sym)

        # 2. .TO / .V suffix mentions
        for m in SUFFIX_RE.finditer(combined):
            sym = m.group(1).upper()
            candidates.add(sym)
            candidates.add(f"{sym}.TO")
            candidates.add(f"{sym}.V")

        # 3. Upper-case word sequences as potential tickers (3-5 chars)
        words = re.findall(r"\b[A-Z]{2,6}\b", combined)
        for word in words:
            if word not in FALSE_POSITIVES and len(word) >= 2:
                candidates.add(word)

        # Resolve to canonical tickers
        resolved = []
        seen = set()
        for cand in candidates:
            canonical = self._canonicalize(cand)
            if canonical and canonical not in seen:
                seen.add(canonical)
                resolved.append(canonical)

        return resolved

    def _canonicalize(self, symbol: str) -> str:
        """Map a raw symbol to canonical form, or None if unrecognised."""
        symbol = symbol.upper().strip()

        # Direct hit
        if symbol in self._ticker_set:
            return self._alias_map.get(symbol, symbol)

        # Try with .TO suffix
        with_to = f"{symbol}.TO"
        if with_to in self._ticker_set:
            return self._alias_map.get(with_to, with_to)

        # Try with .V suffix (TSXV)
        with_v = f"{symbol}.V"
        if with_v in self._ticker_set:
            return self._alias_map.get(with_v, with_v)

        # Strip suffix and try base
        base = symbol.split(".")[0]
        if base in self._alias_map:
            return self._alias_map[base]

        # If no DB loaded, return all plausible symbols (lenient mode)
        if not self._ticker_set and len(symbol) >= 2 and symbol not in FALSE_POSITIVES:
            return symbol

        return None
