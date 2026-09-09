import hmac
import os
from functools import partial

import pandas as pd
import streamlit as st

from knowledge_base.sections import render_sections_admin
from knowledge_base.materials import (
    filter_content_items,
    render_materials_admin,
    table_column_width,
)
from storage import (
    load_content_items,
    load_sections,
)

# Настройка конфигурации страницы
st.set_page_config(page_title="База знаний менеджера", layout="wide")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
DYNAMIC_TABLE_ROW_HEIGHT = 80
DYNAMIC_TABLE_VISIBLE_ROWS = 15


def passwords_match(candidate, expected):
    """Безопасно сравнивает пароли, включая кириллицу и другие Unicode-символы."""
    return hmac.compare_digest(
        candidate.encode("utf-8"),
        expected.encode("utf-8"),
    )


# ===== 3. ВХОД АДМИНИСТРАТОРА =====
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

with st.sidebar:
    if not ADMIN_PASSWORD:
        st.warning("Режим администратора недоступен: переменная ADMIN_PASSWORD не настроена.")
    elif not st.session_state.is_admin:
        st.header("Вход администратора")
        p = st.text_input("Пароль", type="password", key="admin_password")
        if st.button("Войти", width="stretch"):
            if passwords_match(p, ADMIN_PASSWORD):
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("Неверный пароль")
    else:
        st.success("Режим администратора включен")
        if st.button("Выйти", width="stretch"):
            st.session_state.is_admin = False
            st.rerun()

