"""Извлечение полей и преобразования значений."""

from __future__ import annotations

import pytest

from parser.config import config_from_dict
from parser.extract import ExtractError, ItemExtractor, to_price

HTML = """
<html><body>
  <article class="card">
    <h2 class="card__title">  <a href="/p/1"> Первый   товар </a> </h2>
    <span class="card__price">1 299,50 ₽</span>
    <meta class="card__rating" content="4.5">
    <ul class="card__tags"><li>химия</li><li>дом</li></ul>
  </article>
  <article class="card">
    <h2 class="card__title">Второй товар</h2>
    <span class="card__price">999 руб.</span>
    <span class="card__old-price">1 500</span>
  </article>
  <article class="card">
    <h2 class="card__title">Третий товар</h2>
  </article>
</body></html>
"""


def build(fields, container=".card"):
    return config_from_dict(
        {
            "start_url": "https://shop.example/catalog",
            "item": {"container": container, "fields": fields},
        }
    ).item


@pytest.mark.parametrize(
    ("raw", "ожидается"),
    [
        ("1 299 ₽", "1299"),
        ("1 299,50 ₽", "1299.50"),
        ("1.299,50 руб.", "1299.50"),
        ("1,299", "1299"),
        ("12,5", "12.5"),
        ("999", "999"),
        ("Цена по запросу", ""),
    ],
)
def test_нормализация_цены(raw, ожидается):
    assert to_price(raw) == ожидается


def test_извлечение_всех_полей():
    item = build(
        [
            {"name": "title", "selector": "h2.card__title", "required": True},
            {"name": "price", "selector": "span.card__price", "transform": "price"},
            {"name": "link", "selector": "h2.card__title a", "attribute": "href", "transform": "url"},
            {"name": "rating", "selector": "meta.card__rating", "attribute": "content", "transform": "float"},
        ]
    )
    page = ItemExtractor(item).extract(HTML, base_url="https://shop.example/catalog?page=1")

    assert page.found == 3
    assert len(page.rows) == 3
    assert page.rows[0] == {
        "title": "Первый товар",
        "price": "1299.50",
        "link": "https://shop.example/p/1",
        "rating": "4.5",
    }
    assert page.rows[1]["price"] == "999"
    assert page.rows[2]["price"] == ""


def test_карточка_без_обязательного_поля_пропускается():
    item = build([{"name": "price", "selector": "span.card__price", "transform": "price", "required": True}])
    page = ItemExtractor(item).extract(HTML, base_url="https://shop.example/catalog")

    assert page.found == 3
    assert len(page.rows) == 2
    assert page.skipped == 1


def test_отсутствие_контейнеров_даёт_понятную_ошибку():
    item = build([{"name": "title", "selector": "h2"}], container=".product-card")

    with pytest.raises(ExtractError, match=r"product-card"):
        ItemExtractor(item).extract(HTML, base_url="https://shop.example/catalog")


def test_строгий_режим_падает_если_все_карточки_пропущены():
    item = build([{"name": "title", "selector": "h2.missing", "required": True}])

    with pytest.raises(ExtractError, match="пропущены"):
        ItemExtractor(item, strict=True).extract(HTML, base_url="https://shop.example/catalog")


def test_склейка_списка_тегов():
    item = build([{"name": "tags", "selector": "ul.card__tags li", "all": True, "join_with": ", "}])
    page = ItemExtractor(item).extract(HTML, base_url="https://shop.example/catalog")

    assert page.rows[0]["tags"] == "химия, дом"


def test_разбор_работает_и_на_битой_разметке():
    html = "<html><body><div class='card'><h2>Один<div class='card'>Два</div>"
    item = build([{"name": "title", "selector": ".card", "required": True}], container=".card")
    page = ItemExtractor(item).extract(html, base_url="https://shop.example/catalog")

    assert page.found == 2


@pytest.mark.parametrize("parser", ["lxml", "html.parser"])
def test_одинаковый_результат_у_разных_парсеров(parser):
    item = build([{"name": "title", "selector": "h2.card__title"}])
    page = ItemExtractor(item, parser=parser).extract(HTML, base_url="https://shop.example/catalog")

    assert [r["title"] for r in page.rows] == ["Первый товар", "Второй товар", "Третий товар"]


def test_склейка_всех_совпадений_через_all():
    html = """<div class="card">
      <a class="card__link" href="/p/1">Раз</a>
      <a class="card__link" href="/p/2">Два</a>
    </div>"""
    item = build(
        [{"name": "links", "selector": "a.card__link", "attribute": "href", "all": True, "join_with": "|"}]
    )
    page = ItemExtractor(item).extract(html, base_url="https://shop.example/catalog")

    assert page.rows[0]["links"] == "/p/1|/p/2"