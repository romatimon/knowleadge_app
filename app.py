import hmac
import html
import os
import re
from datetime import UTC, datetime
from functools import partial

import pandas as pd
import streamlit as st

from knowledge_base.sections import render_sections_admin
from knowledge_base.materials import render_materials_admin
from storage import (
    TABLE_KEYS,
    load_all_data,
    load_content_items,
    load_sections,
    save_all_data,
)

# Настройка конфигурации страницы
st.set_page_config(page_title="База знаний менеджера", layout="wide")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
MATERIAL_METADATA = {
    "faq": ["Алгоритм", "Поисковые фразы", "Дата обновления", "Источник"],
    "texts_table": [
        "Краткое описание",
        "Поисковые фразы",
        "Дата обновления",
        "Источник",
    ],
}

INSTRUCTION_TEMPLATE = """## Назначение

Кратко опишите, что сотрудник сделает с помощью инструкции.

## Когда применять

- Укажите условия применения.

## Что подготовить

- Перечислите документы и сведения.

## Алгоритм

1. Выполнить первое действие.
2. Выполнить следующее действие.

## Особые случаи

- Если возникает исключение, укажите отдельное действие.

## Результат

Опишите, как понять, что работа завершена.
"""


def passwords_match(candidate, expected):
    """Безопасно сравнивает пароли, включая кириллицу и другие Unicode-символы."""
    return hmac.compare_digest(
        candidate.encode("utf-8"),
        expected.encode("utf-8"),
    )


def normalize(text):
    """Нормализация текста для поиска"""
    return (
        str(text)
        .lower()
        .replace("/", " ")
        .replace("\\", " ")
        .replace("-", " ")
        .replace("№", "")
        .replace(",", " ")
        .replace(".", " ")
        .replace("(", " ")
        .replace(")", " ")
    )


def search_df(df, query):
    if df.empty or not query.strip():
        return df

    search_terms = normalize(query).split()
    if not search_terms:
        return df

    normalized_df = (
        df.fillna("")
        .astype(str)
        .apply(lambda col: col.map(normalize))
    )
    mask = pd.Series(True, index=df.index)
    for term in search_terms:
        term_matches = normalized_df.apply(
            lambda col, term=term: col.str.contains(term, regex=False)
        ).any(axis=1)
        mask &= term_matches

    return df[mask]

def ensure_material_columns(frame, table_name):
    """Добавляет служебные поля, не изменяя оригинальный текст материала."""
    for column in MATERIAL_METADATA.get(table_name, []):
        if column not in frame.columns:
            frame[column] = ""
    return frame

def highlight_text(text, query):
    """Подсвечивает отдельные слова запроса в безопасном HTML."""
    safe_text = html.escape(str(text))
    if not query.strip():
        return safe_text

    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query, flags=re.UNICODE)))
    if not terms:
        return safe_text
    pattern = "|".join(
        re.escape(html.escape(term))
        for term in sorted(terms, key=len, reverse=True)
    )
    compiled = re.compile(f"({pattern})", re.IGNORECASE)
    return compiled.sub(r"<mark style='background-color: #ffeb3b; color: black; padding: 2px 4px; border-radius: 3px;'>\1</mark>", safe_text)

