#!/usr/bin/env python3
"""Генерирует демо-каталог и запускает на нём парсер (сайт-имитация).

    python demo.py            # разбирает три страницы и пишет data/demo.csv
    python demo.py --pages 5
"""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from parser import Scraper, load_config
from parser.exporter import CsvExporter
from parser.extract import ItemExtractor

ROBOTS_TXT = "User-agent: *\nDisallow: /private\n"
PER_PAGE = 6


def build_page(page: int, pages: int) -> str:
    cards = []
    start = (page - 1) * PER_PAGE + 1
    for offset in range(PER_PAGE):
        n = start + offset
        if n > pages * PER_PAGE:
            break
        cards.append(
            f"""
        <article class="product-card">
          <h2 class="product-card__title"><a href="/product/{n}">Товар №{n}</a></h2>
          <span class="product-card__price">{n * 137}.{n % 10}0 ₽</span>
          <meta class="product-card__rating" content="{3 + n % 3}.5">
        </article>"""
        )

    prev_link = (
        f'<a class="pager__prev" href="/catalog?page={page - 1}">← Назад</a>'
        if page > 1
        else '<span class="pager__prev disabled">← Назад</span>'
    )
    next_link = (
        f'<a class="pager__next" href="/catalog?page={page + 1}">Вперёд →</a>'
        if page < pages
        else '<span class="pager__next disabled">Вперёд →</span>'
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Каталог — страница {page}</title>
</head>
<body>
  <main class="catalog">{''.join(cards)}</main>
  <nav class="pager">{prev_link}{next_link}</nav>
</body>
</html>
"""


class CatalogHandler(SimpleHTTPRequestHandler):
    pages = 3

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path == "/robots.txt":
            return self._send(ROBOTS_TXT, "text/plain; charset=utf-8")
        if path == "/catalog":
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            page = int(params.get("page", 1))
            if not 1 <= page <= self.pages:
                return self._send("Страница не найдена", "text/plain; charset=utf-8", status=404)
            return self._send(build_page(page, self.pages), "text/html; charset=utf-8")
        if path.startswith("/product/"):
            return self._send("<h1>Карточка товара</h1>", "text/html; charset=utf-8")
        return self._send("Запрещено", "text/plain; charset=utf-8", status=403)

    def _send(self, body: str, content_type: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


def serve(pages: int) -> tuple[ThreadingHTTPServer, str]:
    CatalogHandler.pages = pages
    server = ThreadingHTTPServer(("127.0.0.1", 0), CatalogHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def make_config(base_url: str, output_path: Path) -> dict:
    return {
        "start_url": f"{base_url}/catalog?page=1",
        "item": {
            "container": "article.product-card",
            "fields": [
                {"name": "title", "selector": "h2.product-card__title", "required": True},
                {"name": "price", "selector": "span.product-card__price", "transform": "price"},
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
        "output": {"path": str(output_path), "encoding": "utf-8-sig"},
        "delay": {"min": 0.05, "max": 0.15},
        "timeout": 5,
        "retries": 1,
        "respect_robots_txt": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Демо-парсер на локальном сайте-имитации")
    ap.add_argument("--pages", type=int, default=3, help="сколько страниц каталога сгенерировать")
    ap.add_argument("-o", "--output", default="data/demo.csv", help="путь к итоговому CSV")
    args = ap.parse_args()

    server, base_url = serve(args.pages)
    config_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as fh:
            json.dump(make_config(base_url, Path(args.output)), fh, ensure_ascii=False, indent=2)
            config_path = Path(fh.name)

        config = load_config(config_path)
        print(f"Демо-сайт: {base_url} ({args.pages} стр., {PER_PAGE} товаров на страницу)\n")

        with Scraper(
            config,
            extractor=ItemExtractor(config.item),
            exporter=CsvExporter(config.output, config.item.field_names),
        ) as scraper:
            stats = scraper.run()

        print(f"\n{stats.summary()}")
        print(f"\nПервые строки {Path(args.output).resolve()}:")
        for line in Path(args.output).read_text(encoding="utf-8-sig").splitlines()[:4]:
            print(" ", line)
        return 0 if not stats.errors else 1
    finally:
        server.shutdown()
        server.server_close()
        if config_path is not None:
            config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())