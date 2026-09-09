"""Чтение, сохранение и резервное копирование SQLite."""

from __future__ import annotations

import os
import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
SQLITE_PATH = DATA_DIR / "knowledge.db"
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_LIMIT = 10

DEFAULT_SECTIONS = (
    {
        "id": "faq",
        "title": "Типовые ситуации (FAQ)",
        "icon": "❓",
        "description": "Рабочие ситуации, короткие ответы, правила и исключения.",
        "page_kind": "faq",
        "position": 10,
        "is_visible": True,
        "is_archived": False,
    },
    {
        "id": "reference_tables",
        "title": "Нормы и сроки",
        "icon": "📊",
        "description": "Сроки испытаний, документы и нормы отбора образцов.",
        "page_kind": "reference_tables",
        "position": 20,
        "is_visible": True,
        "is_archived": False,
    },
    {
        "id": "instructions",
        "title": "Инструкции и алгоритмы",
        "icon": "📝",
        "description": "Пошаговые внутренние инструкции для сотрудников.",
        "page_kind": "instructions",
        "position": 30,
        "is_visible": True,
        "is_archived": False,
    },
)


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


def _create_sections_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS content_sections (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            icon TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            page_kind TEXT NOT NULL DEFAULT 'custom',
            position INTEGER NOT NULL DEFAULT 0,
            is_visible INTEGER NOT NULL DEFAULT 1,
            is_archived INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def _initialize_sections() -> None:
    """Создаёт метаданные разделов, не изменяя таблицы с материалами."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    database_exists = SQLITE_PATH.is_file()
    schema_exists = False

    if database_exists:
        with closing(sqlite3.connect(SQLITE_PATH)) as connection:
            schema_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'content_sections'"
            ).fetchone() is not None

    if database_exists and not schema_exists:
        _create_backup()

    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            _create_sections_schema(connection)
            existing_count = connection.execute(
                "SELECT COUNT(*) FROM content_sections"
            ).fetchone()[0]
            if existing_count == 0:
                connection.executemany(
                    """
                    INSERT INTO content_sections (
                        id, title, icon, description, page_kind, position,
                        is_visible, is_archived
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            section["id"],
                            section["title"],
                            section["icon"],
                            section["description"],
                            section["page_kind"],
                            section["position"],
                            int(section["is_visible"]),
                            int(section["is_archived"]),
                        )
                        for section in DEFAULT_SECTIONS
                    ],
                )


def load_sections(include_archived: bool = False) -> list[dict[str, Any]]:
    """Возвращает разделы в порядке отображения."""
    _initialize_sections()
    query = "SELECT * FROM content_sections"
    if not include_archived:
        query += " WHERE is_archived = 0"
    query += " ORDER BY position, title COLLATE NOCASE"

    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query).fetchall()
        return [
            {
                **dict(row),
                "is_visible": bool(row["is_visible"]),
                "is_archived": bool(row["is_archived"]),
            }
            for row in rows
        ]


