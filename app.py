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
st.set_page_config(
    page_title="Единая база знаний",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
    st.markdown("### 📚 База знаний")
    st.caption("Рабочая информация для сотрудников")
    if not ADMIN_PASSWORD:
        st.warning("Режим администратора недоступен: переменная ADMIN_PASSWORD не настроена.")
    elif not st.session_state.is_admin:
        with st.expander("Вход администратора"):
            p = st.text_input("Пароль", type="password", key="admin_password")
            if st.button("Войти", width="stretch"):
                if passwords_match(p, ADMIN_PASSWORD):
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Неверный пароль")
    else:
        with st.expander("Администратор", expanded=False):
            st.success("Режим редактирования включён")
            if st.button("Выйти", width="stretch"):
                st.session_state.is_admin = False
                st.rerun()

# ===== 4. ОБЩИЙ СТИЛЬ СТРАНИЦ =====
st.markdown(
    """
    <style>
    :root {
        --kb-accent: #176b73;
        --kb-accent-soft: #edf7f6;
        --kb-border: #d9e5e4;
        --kb-muted: #5f7072;
    }

    .stMainBlockContainer {
        max-width: 1500px;
        padding-top: 2.2rem;
        padding-bottom: 4rem;
    }

    [data-testid="stSidebar"] {
        border-right: 1px solid var(--kb-border);
    }

    [data-testid="stSidebarNav"] a[aria-current="page"] {
        background: var(--kb-accent-soft);
        border-radius: 8px;
        color: var(--kb-accent);
        font-weight: 650;
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
        border-radius: 10px;
        margin-bottom: 0.75rem;
        overflow: hidden;
    }

    [data-testid="stExpander"] summary:hover {
        background: var(--kb-accent-soft);
    }

    [data-testid="stCaptionContainer"] {
        color: var(--kb-muted);
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--kb-border);
        border-radius: 12px;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid var(--kb-border);
        border-radius: 8px;
        overflow: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

SECTION_PAGE_BY_ID = {}


def clear_search(key):
    """Очищает указанное поле поиска."""
    st.session_state[key] = ""

def render_section_header(section):
    """Показывает заголовок раздела и единое поле поиска."""
    icon = str(section.get("icon", "")).strip()
    title = str(section.get("title", "")).strip()
    st.title(f"{icon} {title}".strip())
    if str(section.get("description", "")).strip():
        st.caption(str(section["description"]))

    search_key = f"section_search_{section['id']}"
    col_search, col_clear = st.columns([7, 1])
    with col_search:
        query = st.text_input(
            "Поиск в разделе",
            placeholder="Например: МЧД, 007/2011, ДС 353...",
            key=search_key,
        )
    with col_clear:
        st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
        st.button(
            "Сбросить",
            width="stretch",
            on_click=clear_search,
            args=(search_key,),
        )
    return query


def render_content_items(items, search_query="", section_titles=None):
    """Показывает список материалов в одинаковом виде на всех страницах."""
    type_icons = {
        "faq": "❓",
        "article": "📄",
        "instruction": "🧭",
        "table": "📊",
    }
    type_labels = {
        "faq": "FAQ / рабочая ситуация",
        "article": "Справочная статья",
        "instruction": "Инструкция",
        "table": "Таблица",
    }
    for item in items:
        icon = type_icons.get(item.get("item_type"), "📄")
        title = f"{icon} {item['title']}"
        if section_titles:
            section_title = section_titles.get(item.get("section_id"), "")
            if section_title:
                title = f"{title} · {section_title}"
        with st.expander(
            title,
            expanded=bool(search_query.strip()),
        ):
            st.caption(type_labels.get(item.get("item_type"), "Материал"))
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


def render_section_materials(section_id, search_query):
    """Показывает опубликованные материалы выбранного раздела."""
    items = [
        item
        for item in load_content_items(section_id=section_id)
        if item.get("is_visible", True)
    ]
    filtered_items = filter_content_items(items, search_query)
    if not filtered_items:
        return False

    result_label = (
        f"Найдено: {len(filtered_items)}"
        if search_query.strip()
        else f"Материалов: {len(filtered_items)}"
    )
    st.caption(result_label)
    render_content_items(filtered_items, search_query)
    return True


def render_home_page():
    """Главная страница с поиском и рабочими направлениями."""
    sections = [
        section
        for section in load_sections()
        if section.get("is_visible", True)
    ]
    published_items = [
        item for item in load_content_items() if item.get("is_visible", True)
    ]
    section_titles = {section["id"]: section["title"] for section in sections}

    st.title("Единая база знаний")
    st.write(
        "Найдите готовый ответ или откройте нужное рабочее направление."
    )

    home_query = st.text_input(
        "Поиск по всей базе",
        placeholder="Введите документ, номер регламента, продукцию или рабочую ситуацию",
        key="home_search_query",
    )
    if home_query.strip():
        results = filter_content_items(published_items, home_query)
        st.subheader(f"Результаты поиска · {len(results)}")
        if results:
            render_content_items(results, home_query, section_titles)
        else:
            st.info(
                "Ничего не найдено. Попробуйте номер без лишних слов или другой термин."
            )
        return

    st.subheader("Рабочие направления")
    if not sections:
        st.info("Пока нет опубликованных разделов.")
        return
    columns = st.columns(2)
    for index, section in enumerate(sections):
        section_items = [
            item for item in published_items if item.get("section_id") == section["id"]
        ]
        with columns[index % 2]:
            with st.container(border=True):
                icon = str(section.get("icon", "")).strip()
                title = str(section.get("title", "")).strip()
                st.markdown(f"### {icon} {title}".strip())
                if str(section.get("description", "")).strip():
                    st.caption(str(section["description"]))
                st.caption(f"Материалов: {len(section_items)}")
                page = SECTION_PAGE_BY_ID.get(section["id"])
                if page is not None:
                    st.page_link(
                        page,
                        label="Открыть раздел",
                        icon=":material/arrow_forward:",
                    )


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
SECTION_PAGE_BY_ID.update(
    {
        section["id"]: page
        for section, page in zip(visible_sections, section_pages, strict=True)
    }
)

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
            title="Материалы",
            icon=":material/library_books:",
            url_path="admin-materials",
        ),
        st.Page(
            render_sections_admin,
            title="Разделы и навигация",
            icon=":material/settings:",
            url_path="admin-sections",
        )
    ]

current_page = st.navigation(navigation, position="sidebar")
current_page.run()

