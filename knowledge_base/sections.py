"""Административное управление разделами и ветками базы знаний."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import streamlit as st

from storage import (
    CONTENT_ITEM_TYPES,
    archive_branch,
    archive_section,
    load_branches,
    load_sections,
    restore_branch,
    restore_section,
    save_branch,
    save_section,
)


BRANCH_TYPE_LABELS = {
    "instruction": "📄 Инструкции",
    "template": "📝 Шаблоны",
    "faq": "❓ FAQ",
    "checklist": "✅ Чек-листы",
    "table": "📊 Таблицы и матрицы",
    "article": "📚 Справочные материалы",
}


def _section_label(section: dict) -> str:
    label = f"{section.get('icon', '')} {section.get('title', '')}".strip()
    if not section.get("is_visible", True):
        label += " · скрыт"
    return label


def _branch_label(branch: dict) -> str:
    icon_label = BRANCH_TYPE_LABELS.get(
        str(branch.get("branch_kind", "")), "📁 Ветка"
    )
    icon = icon_label.split(maxsplit=1)[0]
    label = f"{icon} {branch.get('title', '')}".strip()
    if not branch.get("is_visible", True):
        label += " · скрыта"
    return label


def _render_sections_editor(sections: list[dict]) -> None:
    active = [section for section in sections if not section["is_archived"]]
    section_by_id = {section["id"]: section for section in active}
    selected_id = st.selectbox(
        "Выберите раздел",
        [""] + list(section_by_id),
        format_func=lambda value: (
            "＋ Новый раздел" if not value else _section_label(section_by_id[value])
        ),
        key="section_admin_select",
    )
    selected = section_by_id.get(selected_id, {})

    with st.form(f"section_form_{selected_id or 'new'}"):
        title = st.text_input(
            "Название",
            value=str(selected.get("title", "")),
            placeholder="Например: Работа с маркировкой",
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
            placeholder="Какие рабочие задачи относятся к разделу",
        )
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
            and not section["is_archived"]
            for section in sections
        )
        if not clean_title:
            st.error("Укажите название раздела.")
        elif duplicate:
            st.error("Раздел с таким названием уже существует.")
        else:
            try:
                save_section(
                    {
                        "id": selected_id or uuid4().hex,
                        "title": clean_title,
                        "icon": icon.strip() or "📁",
                        "description": description.strip(),
                        "page_kind": "custom",
                        "position": int(position),
                        "is_visible": bool(is_visible),
                        "is_archived": False,
                    }
                )
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
                st.error(f"Не удалось сохранить раздел: {error}")
            else:
                st.success("Раздел сохранён.")
                st.rerun()

    if selected_id:
        st.divider()
        st.caption(
            "Удаление переносит раздел и всё его содержимое из навигации в архив. "
            "Данные можно восстановить."
        )
        confirmed = st.checkbox(
            "Подтверждаю удаление раздела из навигации",
            key=f"archive_section_confirm_{selected_id}",
        )
        if st.button(
            "Удалить раздел",
            disabled=not confirmed,
            key=f"archive_section_button_{selected_id}",
        ):
            try:
                archive_section(selected_id)
            except (OSError, RuntimeError, sqlite3.Error) as error:
                st.error(f"Не удалось удалить раздел: {error}")
            else:
                st.success("Раздел перемещён в архив.")
                st.rerun()


def _render_branches_editor(sections: list[dict], branches: list[dict]) -> None:
    active_sections = [
        section for section in sections if not section["is_archived"]
    ]
    if not active_sections:
        st.info("Сначала создайте раздел.")
        return

    section_by_id = {section["id"]: section for section in active_sections}
    section_id = st.selectbox(
        "1. Выберите раздел",
        list(section_by_id),
        format_func=lambda value: _section_label(section_by_id[value]),
        key="branch_admin_section",
    )
    section_branches = [
        branch
        for branch in branches
        if branch["section_id"] == section_id and not branch["is_archived"]
    ]
    branch_by_id = {branch["id"]: branch for branch in section_branches}
    selected_id = st.selectbox(
        "2. Выберите ветку",
        [""] + list(branch_by_id),
        format_func=lambda value: (
            "＋ Новая ветка" if not value else _branch_label(branch_by_id[value])
        ),
        key=f"branch_admin_select_{section_id}",
    )
    selected = branch_by_id.get(selected_id, {})

    with st.form(f"branch_form_{selected_id or 'new'}"):
        title = st.text_input(
            "Название ветки",
            value=str(selected.get("title", "")),
            placeholder="Например: Инструкции",
        )
        kind_options = list(CONTENT_ITEM_TYPES)
        current_kind = str(selected.get("branch_kind", "instruction"))
        if current_kind not in kind_options:
            current_kind = "instruction"
        branch_kind = st.selectbox(
            "Тип материалов",
            kind_options,
            index=kind_options.index(current_kind),
            format_func=lambda value: BRANCH_TYPE_LABELS[value],
            help="Ветка принимает материалы только выбранного типа.",
        )
        description = st.text_area(
            "Описание ветки",
            value=str(selected.get("description", "")),
            height=100,
            placeholder="Какие материалы сотрудник найдёт здесь",
        )
        position = st.number_input(
            "Порядок внутри раздела",
            min_value=0,
            step=10,
            value=int(selected.get("position", (len(section_branches) + 1) * 10)),
        )
        is_visible = st.checkbox(
            "Показывать сотрудникам",
            value=bool(selected.get("is_visible", True)),
            key=f"branch_visible_{selected_id or 'new'}",
        )
        submitted = st.form_submit_button("Сохранить ветку", type="primary")

    if submitted:
        try:
            save_branch(
                {
                    "id": selected_id or uuid4().hex,
                    "section_id": section_id,
                    "title": title.strip(),
                    "branch_kind": branch_kind,
                    "description": description.strip(),
                    "position": int(position),
                    "is_visible": bool(is_visible),
                    "is_archived": False,
                }
            )
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            st.error(f"Не удалось сохранить ветку: {error}")
        else:
            st.success("Ветка сохранена.")
            st.rerun()

    if selected_id:
        st.divider()
        st.caption(
            "Удалить можно только пустую ветку. Сначала перенесите её материалы "
            "в другую ветку или оставьте без ветки."
        )
        confirmed = st.checkbox(
            "Подтверждаю удаление ветки",
            key=f"archive_branch_confirm_{selected_id}",
        )
        if st.button(
            "Удалить ветку",
            disabled=not confirmed,
            key=f"archive_branch_button_{selected_id}",
        ):
            try:
                archive_branch(selected_id)
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
                st.error(f"Не удалось удалить ветку: {error}")
            else:
                st.success("Ветка перемещена в архив.")
                st.rerun()


def _render_sections_archive(sections: list[dict]) -> None:
    archived = [section for section in sections if section["is_archived"]]
    if not archived:
        st.info("Архив разделов пуст.")
        return
    by_id = {section["id"]: section for section in archived}
    selected_id = st.selectbox(
        "Архивный раздел",
        list(by_id),
        format_func=lambda value: _section_label(by_id[value]),
        key="archived_section_select",
    )
    if st.button("Восстановить раздел", type="primary"):
        try:
            restore_section(selected_id)
        except (OSError, RuntimeError, sqlite3.Error) as error:
            st.error(f"Не удалось восстановить раздел: {error}")
        else:
            st.success("Раздел восстановлен. При необходимости включите видимость.")
            st.rerun()


def _render_branches_archive(
    branches: list[dict], sections: list[dict]
) -> None:
    archived = [branch for branch in branches if branch["is_archived"]]
    if not archived:
        st.info("Архив веток пуст.")
        return
    section_by_id = {section["id"]: section for section in sections}
    by_id = {branch["id"]: branch for branch in archived}
    selected_id = st.selectbox(
        "Архивная ветка",
        list(by_id),
        format_func=lambda value: (
            f"{section_by_id.get(by_id[value]['section_id'], {}).get('title', 'Без раздела')}"
            f" → {_branch_label(by_id[value])}"
        ),
        key="archived_branch_select",
    )
    if st.button("Восстановить ветку", type="primary"):
        try:
            restore_branch(selected_id)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            st.error(f"Не удалось восстановить ветку: {error}")
        else:
            st.success("Ветка восстановлена. При необходимости включите видимость.")
            st.rerun()


def render_sections_admin() -> None:
    """Показывает конструктор двухуровневой структуры базы знаний."""
    sections = load_sections(include_archived=True)
    branches = load_branches(include_archived=True)
    active_sections = [section for section in sections if not section["is_archived"]]
    active_branches = [branch for branch in branches if not branch["is_archived"]]

    st.title("⚙️ Структура базы знаний")
    st.caption(
        "Раздел — рабочее направление в боковой панели. Ветка — тип материалов "
        "внутри раздела. Более глубокая вложенность намеренно не используется."
    )
    section_col, branch_col, visible_col = st.columns(3)
    section_col.metric("Разделов", len(active_sections))
    branch_col.metric("Веток", len(active_branches))
    visible_col.metric(
        "В навигации", sum(section["is_visible"] for section in active_sections)
    )

    section_tab, branch_tab, section_archive_tab, branch_archive_tab = st.tabs(
        ["Разделы", "Ветки", "Архив разделов", "Архив веток"]
    )
    with section_tab:
        _render_sections_editor(sections)
    with branch_tab:
        _render_branches_editor(sections, branches)
    with section_archive_tab:
        _render_sections_archive(sections)
    with branch_archive_tab:
        _render_branches_archive(branches, sections)
