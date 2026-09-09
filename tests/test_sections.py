import tempfile
import unittest
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
            ["faq", "reference_tables", "instructions"],
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
