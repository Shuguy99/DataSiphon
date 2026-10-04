"""Загрузка и валидация конфигурации парсера."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

DEFAULT_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
)

PAGINATION_MODES = ("next", "links", "template", "none")
TRANSFORMS = ("text", "strip", "price", "url", "int", "float")
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class ConfigError(ValueError):
    """Конфиг отсутствует, не читается или содержит некорректные значения."""


@dataclass(frozen=True)
class DelayConfig:
    min: float = 1.0
    max: float = 3.0

    def __post_init__(self) -> None:
        if self.min > self.max:
            raise ConfigError("delay.min должен быть <= delay.max")

    @property
    def is_disabled(self) -> bool:
        return self.max == 0


@dataclass(frozen=True)
class FieldSpec:
    """Правило извлечения одного поля карточки."""

    name: str
    selector: str
    attribute: str | None = None
    transform: str = "text"
    required: bool = False
    collect_all: bool = False
    join_with: str = " "


@dataclass(frozen=True)
class ItemConfig:
    container: str
    fields: tuple[FieldSpec, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)


@dataclass(frozen=True)
class PaginationConfig:
    mode: str = "next"
    next_selector: str | None = "a.next, .pagination a[rel=next]"
    link_selector: str | None = None
    url_template: str | None = None
    start_page: int = 1
    max_pages: int = 10

    @property
    def is_enabled(self) -> bool:
        return self.mode != "none"


@dataclass(frozen=True)
class OutputConfig:
    path: str = "data/result.csv"
    encoding: str = "utf-8-sig"
    deduplicate: bool = True
    append: bool = False


@dataclass(frozen=True)
class ParserConfig:
    start_url: str
    item: ItemConfig
    pagination: PaginationConfig = PaginationConfig()
    output: OutputConfig = OutputConfig()
    user_agents: tuple[str, ...] = DEFAULT_USER_AGENTS
    delay: DelayConfig = DelayConfig()
    timeout: float = 15.0
    retries: int = 3
    retry_backoff: float = 1.0
    respect_robots_txt: bool = True
    verify_ssl: bool = True
    allowed_content_types: tuple[str, ...] = HTML_CONTENT_TYPES
    stop_on_error: bool = True

    def with_overrides(self, **kwargs: Any) -> ParserConfig:
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean) if clean else self


def _as_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{where}: ожидался объект JSON, получено {type(value).__name__}")
    return value


def _positive(value: Any, where: str, *, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where}: ожидалось число, получено {value!r}") from exc
    if number < 0 or (number == 0 and not allow_zero):
        raise ConfigError(f"{where}: значение должно быть {'>= 0' if allow_zero else '> 0'}")
    return number


def _int(value: Any, where: str, *, minimum: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where}: ожидалось целое число, получено {value!r}") from exc
    if number < minimum:
        raise ConfigError(f"{where}: значение должно быть >= {minimum}")
    return number


def _bool(value: Any, where: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: ожидалось true/false, получено {value!r}")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: ожидалась непустая строка, получено {value!r}")
    return value.strip()


def parse_field(raw: Any, where: str) -> FieldSpec:
    data = _as_mapping(raw, where)
    if "selector" not in data:
        raise ConfigError(f"{where}.selector: обязательное поле")

    selector = _text(data["selector"], f"{where}.selector")
    name = _text(data.get("name") or selector_to_name(selector), f"{where}.name")

    transform = data.get("transform", "text")
    if transform not in TRANSFORMS:
        raise ConfigError(
            f"{where}.transform: неизвестное преобразование {transform!r}, "
            f"допустимо: {', '.join(TRANSFORMS)}"
        )

    attribute = data.get("attribute")
    if attribute is not None:
        attribute = _text(attribute, f"{where}.attribute")

    return FieldSpec(
        name=name,
        selector=selector,
        attribute=attribute,
        transform=transform,
        required=_bool(data.get("required"), f"{where}.required", False),
        collect_all=_bool(data.get("all"), f"{where}.all", False),
        join_with=str(data.get("join_with", " ")),
    )


def selector_to_name(selector: str) -> str:
    """Читаемое имя колонки из CSS-селектора: ``.card h2 a`` -> ``h2_a``."""
    parts = [p for p in "".join(c if c.isalnum() or c in " _-" else " " for c in selector).split() if p]
    if not parts:
        raise ConfigError("не удалось вывести имя колонки из селектора")
    return "_".join(p.strip(" .#>-") for p in parts[-2:]) or parts[-1]


def parse_item(raw: Any) -> ItemConfig:
    if raw is None:
        raise ConfigError("item: отсутствует блок item с полями container и fields")
    data = _as_mapping(raw, "item")
    container = _text(data.get("container"), "item.container")

    raw_fields = data.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ConfigError("item.fields: ожидался непустой список правил извлечения")

    fields = tuple(parse_field(f, f"item.fields[{i}]") for i, f in enumerate(raw_fields))
    duplicates = {f.name for f in fields if sum(x.name == f.name for x in fields) > 1}
    if duplicates:
        raise ConfigError(f"item.fields: дублирующиеся имена колонок: {', '.join(sorted(duplicates))}")

    return ItemConfig(container=container, fields=fields)


def parse_pagination(raw: Any) -> PaginationConfig:
    data = {} if raw is None else _as_mapping(raw, "pagination")
    defaults = PaginationConfig()
    mode = data.get("mode", defaults.mode)
    if mode not in PAGINATION_MODES:
        raise ConfigError(
            f"pagination.mode: неизвестный режим {mode!r}, допустимо: {', '.join(PAGINATION_MODES)}"
        )

    next_selector = data.get("next_selector", defaults.next_selector)
    if next_selector is not None:
        next_selector = _text(next_selector, "pagination.next_selector")

    link_selector = data.get("link_selector", defaults.link_selector)
    if link_selector is not None:
        link_selector = _text(link_selector, "pagination.link_selector")

    url_template = data.get("url_template")
    if url_template is not None:
        url_template = _text(url_template, "pagination.url_template")
        if "{page}" not in url_template:
            raise ConfigError("pagination.url_template: в шаблоне должна быть подстановка {page}")

    if mode == "next" and not next_selector:
        raise ConfigError("pagination.next_selector обязателен для режима 'next'")
    if mode == "links" and not link_selector:
        raise ConfigError("pagination.link_selector обязателен для режима 'links'")
    if mode == "template" and not url_template:
        raise ConfigError("pagination.url_template обязателен для режима 'template'")

    return PaginationConfig(
        mode=mode,
        next_selector=next_selector,
        link_selector=link_selector,
        url_template=url_template,
        start_page=_int(data.get("start_page", 1), "pagination.start_page", minimum=1),
        max_pages=_int(data.get("max_pages", 10), "pagination.max_pages", minimum=1),
    )


def parse_output(raw: Any) -> OutputConfig:
    data = {} if raw is None else _as_mapping(raw, "output")
    return OutputConfig(
        path=_text(data.get("path", OutputConfig.path), "output.path"),
        encoding=_text(data.get("encoding", OutputConfig.encoding), "output.encoding"),
        deduplicate=_bool(data.get("deduplicate"), "output.deduplicate", True),
        append=_bool(data.get("append"), "output.append", False),
    )


def parse_delay(raw: Any) -> DelayConfig:
    data = {"min": raw, "max": raw} if isinstance(raw, (int, float)) else _as_mapping(raw or {}, "delay")
    return DelayConfig(
        min=_positive(data.get("min", 1.0), "delay.min", allow_zero=True),
        max=_positive(data.get("max", 3.0), "delay.max", allow_zero=True),
    )


def parse_user_agents(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_USER_AGENTS
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ConfigError("user_agents: ожидался непустой список строк")
    return tuple(_text(ua, f"user_agents[{i}]") for i, ua in enumerate(raw))


def config_from_dict(data: Mapping[str, Any]) -> ParserConfig:
    if "start_url" not in data:
        raise ConfigError("start_url: обязательное поле")
    start_url = _text(data["start_url"], "start_url")
    if not start_url.startswith(("http://", "https://")):
        raise ConfigError("start_url: ссылка должна начинаться с http:// или https://")

    content_types = list(data.get("allowed_content_types") or HTML_CONTENT_TYPES)
    if not content_types:
        raise ConfigError("allowed_content_types: ожидался непустой список MIME-типов")

    return ParserConfig(
        start_url=start_url,
        item=parse_item(data.get("item")),
        pagination=parse_pagination(data.get("pagination")),
        output=parse_output(data.get("output")),
        user_agents=parse_user_agents(data.get("user_agents")),
        delay=parse_delay(data.get("delay")),
        timeout=_positive(data.get("timeout", 15.0), "timeout"),
        retries=_int(data.get("retries", 3), "retries", minimum=0),
        retry_backoff=_positive(data.get("retry_backoff", 1.0), "retry_backoff", allow_zero=True),
        respect_robots_txt=_bool(data.get("respect_robots_txt"), "respect_robots_txt", True),
        verify_ssl=_bool(data.get("verify_ssl"), "verify_ssl", True),
        allowed_content_types=tuple(str(c) for c in content_types),
        stop_on_error=_bool(data.get("stop_on_error"), "stop_on_error", True),
    )


def load_config(path: str | Path) -> ParserConfig:
    """Читает JSON-конфиг и возвращает проверенный :class:`ParserConfig`."""
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"файл конфига не найден: {config_path}")
    if config_path.is_dir():
        raise ConfigError(f"ожидался файл конфига, а получена директория: {config_path}")

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"{config_path}: некорректный JSON (строка {exc.lineno}, позиция {exc.colno})"
        ) from exc
    except OSError as exc:
        raise ConfigError(f"{config_path}: не удалось прочитать файл ({exc})") from exc

    if not isinstance(raw, Mapping):
        raise ConfigError(f"{config_path}: корневой элемент конфига должен быть объектом JSON")

    try:
        return config_from_dict(raw)
    except ConfigError as exc:
        raise ConfigError(f"{config_path}: {exc}") from exc


def describe_config(config: ParserConfig) -> str:
    """Краткое описание конфига для логов и --dry-run."""
    fields = ", ".join(config.item.field_names)
    return (
        f"URL: {config.start_url}\n"
        f"Карточка: {config.item.container} -> [{fields}]\n"
        f"Пагинация: {config.pagination.mode} (максимум {config.pagination.max_pages} стр.)\n"
        f"Пауза: {config.delay.min}-{config.delay.max} с, таймаут {config.timeout} с, "
        f"повторов {config.retries}\n"
        f"Результат: {config.output.path}"
    )