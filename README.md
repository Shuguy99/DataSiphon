# DataSiphon — парсер сайтов на requests + BeautifulSoup

Универсальный сборщик структурированных данных с любого сайта: HTTP-запросы с подменой
User-Agent и задержками, извлечение полей по CSS-селекторам, автоматический обход пагинации
и экспорт в CSV. Логика вынесена в конфиг — чтобы переключиться на другой сайт, правки кода
не нужны.

## Возможности

| Требование | Реализация |
|---|---|
| HTTP-запросы с подменой User-Agent и задержками | `parser/fetcher.py`: сессия `requests`, ротация User-Agent, случайная пауза `delay.min…delay.max`, таймаут на запрос |
| Извлечение данных по CSS-селекторам | `parser/extract.py`: селектор контейнера + селекторы полей, атрибуты, трансформации значений |
| Автоматический обход пагинации | `parser/pagination.py`: режимы `next`, `links`, `template`, `none` + защита от зацикливания |
| Обработка исключений | Таймауты, сетевые ошибки, HTTP-коды, отсутствие тегов, битая разметка: ретраи с экспоненциальной паузой, пропуск битых карточек, `robots.txt` |
| Сохранение в CSV | `parser/exporter.py`: инкрементальная запись, дедупликация, `utf-8-sig` для Excel, режим `append` |
| Сборка цикла | `parser/pipeline.py`: обход страниц, статистика, причины остановки, `--dry-run` |

Дополнительно: проверка `robots.txt` (по умолчанию включена), проверка `Content-Type`
(отсекает JSON-ответы и антибот-страницы), CLI с переопределениями, 107 тестов на локальном
сайте-имитации без обращения к внешним ресурсам.

## Установка

```bash
pip install -r requirements.txt
```

`lxml` ускоряет разбор; без него автоматически используется встроенный `html.parser`.

## Быстрый старт

```bash
# 1. Проверить всё на локальном сайте-имитации (ничего не скачивает из интернета)
python demo.py

# 2. Посмотреть, что распарсится, ничего не записывая
python -m parser -c config.example.json --dry-run

# 3. Собрать данные
python -m parser -c config.example.json
```

## Настройка под свой сайт

Всё описывается в JSON-конфиге (пример — `config.example.json`):

```json
{
  "start_url": "https://shop.example/catalog?page=1",

  "item": {
    "container": "article.product-card",
    "fields": [
      { "name": "title", "selector": "h2.product-card__title", "required": true },
      { "name": "price", "selector": "span.product-card__price", "transform": "price" },
      { "name": "link",  "selector": "h2.product-card__title a", "attribute": "href", "transform": "url" }
    ]
  },

  "pagination": { "mode": "next", "next_selector": "a.pager__next", "max_pages": 20 },
  "output": { "path": "data/products.csv", "encoding": "utf-8-sig", "deduplicate": true },
  "delay": { "min": 1.0, "max": 3.0 },
  "timeout": 15,
  "retries": 3
}
```

Имена колонок в CSV берутся из `name`. Если `name` не указать, он выводится из селектора.

### Поля карточки (`item.fields[]`)

| Ключ | Назначение |
|---|---|
| `name` | Имя колонки в CSV |
| `selector` | CSS-селектор относительно контейнера карточки |
| `attribute` | Взять атрибут вместо текста (`href`, `content`, `data-price`…) |
| `transform` | `text`, `strip`, `price`, `int`, `float`, `url` |
| `required` | `true` — карточка без этого поля будет пропущена |
| `all` | `true` — склеить все совпадения селектора (списки тегов, хлебные крошки) |
| `join_with` | Разделитель при склейке (`all: true`), по умолчанию пробел |

`price` чистит валюту и приводит разделители: `1 299,50 ₽` → `1299.50`, `1.299,50 руб.` → `1299.50`.
`url` превращает относительную ссылку в абсолютную.

### Пагинация (`pagination`)

| `mode` | Как работает | Обязательные ключи |
|---|---|---|
| `next` | По ссылке «следующая страница» | `next_selector` |
| `links` | По всем ссылкам блока пагинации, пропуская посещённые | `link_selector` |
| `template` | URL собираются из шаблона: `"https://x/c?page={page}"` | `url_template` |
| `none` | Только стартовая страница | — |

`max_pages` ограничивает глубину обхода. Уже посещённые URL не запрашиваются повторно,
поэтому цикл «вперёд-назад» не зависает.

