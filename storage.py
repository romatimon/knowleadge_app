"""Чтение, сохранение и резервное копирование SQLite."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
SQLITE_PATH = DATA_DIR / "knowledge.db"
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_LIMIT = 10

TABLE_KEYS = (
    "faq",
    "contacts_experts",
    "contacts_labs",
    "testing_battery",
    "texts_table",
    "samples_nd",
)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _check_integrity(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        details = result[0] if result else "нет результата"
        raise RuntimeError(f"Ошибка целостности SQLite: {details}")


def _create_backup() -> Path | None:
    if not SQLITE_PATH.is_file():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    destination = BACKUP_DIR / f"knowledge_{timestamp}.db"
    source_uri = SQLITE_PATH.resolve().as_uri() + "?mode=ro"

    with closing(sqlite3.connect(source_uri, uri=True)) as source:
        _check_integrity(source)
        with closing(sqlite3.connect(destination)) as backup:
            source.backup(backup)
            backup.commit()
            _check_integrity(backup)

    automatic_backups = sorted(
        BACKUP_DIR.glob("knowledge_20*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for obsolete_backup in automatic_backups[BACKUP_LIMIT:]:
        obsolete_backup.unlink()

    return destination


def save_all_data(data: Mapping[str, Any]) -> None:
    """Сохраняет таблицы в SQLite после создания проверенной копии."""
    _create_backup()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            for table_name, table_data in data.items():
                frame = (
                    table_data
                    if isinstance(table_data, pd.DataFrame)
                    else pd.DataFrame(table_data)
                )
                if frame.empty and not frame.columns.tolist():
                    continue
                frame.to_sql(table_name, connection, if_exists="replace", index=False)


def load_all_data() -> dict[str, list[dict[str, Any]]]:
    """Загружает известные таблицы из SQLite только для чтения."""
    if not SQLITE_PATH.is_file():
        return {}

    sqlite_uri = SQLITE_PATH.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(sqlite_uri, uri=True)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        existing_tables = [name for name in TABLE_KEYS if name in tables]
        return {
            table_name: pd.read_sql_query(
                f"SELECT * FROM {_quote_identifier(table_name)}", connection
            ).to_dict(orient="records")
            for table_name in existing_tables
        }
