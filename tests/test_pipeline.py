"""Сквозной обход каталога: пагинация + извлечение + CSV."""

from __future__ import annotations

import csv

import pytest

from parser.extract import ItemExtractor
from parser.pipeline import END_ERROR, END_MAX_PAGES, END_NO_ITEMS, END_NO_NEXT


def read(path):
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_обход_всех_страниц_и_запись_в_csv(site, make_scraper, tmp_path):
    scraper = make_scraper(site.base_url)
    stats = scraper.run()

    rows = read(tmp_path / "result.csv")
    assert stats.pages == 3
    assert stats.containers == 10  # 3+3+3 товара + 1 битая карточка
    assert stats.skipped == 1
    assert stats.rows == 9
    assert stats.finish_reason == END_NO_NEXT
    assert stats.errors == []

    assert len(rows) == 9
    assert rows[0] == {
        "title": "Товар №1",
        "price": "100.10",
        "link": f"{site.base_url}/product/1",
        "rating": "4.5",
    }
    assert rows[-1]["title"] == "Товар №9"


def test_остановка_по_лимиту_страниц(site, make_scraper, tmp_path):
    scraper = make_scraper(site.base_url, max_pages=2)
    stats = scraper.run()

    assert stats.pages == 2
    assert stats.finish_reason == END_MAX_PAGES
    assert len(read(tmp_path / "result.csv")) == 6


def test_остановка_на_странице_без_карточек(site, make_scraper):
    scraper = make_scraper(site.base_url, start_url=site.url("/no-items"))
    stats = scraper.run()

    assert stats.pages == 1
    assert stats.rows == 0
    assert stats.finish_reason == END_NO_ITEMS
    assert stats.errors


def test_ошибка_загрузки_останавливает_обход(site, make_scraper):
    scraper = make_scraper(site.base_url, start_url=site.url("/always-500"))
    stats = scraper.run()

    assert stats.pages == 1
    assert stats.rows == 0
    assert stats.finish_reason == END_ERROR
    assert len(stats.errors) == 1


def test_ошибка_загрузки_не_останавливает_обход(site, make_scraper):
    scraper = make_scraper(
        site.base_url,
        start_url=site.url("/always-500?page=1"),
        pagination={"mode": "template", "url_template": site.url("/always-500?page={page}")},
        stop_on_error=False,
        max_pages=3,
    )
    stats = scraper.run()

    assert stats.pages == 3
    assert stats.finish_reason == END_MAX_PAGES
    assert len(stats.errors) == 3


def test_повтор_при_сбое_и_продолжение_обхода(site, make_scraper, tmp_path):
    """Первая страница один раз отдаёт 503: ретрай спасает, обход продолжается."""
    scraper = make_scraper(
        site.base_url,
        start_url=site.url("/flaky-catalog?fail=1&fail_key=pipeline_retry&page=1"),
        pagination={
            "mode": "template",
            "url_template": site.url("/flaky-catalog?fail=0&page={page}"),
        },
        retries=1,
        retry_backoff=0,
        max_pages=3,
    )
    stats = scraper.run()

    assert stats.pages == 3
    assert stats.rows == 9
    assert stats.errors == []
    assert stats.requests == 4  # три страницы + один ретрай
    assert len(read(tmp_path / "result.csv")) == 9


def test_стабильные_ретраи_без_повторов(site, make_scraper):
    scraper = make_scraper(site.base_url, retries=2, retry_backoff=0)
    stats = scraper.run()

    assert stats.requests == 3
    assert stats.pages == 3


def test_dry_run_не_создаёт_файл(site, make_scraper, tmp_path):
    scraper = make_scraper(site.base_url, dry_run=True)
    pages: list[tuple[int, str, int]] = []
    stats = scraper.run(on_page=lambda n, url, rows: pages.append((n, url, len(rows))))

    out = tmp_path / "result.csv"
    assert stats.rows == 9
    assert len(pages) == 3
    assert pages[0][2] == 3
    assert not out.exists()


def test_на_страницу_вызывается_обработчик(site, make_scraper):
    scraper = make_scraper(site.base_url, max_pages=1)
    seen: list[str] = []
    stats = scraper.run(on_page=lambda number, url, rows: seen.append(url))

    assert stats.pages == 1
    assert seen == [site.url("/catalog?page=1")]


@pytest.mark.parametrize("parser", ["lxml", "html.parser"])
def test_разные_html_парсеры_дают_одинаковый_результат(site, make_scraper, tmp_path, parser):
    scraper = make_scraper(site.base_url, max_pages=1)
    scraper.extractor = ItemExtractor(scraper.config.item, parser=parser)
    stats = scraper.run()

    assert stats.rows == 3
    assert len(read(tmp_path / "result.csv")) == 3


def test_robots_txt_учитывается(site, make_scraper):
    scraper = make_scraper(site.base_url, start_url=site.url("/private/x"))
    stats = scraper.run()

    assert stats.pages == 1
    assert stats.rows == 0
    assert stats.finish_reason == END_ERROR
    assert "robots.txt" in stats.errors[0]