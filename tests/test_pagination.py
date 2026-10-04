"""Определение следующей страницы."""

from __future__ import annotations

import pytest

from parser.config import PaginationConfig
from parser.extract import make_soup
from parser.pagination import Paginator, bump_page

PAGE_WITH_NEXT = """
<html><body>
  <nav class="pager">
    <a class="pager__num" href="/c?page=1">1</a>
    <a class="pager__num" href="/c?page=2">2</a>
    <a class="pager__next" href="/c?page=2">Вперёд</a>
  </nav>
</body></html>
"""

PAGE_LAST = """
<html><body>
  <nav class="pager">
    <a class="pager__num" href="/c?page=1">1</a>
    <span class="pager__next disabled">Вперёд</span>
  </nav>
</body></html>
"""


def test_стартовая_страница_и_переход_вперёд():
    paginator = Paginator(PaginationConfig(next_selector="a.pager__next"), "https://x.test/c?page=1")

    assert paginator.next_url() == "https://x.test/c?page=1"
    paginator.update(make_soup(PAGE_WITH_NEXT), "https://x.test/c?page=1")
    assert paginator.next_url() == "https://x.test/c?page=2"
    paginator.update(make_soup(PAGE_LAST), "https://x.test/c?page=2")
    assert paginator.next_url() is None
    assert not paginator.has_next


def test_на_последней_странице_обход_заканчивается():
    paginator = Paginator(PaginationConfig(next_selector="a.pager__next"), "https://x.test/c?page=2")

    assert paginator.next_url() == "https://x.test/c?page=2"
    paginator.update(make_soup(PAGE_LAST), "https://x.test/c?page=2")

    assert not paginator.has_next


def test_режим_ссылок_обходит_только_непосещённые():
    config = PaginationConfig(mode="links", link_selector="a.pager__num")
    paginator = Paginator(config, "https://x.test/c?page=1")

    first = paginator.next_url()
    paginator.update(make_soup(PAGE_WITH_NEXT), first)
    second = paginator.next_url()
    paginator.update(make_soup(PAGE_WITH_NEXT), second)

    assert first == "https://x.test/c?page=1"
    assert second == "https://x.test/c?page=2"
    assert paginator.next_url() is None


def test_режим_шаблона_строит_url():
    config = PaginationConfig(mode="template", url_template="https://x.test/c?page={page}")
    paginator = Paginator(config, "https://x.test/c?page=1")

    assert paginator.next_url() == "https://x.test/c?page=1"
    paginator.update(make_soup("<html></html>"), "https://x.test/c?page=1")
    assert paginator.next_url() == "https://x.test/c?page=2"
    paginator.update(make_soup("<html></html>"), "https://x.test/c?page=2")
    assert paginator.next_url() == "https://x.test/c?page=3"


def test_защита_от_зацикливания_пагинации():
    paginator = Paginator(PaginationConfig(next_selector="a.pager__next"), "https://x.test/c?page=1")

    url = paginator.next_url()
    visited = [url]
    # Страница всегда ссылается на page=2: после неё цикл обязан оборваться.
    for _ in range(5):
        paginator.update(make_soup(PAGE_WITH_NEXT), url)
        следующая = paginator.next_url()
        if следующая is None:
            break
        visited.append(следующая)
        url = следующая

    assert visited == ["https://x.test/c?page=1", "https://x.test/c?page=2"]
    assert not paginator.has_next


def test_режим_none_берёт_только_стартовую_страницу():
    paginator = Paginator(PaginationConfig(mode="none"), "https://x.test/c?page=1")

    assert paginator.next_url() == "https://x.test/c?page=1"
    paginator.update(make_soup(PAGE_WITH_NEXT), "https://x.test/c?page=1")

    assert paginator.next_url() is None


def test_относительные_ссылки_становятся_абсолютными():
    html = '<html><body><a class="pager__next" href="../page/2?page=2">далее</a></body></html>'
    paginator = Paginator(PaginationConfig(next_selector="a.pager__next"), "https://x.test/catalog/index.html")

    paginator.next_url()
    paginator.update(make_soup(html), "https://x.test/catalog/index.html")

    assert paginator.next_url() == "https://x.test/page/2?page=2"


@pytest.mark.parametrize(
    ("url", "delta", "ожидается"),
    [
        ("https://x.test/c?page=2", 1, "https://x.test/c?page=3"),
        ("https://x.test/c?a=1&page=7&b=2", 1, "https://x.test/c?a=1&page=8&b=2"),
        ("https://x.test/c?page=1&offset=4", 1, "https://x.test/c?page=2&offset=5"),
        ("https://x.test/c?page=1", -1, "https://x.test/c?page=0"),
        ("https://x.test/c", 1, None),
        ("https://x.test/c?sort=price", 1, None),
    ],
)
def test_сдвиг_номера_страницы(url, delta, ожидается):
    assert bump_page(url, delta) == ожидается