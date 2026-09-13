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

CONTENT_ITEM_TYPES = (
    "faq",
    "article",
    "instruction",
    "template",
    "checklist",
    "table",
)
MATERIAL_STATUSES = ("current", "review", "draft")
SECTION_ITEM_TYPES = {
    "faq": ("faq", "article"),
    "reference_tables": ("table",),
    "instructions": ("instruction",),
    "reference": ("article", "table"),
    "templates": ("template", "checklist", "article", "instruction"),
}

SECTION_CATALOG_MIGRATION = "2026-09-final-workflow-sections-v1"
BRANCH_CATALOG_MIGRATION = "2026-09-final-workflow-branches-v1"
CONTENT_STRUCTURE_MIGRATION = "2026-09-workflow-content-v1"
LEGACY_SECTION_CLEANUP_MIGRATION = "2026-09-workflow-cleanup-v1"

DEFAULT_SECTIONS = (
    {
        "id": "client",
        "title": "Работа с клиентом",
        "icon": "📁",
        "description": "Квалификация запроса, красные флаги и FAQ.",
        "page_kind": "custom",
        "position": 10,
        "is_visible": True,
        "is_archived": False,
    },
    {
        "id": "documents",
        "title": "Оформление документов",
        "icon": "📁",
        "description": "Макет заявка, ФГИС и особые процедуры оформления.",
        "page_kind": "custom",
        "position": 20,
        "is_visible": True,
        "is_archived": False,
    },
    {
        "id": "testing",
        "title": "Испытания и образцы",
        "icon": "📁",
        "description": "Отбор, ввоз, лаборатории, АСП, протоколы испытаний, матрицы и нормы.",
        "page_kind": "custom",
        "position": 30,
        "is_visible": True,
        "is_archived": False,
    },
    {
        "id": "support",
        "title": "Сопровождение",
        "icon": "📁",
        "description": "Инспекционный контроль, переоформление, дореализация, нормы и сроки.",
        "page_kind": "custom",
        "position": 40,
        "is_visible": True,
        "is_archived": False,
    },
    {
        "id": "reference",
        "title": "Справочник и внутренние процессы",
        "icon": "📁",
        "description": "Термины, регламенты, схемы и передача дел.",
        "page_kind": "custom",
        "position": 50,
        "is_visible": True,
        "is_archived": False,
    },
)

LEGACY_SECTION_IDS = (
    "faq",
    "instructions",
    "reference_tables",
    "templates",
    "internal",
)
LEGACY_BRANCH_IDS = (
    "internal-instructions",
    "reference-basics",
    "reference-terms",
    "reference-schemes",
    "reference-periods",
)

STANDARD_BRANCHES = (
    ("instructions", "Инструкции", "instruction", "Пошаговые алгоритмы.", 10),
    ("templates", "Шаблоны", "template", "Письма, бланки и акты.", 20),
    ("faq", "FAQ", "faq", "Короткие ответы на рабочие вопросы.", 30),
    ("checklists", "Чек-листы", "checklist", "Проверки перед выполнением действия.", 40),
    ("tables", "Матрицы и нормы", "table", "Таблицы, сроки и нормативные значения.", 50),
)

DEFAULT_BRANCHES = tuple(
    (
        f"{section['id']}-{branch_id}",
        section["id"],
        title,
        branch_kind,
        description,
        position,
    )
    for section in DEFAULT_SECTIONS
    for branch_id, title, branch_kind, description, position in STANDARD_BRANCHES
)


def allowed_item_types(page_kind: str) -> tuple[str, ...]:
    """Возвращает допустимые типы материалов для назначения раздела."""
    return SECTION_ITEM_TYPES.get(page_kind, CONTENT_ITEM_TYPES)


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


