"""CLI: разбор аргументов, пробный запуск, коды возврата."""

from __future__ import annotations

import csv
import json

from parser.cli import build_parser, main
from parser.config import OutputConfig


def read(path):
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def payload(base_url: str, output: str, **overrides) -> dict:
    data = {
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
            ],
        },
        "pagination": {"mode": "next", "next_selector": "a.pager__next", "max_pages": 20},
        "output": {"path": output, "encoding": "utf-8"},
        "delay": {"min": 0, "max": 0},
        "timeout": 5,
        "retries": 0,
    }
    data.update(overrides)
    return data


def test_полный_обход_через_cli(site, tmp_path, write_config, capsys):
    out = tmp_path / "cli.csv"
    config_path = write_config(payload(site.base_url, str(out)))

    assert main(["--config", str(config_path)]) == 0

    rows = read(out)
    assert len(rows) == 9
    assert rows[0]["title"] == "Товар №1"
    assert "строк: 9" in capsys.readouterr().out


def test_лимит_страниц_из_командной_строки(site, tmp_path, write_config):
    out = tmp_path / "cli.csv"
    config_path = write_config(payload(site.base_url, str(out)))

    assert main(["-c", str(config_path), "-n", "1"]) == 0
    assert len(read(out)) == 3


def test_переопределение_пути_и_url(site, tmp_path, write_config):
    out = tmp_path / "override.csv"
    config_path = write_config(payload(site.base_url, str(tmp_path / "ignored.csv")))

    code = main(["-c", str(config_path), "-o", str(out), "-u", site.url("/catalog?page=2")])

    assert code == 0
    assert [r["title"] for r in read(out)] == [f"Товар №{n}" for n in range(4, 10)]


def test_дозапись_через_флаг(site, tmp_path, write_config):
    out = tmp_path / "cli.csv"
    config_path = write_config(payload(site.base_url, str(out)))

    main(["-c", str(config_path), "-n", "1"])
    main(["-c", str(config_path), "-n", "1", "-u", site.url("/catalog?page=2"), "--append"])

    assert len(read(out)) == 6


def test_dry_run_не_трогает_csv(site, tmp_path, write_config, capsys):
    out = tmp_path / "cli.csv"
    config_path = write_config(payload(site.base_url, str(out)))

    assert main(["-c", str(config_path), "--dry-run"]) == 0

    assert not out.exists()
    captured = capsys.readouterr().out
    assert "Товар №1" in captured
    assert "не изменён" in captured


def test_ошибка_конфига_даёт_код_2(tmp_path, write_config, caplog):
    bad = write_config({"start_url": "https://x.test", "item": {"fields": []}}, name="bad.json")

    assert main(["-c", str(bad)]) == 2
    assert "item.container" in caplog.text


def test_отсутствующий_файл_даёт_код_2(tmp_path, caplog):
    assert main(["-c", str(tmp_path / "нет.json")]) == 2
    assert "не найден" in caplog.text


def test_ошибки_разбора_дают_код_1(site, tmp_path, write_config, capsys):
    config_path = write_config(payload(site.base_url, str(tmp_path / "e.csv")))
    document = json.loads(config_path.read_text(encoding="utf-8"))
    document["start_url"] = site.url("/always-500")
    config_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    assert main(["-c", str(config_path)]) == 1
    assert "ошибка загрузки страницы" in capsys.readouterr().out


def test_выбор_другого_html_парсера(site, tmp_path, write_config):
    out = tmp_path / "cli.csv"
    config_path = write_config(payload(site.base_url, str(out)))

    assert main(["-c", str(config_path), "--parser", "html.parser"]) == 0
    assert len(read(out)) == 9


def test_фиксированная_пауза_из_командной_строки(site, tmp_path, write_config):
    config_path = write_config(payload(site.base_url, str(tmp_path / "d.csv"), delay={"min": 5, "max": 9}))

    assert main(["-c", str(config_path), "-n", "1", "-d", "0"]) == 0


def test_отключение_проверки_robots(site, tmp_path, write_config):
    out = tmp_path / "cli.csv"
    config_path = write_config(payload(site.base_url, str(out)))
    document = json.loads(config_path.read_text(encoding="utf-8"))
    document["start_url"] = site.url("/private/secret")
    config_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    assert main(["-c", str(config_path)]) == 1
    assert not out.exists()
    assert main(["-c", str(config_path), "--no-robots"]) == 1


def test_неверный_лимит_страниц(site, tmp_path, write_config, caplog):
    config_path = write_config(payload(site.base_url, str(tmp_path / "x.csv")))

    assert main(["-c", str(config_path), "-n", "0"]) == 2
    assert "--max-pages" in caplog.text
    assert not (tmp_path / "x.csv").exists()


def test_аргументы_по_умолчанию():
    args = build_parser().parse_args(["-c", "cfg.json"])

    assert args.config == "cfg.json"
    assert args.output is None
    assert args.dry_run is False
    assert args.verbose is False


def test_выходной_конфиг_по_умолчанию():
    assert OutputConfig().encoding == "utf-8-sig"