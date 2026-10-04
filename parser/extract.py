"""Извлечение полей карточки по CSS-селекторам."""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .config import FieldSpec, ItemConfig

PARSERS = ("lxml", "html.parser", "html5lib")

_CURRENCY_RE = re.compile(r"[^\d\s., '-]")
_SPACE_RE = re.compile(r"[\s ]+")
VOID_TAGS = frozenset({"meta", "img", "input", "br", "hr", "source", "link"})


class ExtractError(RuntimeError):
    """Страница разобрана, но ожидаемой разметки на ней нет."""


def available_parsers() -> tuple[str, ...]:
    """Список парсеров, установленных в окружении (первый — самый быстрый)."""
    available = [name for name in PARSERS if name == "html.parser" or importlib.util.find_spec(name)]
    return tuple(available) or ("html.parser",)


def make_soup(html: str, parser: str = "lxml") -> BeautifulSoup:
    try:
        return BeautifulSoup(html, parser)
    except Exception:
        fallback = "html.parser" if parser != "html.parser" else None
        if fallback is None:
            raise
        return BeautifulSoup(html, fallback)


def collapse(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()


def to_price(raw: str) -> str:
    """``'1 299 ₽'`` -> ``'1299'``, ``'1 299,50 руб.'`` -> ``'1299.50'``."""
    cleaned = _CURRENCY_RE.sub("", raw).strip()
    cleaned = cleaned.replace(" ", "").replace("'", "").rstrip(".-").lstrip()
    if not cleaned:
        return ""
    if "," in cleaned and "." in cleaned:
        decimal = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        cleaned = cleaned.replace(thousands, "").replace(decimal, ".")
    elif "," in cleaned:
        head, _, tail = cleaned.rpartition(",")
        # «1,299» — тысячи, «12,5» — десятичный разделитель.
        cleaned = cleaned.replace(",", "") if len(tail) == 3 and head else f"{head or '0'}.{tail}"
    return cleaned


def to_number(raw: str) -> str:
    candidate = to_price(raw)
    try:
        float(candidate)
    except ValueError:
        return ""
    return candidate


TRANSFORMERS: dict[str, Callable[[str], str]] = {
    "text": collapse,
    "strip": lambda raw: raw.strip(),
    "price": to_price,
    "int": lambda raw: to_number(raw).split(".")[0],
    "float": to_number,
}


@dataclass(frozen=True)
class PageData:
    """Результат разбора одной страницы."""

    rows: list[dict[str, str]]
    found: int
    skipped: int
    empty_fields: int


class ItemExtractor:
    """Превращает HTML страницы в список плоских словарей."""

    def __init__(self, item: ItemConfig, *, parser: str = "lxml", strict: bool = False) -> None:
        self.item = item
        self.parser = parser
        self.strict = strict

    def parse(self, html: str) -> BeautifulSoup:
        """Разбирает HTML выбранным парсером (с откатом на html.parser)."""
        return make_soup(html, self.parser)

    def extract(self, html: str, base_url: str) -> PageData:
        return self.extract_soup(self.parse(html), base_url)

    def extract_soup(self, soup: BeautifulSoup, base_url: str) -> PageData:
        containers = soup.select(self.item.container)
        if not containers:
            raise ExtractError(
                f"на странице не найдено ни одного элемента по селектору {self.item.container!r}"
            )

        rows: list[dict[str, str]] = []
        skipped = 0
        empty_fields = 0

        for container in containers:
            row, missing_required = self._extract_item(container, base_url)
            if missing_required:
                skipped += 1
                continue
            empty_fields += sum(1 for value in row.values() if not value)
            rows.append(row)

        if self.strict and not rows:
            raise ExtractError("все карточки на странице пропущены: не найдены обязательные поля")

        return PageData(rows=rows, found=len(containers), skipped=skipped, empty_fields=empty_fields)

    def _extract_item(self, container: Tag, base_url: str) -> tuple[dict[str, str], list[str]]:
        row: dict[str, str] = {}
        missing: list[str] = []

        for spec in self.item.fields:
            raw = self._raw_value(container, spec)
            value = self._transform(spec, raw, base_url)
            row[spec.name] = value
            if spec.required and not value:
                missing.append(spec.name)

        return row, missing

    @staticmethod
    def _raw_value(container: Tag, spec: FieldSpec) -> str:
        """Значение поля: первый подходящий узел или склейка всех совпадений."""
        if spec.collect_all:
            values = (ItemExtractor._node_value(node, spec) for node in container.select(spec.selector))
            return spec.join_with.join(value for value in values if value)

        node = container.select_one(spec.selector)
        return "" if node is None else ItemExtractor._node_value(node, spec)

    @staticmethod
    def _node_value(node: Tag, spec: FieldSpec) -> str:
        """Атрибут узла, а для void-элементов — служебное значение, иначе текст."""
        if spec.attribute:
            value = node.get(spec.attribute) or ""
            return " ".join(value) if isinstance(value, list) else str(value).strip()

        if node.name in VOID_TAGS:
            return str(node.get("content") or node.get("src") or node.get("alt") or "").strip()

        return collapse(node.get_text(" ", strip=True))

    @staticmethod
    def _transform(spec: FieldSpec, raw: str, base_url: str) -> str:
        if spec.transform == "url":
            return urljoin(base_url, raw.strip()) if raw.strip() else ""
        return TRANSFORMERS[spec.transform](raw)