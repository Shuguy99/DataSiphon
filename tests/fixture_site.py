"""Локальный сайт-имитация для тестов: каталог с пагинацией и проблемные endpoint'ы."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

PER_PAGE = 3

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Каталог {page}</title></head>
<body>
<main class="catalog">
{cards}
</main>
<nav class="pager">{pager}</nav>
</body></html>
"""

CARD_TEMPLATE = """
<article class="product-card">
  <h2 class="product-card__title"><a href="/product/{n}">Товар №{n}</a></h2>
  <span class="product-card__price">{price}</span>
  <meta class="product-card__rating" content="{rating}">
</article>
"""

BROKEN_CARDS = """
<article class="product-card">
  <span class="product-card__price">100 ₽</span>
</article>
"""

ROBOTS_TXT = "User-agent: *\nDisallow: /private\n"


@dataclass
class SiteState:
    pages: int = 3
    per_page: int = PER_PAGE
    counts: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


def render_page(page: int, state: SiteState) -> str:
    total = state.pages * state.per_page
    cards = []
    start = (page - 1) * state.per_page + 1
    for n in range(start, min(start + state.per_page, total + 1)):
        price = f"{n * 100}.{n % 10}0 ₽"
        cards.append(CARD_TEMPLATE.format(n=n, price=price, rating=f"{3 + n % 3}.5"))
    if page == 2:
        cards.append(BROKEN_CARDS)

    pager = " ".join(
        f'<a class="pager__num" href="/catalog?page={i}">{i}</a>' for i in range(1, state.pages + 1)
    )
    pager += (
        f'<a class="pager__next" href="/catalog?page={page + 1}">Вперёд</a>'
        if page < state.pages
        else '<span class="pager__next disabled">Вперёд</span>'
    )
    return PAGE_TEMPLATE.format(page=page, cards="".join(cards), pager=pager)


class _Handler(BaseHTTPRequestHandler):
    state: SiteState

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        params = parse_qs(parts.query)
        state = self.state

        if parts.path == "/robots.txt":
            return self._send(ROBOTS_TXT, "text/plain; charset=utf-8")
        if parts.path.startswith("/private"):
            return self._send("секрет", "text/html; charset=utf-8")
        if parts.path == "/catalog":
            page = int(params.get("page", ["1"])[0])
            if not 1 <= page <= state.pages:
                return self._send("нет такой страницы", "text/plain; charset=utf-8", 404)
            return self._send(render_page(page, state), "text/html; charset=utf-8")
        if parts.path == "/product":
            return self._send("<h1>Карточка товара</h1>", "text/html; charset=utf-8")
        if parts.path == "/no-items":
            return self._send("<html><body><p>Пусто</p></body></html>", "text/html; charset=utf-8")
        if parts.path == "/broken-items":
            html = PAGE_TEMPLATE.format(page=1, cards=BROKEN_CARDS, pager="")
            return self._send(html, "text/html; charset=utf-8")
        if parts.path in {"/flaky", "/flaky-catalog"}:
            fail_times = int(params.get("fail", ["1"])[0])
            key = params.get("fail_key", ["flaky"])[0]
            if state.bump(key) <= fail_times:
                return self._send("ошибка", "text/plain; charset=utf-8", 503)
            page = int(params.get("page", ["1"])[0])
            if parts.path == "/flaky":
                page = 1
            return self._send(render_page(page, state), "text/html; charset=utf-8")
        if parts.path == "/always-500":
            return self._send("ошибка", "text/plain; charset=utf-8", 500)
        if parts.path == "/slow":
            import time

            time.sleep(2.0)
            return self._send(render_page(1, state), "text/html; charset=utf-8")
        if parts.path == "/json":
            return self._send('{"items": []}', "application/json; charset=utf-8")
        if parts.path == "/empty":
            return self._send("   ", "text/html; charset=utf-8")
        return self._send("не найдено", "text/plain; charset=utf-8", 404)

    def _send(self, body: str, content_type: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


class LocalSite:
    """Поднимает сайт на случайном порту в фоновом потоке."""

    def __init__(self, pages: int = 3, per_page: int = PER_PAGE) -> None:
        self.state = SiteState(pages=pages, per_page=per_page)
        handler = type("_BoundHandler", (_Handler,), {"state": self.state})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @property
    def requests_made(self) -> int:
        return self.state.counts.get("flaky", 0)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)