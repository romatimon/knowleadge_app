import streamlit as st
import pandas as pd
import json
import os
import re

# Настройка конфигурации страницы
st.set_page_config(page_title="База знаний менеджера", layout="wide")

ADMIN_USERS = {"admin": "secret123"}

# ===== 1. ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ =====
def save_all_data(data):
    """Сохраняет все данные в файл database.json"""
    with open("database.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_all_data():
    """Загружает данные из database.json"""
    if os.path.exists("database.json"):
        with open("database.json", "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

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

    query = normalize(query)

    mask = (
        df.fillna("")
        .astype(str)
        .apply(lambda col: col.map(normalize).str.contains(query, regex=False))
        .any(axis=1)
    )

    return df[mask]

def highlight_text(text, query):
    """Подсветка найденного слова в тексте с помощью HTML-тега <mark>"""
    if not query.strip():
        return text
    safe_query = re.escape(query.strip())
    compiled = re.compile(f"({safe_query})", re.IGNORECASE)
    return compiled.sub(r"<mark style='background-color: #ffeb3b; color: black; padding: 2px 4px; border-radius: 3px;'>\1</mark>", text)

# ===== 2. УНИВЕРСАЛЬНАЯ ИНИЦИАЛИЗАЦИЯ СЕССИИ =====
if "db" not in st.session_state or not st.session_state.db:
    raw = load_all_data()
    if not isinstance(raw, dict):
        raw = {}
        
    st.session_state.db = {}
    table_keys = ["faq", "contacts_experts", "contacts_labs", "testing_battery", "texts_table", "samples_nd"]
    
    for key in table_keys:
        saved_data = raw.get(key)
        if saved_data and len(saved_data) > 0:
            st.session_state.db[key] = pd.DataFrame(saved_data)
        else:
            if key == "texts_table":
                st.session_state.db[key] = pd.DataFrame(columns=["Категория", "Заголовок", "Текст инструкции"])
            elif key == "faq":
                st.session_state.db[key] = pd.DataFrame(columns=[
                    "Тип",
                    "Вопрос / Ситуация",
                    "Ответ",
                    "Важно"
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

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# ===== 3. БОКОВАЯ ПАНЕЛЬ ДЛЯ ВХОДА АДМИНА =====
with st.sidebar:
    st.header("Вход для администратора")
    if not st.session_state.is_admin:
        u = st.text_input("Логин", key="u_reg")
        p = st.text_input("Пароль", type="password", key="p_reg")
        if st.button("Войти", width="stretch"):
            if u in ADMIN_USERS and ADMIN_USERS[u] == p:
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("Неверный пароль")
    else:
        st.success("🔓 Режим редактора включен")
        if st.button("Выйти", width="stretch"):
            st.session_state.is_admin = False
            st.rerun()

# ===== 4. ОСНОВНОЙ ИНТЕРФЕЙС И ГЛОБАЛЬНЫЙ ПОИСК =====
st.title("📚 Единая база знаний для менеджеров")

with st.expander("📖 Как пользоваться базой знаний", expanded=False):
    st.markdown("""

Добро пожаловать в базу знаний менеджера.

Используйте поле **🔍 Поиск** в верхней части страницы, чтобы быстро найти нужную информацию. Поиск работает сразу по всем разделам базы и подсвечивает найденные совпадения.

После поиска **переключайтесь между вкладками**, чтобы просмотреть найденную информацию в соответствующем разделе базы знаний.

## 📂 Разделы базы знаний

### ❓ Типовые ситуации (FAQ)

- ответы на часто возникающие вопросы;
- готовые алгоритмы действий;
- внутренние правила и исключения.

### 📊 Сроки испытаний и разрешительные документы

- сроки проведения испытаний;
- сроки действия сертификатов и деклараций;
- информация по испытаниям аккумуляторов и батарей.

### 📝 Инструкции и алгоритмы

- пошаговые инструкции по внутренним процессам;
- порядок выполнения нестандартных операций;
- рабочие алгоритмы.

## 💡 Полезные рекомендации

- Используйте разные варианты ключевых слов, если поиск ничего не нашел.
- Нормативные документы можно искать по номеру полностью или частично (например, **007/2011** или **ТР ТС 007**).
- Если нужной информации нет в базе или она требует уточнения — обратитесь к профильному специалисту.

> ⚠️ **База знаний регулярно обновляется.** Если обнаружили ошибку или отсутствующую информацию, сообщите администратору для внесения изменений.
""")

def clear_search():
    """Очищает поле поиска"""
    st.session_state.search_input_key = ""

# Разделяем строку: 6 частей под поиск, 1 часть под кнопку сброса
col_search, col_clear = st.columns([6, 1])

with col_search:
    search_query = st.text_input(
        "🔍 Поиск по всей базе знаний", 
        placeholder="Введите ключевое слово (например: МЧД, 007/2011, ДС 353)...",
        key="search_input_key"
    )

with col_clear:
    st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
    if st.button("❌ Сбросить", width="stretch", on_click=clear_search):
        st.rerun()

# Подготовка отфильтрованных данных
experts_filtered = search_df(st.session_state.db["contacts_experts"], search_query)
labs_filtered = search_df(st.session_state.db["contacts_labs"], search_query)
texts_filtered = search_df(st.session_state.db["texts_table"], search_query)
battary_filtred = search_df(st.session_state.db["testing_battery"], search_query)
samples_nd_filtered = search_df(st.session_state.db["samples_nd"], search_query)
faq_filtered = search_df(
    st.session_state.db["faq"],
    search_query
)


# Названия вкладок строго статичны
tab1_title = "❓ Типовые ситуации (FAQ)"
tab5_title = "📊 Нормы и сроки: отбор, испытания, РД"
tab4_title = "📝 Инструкции и алгоритмы"

# Создаем вкладки со строгим фиксированным ключом сессии
tab1, tab5, tab4 = st.tabs([tab1_title, tab5_title, tab4_title], key='fixed_main_tabs')

def save_everything():
    """Сохраняет все DataFrame в JSON-файл"""
    json_ready = {k: v.to_dict(orient="records") for k, v in st.session_state.db.items()}
    save_all_data(json_ready)

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
        edited_df = st.data_editor(
            filtered_df, 
            num_rows="dynamic", 
            row_height=row_height, 
            width="stretch",
            hide_index=False,
            column_config=config,
            key=f"editor_{db_key}"
        )
        if not edited_df.equals(filtered_df):
            if search_query.strip():
                st.session_state.db[db_key].loc[edited_df.index] = edited_df
            else:
                st.session_state.db[db_key] = edited_df
            
            save_everything()
            st.toast("Изменения сохранены!", icon="💾")
            st.rerun()
    else:
        calculated_height = (len(filtered_df) * row_height) + 40
        st.dataframe(filtered_df, row_height=row_height, width="stretch", height=calculated_height, hide_index=False, column_config=config)

# Наполнение контентом вкладок
with tab1:
    st.subheader("❓ Типовые ситуации")

    if st.session_state.is_admin:
        st.info(
            "Тип записи:\n"
            "• 🛠️ Ситуация — алгоритм действий\n"
            "• 📖 Справка — ответ на вопрос\n"
            "• ⚖️ Правило — внутренние правила работы"
        )

        render_table_view("faq", faq_filtered, row_height=120)

        st.markdown("---")
        st.markdown("### 👁️ Так это видят менеджеры")

    if faq_filtered.empty:
        if search_query.strip():
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
                    f"❓ {row['Вопрос / Ситуация']}",
                    expanded=bool(search_query.strip())
                ):

                    # Вопрос с подсветкой найденного
                    st.markdown(
                        highlight_text(
                            str(row["Вопрос / Ситуация"]),
                            search_query
                        ),
                        unsafe_allow_html=True
                    )

                    st.markdown("### ✅ Ответ")

                    # Ответ с подсветкой найденного
                    st.markdown(
                        highlight_text(
                            str(row["Ответ"]),
                            search_query
                        ),
                        unsafe_allow_html=True
                    )

                    # Важно с подсветкой найденного
                    if str(row["Важно"]).strip():

                        st.markdown(
                            highlight_text(
                                str(row["Важно"]),
                                search_query
                            ),
                            unsafe_allow_html=True
                        )

with tab5:
    st.subheader("📊 Сроки проведения испытаний и сроки действия разрешительных документов")

    # ===== Испытания =====
    if not experts_filtered.empty or not search_query.strip():

        with st.expander(
            "🔬 Сроки проведения испытаний по регламентам, включая ПП РФ 2425",
            expanded=bool(search_query.strip())
        ):

            st.info("""
💡 **Памятка по срокам испытаний**

Все сроки указаны в **рабочих днях**. Наведите курсор на заголовок колонки, чтобы прочитать его полное название.

**Общие правила:**
- Сроки — от даты направления в ИЦ до даты получения протокола
- Если дата получения «на завтра» → стоимость **удваивается**, нужна отметка о срочности

**Переоформление протокола:**
- Дата направления в ИЛ: **5–10 раб. дней назад** от текущей
- Дата получения: **сегодня–завтра**
- Стоимость: **100 ₽**

⚠️ Важно
- При срочном выполнении ("на завтра") стоимость испытаний увеличивается в 2 раза
""")

            render_table_view("contacts_experts", experts_filtered, row_height=80)

    # ===== Сроки действия документов =====
    if not labs_filtered.empty or not search_query.strip():

        with st.expander(
            "📋 Сроки действия сертификатов и деклараций",
            expanded=bool(search_query.strip())
        ):

            st.info("""
💡 **Памятка по срокам действия документов**

**Обозначения**
- **«—»** — такой тип документа не применяется для данного регламента
- **«бессрочно»** — документ не имеет ограничения по сроку действия

**Особенности**
- Для **007/2011** срок зависит от схемы и группы продукции
- Для **008/2011** и **017/2011** учитывается количество производственных площадок
- Для **032/2013** (7с) срок определяется назначенным сроком службы или ресурса

⚠️ Важно
- Указаны максимально возможные сроки действия документов
- Фактический срок может быть меньше в зависимости от схемы подтверждения соответствия

___

**ГОСТ Р (ПП РФ 2425)**

**Сертификаты:**

Серия: для серийно выпускаемой продукции — не более 5 лет (если иное не установлено в национальном стандарте, определяющем правила сертификации)

Партия:
1. срок годности или срок службы не установлен → **1 год**
2. срок годности или срок службы установлен → **на срок годности (службы), но не более 5 лет**


**Декларации:**

Серия: для серийно выпускаемой продукции — не более 5 лет (если иное не установлено в национальном стандарте, определяющем правила декларирования)

Партия:
1. срок годности или срок службы не установлен → **1 год**
2. срок годности или срок службы установлен → на срок годности (службы), но не более 5 лет
""")

            render_table_view("contacts_labs", labs_filtered, row_height=80)

    # ===== АККУМУЛЯТОРЫ И БАТАРЕИ =====
    if not battary_filtred.empty or not search_query.strip():

        with st.expander(
            "🔋 Аккумуляторы и батареи — сроки испытаний и количество образцов",
            expanded=bool(search_query.strip())
        ):

            st.info("""
    💡 **Памятка по испытаниям аккумуляторов и батарей**

    **Стоимость испытаний в ИЦ ФБУ**
    - Протокол **Б/О** — **2 000 ₽**
    - Протокол **Образец+** — **7 500 ₽**

    **Общие правила**
    - Сроки испытаний указаны в **календарных сутках** от даты регистрации заявки в ИЦ до даты выпуска протокола.
    - Количество образцов указано в **штуках**.
    - Для отдельных видов продукции возможность проведения испытаний, сроки и количество образцов определяются после проработки запроса (**7–10 рабочих дней**).

    ⚠️ **Важно**
    - Указанные сроки испытаний являются минимально необходимыми.
    - Указанное количество образцов является обязательным.
    - Сокращение сроков испытаний и уменьшение количества образцов **не допускается**.
    """)

            render_table_view(
                "testing_battery",
                battary_filtred,
                row_height=80
            )

    # ===== НОРМЫ ОТБОРА ОБРАЗЦОВ =====
    if not samples_nd_filtered.empty or not search_query.strip():

        with st.expander(
            "🧪 Нормы отбора образцов по пищевой продукции/кормам",
            expanded=bool(search_query.strip())
        ):

            st.info("""
    💡 **Справочная информация о нормах отбора проб для пищевой, молочной, мясной, рыбной, табачной, никотинсодержащей продукции, кормов, пищевых добавок и других товаров.
    Для каждого вида продукции приведены нормы для контроля партии и серийного выпуска**
    """)

            render_table_view(
                "samples_nd",
                samples_nd_filtered,
                row_height=80
            )

    # Если ничего не найдено
    if (
        search_query.strip()
        and experts_filtered.empty
        and labs_filtered.empty
        and battary_filtred.empty
        and samples_nd_filtered.empty
    ):
        st.info("По вашему запросу ничего не найдено.")

with tab4:
    st.subheader("📝 Пошаговые руководства и алгоритмы работы")

    if st.session_state.is_admin:
        st.info(
            "🛠️ Режим администратора: вы можете редактировать, добавлять "
            "(кнопка + внизу) и удалять строки прямо в таблице."
        )
        render_table_view("texts_table", texts_filtered, row_height=120)
        st.markdown("---")
        st.markdown("### 👁️ Как это видят обычные менеджеры:")

    categorized_matches = {}

    if not texts_filtered.empty:

        for _, row in texts_filtered.iterrows():

            category = str(row["Категория"]).strip() if pd.notna(row["Категория"]) else ""
            if not category:
                category = "Общие инструкции"

            categorized_matches.setdefault(category, []).append(row)

    if categorized_matches:

        for category, rows in categorized_matches.items():

            # Если категория пустая — показываем инструкции сразу
            if category == "Общие инструкции":

                for _, row in pd.DataFrame(rows).iterrows():

                    with st.expander(
                        f"📘 {row['Заголовок']}",
                        expanded=bool(search_query.strip())
                    ):
                        st.markdown(
                            highlight_text(
                                str(row["Текст инструкции"]),
                                search_query
                            ),
                            unsafe_allow_html=True
                        )

            else:

                with st.expander(
                    f"📂 {category}",
                    expanded=bool(search_query.strip())
                ):

                    for _, row in pd.DataFrame(rows).iterrows():

                        with st.expander(f"📘 {row['Заголовок']}"):

                            st.markdown(
                                highlight_text(
                                    str(row["Текст инструкции"]),
                                    search_query
                                ),
                                unsafe_allow_html=True
                            )

    elif search_query.strip():
        st.info("По вашему запросу ничего не найдено.")