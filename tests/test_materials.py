import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import storage
from knowledge_base.materials import (
    _columns_frame,
    _display_table_frame,
    _excel_bytes,
    _map_import_rows,
    _parse_columns_editor,
    _read_table_file,
    filter_content_items,
    material_relevance,
    table_column_width,
)
from streamlit.testing.v1 import AppTest


def render_materials_test_page():
    from knowledge_base.materials import render_materials_admin

    render_materials_admin()


class MaterialTests(unittest.TestCase):
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

    def test_table_round_trip_and_archive(self):
        item = {
            "id": "sampling-table",
            "section_id": "reference_tables",
            "item_type": "table",
            "title": "Нормы отбора",
            "summary": "Количество образцов",
            "body": "",
            "keywords": "образцы; партия",
            "source": "Регламент",
            "updated_at": "2026-09-09",
            "position": 10,
            "is_visible": True,
            "is_archived": False,
            "table_columns": ["Продукция", "Количество"],
            "table_rows": [{"Продукция": "Молоко", "Количество": "5"}],
        }
        storage.save_content_item(item)

        loaded = storage.load_content_items(section_id="reference_tables")
        columns = loaded[0]["table_columns"]
        self.assertEqual(
            [column["label"] for column in columns], item["table_columns"]
        )
        self.assertEqual(
            loaded[0]["table_rows"][0][columns[0]["id"]], "Молоко"
        )

        storage.archive_content_item(item["id"])
        self.assertEqual(storage.load_content_items(), [])
        storage.restore_content_item(item["id"])
        self.assertEqual(len(storage.load_content_items()), 1)

    def test_admin_can_create_and_open_empty_table(self):
        storage.save_content_item(
            {
                "id": "empty-table",
                "section_id": "reference_tables",
                "item_type": "table",
                "title": "Новая таблица",
                "table_columns": ["Продукция", "Срок"],
                "table_rows": [],
            }
        )
        page = AppTest.from_function(render_materials_test_page).run(timeout=30)
        section_selector = next(
            item
            for item in page.selectbox
            if item.label == "1. Выберите раздел"
        )
        section_selector.select("Матрицы, нормы и сроки")
        page.run(timeout=30)
        material_selector = next(
            item
            for item in page.selectbox
            if item.label == "2. Выберите материал"
        )
        table_option = next(
            option
            for option in material_selector.options
            if "Новая таблица" in option
        )
        material_selector.select(table_option)
        page.run(timeout=30)

        self.assertEqual(list(page.exception), [])
        saved_table = storage.load_content_items()[0]
        self.assertEqual(
            [column["label"] for column in saved_table["table_columns"]],
            ["Продукция", "Срок"],
        )

    def test_column_rename_keeps_id_and_values(self):
        storage.save_content_item(
            {
                "id": "rename-table",
                "section_id": "reference_tables",
                "item_type": "table",
                "title": "Проверка переименования",
                "table_columns": ["Продукция"],
                "table_rows": [{"Продукция": "Молоко"}],
            }
        )
        item = storage.load_content_items()[0]
        column_id = item["table_columns"][0]["id"]
        frame = _columns_frame(item["table_columns"])
        frame.loc[0, "Название"] = "Наименование продукции"
        columns, error = _parse_columns_editor(frame)
        self.assertIsNone(error)

        item["table_columns"] = columns
        storage.save_content_item(item)
        renamed = storage.load_content_items()[0]

        self.assertEqual(renamed["table_columns"][0]["id"], column_id)
        self.assertEqual(renamed["table_rows"][0][column_id], "Молоко")

    def test_faq_is_stored_as_universal_material(self):
        storage.save_content_item(
            {
                "id": "faq-sample",
                "section_id": "faq",
                "item_type": "faq",
                "title": "Что делать в рабочей ситуации?",
                "summary": "Краткий ответ сотруднику",
                "body": "## Что делать\n\n1. Проверить документы.",
                "keywords": "ситуация; документы",
            }
        )

        item = storage.load_content_items(section_id="faq")[0]

        self.assertEqual(item["item_type"], "faq")
        self.assertIn("Проверить документы", item["body"])

    def test_default_sections_restrict_material_types(self):
        self.assertEqual(storage.allowed_item_types("faq"), ("faq", "article"))
        self.assertEqual(storage.allowed_item_types("reference_tables"), ("table",))
        self.assertEqual(storage.allowed_item_types("instructions"), ("instruction",))
        self.assertEqual(storage.allowed_item_types("reference"), ("article", "table"))
        self.assertEqual(
            storage.allowed_item_types("templates"), ("article", "instruction")
        )

        with self.assertRaisesRegex(ValueError, "нельзя сохранять"):
            storage.save_content_item(
                {
                    "id": "wrong-table",
                    "section_id": "faq",
                    "item_type": "table",
                    "title": "Таблица не в том разделе",
                    "table_columns": ["Колонка"],
                }
            )

    def test_draft_is_never_published(self):
        storage.save_content_item(
            {
                "id": "draft-faq",
                "section_id": "faq",
                "item_type": "faq",
                "title": "Черновик ответа",
                "body": "Текст",
                "status": "draft",
                "is_visible": True,
            }
        )

        draft = storage.load_content_items()[0]
        self.assertEqual(draft["status"], "draft")
        self.assertFalse(draft["is_visible"])

    def test_relevance_uses_status_and_review_date(self):
        today = date(2026, 9, 10)

        self.assertEqual(material_relevance({"status": "draft"}, today), "draft")
        self.assertEqual(material_relevance({"status": "review"}, today), "review")
        self.assertEqual(
            material_relevance(
                {"status": "current", "review_due_at": "2026-09-10"},
                today,
            ),
            "overdue",
        )
        self.assertEqual(
            material_relevance(
                {"status": "current", "review_due_at": "2026-10-01"},
                today,
            ),
            "current",
        )

    def test_old_content_schema_is_upgraded_without_losing_item(self):
        storage.load_sections()
        with closing(sqlite3.connect(storage.SQLITE_PATH)) as connection:
            connection.execute(
                """
                CREATE TABLE content_items (
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
                    table_rows_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO content_items (
                    id, section_id, item_type, title, body
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("old-item", "faq", "faq", "Старый материал", "Содержимое"),
            )
            connection.commit()

        item = storage.load_content_items()[0]
        self.assertEqual(item["title"], "Старый материал")
        self.assertEqual(item["body"], "Содержимое")
        self.assertEqual(item["status"], "current")
        self.assertEqual(item["review_due_at"], "")

    def test_search_filters_rows_inside_new_table(self):
        item = {
            "id": "validity-periods",
            "item_type": "table",
            "title": "Сроки действия документов",
            "summary": "Справочная таблица",
            "body": "Срок зависит от схемы подтверждения.",
            "keywords": "сертификат; декларация",
            "source": "Регламенты",
            "table_columns": [
                {"id": "regulation", "label": "Регламент", "type": "text"},
                {"id": "period", "label": "Срок", "type": "text"},
            ],
            "table_rows": [
                {"regulation": "ТР ТС 007/2011", "period": "5 лет"},
                {"regulation": "ТР ТС 017/2011", "period": "3 года"},
            ],
        }

        matches = filter_content_items([item], "007")

        self.assertEqual(len(matches), 1)
        self.assertEqual(
            matches[0]["table_rows"],
            [{"regulation": "ТР ТС 007/2011", "period": "5 лет"}],
        )

    def test_search_by_table_title_keeps_all_rows(self):
        item = {
            "item_type": "table",
            "title": "Сроки действия документов",
            "table_columns": [],
            "table_rows": [{"value": "007"}, {"value": "017"}],
        }

        matches = filter_content_items([item], "сроки документов")

        self.assertEqual(matches[0]["table_rows"], item["table_rows"])

    def test_table_column_width_adapts_to_column_count(self):
        self.assertEqual(table_column_width(3), "large")
        self.assertEqual(table_column_width(5), "medium")
        self.assertEqual(table_column_width(6), "small")
        self.assertEqual(table_column_width(8), "small")

    def test_csv_import_supports_semicolon_and_cp1251(self):
        content = "Продукция;Количество\nМолоко;5\n".encode("cp1251")

        frame = _read_table_file("samples.csv", content)

        self.assertEqual(
            frame.to_dict(orient="records"),
            [{"Продукция": "Молоко", "Количество": "5"}],
        )

    def test_import_mapping_and_excel_export(self):
        columns = [
            {
                "id": "product-id",
                "label": "Продукция",
                "type": "text",
                "required": True,
                "position": 10,
            },
            {
                "id": "amount-id",
                "label": "Количество",
                "type": "number",
                "required": False,
                "position": 20,
            },
        ]
        source = pd.DataFrame([{"Товар": "Молоко", "Кол-во": 5}])
        rows = _map_import_rows(
            source,
            columns,
            {"product-id": "Товар", "amount-id": "Кол-во"},
        )
        item = {"table_columns": columns, "table_rows": rows}

        exported = _display_table_frame(item)
        excel_content = _excel_bytes(exported)
        imported = pd.read_excel(BytesIO(excel_content), dtype=str)

        self.assertEqual(rows, [{"product-id": "Молоко", "amount-id": "5"}])
        self.assertEqual(imported.iloc[0].to_dict(), {
            "Продукция": "Молоко",
            "Количество": "5",
        })


if __name__ == "__main__":
    unittest.main()
