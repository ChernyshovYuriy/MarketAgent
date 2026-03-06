"""
setup.py — install the CA Market Agent as an editable package.

    pip install -e .

This places the project root on sys.path permanently so all absolute
imports (collector.*, core.*, storage.*, agents.*) work from anywhere.
"""
from setuptools import setup, find_packages

setup(
    name="ca_market_agent",
    version="1.0.0",
    description="Canadian Market Opportunity Detection Agent",
    python_requires=">=3.10",
    packages=find_packages(
        include=[
            "collector", "collector.*",
            "core", "core.*",
            "storage", "storage.*",
            "agents", "agents.*",
            "tools", "tools.*",
        ]
    ),
    install_requires=[
        "requests>=2.31.0",
        "feedparser>=6.0.10",
        "beautifulsoup4>=4.12.0",
        "lxml>=4.9.0",
        "PyYAML>=6.0.1",
        "psutil>=5.9.8",
        "python-dateutil>=2.8.2",
    ],
    entry_points={
        "console_scripts": [
            "ca-market-agent=main:main",
        ],
    },
)
