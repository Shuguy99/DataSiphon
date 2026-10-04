"""Определение следующей страницы: по ссылке «вперёд», по списку ссылок или по шаблону URL."""

from __future__ import annotations

import logging
import re
from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .config import PaginationConfig

logger = logging.getLogger("parser.pagination")

_PAGE_NUM_RE = re.compile(r"([?&](?:page|p|offset)=)(\d+)", re.IGNORECASE)


class PaginationError(RuntimeError):
    """Некорректные настройки пагинации."""


class Paginator:
    """Итератор по URL страниц каталога.

    Поддерживает три режима:

    * ``next`` — идём по ссылке «следующая страница» (``pagination.next_selector``);
    * ``links`` — обходим все ссылки из ``pagination.link_selector`` по порядку;
    * ``template`` — строим URL из ``pagination.url_template`` с ``{page}``;
    * ``none`` — только стартовая страница.
    """

    def __init__(self, config: PaginationConfig, start_url: str) -> None:
        self.config = config
        self.start_url = start_url
        self.visited: set[str] = set()
        self.pages_yielded = 0
        self._queue: deque[str] = deque()
        self._planned: str | None = None
        self._first = True
        self._template_page: int = config.start_page

    @property
    def has_next(self) -> bool:
        """Есть ли ещё URL для обхода (стартовая страница тоже считается)."""
        return self._planned is not None or bool(self._queue) or self._first

    def next_url(self) -> str | None:
        """Отдаёт следующий URL и запоминает его как посещённый."""
        if self._planned is not None:
            url, self._planned = self._planned, None
        elif self._queue:
            url = self._queue.popleft()
        elif self._first:
            url, self._first = self.start_url, False
        else:
            return None

        self.visited.add(url)
        self.pages_yielded += 1
        return url

    def update(self, soup: BeautifulSoup, current_url: str) -> None:
        """Планирует следующий URL на основе разобранной страницы."""
        self._queue.clear()
        mode = self.config.mode
        if mode == "next":
            self._planned = self._accept(self._find_next(soup, current_url))
        elif mode == "links":
            self._planned = self._accept(self._first_unvisited_link(soup, current_url))
        elif mode == "template":
            self._planned = self._accept(self._next_from_template())
        else:
            self._planned = None

    def skip(self) -> None:
        """Продолжает обход после неудачной загрузки страницы.

        Реально это возможно только в режиме ``template``: для ``next`` и ``links``
        следующий URL берётся из разметки, которой у нас нет.
        """
        self._queue.clear()
        if self.config.mode == "template":
            self._planned = self._accept(self._next_from_template())
        else:
            logger.debug("страница пропущена: продолжение пагинации невозможно")
            self._planned = None

    def _accept(self, url: str | None) -> str | None:
        """Пропускает URL, который уже посещён (защита от бесконечного цикла)."""
        if url is None:
            return None
        if url in self.visited:
            logger.info("повторяющийся URL %s — пагинация остановлена", url)
            return None
        return url

    def _find_next(self, soup: BeautifulSoup, current_url: str) -> str | None:
        node = soup.select_one(self.config.next_selector or "")
        if node is None:
            return None
        if "disabled" in (node.get("class") or []):
            return None
        href = str(node.get("href") or "").strip()
        if not href or href == "#":
            return None
        return urljoin(current_url, href)

    def _first_unvisited_link(self, soup: BeautifulSoup, current_url: str) -> str | None:
        """Берёт следующую непосещённую ссылку из блока пагинации."""
        for node in soup.select(self.config.link_selector or ""):
            href = str(node.get("href") or "").strip()
            if not href or href == "#":
                continue
            url = urljoin(current_url, href)
            if url not in self.visited:
                return url
        return None

    def _next_from_template(self) -> str:
        if self.config.url_template is None:  # защита от неверного конфига
            raise PaginationError("для режима 'template' нужен pagination.url_template")
        self._template_page += 1
        return self.config.url_template.format(page=self._template_page)


def bump_page(url: str, delta: int = 1) -> str | None:
    """Увеличивает номер страницы в URL (``?page=2`` -> ``?page=3``)."""
    parts = urlsplit(url)
    query = f"?{parts.query}"
    if not _PAGE_NUM_RE.search(query):
        return None

    def replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}{int(match.group(2)) + delta}"

    return urlunsplit(parts._replace(query=_PAGE_NUM_RE.sub(replace, query)[1:]))