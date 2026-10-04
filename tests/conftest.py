"""Общие фикстуры pytest."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.config import DelayConfig, config_from_dict
from parser.exporter import CsvExporter
from parser.extract import ItemExtractor
from parser.fetcher import Fetcher
from parser.pipeline import Scraper
from tests.fixture_site import LocalSite

# Переопределения вида max_pages=3 должны попадать внутрь секции pagination, а не в корень.
SECTION_KEYS = {
    "mode": "pagination",
    "next_selector": "pagination",
    "link_selector": "pagination",
    "url_template": "pagination",
    "start_page": "pagination",
    "max_pages": "pagination",
    "path": "output",
    "encoding": "output",
    "deduplicate": "output",
    "append": "output",
    "container": "item",
    "fields": "item",
}


@pytest.fixture(scope="session")
def site() -> LocalSite:
    server = LocalSite(pages=3, per_page=3)
    yield server
    server.close()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def make_config(tmp_path: Path):
    """Фабрика конфигов: принимает base_url и переопределения, возвращает ParserConfig."""

    def factory(base_url: str, output: str | Path = "result.csv", **overrides: Any):
        payload: dict[str, Any] = {
            "start_url": f"{base_url}/catalog?page=1",
            "item": {
                "container": "article.product-card",
                "fields": [
                    {"name": "title", "selector": "h2.product-card__title", "required": True},
                    {
                        "name": "price",
                        "selector": "span.product-card__price",
                        "transform": "price",
                    },
                    {
                        "name": "link",
                        "selector": "h2.product-card__title a",
                        "attribute": "href",
                        "transform": "url",
                    },
                    {
                        "name": "rating",
                        "selector": "meta.product-card__rating",
                        "attribute": "content",
                        "transform": "float",
                    },
                ],
            },
            "pagination": {"mode": "next", "next_selector": "a.pager__next", "max_pages": 20},
            "output": {"path": str(tmp_path / output), "encoding": "utf-8"},
            "delay": {"min": 0, "max": 0},
            "timeout": 5,
            "retries": 0,
            "respect_robots_txt": True,
        }
        for key, value in overrides.items():
            section = SECTION_KEYS.get(key)
            if section and isinstance(payload.get(section), dict):
                payload[section][key] = value
            else:
                payload[key] = value
        return config_from_dict(payload)

    return factory


@pytest.fixture
def make_scraper(make_config, sleeps):
    """Готовит Scraper поверх локального сайта (аргументы -> конфиг, dry_run -> Scraper)."""

    def factory(base_url: str, output: str | Path = "result.csv", *, dry_run: bool = False, **overrides: Any):
        config = make_config(base_url, output, **overrides)
        fetcher = Fetcher(config, sleep=sleeps.append, rng=random.Random(0))
        exporter = CsvExporter(config.output, config.item.field_names)
        return Scraper(
            config,
            fetcher=fetcher,
            extractor=ItemExtractor(config.item),
            exporter=exporter,
            delay=DelayConfig(0, 0),
            dry_run=dry_run,
        )

    return factory


@pytest.fixture
def write_config(tmp_path: Path):
    """Пишет конфиг в tmp и возвращает путь (для тестов CLI)."""

    def factory(payload: dict[str, Any], name: str = "config.json") -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    return factory