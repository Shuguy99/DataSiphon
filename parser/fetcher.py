"""HTTP-слой: сессия с ротацией User-Agent, задержками, таймаутами и ретраями."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter

from .config import DelayConfig, ParserConfig

logger = logging.getLogger("parser.fetcher")

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """Ошибка получения страницы (сеть, таймаут, неожиданный статус или тип контента)."""

    def __init__(self, url: str, message: str, status: int | None = None) -> None:
        super().__init__(f"{url}: {message}")
        self.url = url
        self.status = status


class RobotsPolicy:
    """Проверка robots.txt. Ошибки сети трактуются как «разрешено»."""

    def __init__(self, user_agent: str, timeout: float, enabled: bool = True) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.enabled = enabled
        self._parsers: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        if not self.enabled:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = self._load(origin)
        parser = self._parsers[origin]
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def _load(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        parser.user_agent = self.user_agent
        try:
            parser.read()
        except Exception as exc:
            logger.warning("robots.txt %s недоступен (%s) — продолжаю без ограничений", origin, exc)
            return None
        return parser


class Fetcher:
    """Загружает HTML-страницы с вежливыми паузами между запросами."""

    def __init__(
        self,
        config: ParserConfig,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self.session = session or self._build_session(config)
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._requests_made = 0
        self.user_agent = config.user_agents[0]
        self.robots = RobotsPolicy(self.user_agent, config.timeout, config.respect_robots_txt)

    @staticmethod
    def _build_session(config: ParserConfig) -> requests.Session:
        session = requests.Session()
        session.verify = config.verify_ssl
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8, max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    @property
    def requests_made(self) -> int:
        return self._requests_made

    def get(self, url: str, delay: DelayConfig | None = None) -> str:
        """Возвращает текст страницы. Повторяет запрос при временных ошибках."""
        if not self.robots.allowed(url):
            raise FetchError(url, "запрещено robots.txt", status=403)

        pause = self.config.delay if delay is None else delay
        if not pause.is_disabled:
            self._wait(pause)

        last_error: FetchError | None = None
        for attempt in range(self.config.retries + 1):
            self.user_agent = self._rng.choice(self.config.user_agents)
            headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"}
            self._requests_made += 1
            try:
                response = self.session.get(url, headers=headers, timeout=self.config.timeout)
            except requests.Timeout as exc:
                last_error = FetchError(url, f"таймаут {self.config.timeout}s ({exc})")
            except requests.RequestException as exc:
                last_error = FetchError(url, f"сетевая ошибка: {exc}")
            else:
                last_error = self._check_response(url, response)
                if last_error is None:
                    return response.text

            if last_error.status is not None and last_error.status not in RETRY_STATUSES:
                raise last_error
            if attempt < self.config.retries:
                backoff = self.config.retry_backoff * (2**attempt)
                backoff = backoff + self._rng.uniform(0, max(backoff * 0.25, 0.1))
                logger.warning(
                    "Попытка %d/%d не удалась (%s), повтор через %.1fs",
                    attempt + 1,
                    self.config.retries + 1,
                    last_error,
                    backoff,
                )
                if backoff:
                    self._sleep(backoff)

        assert last_error is not None
        raise last_error

    def _check_response(self, url: str, response: requests.Response) -> FetchError | None:
        if response.status_code != 200:
            return FetchError(url, f"HTTP {response.status_code}", status=response.status_code)

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type and not any(content_type.startswith(t) for t in self.config.allowed_content_types):
            return FetchError(url, f"неожиданный Content-Type: {content_type}", status=response.status_code)

        if not response.text.strip():
            return FetchError(url, "пустой ответ", status=response.status_code)
        return None

    def _wait(self, delay: DelayConfig) -> None:
        seconds = self._rng.uniform(delay.min, delay.max)
        logger.debug("пауза %.2fs перед следующим запросом", seconds)
        if seconds:
            self._sleep(seconds)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()