"""Точка входа: ``python -m parser --config config.json``."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from .config import ConfigError, DelayConfig, OutputConfig, ParserConfig, describe_config, load_config
from .exporter import CsvExporter
from .extract import ItemExtractor, available_parsers
from .fetcher import Fetcher, FetchError
from .pipeline import Scraper

logger = logging.getLogger("parser.cli")

PREVIEW_ROWS = 5


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m parser",
        description="Сбор структурированных данных с сайта в CSV (requests + BeautifulSoup).",
    )
    ap.add_argument("-c", "--config", required=True, help="путь к JSON-конфигу")
    ap.add_argument("-o", "--output", help="переопределить output.path из конфига")
    ap.add_argument("-u", "--url", dest="start_url", help="переопределить start_url")
    ap.add_argument("-n", "--max-pages", type=int, help="переопределить pagination.max_pages")
    ap.add_argument("-d", "--delay", type=float, help="фиксированная пауза между запросами, сек")
    ap.add_argument(
        "--parser",
        choices=available_parsers(),
        help="HTML-парсер BeautifulSoup (по умолчанию lxml, если установлен)",
    )
    ap.add_argument("--append", action="store_true", help="дописать в существующий CSV")
    ap.add_argument("--no-robots", action="store_true", help="не проверять robots.txt")
    ap.add_argument("--dry-run", action="store_true", help="разобрать страницы, но не писать CSV")
    ap.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    return ap


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def apply_overrides(config: ParserConfig, args: argparse.Namespace) -> ParserConfig:
    output = config.output
    if args.output:
        output = OutputConfig(
            path=args.output,
            encoding=output.encoding,
            deduplicate=output.deduplicate,
            append=output.append or args.append,
        )
    elif args.append:
        output = OutputConfig(
            path=output.path,
            encoding=output.encoding,
            deduplicate=output.deduplicate,
            append=True,
        )

    pagination = config.pagination
    if args.max_pages is not None:
        pagination = replace(pagination, max_pages=args.max_pages)

    delay = DelayConfig(args.delay, args.delay) if args.delay is not None else config.delay

    return config.with_overrides(
        start_url=args.start_url,
        output=output,
        pagination=pagination,
        delay=delay,
        respect_robots_txt=False if args.no_robots else config.respect_robots_txt,
    )


def preview(scraper: Scraper, limit: int = PREVIEW_ROWS) -> int:
    """Показывает первые строки первой страницы и ничего не сохраняет."""
    logger.info("Пробный запуск: %s", scraper.config.start_url)
    html = scraper.fetcher.get(scraper.config.start_url, scraper.delay)
    page = scraper.extractor.extract(html, base_url=scraper.config.start_url)
    columns = list(scraper.config.item.field_names)

    sample = page.rows[:limit]
    widths = {c: max([len(c), *(len(row.get(c, "")) for row in sample)]) for c in columns}
    logger.info("карточек на странице: %d, пример первых %d:", page.found, min(limit, len(page.rows)))
    print(" | ".join(c.ljust(widths[c]) for c in columns))
    for row in page.rows[:limit]:
        print(" | ".join(row.get(c, "").ljust(widths[c]) for c in columns))
    return page.found


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    if args.max_pages is not None and args.max_pages < 1:
        logger.error("--max-pages должен быть >= 1")
        return 2

    try:
        config = apply_overrides(load_config(args.config), args)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    logger.debug("%s", describe_config(config))

    output = Path(config.output.path)
    exporter = CsvExporter(config.output, config.item.field_names)
    extractor = ItemExtractor(config.item, parser=args.parser or "lxml")

    try:
        with Fetcher(config) as fetcher:
            scraper = Scraper(
                config,
                fetcher=fetcher,
                extractor=extractor,
                exporter=exporter,
                dry_run=args.dry_run,
            )
            if args.dry_run:
                found = preview(scraper)
                print(f"\nРежим --dry-run: CSV {output} не изменён. Найдено карточек: {found}")
                return 0

            stats = scraper.run()

        print(f"\n{stats.summary()}")
        if stats.errors:
            print(f"Ошибки ({len(stats.errors)}):")
            for err in stats.errors[:10]:
                print(f"  - {err}")
        if output.exists():
            print(f"Данные: {output} ({output.stat().st_size} байт)")
        else:
            print(f"CSV не создан: {output}")
        return 0 if not stats.errors else 1
    except FetchError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Прервано пользователем — часть данных сохранена в %s", output)
        return 130


if __name__ == "__main__":
    sys.exit(main())