# ===== 4. ОБЩИЙ СТИЛЬ СТРАНИЦ =====
st.markdown(
    """
    <style>
    :root {
        --kb-accent: #1f6f78;
        --kb-accent-soft: #e8f3f3;
        --kb-border: #d9e2e3;
        --kb-muted: #607174;
    }

    [data-testid="stTextInput"] {
        margin-bottom: 0.75rem;
    }

    [data-testid="stTextInput"] input:focus {
        border-color: var(--kb-accent);
        box-shadow: 0 0 0 1px var(--kb-accent);
    }

    button[data-baseweb="tab"] {
        color: var(--kb-muted);
        font-weight: 600;
    }

    button[data-baseweb="tab"][aria-selected="true"] {
        color: var(--kb-accent);
    }

    [data-testid="stExpander"] {
        border: 1px solid var(--kb-border);
        border-radius: 6px;
        margin-bottom: 0.65rem;
    }

    [data-testid="stExpander"] summary:hover {
        background: var(--kb-accent-soft);
    }

    [data-testid="stCaptionContainer"] {
        color: var(--kb-muted);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def clear_search():
    """Очищает поле поиска"""
    st.session_state.search_input_key = ""

def render_section_header(section):
    """Показывает заголовок раздела и единое поле поиска."""
    icon = str(section.get("icon", "")).strip()
    title = str(section.get("title", "")).strip()
    st.title(f"{icon} {title}".strip())
    if str(section.get("description", "")).strip():
        st.caption(str(section["description"]))

    col_search, col_clear = st.columns([6, 1])
    with col_search:
        query = st.text_input(
            "Поиск в разделе",
            placeholder="Например: МЧД, 007/2011, ДС 353...",
            key="search_input_key",
        )
    with col_clear:
        st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
        st.button("Сбросить", width="stretch", on_click=clear_search)
    return query


def render_section_materials(section_id, search_query):
    """Показывает опубликованные универсальные материалы выбранного раздела."""
    items = [
        item
        for item in load_content_items(section_id=section_id)
        if item.get("is_visible", True)
    ]
    filtered_items = filter_content_items(items, search_query)
    if not filtered_items:
        return False

    st.subheader("Материалы раздела")
    type_icons = {
        "faq": "❓",
        "article": "📄",
        "instruction": "🧭",
        "table": "📊",
    }
    for item in filtered_items:
        icon = type_icons.get(item.get("item_type"), "📄")
        with st.expander(
            f"{icon} {item['title']}",
            expanded=bool(search_query.strip()),
        ):
            if str(item.get("summary", "")).strip():
                st.info(str(item["summary"]))

            if item.get("item_type") == "table":
                if str(item.get("body", "")).strip():
                    st.markdown(str(item["body"]))
                columns = item.get("table_columns", [])
                display_rows = []
                for row in item.get("table_rows", []):
                    display_row = {}
                    for column in columns:
                        value = str(row.get(column["id"], ""))
                        if column.get("type") == "checkbox":
                            value = (
                                "Да"
                                if value.casefold() in {"1", "true", "yes", "да"}
                                else "Нет"
                            )
                        display_row[column["label"]] = value
                    display_rows.append(display_row)
                frame = pd.DataFrame(display_rows).reindex(
                    columns=[column["label"] for column in columns]
                )
                if frame.empty:
                    st.caption("Таблица пока не заполнена.")
                else:
                    table_height = (
                        "content"
                        if len(frame) <= DYNAMIC_TABLE_VISIBLE_ROWS
                        else (
                            DYNAMIC_TABLE_VISIBLE_ROWS
                            * DYNAMIC_TABLE_ROW_HEIGHT
                            + 40
                        )
                    )
                    table_config = {
                        column["label"]: st.column_config.TextColumn(
                            column["label"],
                            help=column["label"],
                            width=(
                                "small"
                                if column.get("type") == "checkbox"
                                else table_column_width(len(columns))
                            ),
                        )
                        for column in columns
                    }
                    st.dataframe(
                        frame.fillna(""),
                        row_height=DYNAMIC_TABLE_ROW_HEIGHT,
                        width="stretch",
                        height=table_height,
                        hide_index=True,
                        column_config=table_config,
                    )
            elif str(item.get("body", "")).strip():
                st.markdown(str(item["body"]))

            metadata = []
            if str(item.get("updated_at", "")).strip():
                metadata.append(f"Обновлено: {item['updated_at']}")
            if str(item.get("source", "")).strip():
                metadata.append(f"Источник: {item['source']}")
            if metadata:
                st.caption(" | ".join(metadata))

    return True

def render_home_page():
    """Главная страница с коротким объяснением новой навигации."""
    sections = [
        section
        for section in load_sections()
        if section.get("is_visible", True)
    ]
    published_items = [
        item for item in load_content_items() if item.get("is_visible", True)
    ]
    st.title("📚 Единая база знаний")
    st.write(
        "Выберите рабочий раздел в боковой панели. Внутри каждого раздела "
        "доступен поиск по его материалам."
    )

    faq_col, tables_col, instructions_col = st.columns(3)
    faq_col.metric(
        "Статьи и FAQ",
        sum(
            item.get("item_type") in {"article", "faq"}
            for item in published_items
        ),
    )
    tables_col.metric(
        "Строки в таблицах",
        sum(
            len(item.get("table_rows", []))
            for item in published_items
            if item.get("item_type") == "table"
        ),
    )
    instructions_col.metric(
        "Инструкции",
        sum(
            item.get("item_type") == "instruction"
            for item in published_items
        ),
    )

    st.subheader("Разделы")
    if not sections:
        st.info("Пока нет опубликованных разделов.")
        return
    for section in sections:
        icon = str(section.get("icon", "")).strip()
        title = str(section.get("title", "")).strip()
        st.markdown(f"### {icon} {title}".strip())
        if str(section.get("description", "")).strip():
            st.caption(str(section["description"]))


def render_custom_section(section):
    """Показывает материалы пользовательского раздела."""
    search_query = render_section_header(section)
    if not render_section_materials(section["id"], search_query):
        if search_query.strip():
            st.info("По вашему запросу ничего не найдено.")
        else:
            st.info("В этом разделе пока нет опубликованных материалов.")


def render_section(section):
    """Показывает универсальные материалы выбранного раздела."""
    render_custom_section(section)


visible_sections = [
    section
    for section in load_sections()
    if section.get("is_visible", True)
]
section_pages = [
    st.Page(
        partial(render_section, section),
        title=(
            f"{str(section.get('icon', '')).strip()} "
            f"{str(section.get('title', '')).strip()}"
        ).strip(),
        url_path=f"section-{section['id'].replace('_', '-')}",
    )
    for section in visible_sections
]

navigation = {
    "База знаний": [
        st.Page(render_home_page, title="Главная", icon=":material/home:"),
        *section_pages,
    ]
}
if st.session_state.is_admin:
    navigation["Администрирование"] = [
        st.Page(
            render_materials_admin,
            title="Управление материалами",
            icon=":material/library_books:",
            url_path="admin-materials",
        ),
        st.Page(
            render_sections_admin,
            title="Управление разделами",
            icon=":material/settings:",
            url_path="admin-sections",
        )
    ]

current_page = st.navigation(navigation, position="sidebar")
current_page.run()