# ===== 2. УНИВЕРСАЛЬНАЯ ИНИЦИАЛИЗАЦИЯ СЕССИИ =====
if "db" not in st.session_state or not st.session_state.db:
    raw = load_all_data()
    if not isinstance(raw, dict):
        raw = {}
        
    st.session_state.db = {}
    for key in TABLE_KEYS:
        saved_data = raw.get(key)
        if saved_data and len(saved_data) > 0:
            frame = pd.DataFrame(saved_data)
            if key == "texts_table":
                frame = frame.drop(columns=["Категория"], errors="ignore")
            frame = ensure_material_columns(frame, key)
            st.session_state.db[key] = frame
        else:
            if key == "texts_table":
                st.session_state.db[key] = pd.DataFrame(
                    columns=[
                        "Заголовок",
                        "Краткое описание",
                        "Текст инструкции",
                        "Поисковые фразы",
                        "Дата обновления",
                        "Источник",
                    ]
                )
            elif key == "faq":
                st.session_state.db[key] = pd.DataFrame(columns=[
                    "Тип",
                    "Вопрос / Ситуация",
                    "Ответ",
                    "Алгоритм",
                    "Важно",
                    "Поисковые фразы",
                    "Дата обновления",
                    "Источник",
                ])
            elif key == "contacts_experts":
                st.session_state.db[key] = pd.DataFrame(columns=[
                    "Группа (вид) продукции", 
                    "Лаборатории", 
                    "Срок проведения испытаний от даты заявки в ИЦ до даты выпуска протокола (раб. дней), не менее", 
                    "Минимальный срок проведения испытаний от даты заявки в ИЦ до даты выпуска протокола (раб. дней), не менее", 
                    "Срок переоформления протоколов (раб. дней)"
                ])
            elif key == "contacts_labs":
                st.session_state.db[key] = pd.DataFrame(columns=["Регламент", "Название", "ДС (серия)", "ДС (партия)", "СС (серия)", "СС (партия)"])
            elif key == "testing_battery":
                st.session_state.db[key] = pd.DataFrame(columns=["Наименование продукции",	"Ограничения при проведении испытаний",	"Максимальный срок проведения испытаний",	"Необходимое кол-во образцов"])
            elif key == "samples_nd":
                st.session_state.db[key] = pd.DataFrame(columns=[
                    "ТР ТС/ЕАЭС и/или сочетание",
                    "Группа (вид) продукции",
                    "Кол-во образцов (партия)",
                    "Кол-во образцов (серийный выпуск)",
                    "ГОСТ на отбор"
                ])

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
    terms = normalize(search_query).split()

    def matches(item):
        if not terms:
            return True
        table_text = " ".join(
            str(value)
            for row in item.get("table_rows", [])
            for value in row.values()
        )
        haystack = normalize(
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
                    table_text,
                ]
            )
        )
        return all(term in haystack for term in terms)

    filtered_items = [item for item in items if matches(item)]
    if not filtered_items:
        return False

    st.subheader("Материалы раздела")
    type_icons = {"article": "📄", "instruction": "🧭", "table": "📊"}
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
                    height = min(max(len(frame) * 42 + 40, 120), 700)
                    st.dataframe(
                        frame.fillna(""),
                        width="stretch",
                        height=height,
                        hide_index=True,
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

def save_everything():
    """Сохраняет все DataFrame в SQLite."""
    save_all_data(st.session_state.db)

# Универсальная функция отображения со встроенной картой автоматических сокращений
def render_table_view(db_key, filtered_df, row_height=80):
    SHORT_NAMES = {
        "Группа (вид) продукции": "Группа продукции",
        "Лаборатории": "Лаборатория",
        "Срок проведения испытаний от даты заявки в ИЦ до даты выпуска протокола (раб. дней), не менее": "Срок ИЦ (дней)",
        "Минимальный срок проведения испытаний от даты заявки в ИЦ до даты выпуска протокола (раб. дней), не менее": "Мин. срок ИЦ (дней)",
        "Срок переоформления протоколов (раб. дней)": "Переоформление (дней)",

        # Аккумуляторы
        "Наименование продукции": "Продукция",
        "Ограничения при проведении испытаний": "Ограничения",
        "Максимальный срок проведения испытаний": "Срок испытаний",
        "Необходимое кол-во образцов": "Образцы",
        "Важно": "Примечание",

        "Тип": "Тип",
        "Ответ": "Ответ"
    }
    
    config = {}
    for col in filtered_df.columns:
        display_label = SHORT_NAMES.get(col, col)
        config[col] = st.column_config.TextColumn(
            label=display_label,
            help=col,
            width="small",
            disabled=not st.session_state.is_admin
        )

    if st.session_state.is_admin:
        st.caption(
            "Редактируйте ячейки в таблице. Новые строки добавляются снизу, "
            "а выбранные строки удаляются через панель редактора."
        )
        editable_df = filtered_df.copy()
        for column in editable_df.columns:
            editable_df[column] = editable_df[column].astype("string").fillna("")
        with st.form(f"legacy_table_form_{db_key}"):
            edited_df = st.data_editor(
                editable_df,
                num_rows="dynamic",
                row_height=row_height,
                width="stretch",
                hide_index=True,
                column_config=config,
                key=f"editor_{db_key}",
            )
            save_table = st.form_submit_button(
                "Сохранить изменения", type="primary"
            )
        if save_table and not edited_df.equals(editable_df):
            original_df = st.session_state.db[db_key]
            if filtered_df.index.equals(original_df.index):
                st.session_state.db[db_key] = edited_df
            else:
                remaining_df = original_df.drop(
                    index=filtered_df.index,
                    errors="ignore"
                )
                st.session_state.db[db_key] = pd.concat(
                    [remaining_df, edited_df],
                    ignore_index=True
                )
            
            save_everything()
            st.toast("Изменения сохранены!", icon="💾")
            st.rerun()
        elif save_table:
            st.info("Изменений для сохранения нет.")
    else:
        calculated_height = (len(filtered_df) * row_height) + 40
        st.dataframe(filtered_df, row_height=row_height, width="stretch", height=calculated_height, hide_index=True, column_config=config)

def filter_table_by_column(filtered_df, column, label, key):
    """Добавляет простой фильтр к справочной таблице."""
    if filtered_df.empty or column not in filtered_df.columns:
        return filtered_df

    values = sorted(
        value for value in filtered_df[column].fillna("").astype(str).unique()
        if value.strip()
    )
    if not values:
        return filtered_df

    selected = st.selectbox(label, ["Все"] + values, key=key)
    if selected == "Все":
        return filtered_df
    return filtered_df[filtered_df[column].fillna("").astype(str) == selected]

def render_faq_editor():
    """Показывает форму добавления и редактирования FAQ для администратора."""
    faq_df = st.session_state.db["faq"]
    options = [None] + faq_df.index.tolist()
    selected_index = st.selectbox(
        "Материал для редактирования",
        options,
        format_func=lambda index: "Новый материал" if index is None else (
            f"{index + 1}. {str(faq_df.loc[index, 'Вопрос / Ситуация'])[:100]}"
        ),
        key="faq_material_select",
    )
    row = faq_df.loc[selected_index] if selected_index is not None else {}
    form_key = f"faq_material_form_{selected_index if selected_index is not None else 'new'}"

    with st.form(form_key):
        faq_type = st.selectbox(
            "Тип записи",
            ["Ситуация", "Справка", "Правило"],
            index=["Ситуация", "Справка", "Правило"].index(row.get("Тип", "Ситуация"))
            if row.get("Тип", "Ситуация") in ["Ситуация", "Справка", "Правило"] else 0,
        )
        question = st.text_input(
            "Вопрос / ситуация",
            value=str(row.get("Вопрос / Ситуация", "")),
        )
        answer = st.text_area(
            "Ответ",
            value=str(row.get("Ответ", "")),
            height=180,
        )
        algorithm = st.text_area(
            "Алгоритм, если есть",
            value=str(row.get("Алгоритм", "")),
            height=180,
        )
        important = st.text_area(
            "Важно",
            value=str(row.get("Важно", "")),
            height=120,
            placeholder="Ограничения, риски и исключения",
        )
        search_phrases = st.text_area(
            "Ключевые слова для поиска",
            value=str(row.get("Поисковые фразы", "")),
            height=80,
            placeholder="Синонимы и формулировки сотрудников через точку с запятой",
        )
        updated_at = st.date_input(
            "Дата обновления",
            value=datetime.fromisoformat(row["Дата обновления"]).date()
            if row.get("Дата обновления", "") else datetime.now(UTC).date(),
        )
        source = st.text_input(
            "Источник",
            value=str(row.get("Источник", "")),
            placeholder="Письмо Outlook, файл или ссылка",
        )
        submitted = st.form_submit_button("Сохранить материал", type="primary")

    if submitted:
        if not question.strip() or not answer.strip():
            st.error("Заполните вопрос / ситуацию и ответ.")
        else:
            values = {
                "Тип": faq_type,
                "Вопрос / Ситуация": question,
                "Ответ": answer,
                "Алгоритм": algorithm,
                "Важно": important,
                "Поисковые фразы": search_phrases,
                "Дата обновления": updated_at.isoformat(),
                "Источник": source,
            }
            if selected_index is None:
                st.session_state.db["faq"] = pd.concat(
                    [faq_df, pd.DataFrame([values])], ignore_index=True
                )
            else:
                for column, value in values.items():
                    st.session_state.db["faq"].loc[selected_index, column] = value
            save_everything()
            st.success("Материал сохранён.")
            st.rerun()

    if selected_index is not None:
        confirm_delete = st.checkbox("Подтверждаю удаление этого материала", key=f"faq_delete_{selected_index}")
        if st.button("Удалить материал", disabled=not confirm_delete, key=f"faq_delete_button_{selected_index}"):
            st.session_state.db["faq"] = faq_df.drop(index=selected_index)
            save_everything()
            st.rerun()

def render_text_editor():
    """Показывает форму добавления и редактирования инструкции для администратора."""
    texts_df = st.session_state.db["texts_table"]
    options = [None] + texts_df.index.tolist()
    selected_index = st.selectbox(
        "Материал для редактирования",
        options,
        format_func=lambda index: "Новый материал" if index is None else (
            f"{index + 1}. {str(texts_df.loc[index, 'Заголовок'])[:100]}"
        ),
        key="text_material_select",
    )
    row = texts_df.loc[selected_index] if selected_index is not None else {}
    form_key = f"text_material_form_{selected_index if selected_index is not None else 'new'}"

    with st.form(form_key):
        title = st.text_input("Заголовок", value=str(row.get("Заголовок", "")))
        summary = st.text_area(
            "Краткое описание",
            value=str(row.get("Краткое описание", "")),
            height=90,
            placeholder="Что сотрудник получит после выполнения инструкции",
        )
        instruction = st.text_area(
            "Текст инструкции",
            value=(
                str(row.get("Текст инструкции", ""))
                if selected_index is not None
                else INSTRUCTION_TEMPLATE
            ),
            height=480,
        )
        search_phrases = st.text_area(
            "Ключевые слова для поиска",
            value=str(row.get("Поисковые фразы", "")),
            height=80,
            placeholder="Синонимы, сокращения и альтернативные запросы",
        )
        updated_at = st.date_input(
            "Дата обновления",
            value=datetime.fromisoformat(row["Дата обновления"]).date()
            if row.get("Дата обновления", "") else datetime.now(UTC).date(),
        )
        source = st.text_input(
            "Источник",
            value=str(row.get("Источник", "")),
            placeholder="Письмо Outlook, файл или ссылка",
        )
        submitted = st.form_submit_button("Сохранить материал", type="primary")

    if submitted:
        if not title.strip() or not instruction.strip():
            st.error("Заполните заголовок и текст инструкции.")
        else:
            values = {
                "Заголовок": title,
                "Краткое описание": summary,
                "Текст инструкции": instruction,
                "Поисковые фразы": search_phrases,
                "Дата обновления": updated_at.isoformat(),
                "Источник": source,
            }
            if selected_index is None:
                st.session_state.db["texts_table"] = pd.concat(
                    [texts_df, pd.DataFrame([values])], ignore_index=True
                )
            else:
                for column, value in values.items():
                    st.session_state.db["texts_table"].loc[selected_index, column] = value
            save_everything()
            st.success("Материал сохранён.")
            st.rerun()

    if selected_index is not None:
        confirm_delete = st.checkbox("Подтверждаю удаление этой инструкции", key=f"text_delete_{selected_index}")
        if st.button("Удалить инструкцию", disabled=not confirm_delete, key=f"text_delete_button_{selected_index}"):
            st.session_state.db["texts_table"] = texts_df.drop(index=selected_index)
            save_everything()
            st.rerun()

# Страница типовых ситуаций
def render_faq_section(section):
    search_query = render_section_header(section)
    faq_filtered = search_df(st.session_state.db["faq"], search_query)

    if st.session_state.is_admin:
        st.info(
            "Выберите существующий материал для редактирования или создайте новый. "
            "Текст сохраняется без автоматических изменений."
        )
        render_faq_editor()

        st.caption("Предпросмотр для менеджеров")

    dynamic_matches = render_section_materials(section["id"], search_query)

    if faq_filtered.empty:
        if search_query.strip() and not dynamic_matches:
            st.info("По вашему запросу ничего не найдено.")

    else:

        sections = [
            ("🛠️ Рабочие ситуации", "Ситуация"),
            ("📖 Справочные вопросы", "Справка"),
            ("⚖️ Правила и исключения", "Правило"),
        ]

        for title, faq_type in sections:

            block = faq_filtered[
                faq_filtered["Тип"].fillna("") == faq_type
            ]

            if block.empty:
                continue

            st.markdown(f"## {title}")

            for _, row in block.iterrows():

                with st.expander(
                    str(row["Вопрос / Ситуация"]),
                    expanded=bool(search_query.strip())
                ):

                    st.caption("Ответ")

                    # Ответ с подсветкой найденного
                    st.markdown(
                        highlight_text(
                            str(row["Ответ"]),
                            search_query
                        ),
                        unsafe_allow_html=True
                    )

                    if str(row.get("Алгоритм", "")).strip():
                        st.caption("Алгоритм")
                        st.markdown(
                            highlight_text(
                                str(row["Алгоритм"]),
                                search_query
                            ),
                            unsafe_allow_html=True
                        )

                    # Важно с подсветкой найденного
                    if str(row["Важно"]).strip():
                        st.caption("Важно")
                        st.markdown(
                            highlight_text(
                                str(row["Важно"]),
                                search_query
                            ),
                            unsafe_allow_html=True
                        )

                    metadata = []
                    if str(row.get("Дата обновления", "")).strip():
                        metadata.append(f"Обновлено: {row['Дата обновления']}")
                    if str(row.get("Источник", "")).strip():
                        metadata.append(f"Источник: {row['Источник']}")
                    if metadata:
                        st.caption(" | ".join(metadata))

def render_reference_tables_section(section):
    search_query = render_section_header(section)
    experts_filtered = search_df(
        st.session_state.db["contacts_experts"], search_query
    )
    labs_filtered = search_df(st.session_state.db["contacts_labs"], search_query)
    battary_filtred = search_df(
        st.session_state.db["testing_battery"], search_query
    )
    samples_nd_filtered = search_df(
        st.session_state.db["samples_nd"], search_query
    )
    dynamic_matches = render_section_materials(section["id"], search_query)

    # ===== Испытания =====
    if not experts_filtered.empty or not search_query.strip():

        with st.expander(
            "🔬 Сроки проведения испытаний по регламентам, включая ПП РФ 2425",
            expanded=bool(search_query.strip())
        ):

            experts_view = filter_table_by_column(
                experts_filtered,
                "Группа (вид) продукции",
                "Фильтр по группе продукции",
                "experts_group_filter",
            )
            render_table_view("contacts_experts", experts_view, row_height=80)

    # ===== Сроки действия документов =====
    if not labs_filtered.empty or not search_query.strip():

        with st.expander(
            "📋 Сроки действия сертификатов и деклараций",
            expanded=bool(search_query.strip())
        ):

            labs_view = filter_table_by_column(
                labs_filtered,
                "Регламент",
                "Фильтр по регламенту",
                "labs_regulation_filter",
            )
            render_table_view("contacts_labs", labs_view, row_height=80)

    # ===== АККУМУЛЯТОРЫ И БАТАРЕИ =====
    if not battary_filtred.empty or not search_query.strip():

        with st.expander(
            "🔋 Аккумуляторы и батареи — сроки испытаний и количество образцов",
            expanded=bool(search_query.strip())
        ):

            render_table_view(
                "testing_battery",
                filter_table_by_column(
                    battary_filtred,
                    "Наименование продукции",
                    "Фильтр по продукции",
                    "battery_product_filter",
                ),
                row_height=80
            )

    # ===== НОРМЫ ОТБОРА ОБРАЗЦОВ =====
    if not samples_nd_filtered.empty or not search_query.strip():

        with st.expander(
            "🧪 Нормы отбора образцов по пищевой продукции/кормам",
            expanded=bool(search_query.strip())
        ):

            render_table_view(
                "samples_nd",
                filter_table_by_column(
                    samples_nd_filtered,
                    "Группа (вид) продукции",
                    "Фильтр по группе продукции",
                    "samples_group_filter",
                ),
                row_height=80
            )

    # Если ничего не найдено
    if (
        search_query.strip()
        and experts_filtered.empty
        and labs_filtered.empty
        and battary_filtred.empty
        and samples_nd_filtered.empty
        and not dynamic_matches
    ):
        st.info("По вашему запросу ничего не найдено.")


def render_instructions_section(section):
    search_query = render_section_header(section)
    texts_filtered = search_df(st.session_state.db["texts_table"], search_query)

    if st.session_state.is_admin:
        st.info(
            "Выберите существующую инструкцию для редактирования или создайте новую. "
            "Текст сохраняется без автоматических изменений."
        )
        render_text_editor()

    dynamic_matches = render_section_materials(section["id"], search_query)

    if not texts_filtered.empty:
        for _, row in texts_filtered.iterrows():
            with st.expander(
                str(row["Заголовок"]),
                expanded=bool(search_query.strip())
            ):
                if str(row.get("Краткое описание", "")).strip():
                    st.caption("Коротко")
                    st.markdown(
                        highlight_text(
                            str(row["Краткое описание"]),
                            search_query,
                        ),
                        unsafe_allow_html=True,
                    )
                    st.divider()
                st.caption("Текст инструкции")
                st.markdown(
                    highlight_text(
                        str(row["Текст инструкции"]),
                        search_query
                    ),
                    unsafe_allow_html=True
                )
                metadata = []
                if str(row.get("Дата обновления", "")).strip():
                    metadata.append(f"Обновлено: {row['Дата обновления']}")
                if str(row.get("Источник", "")).strip():
                    metadata.append(f"Источник: {row['Источник']}")
                if metadata:
                    st.caption(" | ".join(metadata))

    elif search_query.strip() and not dynamic_matches:
        st.info("По вашему запросу ничего не найдено.")


def render_home_page():
    """Главная страница с коротким объяснением новой навигации."""
    sections = [
        section
        for section in load_sections()
        if section.get("is_visible", True)
    ]
    st.title("📚 Единая база знаний")
    st.write(
        "Выберите рабочий раздел в боковой панели. Внутри каждого раздела "
        "доступен поиск по его материалам."
    )

    faq_col, tables_col, instructions_col = st.columns(3)
    faq_col.metric("Материалы FAQ", len(st.session_state.db["faq"]))
    tables_col.metric(
        "Строки в справочниках",
        sum(
            len(st.session_state.db[key])
            for key in (
                "contacts_experts",
                "contacts_labs",
                "testing_battery",
                "samples_nd",
            )
        ),
    )
    instructions_col.metric(
        "Инструкции", len(st.session_state.db["texts_table"])
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
    """Выбирает экран по назначению раздела."""
    page_kind = section.get("page_kind", "custom")
    if page_kind == "faq":
        render_faq_section(section)
    elif page_kind == "reference_tables":
        render_reference_tables_section(section)
    elif page_kind == "instructions":
        render_instructions_section(section)
    else:
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

