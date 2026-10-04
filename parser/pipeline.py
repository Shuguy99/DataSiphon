"""Основной цикл: обход страниц, извлечение данных и экспорт в CSV."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .config import DelayConfig, ParserConfig
from .exporter import CsvExporter
from .extract import ItemExtractor, PageData
from .fetcher import Fetcher, FetchError
from .pagination import Paginator

logger = logging.getLogger("parser.pipeline")

# Причины завершения обхода
END_NO_NEXT = "следующей страницы нет"
END_NO_ITEMS = "на странице нет карточек"
END_EMPTY_ROWS = "не найдено ни одной подходящей карточки"
END_MAX_PAGES = "достигнут лимит страниц"
END_ERROR = "ошибка загрузки страницы"


@dataclass
class RunStats:
    pages: int = 0
    containers: int = 0
    rows: int = 0
    skipped: int = 0
    duplicates: int = 0
    requests: int = 0
    errors: list[str] = field(default_factory=list)
    finish_reason: str = ""

    def summary(self) -> str:
        parts = [
            f"страниц: {self.pages}",
            f"карточек: {self.containers}",
            f"строк: {self.rows}",
        ]
        if self.skipped:
            parts.append(f"пропущено карточек: {self.skipped}")
        if self.duplicates:
            parts.append(f"дублей отброшено: {self.duplicates}")
        parts.append(f"запросов: {self.requests}")
        parts.append(f"остановка: {self.finish_reason or END_NO_NEXT}")
        return ", ".join(parts)


class Scraper:
    """Оркестрирует пагинацию, парсинг и запись в CSV.

    Конструктор принимает уже готовые ``fetcher``/``extractor``/``exporter`` —
    это используется в тестах и позволяет подменять слои.
    """

    def __init__(
        self,
        config: ParserConfig,
        *,
        fetcher: Fetcher | None = None,
        extractor: ItemExtractor | None = None,
        exporter: CsvExporter | None = None,
        delay: DelayConfig | None = None,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.delay = delay if delay is not None else config.delay
        self._owns_fetcher = fetcher is None
        self.fetcher = fetcher or Fetcher(config)
        self.extractor = extractor or ItemExtractor(config.item)
        self.exporter = exporter or CsvExporter(config.output, config.item.field_names)
        self.paginator = Paginator(config.pagination, config.start_url)

    def run(self, on_page: Callable[[int, str, list[dict[str, str]]], None] | None = None) -> RunStats:
        stats = RunStats()
        max_pages = self.config.pagination.max_pages

        try:
            while self.paginator.has_next and stats.pages < max_pages:
                url = self.paginator.next_url()
                if url is None:
                    break

                stats.pages += 1
                logger.info("[%d/%d] %s", stats.pages, max_pages, url)

                try:
                    html = self.fetcher.get(url, self.delay)
                except FetchError as exc:
                    stats.errors.append(str(exc))
                    logger.error("не удалось загрузить %s: %s", url, exc)
                    if self.config.stop_on_error:
                        stats.finish_reason = END_ERROR
                        break
                    self.paginator.skip()
                    continue

                soup = self.extractor.parse(html)
                page = self._process(soup, url, stats)
                if on_page is not None:
                    on_page(stats.pages, url, page.rows)
                if not self.dry_run:
                    self.exporter.write(page.rows)

                if page.found == 0:
                    stats.finish_reason = END_NO_ITEMS
                    break
                if not page.rows:
                    stats.finish_reason = END_EMPTY_ROWS
                    break

                self.paginator.update(soup, url)
        finally:
            stats.requests = self.fetcher.requests_made
            stats.duplicates = self.exporter.duplicates_skipped
            self.close()

        if not stats.finish_reason:
            stats.finish_reason = END_MAX_PAGES if stats.pages >= max_pages else END_NO_NEXT
        logger.info("Готово: %s", stats.summary())
        return stats

    def _process(self, soup: BeautifulSoup, url: str, stats: RunStats) -> PageData:
        """Извлекает карточки страницы; отсутствие нужной разметки не роняет обход."""
        try:
            page = self.extractor.extract_soup(soup, base_url=url)
        except Exception as exc:
            stats.errors.append(str(exc))
            logger.warning("страница %s пропущена: %s", url, exc)
            return PageData(rows=[], found=0, skipped=0, empty_fields=0)

        stats.containers += page.found
        stats.rows += len(page.rows)
        stats.skipped += page.skipped
        return page

    def close(self) -> None:
        self.exporter.close()
        if self._owns_fetcher:
            self.fetcher.close()

    def __enter__(self) -> Scraper:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()