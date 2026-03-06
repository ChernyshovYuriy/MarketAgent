"""
agents/scheduler.py
Runs the MarketAgent on a configurable polling interval.
Monitors memory and CPU usage to stay within Jetson Nano limits.
"""

import gc
import sys
import time
import signal
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil
import yaml

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so MarketAgent (and its transitive
# imports of collector/, core/, storage/) can be resolved from anywhere.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

# Shutdown sentinel
_shutdown_event = threading.Event()


def _handle_signal(sig, frame):
    logger.info("Shutdown signal received (%s). Stopping...", sig)
    _shutdown_event.set()


def _setup_signals():
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)


def _log_resources():
    proc    = psutil.Process()
    mem_mb  = proc.memory_info().rss / 1024 / 1024
    cpu_pct = psutil.cpu_percent(interval=0.5)
    logger.info("Resources — RAM: %.0f MB | CPU: %.1f%%", mem_mb, cpu_pct)
    return mem_mb, cpu_pct


def run(config_path: str = "config.yaml"):
    """Entry point: start the continuous polling loop."""
    _setup_signals()

    with open(config_path) as f:
        config = yaml.safe_load(f)

    agent_cfg    = config.get("agent", {})
    poll_interval = agent_cfg.get("poll_interval_seconds", 120)
    max_memory_mb = agent_cfg.get("max_memory_mb", 900)
    log_level     = agent_cfg.get("log_level", "INFO")

    logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))

    # Import after path fix is in place
    from agents.market_agent import MarketAgent  # noqa: E402

    logger.info("Scheduler starting — poll interval: %ds", poll_interval)
    agent: Optional[MarketAgent] = None

    try:
        agent = MarketAgent(config_path)
    except Exception as exc:
        logger.critical("Failed to initialise MarketAgent: %s", exc)
        sys.exit(1)

    cycle_count = 0
    while not _shutdown_event.is_set():
        cycle_start = time.monotonic()
        cycle_count += 1
        logger.info(
            "--- Cycle #%d  [%s] ---",
            cycle_count,
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

        try:
            stats = agent.run_cycle()
            logger.info("Cycle #%d stats: %s", cycle_count, stats)
        except Exception as exc:
            logger.error("Cycle #%d error: %s", cycle_count, exc, exc_info=True)

        # Resource check — force GC if we're approaching the memory ceiling
        mem_mb, _cpu = _log_resources()
        if mem_mb > max_memory_mb:
            logger.warning(
                "Memory %.0f MB > limit %.0f MB — forcing GC",
                mem_mb, max_memory_mb,
            )
            gc.collect()

        # Sleep until the next poll, checking for shutdown every second
        elapsed    = time.monotonic() - cycle_start
        sleep_time = max(0, poll_interval - elapsed)
        logger.debug("Cycle took %.1fs. Sleeping %.1fs", elapsed, sleep_time)
        _sleep_interruptible(sleep_time)

    logger.info("Scheduler stopped after %d cycles", cycle_count)


def _sleep_interruptible(seconds: float, chunk: float = 1.0):
    """Sleep for `seconds` total, waking every `chunk` s to honour shutdown."""
    deadline = time.monotonic() + seconds
    while not _shutdown_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(chunk, remaining))
