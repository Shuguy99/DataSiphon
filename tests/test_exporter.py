"""Экспорт в CSV."""

from __future__ import annotations

import csv

from parser.config import OutputConfig
from parser.exporter import CsvExporter

COLUMNS = ["title", "price", "link"]
ROWS = [
    {"title": "Товар 1", "price": "100", "link": "https://x.test/1", "лишнее": "ignore"},
    {"title": "Товар 2", "price": "200", "link": "https://x.test/2"},
]


def read(path):
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_заголовок_и_строки(tmp_path):
    out = tmp_path / "nested" / "result.csv"
    with CsvExporter(OutputConfig(path=str(out), encoding="utf-8"), COLUMNS) as exporter:
        assert exporter.write(ROWS) == 2

    assert out.exists()
    assert out.read_text(encoding="utf-8").splitlines()[0] == "title,price,link"
    assert read(out) == [
        {"title": "Товар 1", "price": "100", "link": "https://x.test/1"},
        {"title": "Товар 2", "price": "200", "link": "https://x.test/2"},
    ]


def test_пустые_строки_пропускаются(tmp_path):
    out = tmp_path / "r.csv"
    with CsvExporter(OutputConfig(path=str(out), encoding="utf-8"), COLUMNS) as exporter:
        assert exporter.write([{"title": "", "price": "", "link": ""}]) == 0
        assert exporter.write(ROWS) == 2

    assert len(read(out)) == 2


def test_дубли_отбрасываются(tmp_path):
    out = tmp_path / "r.csv"
    with CsvExporter(OutputConfig(path=str(out), encoding="utf-8", deduplicate=True), COLUMNS) as exporter:
        exporter.write(ROWS)
        assert exporter.write(ROWS) == 0

    assert len(read(out)) == 2
    assert exporter.duplicates_skipped == 2


def test_дубли_разрешены_настройкой(tmp_path):
    out = tmp_path / "r.csv"
    with CsvExporter(OutputConfig(path=str(out), encoding="utf-8", deduplicate=False), COLUMNS) as exporter:
        exporter.write(ROWS)
        exporter.write(ROWS)

    assert len(read(out)) == 4


def test_дозапись_не_дублирует_старое(tmp_path):
    out = tmp_path / "r.csv"
    with CsvExporter(OutputConfig(path=str(out), encoding="utf-8", append=True), COLUMNS) as exporter:
        exporter.write(ROWS)
    with CsvExporter(OutputConfig(path=str(out), encoding="utf-8", append=True), COLUMNS) as exporter:
        assert exporter.write(ROWS) == 0
        assert exporter.write([{"title": "Товар 3", "price": "300", "link": "https://x.test/3"}]) == 1

    data = read(out)
    assert len(data) == 3
    assert data[-1]["title"] == "Товар 3"


def test_без_дозаписи_файл_перезаписывается(tmp_path):
    out = tmp_path / "r.csv"
    with CsvExporter(OutputConfig(path=str(out), encoding="utf-8"), COLUMNS) as exporter:
        exporter.write(ROWS)
    with CsvExporter(OutputConfig(path=str(out), encoding="utf-8"), COLUMNS) as exporter:
        exporter.write(ROWS[:1])

    assert len(read(out)) == 1


def test_данные_пишутся_по_мере_поступления(tmp_path):
    out = tmp_path / "r.csv"
    exporter = CsvExporter(OutputConfig(path=str(out), encoding="utf-8"), COLUMNS)
    exporter.write(ROWS[:1])

    assert len(read(out)) == 1  # файл читается до закрытия

    exporter.write(ROWS[1:])
    exporter.close()
    assert len(read(out)) == 2


def test_значения_обрезаются_от_пробелов(tmp_path):
    out = tmp_path / "r.csv"
    with CsvExporter(OutputConfig(path=str(out), encoding="utf-8"), COLUMNS) as exporter:
        exporter.write([{"title": "  Товар  ", "price": " 100 ", "link": ""}])

    assert read(out)[0] == {"title": "Товар", "price": "100", "link": ""}


def test_экспорт_в_csv_с_bom(tmp_path):
    out = tmp_path / "excel.csv"
    with CsvExporter(OutputConfig(path=str(out)), COLUMNS) as exporter:
        exporter.write(ROWS)

    assert out.read_bytes().startswith(b"\xef\xbb\xbf")