### Прочие ключи

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `user_agents` | три популярных UA | ротация заголовка `User-Agent` |
| `delay` | `{min: 1.0, max: 3.0}` | случайная пауза между запросами; `{min: 0, max: 0}` — без пауз |
| `timeout` | `15` | таймаут запроса, сек |
| `retries` | `3` | число повторов при таймаутах и кодах 5xx/429 |
| `retry_backoff` | `1.0` | база экспоненциальной паузы между повторами, сек |
| `respect_robots_txt` | `true` | проверка `robots.txt` перед запросом |
| `verify_ssl` | `true` | проверка TLS-сертификата |
| `allowed_content_types` | `text/html`, `application/xhtml+xml`, `text/plain` | что считать HTML |
| `stop_on_error` | `true` | прерывать обход при сетевой ошибке или продолжать |
| `output.path` | `data/result.csv` | путь к CSV (папки создаются автоматически) |
| `output.encoding` | `utf-8-sig` | BOM — чтобы Excel корректно открыл кириллицу |
| `output.deduplicate` | `true` | не записывать повторяющиеся строки |
| `output.append` | `false` | дописывать в существующий файл (без дублей) |

## CLI

```bash
python -m parser -c config.json [опции]
```

| Опция | Смысл |
|---|---|
| `-c, --config` | путь к конфигу (обязательно) |
| `-o, --output` | переопределить `output.path` |
| `-u, --url` | переопределить `start_url` |
| `-n, --max-pages` | переопределить `pagination.max_pages` |
| `-d, --delay` | фиксированная пауза между запросами, сек |
| `--parser` | HTML-парсер: `lxml`, `html.parser`, `html5lib` |
| `--append` | дописать в существующий CSV |
| `--no-robots` | не проверять `robots.txt` |
| `--dry-run` | показать первые строки первой страницы, CSV не трогать |
| `-v, --verbose` | подробный лог |

Коды возврата: `0` — успех, `1` — были ошибки загрузки или разбора, `2` — неверный конфиг
или аргументы, `130` — прерывание пользователем (часть данных уже сохранена).

## Пример вывода

```
$ python -m parser -c config.example.json
21:09:02 INFO    parser.pipeline: [1/20] https://shop.example/catalog?page=1
21:09:04 INFO    parser.pipeline: [2/20] https://shop.example/catalog?page=2
...
21:09:11 INFO    parser.exporter: CSV сохранён: data/products.csv
21:09:11 INFO    parser.pipeline: Готово: страниц: 12, карточек: 240, строк: 238,
                  пропущено карточек: 2, запросов: 12, остановка: следующей страницы нет

страниц: 12, карточек: 240, строк: 238, пропущено карточек: 2, запросов: 12,
остановка: следующей страницы нет
Данные: data/products.csv (18422 байта)
```

## Структура проекта

```
parser/
  config.py      разбор и валидация JSON-конфига в dataclass
  fetcher.py     HTTP: сессия, User-Agent, паузы, ретраи, robots.txt
  extract.py     выборка карточек и полей по CSS-селекторам
  pagination.py  определение следующей страницы (next/links/template)
  exporter.py    инкрементальная запись CSV
  pipeline.py    цикл обхода, статистика, причины остановки
  cli.py         точка входа: python -m parser
demo.py          локальный сайт-имитация и готовый пример запуска
tests/           107 тестов (pytest) на локальном стенде
```

Слои не зависят друг от друга напрямую: `Scraper` принимает готовые `Fetcher`,
`ItemExtractor` и `CsvExporter`, поэтому их легко подменять в тестах.

## Тесты

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Тесты поднимают локальный HTTP-сервер с каталогом, битыми карточками, `robots.txt`,
нестабильным ответом (503 → успех), таймаутом и неверным Content-Type. Сеть не нужна:
проверяются пагинация, ретраи, нормализация цен, дедупликация, экспорт и коды возврата CLI.

```bash
python -m ruff check parser tests demo.py   # статическая проверка
```

## Использование из кода

```python
from parser import Scraper, load_config
from parser.exporter import CsvExporter

config = load_config("config.example.json")
with Scraper(config, exporter=CsvExporter(config.output, config.item.field_names)) as scraper:
    stats = scraper.run()
print(stats.summary())
```

## Юридическая сторона

Парсер по умолчанию соблюдает `robots.txt`, делает паузы между запросами и не обходит
защиту от ботов. Перед использованием проверьте условия сайта и закон о защите персональных
данных: собирайте только те данные, на которые у вас есть основание.