"""HTTP-слой: задержки, User-Agent, ретраи, robots.txt."""

from __future__ import annotations

import random

import pytest

from parser.config import DelayConfig
from parser.fetcher import Fetcher, FetchError


def test_успешный_запрос_возвращает_html(site, make_config, sleeps):
    config = make_config(site.base_url)
    with Fetcher(config, sleep=sleeps.append) as fetcher:
        html = fetcher.get(site.url("/catalog?page=1"))

    assert "Товар №1" in html
    assert fetcher.requests_made == 1


def test_user_agent_подставляется_и_ротируется(site, make_config, sleeps):
    config = make_config(site.base_url)
    with Fetcher(config, sleep=sleeps.append, rng=random.Random(1)) as fetcher:
        fetcher.get(site.url("/catalog?page=1"))
        assert fetcher.user_agent in config.user_agents
        fetcher.get(site.url("/catalog?page=2"))
        assert fetcher.user_agent in config.user_agents


def test_пауза_между_запросами(site, make_config, sleeps):
    config = make_config(site.base_url, delay={"min": 0.5, "max": 0.5})
    with Fetcher(config, sleep=sleeps.append, rng=random.Random(0)) as fetcher:
        fetcher.get(site.url("/catalog?page=1"))
        fetcher.get(site.url("/catalog?page=2"))

    assert sleeps == [0.5, 0.5]


def test_нулевая_пауза_отключает_ожидание(site, make_config, sleeps):
    config = make_config(site.base_url)
    with Fetcher(config, sleep=sleeps.append) as fetcher:
        fetcher.get(site.url("/catalog?page=1"), DelayConfig(0, 0))
        fetcher.get(site.url("/catalog?page=2"), DelayConfig(0, 0))

    assert sleeps == []


def test_повтор_при_временной_ошибке_503(site, make_config, sleeps):
    config = make_config(site.base_url, retries=2)
    with Fetcher(config, sleep=sleeps.append) as fetcher:
        html = fetcher.get(site.url("/flaky?fail=2&fail_key=fetcher_retry"))

    assert "Товар №1" in html
    assert fetcher.requests_made == 3
    assert len(sleeps) == 2  # две паузы перед повторами


def test_исчерпание_ретраев_даёт_ошибку(site, make_config, sleeps):
    config = make_config(site.base_url, retries=1)
    with Fetcher(config, sleep=sleeps.append) as fetcher, pytest.raises(FetchError) as exc_info:
        fetcher.get(site.url("/always-500"))

    assert exc_info.value.status == 500
    assert fetcher.requests_made == 2


def test_ошибка_клиента_не_повторяется(site, make_config, sleeps):
    config = make_config(site.base_url, retries=3)
    with Fetcher(config, sleep=sleeps.append) as fetcher, pytest.raises(FetchError) as exc_info:
        fetcher.get(site.url("/nope"))

    assert exc_info.value.status == 404
    assert fetcher.requests_made == 1


def test_неожиданный_content_type_отклоняется(site, make_config, sleeps):
    config = make_config(site.base_url)
    with Fetcher(config, sleep=sleeps.append) as fetcher, pytest.raises(FetchError, match="Content-Type"):
        fetcher.get(site.url("/json"))


def test_пустой_ответ_отклоняется(site, make_config, sleeps):
    config = make_config(site.base_url)
    with Fetcher(config, sleep=sleeps.append) as fetcher, pytest.raises(FetchError, match="пустой ответ"):
        fetcher.get(site.url("/empty"))


def test_таймаут_обрабатывается(site, make_config, sleeps):
    config = make_config(site.base_url, timeout=0.3, retries=0)
    with Fetcher(config, sleep=sleeps.append) as fetcher, pytest.raises(FetchError, match="таймаут"):
        fetcher.get(site.url("/slow"))


def test_robots_txt_запрещает_обход(site, make_config, sleeps):
    config = make_config(site.base_url)
    with Fetcher(config, sleep=sleeps.append) as fetcher, pytest.raises(FetchError, match=r"robots\.txt"):
        fetcher.get(site.url("/private/secret"))


def test_robots_txt_can_be_disabled(site, make_config, sleeps):
    config = make_config(site.base_url, respect_robots_txt=False)
    with Fetcher(config, sleep=sleeps.append) as fetcher:
        assert fetcher.get(site.url("/private/secret"))


def test_повтор_с_экспоненциальной_паузой(site, make_config, sleeps):
    config = make_config(site.base_url, retries=2, retry_backoff=0.5)
    with Fetcher(config, sleep=sleeps.append, rng=random.Random(0)) as fetcher, pytest.raises(FetchError):
        fetcher.get(site.url("/always-500"))

    # Пауза между попытками растёт экспоненциально: 0.5 -> 1.0 (с джиттером).
    assert len(sleeps) == 2
    assert sleeps[0] == pytest.approx(0.5, abs=0.2)
    assert sleeps[1] == pytest.approx(1.0, abs=0.3)