def _create_migrations_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _apply_section_catalog_migration(connection: sqlite3.Connection) -> None:
    """Один раз обновляет базовые разделы, не затрагивая их материалы."""
    applied = connection.execute(
        "SELECT 1 FROM app_migrations WHERE id = ?",
        (SECTION_CATALOG_MIGRATION,),
    ).fetchone()
    if applied:
        return

    for section in DEFAULT_SECTIONS:
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
                position = excluded.position
            """,
            (
                section["id"],
                section["title"],
                section["icon"],
                section["description"],
                section["page_kind"],
                section["position"],
                int(section["is_visible"]),
                int(section["is_archived"]),
            ),
        )

    connection.executemany(
        "UPDATE content_sections SET is_visible = 0, is_archived = 1 WHERE id = ?",
        [(section_id,) for section_id in LEGACY_SECTION_IDS],
    )

    connection.execute(
        "INSERT INTO app_migrations (id, applied_at) VALUES (?, ?)",
        (SECTION_CATALOG_MIGRATION, datetime.now(UTC).isoformat()),
    )


def _initialize_sections() -> None:
    """Создаёт метаданные разделов, не изменяя таблицы с материалами."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    database_exists = SQLITE_PATH.is_file()
    schema_exists = False
    migration_applied = False

    if database_exists:
        with closing(sqlite3.connect(SQLITE_PATH)) as connection:
            schema_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'content_sections'"
            ).fetchone() is not None
            migrations_exist = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'app_migrations'"
            ).fetchone() is not None
            if migrations_exist:
                migration_applied = connection.execute(
                    "SELECT 1 FROM app_migrations WHERE id = ?",
                    (SECTION_CATALOG_MIGRATION,),
                ).fetchone() is not None

    if database_exists and (not schema_exists or not migration_applied):
        _create_backup()

    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            _create_sections_schema(connection)
            _create_migrations_schema(connection)
            _apply_section_catalog_migration(connection)


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
            page_kind = str(section.get("page_kind", "custom")).strip() or "custom"
            content_schema_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'content_items'"
            ).fetchone() is not None
            if content_schema_exists:
                stored_types = {
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT item_type FROM content_items "
                        "WHERE section_id = ? AND is_archived = 0",
                        (section_id,),
                    )
                }
                incompatible = stored_types - set(allowed_item_types(page_kind))
                if incompatible:
                    raise ValueError(
                        "Назначение раздела не подходит для уже созданных "
                        "в нём материалов."
                    )

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
                    page_kind,
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


def _create_branches_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS content_branches (
            id TEXT PRIMARY KEY,
            section_id TEXT NOT NULL,
            title TEXT NOT NULL,
            branch_kind TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0,
            is_visible INTEGER NOT NULL DEFAULT 1,
            is_archived INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(section_id) REFERENCES content_sections(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_branches_section "
        "ON content_branches(section_id, position)"
    )


def _apply_branch_catalog_migration(connection: sqlite3.Connection) -> None:
    """Один раз создаёт рекомендуемые ветки рабочего каркаса."""
    applied = connection.execute(
        "SELECT 1 FROM app_migrations WHERE id = ?",
        (BRANCH_CATALOG_MIGRATION,),
    ).fetchone()
    if applied:
        return

    connection.executemany(
        """
        INSERT INTO content_branches (
            id, section_id, title, branch_kind, description, position,
            is_visible, is_archived
        ) VALUES (?, ?, ?, ?, ?, ?, 1, 0)
        ON CONFLICT(id) DO NOTHING
        """,
        DEFAULT_BRANCHES,
    )
    content_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'content_items'"
    ).fetchone() is not None
    if content_exists and "branch_id" in _content_columns(connection):
        connection.executemany(
            "UPDATE content_items SET branch_id = '' WHERE branch_id = ?",
            [(branch_id,) for branch_id in LEGACY_BRANCH_IDS],
        )
    connection.executemany(
        "DELETE FROM content_branches WHERE id = ?",
        [(branch_id,) for branch_id in LEGACY_BRANCH_IDS],
    )
    connection.execute(
        "INSERT INTO app_migrations (id, applied_at) VALUES (?, ?)",
        (BRANCH_CATALOG_MIGRATION, datetime.now(UTC).isoformat()),
    )


def _initialize_branches() -> None:
    """Создаёт управляемый уровень веток внутри разделов."""
    _initialize_sections()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        schema_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'content_branches'"
        ).fetchone() is not None
        migration_applied = connection.execute(
            "SELECT 1 FROM app_migrations WHERE id = ?",
            (BRANCH_CATALOG_MIGRATION,),
        ).fetchone() is not None

    if not schema_exists or not migration_applied:
        _create_backup()

    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute("PRAGMA foreign_keys = ON")
            _create_branches_schema(connection)
            _create_migrations_schema(connection)
            _apply_branch_catalog_migration(connection)


