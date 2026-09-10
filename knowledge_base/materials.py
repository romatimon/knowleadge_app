"""Создание и редактирование материалов внутри разделов."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from storage import (
    allowed_item_types,
    archive_content_item,
    load_content_items,
    load_sections,
    restore_content_item,
    save_content_item,
)


TYPE_LABELS = {
    "faq": "FAQ / рабочая ситуация",
    "article": "Справка / статья",
    "instruction": "Инструкция",
    "table": "Таблица",
}

STATUS_LABELS = {
    "current": "Актуально",
    "review": "Требует проверки",
    "draft": "Черновик",
}

STATUS_MARKERS = {
    "current": "",
    "review": "⚠️",
    "overdue": "⏰",
    "draft": "📝",
}

COLUMN_TYPE_LABELS = {
    "text": "Текст",
    "number": "Число",
    "checkbox": "Да / Нет",
}

MAX_IMPORT_ROWS = 50_000
TABLE_ROW_HEIGHT = 80

INSTRUCTION_TEMPLATE = """## Назначение

Кратко опишите результат инструкции.

## Что подготовить

- Перечислите документы и сведения.

## Алгоритм

1. Выполните первое действие.
2. Выполните следующее действие.

## Особые случаи

- Опишите исключения и ограничения.

## Результат

Укажите, как проверить завершение работы.
"""

FAQ_TEMPLATE = """## Краткий ответ

Дайте сотруднику прямой ответ на вопрос.

## Что делать

1. Укажите первое действие.
2. Укажите следующее действие.

## Важно

