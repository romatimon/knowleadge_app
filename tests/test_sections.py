import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import storage
from streamlit.testing.v1 import AppTest


def render_sections_test_page():
    from knowledge_base.sections import render_sections_admin

    render_sections_admin()


class SectionStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.patches = [
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "SQLITE_PATH", data_dir / "knowledge.db"),
            patch.object(storage, "BACKUP_DIR", data_dir / "backups"),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temp_dir.cleanup()

    def test_default_sections_are_initialized(self):
        sections = storage.load_sections()

        self.assertEqual(
            [section["page_kind"] for section in sections],
            ["custom", "custom", "custom", "custom", "custom"],
        )
        self.assertEqual(
            [section["title"] for section in sections],
            [
                "Работа с клиентом",
                "Оформление документов",
                "Испытания и образцы",
                "Сопровождение",
                "Справочник и внутренние процессы",
            ],
        )

    def test_section_can_be_created_edited_archived_and_restored(self):
        section = {
            "id": "samples",
            "title": "Образцы",
            "icon": "🧪",
            "description": "Отбор и передача",
            "page_kind": "custom",
            "position": 40,
            "is_visible": True,
            "is_archived": False,
        }
        storage.save_section(section)

        section["title"] = "Отбор образцов"
        storage.save_section(section)
        created = next(
            item for item in storage.load_sections() if item["id"] == "samples"
        )
        self.assertEqual(created["title"], "Отбор образцов")

        storage.archive_section("samples")
        self.assertFalse(
            any(item["id"] == "samples" for item in storage.load_sections())
        )

        storage.restore_section("samples")
        restored = next(
            item for item in storage.load_sections() if item["id"] == "samples"
        )
        self.assertFalse(restored["is_visible"])

    def test_default_branches_are_initialized(self):
        branches = storage.load_branches()

        self.assertEqual(len(branches), 25)
        expected_titles = [
            "Инструкции",
            "Шаблоны",
            "FAQ",
            "Чек-листы",
            "Матрицы и нормы",
        ]
        for section_id in ("client", "documents", "testing", "support", "reference"):
            self.assertEqual(
                [
                    branch["title"]
                    for branch in branches
                    if branch["section_id"] == section_id
                ],
                expected_titles,
            )

    def test_branch_can_be_created_edited_archived_and_restored(self):
        branch = {
            "id": "client-checklists",
            "section_id": "client",
            "title": "Проверки",
            "branch_kind": "checklist",
            "description": "Проверки перед отправкой",
            "position": 40,
            "is_visible": True,
        }
        storage.save_branch(branch)
        branch["title"] = "Чек-листы"
        storage.save_branch(branch)

        created = next(
            item
            for item in storage.load_branches()
            if item["id"] == "client-checklists"
        )
        self.assertEqual(created["title"], "Чек-листы")

        storage.archive_branch("client-checklists")
        self.assertFalse(
            any(
                item["id"] == "client-checklists"
                for item in storage.load_branches()
            )
        )
        storage.restore_branch("client-checklists")
        self.assertTrue(
            any(
                item["id"] == "client-checklists"
                for item in storage.load_branches()
            )
        )

    def test_non_empty_branch_cannot_be_archived(self):
        storage.save_content_item(
            {
                "id": "client-guide",
                "section_id": "client",
                "branch_id": "client-instructions",
                "item_type": "instruction",
                "title": "Проверка заявки",
                "body": "Текст",
            }
        )

        with self.assertRaisesRegex(ValueError, "Сначала перенесите материалы"):
            storage.archive_branch("client-instructions")

    def test_catalog_migration_runs_once_and_preserves_visibility(self):
        with closing(sqlite3.connect(storage.SQLITE_PATH)) as connection:
            storage._create_sections_schema(connection)
            connection.execute(
                """
                INSERT INTO content_sections (
                    id, title, icon, description, page_kind, position,
                    is_visible, is_archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "client",
                    "Старое название FAQ",
                    "❓",
                    "Старое описание",
                    "custom",
                    10,
                    0,
                    0,
                ),
            )
            connection.commit()

        migrated = storage.load_sections()
        client = next(section for section in migrated if section["id"] == "client")
        self.assertEqual(client["title"], "Работа с клиентом")
        self.assertFalse(client["is_visible"])
        self.assertEqual(len(migrated), 5)

        client["title"] = "Моё название"
        storage.save_section(client)
        reloaded = next(
            section for section in storage.load_sections() if section["id"] == "client"
        )
        self.assertEqual(reloaded["title"], "Моё название")

    def test_section_purpose_cannot_hide_existing_material_type(self):
        storage.save_content_item(
            {
                "id": "faq-example",
                "section_id": "documents",
                "branch_id": "documents-faq",
                "item_type": "faq",
                "title": "Рабочая ситуация",
                "body": "Краткий ответ",
            }
        )
        section = next(
            section
            for section in storage.load_sections()
            if section["id"] == "documents"
        )
        section["page_kind"] = "reference_tables"

        with self.assertRaisesRegex(ValueError, "не подходит"):
            storage.save_section(section)

    def test_admin_page_creates_section(self):
        page = AppTest.from_function(render_sections_test_page).run(timeout=30)
        title_input = next(
            item for item in page.text_input if item.label == "Название"
        )
        save_button = next(
            item for item in page.button if item.label == "Сохранить раздел"
        )

        title_input.input("Испытания")
        save_button.click()
        page.run(timeout=30)

        self.assertEqual(list(page.exception), [])
        self.assertTrue(
            any(
                section["title"] == "Испытания"
                for section in storage.load_sections()
            )
        )


if __name__ == "__main__":
    unittest.main()
