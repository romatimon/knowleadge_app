"""Административное управление разделами навигации."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import streamlit as st

from storage import archive_section, load_sections, restore_section, save_section


SECTION_KIND_LABELS = {
    "faq": "FAQ и рабочие ситуации",
    "instructions": "Инструкции и алгоритмы",
    "reference_tables": "Матрицы, нормы и сроки",
    "reference": "Справочник и нормативная база",
    "templates": "Шаблоны и чек-листы",
    "custom": "Универсальный раздел",
}

SECTION_KIND_HINTS = {
    "faq": "FAQ и справочные статьи",
    "instructions": "только пошаговые инструкции",
    "reference_tables": "только таблицы и памятки к ним",
    "reference": "справочные статьи и таблицы",
    "templates": "шаблоны, чек-листы и инструкции по их заполнению",
    "custom": "любые типы материалов",
}


def _section_label(section: dict) -> str:
    icon = str(section.get("icon", "")).strip()
    title = str(section.get("title", "")).strip()
    label = f"{icon} {title}".strip()
    if not section.get("is_visible", True):
        label += " · скрыт"
    return label


def render_sections_admin() -> None:
    """Позволяет создавать, изменять, архивировать и восстанавливать разделы."""
    sections = load_sections(include_archived=True)
    active = [section for section in sections if not section["is_archived"]]
    archived = [section for section in sections if section["is_archived"]]

    st.title("⚙️ Управление разделами")
    st.caption(
        "Здесь настраивается боковая навигация сотрудников. Укажите назначение "
        "раздела — редактор предложит только подходящие типы материалов."
    )

    visible_count = sum(section["is_visible"] for section in active)
    total_col, visible_col, archived_col = st.columns(3)
    total_col.metric("Активные", len(active))
    visible_col.metric("В навигации", visible_count)
    archived_col.metric("В архиве", len(archived))

    edit_tab, archive_tab = st.tabs(["Разделы", "Архив"])

    with edit_tab:
        section_by_id = {section["id"]: section for section in active}
        options = [""] + list(section_by_id)
        selected_id = st.selectbox(
            "Выберите раздел",
            options,
            format_func=lambda value: (
                "＋ Новый раздел"
                if not value
                else _section_label(section_by_id[value])
            ),
            key="section_admin_select",
        )
        selected = section_by_id.get(selected_id, {})

        with st.form(f"section_admin_form_{selected_id or 'new'}"):
            title = st.text_input(
                "Название",
                value=str(selected.get("title", "")),
                placeholder="Например: Отбор образцов",
            )
            icon = st.text_input(
                "Значок",
                value=str(selected.get("icon", "📁")),
                max_chars=8,
                help="Можно указать один эмодзи.",
            )
            description = st.text_area(
                "Краткое описание",
                value=str(selected.get("description", "")),
                height=100,
                placeholder="Какие материалы сотрудник найдёт в этом разделе",
            )
            kind_options = list(SECTION_KIND_LABELS)
            selected_kind = str(selected.get("page_kind", "custom"))
            if selected_kind not in kind_options:
                kind_options.append(selected_kind)
            page_kind = st.selectbox(
                "Назначение раздела",
                kind_options,
                index=kind_options.index(selected_kind),
                format_func=lambda value: SECTION_KIND_LABELS.get(
                    value, "Пользовательское назначение"
                ),
                help=(
                    "Назначение определяет, какие материалы можно добавлять. "
                    "Его нельзя сменить на несовместимое с уже созданными материалами."
                ),
            )
            kind_hint = SECTION_KIND_HINTS.get(page_kind, "любых материалов")
            st.caption(f"Подходит для: {kind_hint}.")
            position = st.number_input(
                "Порядок в боковой панели",
                min_value=0,
                step=10,
                value=int(selected.get("position", (len(active) + 1) * 10)),
            )
            is_visible = st.checkbox(
                "Показывать сотрудникам",
                value=bool(selected.get("is_visible", True)),
            )
            submitted = st.form_submit_button("Сохранить раздел", type="primary")

        if submitted:
            clean_title = title.strip()
            duplicate = any(
                section["id"] != selected_id
                and section["title"].strip().casefold() == clean_title.casefold()
                for section in sections
            )
            if not clean_title:
                st.error("Укажите название раздела.")
            elif duplicate:
                st.error("Раздел с таким названием уже существует.")
            else:
                values = {
                    "id": selected_id or uuid4().hex,
                    "title": clean_title,
                    "icon": icon.strip(),
                    "description": description.strip(),
                    "page_kind": page_kind,
                    "position": int(position),
                    "is_visible": bool(is_visible),
                    "is_archived": False,
                }
                try:
                    save_section(values)
                except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
                    st.error(f"Не удалось сохранить раздел: {error}")
                else:
                    st.success("Раздел сохранён.")
                    st.rerun()

        if selected_id:
            confirm_archive = st.checkbox(
                "Подтверждаю удаление раздела из боковой панели",
                key=f"archive_section_confirm_{selected_id}",
            )
            if st.button(
                "Удалить раздел",
                disabled=not confirm_archive,
                key=f"archive_section_button_{selected_id}",
            ):
                try:
                    archive_section(selected_id)
                except (OSError, RuntimeError, sqlite3.Error) as error:
                    st.error(f"Не удалось удалить раздел: {error}")
                else:
                    st.success("Раздел перемещён в архив.")
                    st.rerun()

    with archive_tab:
        if not archived:
            st.info("Архив пуст.")
        else:
            archived_by_id = {section["id"]: section for section in archived}
            archived_id = st.selectbox(
                "Архивный раздел",
                list(archived_by_id),
                format_func=lambda value: _section_label(archived_by_id[value]),
                key="archived_section_select",
            )
            archived_section = archived_by_id[archived_id]
            if archived_section.get("description"):
                st.caption(str(archived_section["description"]))
            if st.button("Восстановить раздел", type="primary"):
                try:
                    restore_section(archived_id)
                except (OSError, RuntimeError, sqlite3.Error) as error:
                    st.error(f"Не удалось восстановить раздел: {error}")
                else:
                    st.success("Раздел восстановлен. Включите его видимость при необходимости.")
                    st.rerun()
