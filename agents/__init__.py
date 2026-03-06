"""
agents/__init__.py
Lazy imports — avoids importing MarketAgent at package load time,
which would chain into collector/core/storage before sys.path is ready.
"""


def get_market_agent():
    from agents.market_agent import MarketAgent  # noqa: E402
    return MarketAgent


def get_scheduler():
    from agents.scheduler import run  # noqa: E402
    return run


# Convenience: expose names directly when the package is already on sys.path
try:
    from agents.market_agent import MarketAgent  # noqa: F401
    from agents.scheduler import run as run_scheduler  # noqa: F401
    __all__ = ["MarketAgent", "run_scheduler"]
except ImportError:
    __all__ = ["get_market_agent", "get_scheduler"]
