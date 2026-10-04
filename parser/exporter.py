"""Инкрементальная запись результатов в CSV."""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

from .config import OutputConfig

logger = logging.getLogger("parser.exporter")


class CsvExporter:
    """Пишет строки в CSV сразу после каждой страницы, чтобы не терять прогресс."""

    def __init__(self, config: OutputConfig, fieldnames: Sequence[str]) -> None:
        self.config = config
        self.fieldnames = list(fieldnames)
        self.path = Path(config.path)
        self.rows_written = 0
        self.duplicates_skipped = 0
        self._seen: set[tuple[str, ...]] = set()
        self._handle = None
        self._writer: csv.DictWriter | None = None

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists() and self.path.stat().st_size > 0
        write_header = not (self.config.append and exists)
        if self.config.append and exists and self.config.deduplicate:
            self._load_existing()
        self._handle = self.path.open(
            "a" if self.config.append else "w",
            encoding=self.config.encoding,
            newline="",
        )
        self._writer = csv.DictWriter(
            self._handle,
            fieldnames=self.fieldnames,
            extrasaction="ignore",
        )
        if write_header:
            self._writer.writeheader()
            self._handle.flush()

    def _load_existing(self) -> None:
        """Читает ключи уже сохранённых строк, чтобы не дублировать их при append."""
        try:
            with self.path.open("r", encoding=self.config.encoding, newline="") as handle:
                for row in csv.DictReader(handle):
                    self._seen.add(tuple((row.get(key) or "").strip() for key in self.fieldnames))
        except OSError as exc:
            logger.warning("не удалось прочитать существующий CSV %s: %s", self.path, exc)

    def _ensure_open(self) -> csv.DictWriter:
        if self._writer is None:
            self._open()
        assert self._writer is not None
        return self._writer

    def write(self, rows: Iterable[dict[str, str]]) -> int:
        """Добавляет строки в файл. Возвращает количество реально записанных."""
        writer = self._ensure_open()
        written = 0

        for row in rows:
            values = {key: (row.get(key) or "").strip() for key in self.fieldnames}
            if not any(values.values()):
                continue
            if self.config.deduplicate:
                key = tuple(values[k] for k in self.fieldnames)
                if key in self._seen:
                    self.duplicates_skipped += 1
                    continue
                self._seen.add(key)
            writer.writerow(values)
            written += 1

        self.rows_written += written
        self._handle.flush()
        return written

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None
            self._writer = None
            logger.info("CSV сохранён: %s", self.path)

    def __enter__(self) -> CsvExporter:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()