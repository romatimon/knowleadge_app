import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import storage
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def render_control_test_page():
    from knowledge_base.control import render_content_control

    render_content_control()


class AppSmokeTests(unittest.TestCase):
    def test_app_starts_and_admin_can_sign_in(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            environment = {"ADMIN_PASSWORD": "тестовый-пароль"}
            with (
                patch.dict(os.environ, environment, clear=False),
                patch.object(storage, "DATA_DIR", data_dir),
                patch.object(storage, "SQLITE_PATH", data_dir / "knowledge.db"),
                patch.object(storage, "BACKUP_DIR", data_dir / "backups"),
            ):
                app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=30)
                password_input = next(
                    item for item in app.text_input if item.label == "Пароль"
                )
                login_button = next(
                    item for item in app.button if item.label == "Войти"
                )
                password_input.input(environment["ADMIN_PASSWORD"])
                login_button.click()
                app.run(timeout=30)

        self.assertEqual(list(app.exception), [])
        self.assertTrue(app.session_state["is_admin"])

    def test_control_page_starts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            with (
                patch.object(storage, "DATA_DIR", data_dir),
                patch.object(storage, "SQLITE_PATH", data_dir / "knowledge.db"),
                patch.object(storage, "BACKUP_DIR", data_dir / "backups"),
            ):
                app = AppTest.from_function(render_control_test_page).run(timeout=30)

        self.assertEqual(list(app.exception), [])


if __name__ == "__main__":
    unittest.main()
