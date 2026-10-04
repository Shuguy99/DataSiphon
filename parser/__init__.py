"""Универсальный парсер: HTTP-запросы + BeautifulSoup + экспорт в CSV."""

from .config import ConfigError, ParserConfig, load_config
from .exporter import CsvExporter
from .extract import ItemExtractor
from .fetcher import Fetcher, FetchError
from .pipeline import RunStats, Scraper

__all__ = (
    "ConfigError",
    "CsvExporter",
    "FetchError",
    "Fetcher",
    "ItemExtractor",
    "ParserConfig",
    "RunStats",
    "Scraper",
    "load_config",
)
__version__ = "1.0.0"