def load_branches(
    section_id: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Возвращает ветки одного раздела или всей базы знаний."""
    _initialize_branches()
    conditions = []
    parameters: list[Any] = []
    if section_id:
        conditions.append("section_id = ?")
        parameters.append(section_id)
    if not include_archived:
        conditions.append("is_archived = 0")

    query = "SELECT * FROM content_branches"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY section_id, position, title COLLATE NOCASE"

    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query, parameters).fetchall()
        return [
            {
                **dict(row),
                "is_visible": bool(row["is_visible"]),
                "is_archived": bool(row["is_archived"]),
            }
            for row in rows
        ]


def save_branch(branch: Mapping[str, Any]) -> None:
    """Создаёт или обновляет ветку внутри раздела."""
    branch_id = str(branch.get("id", "")).strip()
    section_id = str(branch.get("section_id", "")).strip()
    title = str(branch.get("title", "")).strip()
    branch_kind = str(branch.get("branch_kind", "")).strip()
    if not branch_id or not section_id or not title:
        raise ValueError("Идентификатор, раздел и название ветки обязательны.")
    if branch_kind not in CONTENT_ITEM_TYPES:
        raise ValueError("Неизвестный тип ветки.")

    _initialize_branches()
    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute(
            "SELECT 1 FROM content_sections WHERE id = ? AND is_archived = 0",
            (section_id,),
        ).fetchone() is None:
            raise ValueError("Выбранный раздел не существует или находится в архиве.")
        duplicate = connection.execute(
            "SELECT 1 FROM content_branches "
            "WHERE section_id = ? AND id <> ? AND is_archived = 0 "
            "AND title = ? COLLATE NOCASE",
            (section_id, branch_id, title),
        ).fetchone()
        if duplicate:
            raise ValueError("В этом разделе уже есть ветка с таким названием.")

        content_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'content_items'"
        ).fetchone() is not None
        content_columns = _content_columns(connection) if content_exists else set()
        if "branch_id" in content_columns:
            incompatible = connection.execute(
                "SELECT 1 FROM content_items WHERE branch_id = ? "
                "AND is_archived = 0 AND item_type <> ? LIMIT 1",
                (branch_id, branch_kind),
            ).fetchone()
            if incompatible:
                raise ValueError(
                    "Тип ветки нельзя изменить, пока в ней находятся материалы."
                )

        with connection:
            connection.execute(
                """
                INSERT INTO content_branches (
                    id, section_id, title, branch_kind, description, position,
                    is_visible, is_archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    section_id = excluded.section_id,
                    title = excluded.title,
                    branch_kind = excluded.branch_kind,
                    description = excluded.description,
                    position = excluded.position,
                    is_visible = excluded.is_visible,
                    is_archived = excluded.is_archived
                """,
                (
                    branch_id,
                    section_id,
                    title,
                    branch_kind,
                    str(branch.get("description", "")).strip(),
                    int(branch.get("position", 0)),
                    int(bool(branch.get("is_visible", True))),
                    int(bool(branch.get("is_archived", False))),
                ),
            )


def archive_branch(branch_id: str) -> None:
    """Перемещает пустую ветку в архив."""
    _initialize_branches()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        content_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'content_items'"
        ).fetchone() is not None
        content_columns = _content_columns(connection) if content_exists else set()
        if "branch_id" in content_columns:
            assigned = connection.execute(
                "SELECT COUNT(*) FROM content_items "
                "WHERE branch_id = ? AND is_archived = 0",
                (branch_id,),
            ).fetchone()[0]
            if assigned:
                raise ValueError(
                    "Сначала перенесите материалы ветки или оставьте их без ветки."
                )

    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute(
                "UPDATE content_branches SET is_visible = 0, is_archived = 1 "
                "WHERE id = ?",
                (branch_id,),
            )


def restore_branch(branch_id: str) -> None:
    """Возвращает ветку из архива."""
    _initialize_branches()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        branch = connection.execute(
            "SELECT section_id, title FROM content_branches WHERE id = ?",
            (branch_id,),
        ).fetchone()
        if branch is None:
            raise ValueError("Ветка не найдена.")
        duplicate = connection.execute(
            "SELECT 1 FROM content_branches "
            "WHERE section_id = ? AND id <> ? AND is_archived = 0 "
            "AND title = ? COLLATE NOCASE",
            (branch[0], branch_id, branch[1]),
        ).fetchone()
        if duplicate:
            raise ValueError("В разделе уже есть активная ветка с таким названием.")

    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute(
                "UPDATE content_branches SET is_archived = 0 WHERE id = ?",
                (branch_id,),
            )


def _create_content_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS content_items (
            id TEXT PRIMARY KEY,
            section_id TEXT NOT NULL,
            branch_id TEXT NOT NULL DEFAULT '',
            item_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            keywords TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'current',
            review_due_at TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0,
            is_featured INTEGER NOT NULL DEFAULT 0,
            is_visible INTEGER NOT NULL DEFAULT 1,
            is_archived INTEGER NOT NULL DEFAULT 0,
            table_columns_json TEXT NOT NULL DEFAULT '[]',
            table_rows_json TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY(section_id) REFERENCES content_sections(id)
        )
        """
    )


def _content_columns(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(content_items)")
    }


def _upgrade_content_schema(connection: sqlite3.Connection) -> None:
    """Добавляет поля актуальности в существующую базу без потери данных."""
    columns = _content_columns(connection)
    if "branch_id" not in columns:
        connection.execute(
            "ALTER TABLE content_items "
            "ADD COLUMN branch_id TEXT NOT NULL DEFAULT ''"
        )
    if "status" not in columns:
        connection.execute(
            "ALTER TABLE content_items "
            "ADD COLUMN status TEXT NOT NULL DEFAULT 'current'"
        )
    if "review_due_at" not in columns:
        connection.execute(
            "ALTER TABLE content_items "
            "ADD COLUMN review_due_at TEXT NOT NULL DEFAULT ''"
        )
    if "is_featured" not in columns:
        connection.execute(
            "ALTER TABLE content_items "
            "ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_items_section "
        "ON content_items(section_id, position)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_items_branch "
        "ON content_items(branch_id, position)"
    )


def _apply_content_structure_migration(connection: sqlite3.Connection) -> None:
    """Распределяет материалы старого каркаса, не меняя их содержимое."""
    applied = connection.execute(
        "SELECT 1 FROM app_migrations WHERE id = ?",
        (CONTENT_STRUCTURE_MIGRATION,),
    ).fetchone()
    if applied:
        return

    connection.execute(
        "UPDATE content_items SET section_id = 'documents', "
        "branch_id = 'documents-faq', item_type = 'faq' "
        "WHERE section_id = 'faq'"
    )
    connection.execute(
        "UPDATE content_items SET section_id = 'documents', "
        "branch_id = 'documents-instructions', item_type = 'instruction' "
        "WHERE section_id = 'instructions'"
    )
    connection.execute(
        "UPDATE content_items SET section_id = 'testing', "
        "branch_id = 'testing-tables', item_type = 'table' "
        "WHERE section_id = 'reference_tables'"
    )
    connection.execute(
        "UPDATE content_items SET section_id = 'reference', branch_id = '' "
        "WHERE branch_id = 'testing-tables' AND title LIKE ?",
        ("%Сроки действия%",),
    )
    connection.execute(
        "UPDATE content_items SET section_id = 'documents', "
        "branch_id = 'documents-templates', item_type = 'template' "
        "WHERE section_id = 'templates'"
    )
    connection.execute(
        "INSERT INTO app_migrations (id, applied_at) VALUES (?, ?)",
        (CONTENT_STRUCTURE_MIGRATION, datetime.now(UTC).isoformat()),
    )


def _apply_legacy_section_cleanup(connection: sqlite3.Connection) -> None:
    """Удаляет только опустевшие системные разделы прежнего каркаса."""
    applied = connection.execute(
        "SELECT 1 FROM app_migrations WHERE id = ?",
        (LEGACY_SECTION_CLEANUP_MIGRATION,),
    ).fetchone()
    if applied:
        return

    for section_id in LEGACY_SECTION_IDS:
        connection.execute(
            "DELETE FROM content_sections WHERE id = ? "
            "AND NOT EXISTS ("
            "SELECT 1 FROM content_items WHERE section_id = ?"
            ") AND NOT EXISTS ("
            "SELECT 1 FROM content_branches WHERE section_id = ?"
            ")",
            (section_id, section_id, section_id),
        )
    connection.execute(
        "INSERT INTO app_migrations (id, applied_at) VALUES (?, ?)",
        (LEGACY_SECTION_CLEANUP_MIGRATION, datetime.now(UTC).isoformat()),
    )


def _initialize_content() -> None:
    """Создаёт универсальное хранилище материалов при первом обращении."""
    _initialize_branches()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        schema_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'content_items'"
        ).fetchone() is not None
        columns = _content_columns(connection) if schema_exists else set()
        migration_applied = connection.execute(
            "SELECT 1 FROM app_migrations WHERE id = ?",
            (CONTENT_STRUCTURE_MIGRATION,),
        ).fetchone() is not None
        cleanup_applied = connection.execute(
            "SELECT 1 FROM app_migrations WHERE id = ?",
            (LEGACY_SECTION_CLEANUP_MIGRATION,),
        ).fetchone() is not None

    required_columns = {"branch_id", "status", "review_due_at", "is_featured"}
    upgrade_required = schema_exists and not required_columns.issubset(columns)

    if (
        not schema_exists
        or upgrade_required
        or not migration_applied
        or not cleanup_applied
    ):
        _create_backup()

    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        with connection:
            connection.execute("PRAGMA foreign_keys = ON")
            _create_content_schema(connection)
            _upgrade_content_schema(connection)
            _apply_content_structure_migration(connection)
            _apply_legacy_section_cleanup(connection)


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
    branch_id: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Загружает статьи, инструкции и произвольные таблицы."""
    _initialize_content()
    conditions = []
    parameters: list[Any] = []
    if section_id:
        conditions.append("ci.section_id = ?")
        parameters.append(section_id)
    if branch_id is not None:
        conditions.append("ci.branch_id = ?")
        parameters.append(branch_id)
    if not include_archived:
        conditions.append("ci.is_archived = 0")

    query = (
        "SELECT ci.*, COALESCE(cb.title, '') AS branch_title, "
        "COALESCE(cb.branch_kind, '') AS branch_kind, "
        "COALESCE(cb.is_visible, 0) AS branch_is_visible, "
        "COALESCE(cb.is_archived, 0) AS branch_is_archived "
        "FROM content_items AS ci "
        "LEFT JOIN content_branches AS cb ON cb.id = ci.branch_id"
    )
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY ci.position, ci.title COLLATE NOCASE"

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
                    "is_featured": bool(row["is_featured"]),
                    "branch_is_visible": bool(row["branch_is_visible"]),
                    "branch_is_archived": bool(row["branch_is_archived"]),
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
    branch_id = str(item.get("branch_id", "")).strip()
    item_type = str(item.get("item_type", "")).strip()
    title = str(item.get("title", "")).strip()
    if not item_id or not section_id or not title:
        raise ValueError("Идентификатор, раздел и название материала обязательны.")
    if item_type not in CONTENT_ITEM_TYPES:
        raise ValueError("Неизвестный тип материала.")
    status = str(item.get("status", "current")).strip() or "current"
    if status not in MATERIAL_STATUSES:
        raise ValueError("Неизвестный статус материала.")

    columns, rows = _normalize_table_content(
        item_id,
        item.get("table_columns", []),
        item.get("table_rows", []),
    )

    _initialize_content()
    _create_backup()
    with closing(sqlite3.connect(SQLITE_PATH)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        section_row = connection.execute(
            "SELECT page_kind FROM content_sections WHERE id = ?",
            (section_id,),
        ).fetchone()
        if section_row is None:
            raise ValueError("Выбранный раздел не существует.")
        if item_type not in allowed_item_types(str(section_row[0])):
            raise ValueError("Этот тип материала нельзя сохранять в выбранном разделе.")
        if branch_id:
            branch_row = connection.execute(
                "SELECT branch_kind FROM content_branches "
                "WHERE id = ? AND section_id = ? AND is_archived = 0",
                (branch_id, section_id),
            ).fetchone()
            if branch_row is None:
                raise ValueError("Выбранная ветка не относится к этому разделу.")
            if str(branch_row[0]) != item_type:
                raise ValueError("Тип материала не соответствует типу выбранной ветки.")

        with connection:
            connection.execute(
                """
                INSERT INTO content_items (
                    id, section_id, branch_id, item_type, title, summary, body, keywords,
                    source, updated_at, status, review_due_at, position,
                    is_featured, is_visible, is_archived,
                    table_columns_json, table_rows_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    section_id = excluded.section_id,
                    branch_id = excluded.branch_id,
                    item_type = excluded.item_type,
                    title = excluded.title,
                    summary = excluded.summary,
                    body = excluded.body,
                    keywords = excluded.keywords,
                    source = excluded.source,
                    updated_at = excluded.updated_at,
                    status = excluded.status,
                    review_due_at = excluded.review_due_at,
                    position = excluded.position,
                    is_featured = excluded.is_featured,
                    is_visible = excluded.is_visible,
                    is_archived = excluded.is_archived,
                    table_columns_json = excluded.table_columns_json,
                    table_rows_json = excluded.table_rows_json
                """,
                (
                    item_id,
                    section_id,
                    branch_id,
                    item_type,
                    title,
                    str(item.get("summary", "")).strip(),
                    str(item.get("body", "")),
                    str(item.get("keywords", "")).strip(),
                    str(item.get("source", "")).strip(),
                    str(item.get("updated_at", "")).strip(),
                    status,
                    str(item.get("review_due_at", "")).strip(),
                    int(item.get("position", 0)),
                    int(bool(item.get("is_featured", False))),
                    int(bool(item.get("is_visible", True)) and status != "draft"),
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