- Опишите ограничения и исключения.
"""


def _normalize_search_text(value: object) -> str:
    """Приводит пользовательский текст к словам для нечувствительного поиска."""
    return re.sub(r"[^\w]+", " ", str(value).casefold(), flags=re.UNICODE).strip()


def filter_content_items(items: list[dict], query: str) -> list[dict]:
    """Фильтрует материалы, а у таблиц оставляет только найденные строки."""
    terms = _normalize_search_text(query).split()
    if not terms:
        return list(items)

    results = []
    for item in items:
        metadata_text = _normalize_search_text(
            " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("summary", "")),
                    str(item.get("body", "")),
                    str(item.get("keywords", "")),
                    str(item.get("source", "")),
                    " ".join(
                        str(column.get("label", ""))
                        for column in item.get("table_columns", [])
                    ),
                ]
            )
        )

        if item.get("item_type") != "table":
            if all(term in metadata_text for term in terms):
                results.append(item)
            continue

        rows = item.get("table_rows", [])
        matching_rows = []
        for row in rows:
            row_text = _normalize_search_text(" ".join(map(str, row.values())))
            combined_text = f"{metadata_text} {row_text}"
            if all(term in combined_text for term in terms):
                matching_rows.append(row)

        if matching_rows or (
            not rows and all(term in metadata_text for term in terms)
        ):
            filtered_item = dict(item)
            filtered_item["table_rows"] = matching_rows
            results.append(filtered_item)

    return results


def table_column_width(column_count: int) -> str:
    """Подбирает ширину колонок так, чтобы таблица помещалась на экране."""
    if column_count <= 3:
        return "large"
    if column_count <= 5:
        return "medium"
    return "small"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now(UTC).date()


def _parse_optional_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def material_relevance(item: dict, today: date | None = None) -> str:
    """Возвращает фактическое состояние актуальности материала."""
    status = str(item.get("status", "current"))
    if status == "draft":
        return "draft"
    if status == "review":
        return "review"

    review_due = _parse_optional_date(str(item.get("review_due_at", "")))
    if review_due and review_due <= (today or datetime.now(UTC).date()):
        return "overdue"
    return "current"


def _columns_frame(columns: list[dict]) -> pd.DataFrame:
    """Готовит отдельный визуальный редактор структуры таблицы."""
    records = [
        {
            "_id": str(column.get("id", "")),
            "Название": str(column.get("label", "")),
            "Тип": COLUMN_TYPE_LABELS.get(column.get("type"), "Текст"),
            "Обязательное": bool(column.get("required", False)),
            "Порядок": int(column.get("position", (index + 1) * 10)),
        }
        for index, column in enumerate(columns)
    ]
    if records:
        frame = pd.DataFrame(records)
    else:
        frame = pd.DataFrame(
            {
                "_id": pd.Series(dtype="string"),
                "Название": pd.Series(dtype="string"),
                "Тип": pd.Series(dtype="string"),
                "Обязательное": pd.Series(dtype="bool"),
                "Порядок": pd.Series(dtype="int64"),
            }
        )
    frame["_id"] = frame["_id"].astype("string").fillna("")
    frame["Название"] = frame["Название"].astype("string").fillna("")
    frame["Тип"] = frame["Тип"].astype("string").fillna("Текст")
    frame["Обязательное"] = frame["Обязательное"].fillna(False).astype(bool)
    frame["Порядок"] = (
        pd.to_numeric(frame["Порядок"], errors="coerce").fillna(0).astype(int)
    )
    return frame


def _parse_columns_editor(frame: pd.DataFrame) -> tuple[list[dict], str | None]:
    """Проверяет и преобразует строки визуального редактора колонок."""
    type_by_label = {label: key for key, label in COLUMN_TYPE_LABELS.items()}
    columns = []
    for index, row in frame.fillna("").iterrows():
        label = str(row.get("Название", "")).strip()
        if not label:
            continue
        column_id = str(row.get("_id", "")).strip() or f"column_{uuid4().hex[:12]}"
        type_label = str(row.get("Тип", "Текст")).strip()
        try:
            position = int(row.get("Порядок", (index + 1) * 10))
        except (TypeError, ValueError):
            position = (index + 1) * 10
        columns.append(
            {
                "id": column_id,
                "label": label,
                "type": type_by_label.get(type_label, "text"),
                "required": bool(row.get("Обязательное", False)),
                "position": max(position, 0),
            }
        )

    labels = [column["label"].casefold() for column in columns]
    if not columns:
        return [], "Добавьте хотя бы одну колонку."
    if len(columns) > 40:
        return [], "В одной таблице допускается не более 40 колонок."
    if len(set(labels)) != len(labels):
        return [], "Названия колонок не должны повторяться."
    columns.sort(key=lambda column: (column["position"], column["label"].casefold()))
    return columns, None


def _item_label(
    item: dict,
    section_by_id: dict[str, dict],
    include_section: bool = True,
) -> str:
    section = section_by_id.get(item.get("section_id"), {})
    type_label = TYPE_LABELS.get(item.get("item_type"), "Материал")
    relevance = material_relevance(item)
    marker = STATUS_MARKERS.get(relevance, "")
    label = f"{marker} {item['title']} · {type_label}".strip()
    if include_section:
        return f"{section.get('title', 'Без раздела')} → {label}"
    return label


def _next_position(items: list[dict], section_id: str) -> int:
    positions = [
        int(item.get("position", 0))
        for item in items
        if item.get("section_id") == section_id
    ]
    return (max(positions) if positions else 0) + 10


def _save_with_feedback(item: dict, message: str) -> bool:
    try:
        save_content_item(item)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        st.error(f"Не удалось сохранить материал: {error}")
        return False
    st.success(message)
    return True


def _render_settings_form(
    selected_id: str,
    selected: dict,
    item_type: str,
    section_id: str,
    active_items: list[dict],
) -> None:
    with st.form(f"material_form_{selected_id or 'new'}_{item_type}"):
        title = st.text_input("Название", value=str(selected.get("title", "")))
        summary = st.text_area(
            "Краткое описание",
            value=str(selected.get("summary", "")),
            height=90,
            placeholder="Что сотрудник найдёт в этом материале",
        )

        columns_editor = None
        confirm_removed_columns = False
        if item_type == "table":
            st.markdown("#### Колонки")
            st.caption(
                "Добавляйте и удаляйте колонки прямо в списке. Переименование "
                "не удаляет значения из таблицы."
            )
            columns_editor = st.data_editor(
                _columns_frame(selected.get("table_columns", [])),
                num_rows="dynamic",
                row_height=TABLE_ROW_HEIGHT,
                width="stretch",
                hide_index=True,
                column_config={
                    "_id": None,
                    "Название": st.column_config.TextColumn(
                        "Название", required=True, width="large"
                    ),
                    "Тип": st.column_config.SelectboxColumn(
                        "Тип",
                        options=list(COLUMN_TYPE_LABELS.values()),
                        required=True,
                        width="medium",
                    ),
                    "Обязательное": st.column_config.CheckboxColumn(
                        "Обязательное", width="small"
                    ),
                    "Порядок": st.column_config.NumberColumn(
                        "Порядок", min_value=0, step=10, width="small"
                    ),
                },
                key=f"columns_editor_{selected_id or 'new'}",
            )
            confirm_removed_columns = st.checkbox(
                "Подтверждаю удаление данных из исключённых колонок",
                disabled=not selected_id,
            )
            body = st.text_area(
                "Памятка к таблице",
                value=str(selected.get("body", "")),
                height=220,
                placeholder=(
                    "Необязательный текст над таблицей: пояснения, правила, "
                    "единицы измерения или важные исключения"
                ),
                help="Можно использовать Markdown: заголовки, списки и выделение.",
            )
        else:
            if selected_id:
                default_body = str(selected.get("body", ""))
            elif item_type == "instruction":
                default_body = INSTRUCTION_TEMPLATE
            elif item_type == "faq":
                default_body = FAQ_TEMPLATE
            else:
                default_body = ""
            body = st.text_area(
                "Текст материала",
                value=default_body,
                height=430,
                help="Можно использовать Markdown: заголовки, списки и выделение.",
            )

        st.markdown("#### Актуальность")
        relevance_col, review_col = st.columns(2)
        with relevance_col:
            status_ids = list(STATUS_LABELS)
            current_status = str(selected.get("status", "current"))
            if current_status not in status_ids:
                current_status = "current"
            status = st.selectbox(
                "Статус",
                status_ids,
                index=status_ids.index(current_status),
                format_func=lambda value: STATUS_LABELS[value],
            )
            updated_at = st.date_input(
                "Проверено или обновлено",
                value=_parse_date(str(selected.get("updated_at", ""))),
            )
        with review_col:
            review_due_at = st.date_input(
                "Проверить снова",
                value=_parse_optional_date(
                    str(selected.get("review_due_at", ""))
                ),
                help="Необязательно. В указанную дату появится предупреждение.",
            )
        is_visible = st.checkbox(
            "Показывать сотрудникам",
            value=bool(selected.get("is_visible", True)),
            help="Черновик не публикуется независимо от этой настройки.",
        )

        with st.expander("Дополнительные настройки"):
            keywords = st.text_area(
                "Ключевые слова для поиска",
                value=str(selected.get("keywords", "")),
                height=75,
                placeholder="Синонимы и сокращения через точку с запятой",
            )
            source = st.text_input(
                "Источник",
                value=str(selected.get("source", "")),
                placeholder="Документ, письмо или ссылка",
            )
            position = st.number_input(
                "Порядок внутри раздела",
                min_value=0,
                step=10,
                value=int(
                    selected.get(
                        "position", _next_position(active_items, section_id)
                    )
                ),
            )

        submitted = st.form_submit_button("Сохранить материал", type="primary")

    if not submitted:
        return

    clean_title = title.strip()
    columns = []
    columns_error = None
    if item_type == "table" and columns_editor is not None:
        columns, columns_error = _parse_columns_editor(columns_editor)
    old_column_ids = {
        str(column.get("id", ""))
        for column in selected.get("table_columns", [])
    }
    new_column_ids = {column["id"] for column in columns}
    removed_column_ids = old_column_ids - new_column_ids
    duplicate = any(
        item["id"] != selected_id
        and item.get("section_id") == section_id
        and item["title"].strip().casefold() == clean_title.casefold()
        for item in active_items
    )
    if not clean_title:
        st.error("Укажите название материала.")
    elif duplicate:
        st.error("В этом разделе уже есть материал с таким названием.")
    elif item_type != "table" and not body.strip():
        st.error("Заполните текст материала.")
    elif columns_error:
        st.error(columns_error)
    elif removed_column_ids and not confirm_removed_columns:
        st.error("Подтвердите удаление исключённых колонок и их данных.")
    else:
        old_rows = selected.get("table_rows", []) if item_type == "table" else []
        clean_rows = [
            {
                column["id"]: str(row.get(column["id"], ""))
                for column in columns
            }
            for row in old_rows
        ]
        values = {
            "id": selected_id or uuid4().hex,
            "section_id": section_id,
            "item_type": item_type,
            "title": clean_title,
            "summary": summary.strip(),
            "body": body,
            "keywords": keywords.strip(),
            "source": source.strip(),
            "updated_at": updated_at.isoformat(),
            "status": status,
            "review_due_at": (
                review_due_at.isoformat() if review_due_at else ""
            ),
            "position": int(position),
            "is_visible": bool(is_visible and status != "draft"),
            "is_archived": False,
            "table_columns": columns,
            "table_rows": clean_rows,
        }
        if _save_with_feedback(values, "Материал сохранён."):
            st.rerun()


def _checkbox_value(value) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "да"}


def _table_editor_data(selected: dict) -> tuple[pd.DataFrame, dict]:
    columns = selected.get("table_columns", [])
    column_ids = [column["id"] for column in columns]
    frame = pd.DataFrame(selected.get("table_rows", [])).reindex(columns=column_ids)
    config = {}
    content_width = table_column_width(len(columns))

    for column in columns:
        column_id = column["id"]
        label = column["label"]
        required = bool(column.get("required", False))
        if column.get("type") == "number":
            frame[column_id] = pd.to_numeric(frame[column_id], errors="coerce")
            config[column_id] = st.column_config.NumberColumn(
                label, help=label, required=required, width=content_width
            )
        elif column.get("type") == "checkbox":
            frame[column_id] = frame[column_id].map(_checkbox_value).astype(bool)
            config[column_id] = st.column_config.CheckboxColumn(
                label, help=label, width="small"
            )
        else:
            frame[column_id] = frame[column_id].astype("string").fillna("")
            config[column_id] = st.column_config.TextColumn(
                label, help=label, required=required, width=content_width
            )
    return frame, config


def _serialize_cell(value) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _display_table_frame(item: dict) -> pd.DataFrame:
    """Преобразует внутренние ID колонок в понятные заголовки для файла."""
    columns = item.get("table_columns", [])
    records = []
    for row in item.get("table_rows", []):
        record = {}
        for column in columns:
            value = str(row.get(column["id"], ""))
            if column.get("type") == "checkbox":
                value = "Да" if _checkbox_value(value) else "Нет"
            record[column["label"]] = value
        records.append(record)
    return pd.DataFrame(records).reindex(
        columns=[column["label"] for column in columns]
    )


def _read_table_file(filename: str, content: bytes) -> pd.DataFrame:
    """Читает CSV/XLSX в строки, пригодные для предварительного просмотра."""
    suffix = Path(filename).suffix.casefold()
    if suffix == ".xlsx":
        frame = pd.read_excel(BytesIO(content), dtype=object, engine="openpyxl")
    elif suffix == ".csv":
        last_error = None
        frame = None
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                frame = pd.read_csv(
                    BytesIO(content),
                    dtype=object,
                    encoding=encoding,
                    sep=None,
                    engine="python",
                )
                break
            except UnicodeDecodeError as error:
                last_error = error
        if frame is None:
            raise ValueError("Не удалось определить кодировку CSV-файла.") from last_error
    else:
        raise ValueError("Поддерживаются только файлы CSV и XLSX.")

    if len(frame) > MAX_IMPORT_ROWS:
        raise ValueError(
            f"В файле больше {MAX_IMPORT_ROWS:,} строк. Разделите его на части."
        )
    frame = frame.dropna(axis=0, how="all").dropna(axis=1, how="all")
    frame.columns = [str(value).strip() for value in frame.columns]
    if any(not column for column in frame.columns):
        raise ValueError("У всех колонок файла должны быть названия.")
    return frame.fillna("")


def _map_import_rows(
    source: pd.DataFrame,
    columns: list[dict],
    mapping: dict[str, str | None],
) -> list[dict[str, str]]:
    """Сопоставляет колонки загруженного файла с постоянными ID таблицы."""
    imported_rows = []
    for _, source_row in source.iterrows():
        result = {}
        for column in columns:
            source_name = mapping.get(column["id"])
            value = source_row.get(source_name, "") if source_name else ""
            result[column["id"]] = _serialize_cell(value)
        if any(value.strip() for value in result.values()):
            imported_rows.append(result)
    return imported_rows


def _excel_bytes(frame: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Данные")
    return output.getvalue()


def _safe_filename(value: str) -> str:
    clean = re.sub(r"[^\w.-]+", "_", value.strip(), flags=re.UNICODE).strip("_.")
    return clean or "table"


def _render_import_export(selected: dict) -> None:
    """Показывает скачивание и безопасный импорт табличных файлов."""
    columns = selected.get("table_columns", [])
    export_frame = _display_table_frame(selected)
    filename = _safe_filename(str(selected.get("title", "table")))

    st.markdown("#### Импорт и экспорт")
    csv_col, excel_col = st.columns(2)
    csv_col.download_button(
        "Скачать CSV",
        data=export_frame.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{filename}.csv",
        mime="text/csv",
        key=f"export_csv_{selected['id']}",
        width="stretch",
    )
    excel_col.download_button(
        "Скачать Excel",
        data=_excel_bytes(export_frame),
        file_name=f"{filename}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"export_xlsx_{selected['id']}",
        width="stretch",
    )

    with st.expander("Импортировать CSV или Excel"):
        uploaded = st.file_uploader(
            "Файл с заголовками в первой строке",
            type=["csv", "xlsx"],
            key=f"table_import_file_{selected['id']}",
        )
        if uploaded is None:
            return

        try:
            source = _read_table_file(uploaded.name, uploaded.getvalue())
        except (ImportError, OSError, ValueError, TypeError) as error:
            st.error(f"Не удалось прочитать файл: {error}")
            return
        if source.empty:
            st.warning("В файле нет строк для импорта.")
            return

        st.caption(f"Найдено строк: {len(source)}. Предварительный просмотр:")
        st.dataframe(source.head(20), width="stretch", hide_index=True)

        source_columns = list(source.columns)
        skip_option = "— Не импортировать —"
        mapping = {}
        st.markdown("##### Сопоставление колонок")
        for column in columns:
            exact_match = next(
                (
                    source_name
                    for source_name in source_columns
                    if source_name.casefold() == column["label"].casefold()
                ),
                None,
            )
            options = [skip_option, *source_columns]
            selected_source = st.selectbox(
                f"{column['label']} ← колонка файла",
                options,
                index=options.index(exact_match) if exact_match else 0,
                key=f"import_map_{selected['id']}_{column['id']}",
            )
            mapping[column["id"]] = (
                None if selected_source == skip_option else selected_source
            )

        import_mode = st.radio(
            "Как сохранить строки",
            ["Добавить к существующим", "Заменить все строки"],
            horizontal=True,
            key=f"import_mode_{selected['id']}",
        )
        replace_confirmed = st.checkbox(
            "Подтверждаю замену всех существующих строк",
            disabled=import_mode != "Заменить все строки",
            key=f"import_replace_confirm_{selected['id']}",
        )
        if st.button(
            "Импортировать данные",
            type="primary",
            key=f"import_submit_{selected['id']}",
        ):
            required_without_source = [
                column["label"]
                for column in columns
                if column.get("required") and not mapping.get(column["id"])
            ]
            if not any(mapping.values()):
                st.error("Сопоставьте хотя бы одну колонку.")
            elif required_without_source:
                st.error(
                    "Сопоставьте обязательные колонки: "
                    + ", ".join(required_without_source)
                )
            elif import_mode == "Заменить все строки" and not replace_confirmed:
                st.error("Подтвердите замену существующих строк.")
            else:
                imported_rows = _map_import_rows(source, columns, mapping)
                if not imported_rows:
                    st.error("После сопоставления не осталось заполненных строк.")
                else:
                    updated = dict(selected)
                    if import_mode == "Заменить все строки":
                        updated["table_rows"] = imported_rows
                    else:
                        updated["table_rows"] = [
                            *selected.get("table_rows", []),
                            *imported_rows,
                        ]
                    if _save_with_feedback(
                        updated,
                        f"Импортировано строк: {len(imported_rows)}.",
                    ):
                        st.rerun()


def _render_table_data(selected: dict) -> None:
    columns = selected.get("table_columns", [])
    if not columns:
        st.info("Сначала добавьте колонки на вкладке «Настройки».")
        return

    st.caption(
        "Редактируйте ячейки прямо в таблице. Строки добавляются и удаляются "
        "кнопками самого редактора; можно вставлять диапазоны из Excel."
    )
    frame, column_config = _table_editor_data(selected)
    schema_key = abs(
        hash(
            tuple(
                (column["id"], column["label"], column["type"])
                for column in columns
            )
        )
    )
    with st.form(f"material_rows_form_{selected['id']}_{schema_key}"):
        edited = st.data_editor(
            frame,
            num_rows="dynamic",
            row_height=TABLE_ROW_HEIGHT,
            width="stretch",
            hide_index=True,
            column_config=column_config,
            key=f"material_rows_editor_{selected['id']}_{schema_key}",
        )
        save_rows = st.form_submit_button("Сохранить данные", type="primary")

    if save_rows:
        updated = dict(selected)
        updated["table_rows"] = [
            {
                column["id"]: _serialize_cell(record.get(column["id"]))
                for column in columns
            }
            for record in edited.to_dict(orient="records")
        ]
        if _save_with_feedback(updated, "Данные таблицы сохранены."):
            st.rerun()

    st.divider()
    _render_import_export(selected)


def _render_delete_action(selected_id: str) -> None:
    confirm_archive = st.checkbox(
        "Подтверждаю удаление материала из раздела",
        key=f"archive_material_confirm_{selected_id}",
    )
    if st.button(
        "Удалить материал",
        disabled=not confirm_archive,
        key=f"archive_material_button_{selected_id}",
    ):
        try:
            archive_content_item(selected_id)
        except (OSError, RuntimeError, sqlite3.Error) as error:
            st.error(f"Не удалось удалить материал: {error}")
        else:
            st.success("Материал перемещён в архив.")
            st.rerun()


def _render_active_editor(sections: list[dict], active_items: list[dict]) -> None:
    section_by_id = {section["id"]: section for section in sections}
    section_ids = list(section_by_id)
    section_id = st.selectbox(
        "1. Выберите раздел",
        section_ids,
        format_func=lambda value: section_by_id[value]["title"],
        key="material_admin_section",
    )
    section = section_by_id[section_id]
    allowed_types = list(
        allowed_item_types(str(section.get("page_kind", "custom")))
    )
    section_items = [
        item for item in active_items if item.get("section_id") == section_id
    ]
    item_by_id = {item["id"]: item for item in section_items}
    options = [""] + list(item_by_id)
    selected_id = st.selectbox(
        "2. Выберите материал",
        options,
        format_func=lambda value: (
            "＋ Создать новый материал"
            if not value
            else _item_label(
                item_by_id[value], section_by_id, include_section=False
            )
        ),
        key=f"material_admin_select_{section_id}",
    )
    selected = item_by_id.get(selected_id, {"section_id": section_id})

    if selected_id:
        item_type = str(selected["item_type"])
        st.caption(f"Тип: {TYPE_LABELS[item_type]}")
    elif len(allowed_types) == 1:
        item_type = allowed_types[0]
        st.caption(f"Будет создан материал типа «{TYPE_LABELS[item_type]}».")
    else:
        default_type = "article" if "article" in allowed_types else allowed_types[0]
        item_type = st.selectbox(
            "3. Выберите тип нового материала",
            allowed_types,
            index=allowed_types.index(default_type),
            format_func=lambda value: TYPE_LABELS[value],
            key=f"material_type_{section_id}",
        )

    if item_type == "table":
        settings_tab, data_tab = st.tabs(["Описание и колонки", "Данные"])
        with settings_tab:
            _render_settings_form(
                selected_id, selected, item_type, section_id, active_items
            )
        with data_tab:
            if selected_id:
                _render_table_data(selected)
            else:
                st.info("Сначала настройте и сохраните новую таблицу.")
    else:
        _render_settings_form(
            selected_id, selected, item_type, section_id, active_items
        )

    if selected_id:
        st.divider()
        _render_delete_action(selected_id)


def _render_archive(archived_items: list[dict], sections: list[dict]) -> None:
    if not archived_items:
        st.info("Архив материалов пуст.")
        return

    section_by_id = {section["id"]: section for section in sections}
    item_by_id = {item["id"]: item for item in archived_items}
    selected_id = st.selectbox(
        "Архивный материал",
        list(item_by_id),
        format_func=lambda value: _item_label(item_by_id[value], section_by_id),
        key="archived_material_select",
    )
    if st.button("Восстановить материал", type="primary"):
        try:
            restore_content_item(selected_id)
        except (OSError, RuntimeError, sqlite3.Error) as error:
            st.error(f"Не удалось восстановить материал: {error}")
        else:
            st.success("Материал восстановлен. Включите публикацию при необходимости.")
            st.rerun()


def render_materials_admin() -> None:
    """Показывает единый редактор FAQ, статей, инструкций и таблиц."""
    sections = [
        section for section in load_sections() if not section.get("is_archived")
    ]
    if not sections:
        st.title("🗂️ Материалы")
        st.info("Сначала создайте хотя бы один раздел.")
        return

    items = load_content_items(include_archived=True)
    active_items = [item for item in items if not item["is_archived"]]
    archived_items = [item for item in items if item["is_archived"]]

    st.title("🗂️ Материалы")
    st.caption("Выберите раздел, затем создайте новый или откройте существующий материал.")

    attention_items = [
        item
        for item in active_items
        if material_relevance(item) in {"review", "overdue"}
    ]
    published_col, draft_col, review_col = st.columns(3)
    published_col.metric(
        "Опубликовано", sum(item["is_visible"] for item in active_items)
    )
    draft_col.metric(
        "Черновики",
        sum(material_relevance(item) == "draft" for item in active_items),
    )
    review_col.metric("Требуют проверки", len(attention_items))

    if attention_items:
        section_by_id = {section["id"]: section for section in sections}
        with st.expander(f"⚠️ Требуют проверки · {len(attention_items)}"):
            for item in attention_items:
                section_title = section_by_id.get(
                    item.get("section_id"), {}
                ).get("title", "Без раздела")
                due = str(item.get("review_due_at", "")).strip()
                due_text = f" — срок проверки {due}" if due else ""
                st.markdown(f"- **{item['title']}** · {section_title}{due_text}")

    edit_tab, archive_tab = st.tabs(["Материалы", "Архив"])
    with edit_tab:
        _render_active_editor(sections, active_items)
    with archive_tab:
        _render_archive(archived_items, sections)