def save_section(section: Mapping[str, Any]) -> None:
    """Создаёт или обновляет раздел после резервного копирования базы."""
    section_id = str(section.get("id", "")).strip()
    title = str(section.get("title", "")).strip()
    if not section_id or not title:
        raise ValueError("Идентификатор и название раздела обязательны.")

    _initialize_sections()
    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO content_sections (
                    id, title, icon, description, page_kind, position,
                    is_visible, is_archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    icon = excluded.icon,
                    description = excluded.description,
                    page_kind = excluded.page_kind,
                    position = excluded.position,
                    is_visible = excluded.is_visible,
                    is_archived = excluded.is_archived
                """,
                (
                    section_id,
                    title,
                    str(section.get("icon", "")).strip(),
                    str(section.get("description", "")).strip(),
                    str(section.get("page_kind", "custom")).strip() or "custom",
                    int(section.get("position", 0)),
                    int(bool(section.get("is_visible", True))),
                    int(bool(section.get("is_archived", False))),
                ),
            )


def archive_section(section_id: str) -> None:
    """Убирает раздел из навигации, сохраняя возможность восстановления."""
    _initialize_sections()
    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute(
                "UPDATE content_sections SET is_archived = 1, is_visible = 0 "
                "WHERE id = ?",
                (section_id,),
            )


def restore_section(section_id: str) -> None:
    """Возвращает архивный раздел в административный список."""
    _initialize_sections()
    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute(
                "UPDATE content_sections SET is_archived = 0 WHERE id = ?",
                (section_id,),
            )


def _create_content_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS content_items (
            id TEXT PRIMARY KEY,
            section_id TEXT NOT NULL,
            item_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            keywords TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0,
            is_visible INTEGER NOT NULL DEFAULT 1,
            is_archived INTEGER NOT NULL DEFAULT 0,
            table_columns_json TEXT NOT NULL DEFAULT '[]',
            table_rows_json TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY(section_id) REFERENCES content_sections(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_items_section "
        "ON content_items(section_id, position)"
    )


def _initialize_content() -> None:
    """Создаёт универсальное хранилище материалов при первом обращении."""
    _initialize_sections()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        schema_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'content_items'"
        ).fetchone() is not None

    if not schema_exists:
        _create_backup()

    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute("PRAGMA foreign_keys = ON")
            _create_content_schema(connection)


def _decode_json_list(value: str) -> list[Any]:
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _normalize_table_content(
    item_id: str,
    columns_value: Any,
    rows_value: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Приводит старые и новые таблицы к колонкам с постоянными ID."""
    raw_columns = columns_value if isinstance(columns_value, list) else []
    raw_rows = rows_value if isinstance(rows_value, list) else []
    columns: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for index, value in enumerate(raw_columns):
        if isinstance(value, Mapping):
            label = str(value.get("label", "")).strip()
            column_id = str(value.get("id", "")).strip()
            column_type = str(value.get("type", "text")).strip()
            required = bool(value.get("required", False))
            position = int(value.get("position", (index + 1) * 10))
        else:
            label = str(value).strip()
            column_id = ""
            column_type = "text"
            required = False
            position = (index + 1) * 10

        if not label:
            continue
        if not column_id or column_id in used_ids:
            column_id = "column_" + uuid5(
                NAMESPACE_URL,
                f"knowledge-table:{item_id}:{index}:{label}",
            ).hex[:12]
        if column_type not in {"text", "number", "checkbox"}:
            column_type = "text"
        used_ids.add(column_id)
        columns.append(
            {
                "id": column_id,
                "label": label,
                "type": column_type,
                "required": required,
                "position": position,
            }
        )

    columns.sort(key=lambda item: (int(item["position"]), item["label"].casefold()))
    normalized_rows = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            continue
        normalized_rows.append(
            {
                column["id"]: str(
                    raw_row.get(column["id"], raw_row.get(column["label"], ""))
                )
                for column in columns
            }
        )
    return columns, normalized_rows


def load_content_items(
    section_id: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Загружает статьи, инструкции и произвольные таблицы."""
    _initialize_content()
    conditions = []
    parameters: list[Any] = []
    if section_id:
        conditions.append("section_id = ?")
        parameters.append(section_id)
    if not include_archived:
        conditions.append("is_archived = 0")

    query = "SELECT * FROM content_items"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY position, title COLLATE NOCASE"

    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query, parameters).fetchall()
        items = []
        for row in rows:
            values = dict(row)
            columns, table_rows = _normalize_table_content(
                str(row["id"]),
                _decode_json_list(row["table_columns_json"]),
                _decode_json_list(row["table_rows_json"]),
            )
            items.append(
                {
                    **values,
                    "is_visible": bool(row["is_visible"]),
                    "is_archived": bool(row["is_archived"]),
                    "table_columns": columns,
                    "table_rows": table_rows,
                }
            )
        return items


def save_content_item(item: Mapping[str, Any]) -> None:
    """Создаёт или обновляет материал после резервного копирования."""
    item_id = str(item.get("id", "")).strip()
    section_id = str(item.get("section_id", "")).strip()
    item_type = str(item.get("item_type", "")).strip()
    title = str(item.get("title", "")).strip()
    if not item_id or not section_id or not title:
        raise ValueError("Идентификатор, раздел и название материала обязательны.")
    if item_type not in {"faq", "article", "instruction", "table"}:
        raise ValueError("Неизвестный тип материала.")

    columns, rows = _normalize_table_content(
        item_id,
        item.get("table_columns", []),
        item.get("table_rows", []),
    )

    _initialize_content()
    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        section_exists = connection.execute(
            "SELECT 1 FROM content_sections WHERE id = ?",
            (section_id,),
        ).fetchone()
        if section_exists is None:
            raise ValueError("Выбранный раздел не существует.")

        with connection:
            connection.execute(
                """
                INSERT INTO content_items (
                    id, section_id, item_type, title, summary, body, keywords,
                    source, updated_at, position, is_visible, is_archived,
                    table_columns_json, table_rows_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    section_id = excluded.section_id,
                    item_type = excluded.item_type,
                    title = excluded.title,
                    summary = excluded.summary,
                    body = excluded.body,
                    keywords = excluded.keywords,
                    source = excluded.source,
                    updated_at = excluded.updated_at,
                    position = excluded.position,
                    is_visible = excluded.is_visible,
                    is_archived = excluded.is_archived,
                    table_columns_json = excluded.table_columns_json,
                    table_rows_json = excluded.table_rows_json
                """,
                (
                    item_id,
                    section_id,
                    item_type,
                    title,
                    str(item.get("summary", "")).strip(),
                    str(item.get("body", "")),
                    str(item.get("keywords", "")).strip(),
                    str(item.get("source", "")).strip(),
                    str(item.get("updated_at", "")).strip(),
                    int(item.get("position", 0)),
                    int(bool(item.get("is_visible", True))),
                    int(bool(item.get("is_archived", False))),
                    json.dumps(columns, ensure_ascii=False),
                    json.dumps(rows, ensure_ascii=False),
                ),
            )


def archive_content_item(item_id: str) -> None:
    """Перемещает материал в архив."""
    _initialize_content()
    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute(
                "UPDATE content_items SET is_archived = 1, is_visible = 0 "
                "WHERE id = ?",
                (item_id,),
            )


def restore_content_item(item_id: str) -> None:
    """Возвращает материал из архива."""
    _initialize_content()
    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute(
                "UPDATE content_items SET is_archived = 0 WHERE id = ?",
                (item_id,),
            )
