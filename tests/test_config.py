"""Валидация конфигурации."""

from __future__ import annotations

import json

import pytest

from parser.config import ConfigError, config_from_dict, describe_config, load_config


def minimal(**overrides):
    data = {
        "start_url": "https://shop.example/catalog?page=1",
        "item": {
            "container": ".card",
            "fields": [{"name": "title", "selector": "h2", "required": True}],
        },
    }
    data.update(overrides)
    return data


def test_минимальный_конфиг_даёт_разумные_умолчания():
    config = config_from_dict(minimal())

    assert config.pagination.mode == "next"
    assert config.output.path == "data/result.csv"
    assert config.output.encoding == "utf-8-sig"
    assert config.timeout == 15.0
    assert config.retries == 3
    assert config.delay.min == 1.0
    assert config.respect_robots_txt is True
    assert len(config.user_agents) >= 2
    assert config.item.field_names == ("title",)


def test_имя_колонки_выводится_из_селектора():
    config = config_from_dict(
        minimal(item={"container": ".card", "fields": [{"selector": "h2.product__title a"}]})
    )

    assert config.item.field_names == ("product__title_a",)


@pytest.mark.parametrize(
    ("payload", "фрагмент"),
    [
        ({}, "start_url"),
        ({"start_url": "shop.example"}, "http://"),
        (minimal(start_url="ftp://shop.example"), "http://"),
        (minimal(item=None), "item"),
        (minimal(item={"container": ".card", "fields": []}), "item.fields"),
        (minimal(item={"container": ".card"}), "item.fields"),
        (minimal(item={"container": ".card", "fields": [{"name": "t"}]}), "selector"),
        (
            minimal(item={"container": ".c", "fields": [{"selector": "h2", "transform": "magic"}]}),
            "transform",
        ),
        (
            minimal(
                item={
                    "container": ".c",
                    "fields": [{"name": "t", "selector": "h2"}, {"name": "t", "selector": "h3"}],
                }
            ),
            "дублирующиеся",
        ),
        (minimal(pagination={"mode": "infinite-scroll"}), "pagination.mode"),
        (minimal(pagination={"mode": "next", "next_selector": None}), "next_selector"),
        (minimal(pagination={"mode": "links"}), "link_selector"),
        (minimal(pagination={"mode": "template"}), "url_template"),
        (minimal(pagination={"mode": "template", "url_template": "/p?page=1"}), "{page}"),
        (minimal(pagination={"max_pages": 0}), "max_pages"),
        (minimal(delay={"min": 5, "max": 1}), "delay.min"),
        (minimal(delay={"min": -1, "max": 1}), "delay.min"),
        (minimal(timeout=0), "timeout"),
        (minimal(retries=-2), "retries"),
        (minimal(user_agents=[]), "user_agents"),
        (minimal(output={"path": ""}), "output.path"),
    ],
)
def test_некорректный_конфиг_понятно_сообщает_об_ошибке(payload, фрагмент):
    with pytest.raises(ConfigError) as exc_info:
        config_from_dict(payload)

    assert фрагмент in str(exc_info.value)


def test_загрузка_конфига_из_файла(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(minimal(), ensure_ascii=False), encoding="utf-8")

    assert load_config(path).start_url.endswith("page=1")


def test_отсутствующий_файл(tmp_path):
    with pytest.raises(ConfigError, match="не найден"):
        load_config(tmp_path / "нет.json")


def test_битый_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"start_url": ', encoding="utf-8")

    with pytest.raises(ConfigError, match="некорректный JSON"):
        load_config(path)


def test_корень_не_объект(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(ConfigError, match="объектом JSON"):
        load_config(path)


def test_ошибки_содержат_имя_файла(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"start_url": "https://a.example"}), encoding="utf-8")

    with pytest.raises(ConfigError, match=r"bad\.json"):
        load_config(path)


def test_описание_конфига_для_логов():
    описание = describe_config(config_from_dict(minimal(output={"path": "data/x.csv"})))

    assert "https://shop.example/catalog?page=1" in описание
    assert "title" in описание
    assert "data/x.csv" in описание


def test_числовые_поля_приводятся_к_float():
    config = config_from_dict(minimal(delay=2, timeout="12", retries="4"))

    assert config.delay == type(config.delay)(2.0, 2.0)
    assert config.timeout == 12.0
    assert config.retries == 4