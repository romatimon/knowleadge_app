import time
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import hashlib
from contextlib import contextmanager

# Настройка
ADMIN_PASSWORD = "admin123"
DB_FILE = "knowledge.db"

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    try:
        yield conn
    finally:
        conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

ADMIN_PASSWORD_HASH = hash_password(ADMIN_PASSWORD)

def format_datetime(timestamp):
    try:
        utc_dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        moscow_dt = utc_dt + timedelta(hours=3)
        return moscow_dt.strftime('%d.%m.%Y %H:%M')
    except:
        return timestamp

st.set_page_config(
    page_title="База знаний",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== КОМПАКТНЫЙ CSS =====
st.markdown("""
<style>
    section[data-testid="stSidebar"] .element-container {
        margin-bottom: -0.2rem !important;
    }
    section[data-testid="stSidebar"] .stButton {
        margin-bottom: -0.3rem !important;
    }
    section[data-testid="stSidebar"] .stTextInput {
        margin-bottom: -0.2rem !important;
    }
    section[data-testid="stSidebar"] hr {
        margin-top: 0.2rem !important;
        margin-bottom: 0.2rem !important;
    }
    section[data-testid="stSidebar"] .stSubheader {
        margin-bottom: 0.2rem !important;
    }
    section[data-testid="stSidebar"] .stForm {
        margin-bottom: 0rem !important;
    }
    .block-container {
        padding-top: 3rem !important;
        padding-bottom: 0rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    .streamlit-expanderHeader {
        font-size: 0.9rem !important;
        padding: 0.4rem 0.8rem !important;
        background-color: #f0f2f6 !important;
        border-radius: 0.5rem !important;
    }
    .streamlit-expanderContent {
        padding: 0.5rem !important;
    }
    section[data-testid="stSidebar"] {
        width: 280px !important;
    }
    section[data-testid="stSidebar"] .block-container {
        padding-top: 1rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    section[data-testid="stSidebar"] button {
        padding: 0.3rem 0.5rem !important;
        font-size: 0.85rem !important;
    }
    h1 {
        font-size: 1.8rem !important;
        margin-top: 0rem !important;
        margin-bottom: 0.5rem !important;
        line-height: 1.2 !important;
    }
    h2, h3 {
        font-size: 1.2rem !important;
    }
    [data-testid="stMetric"] {
        padding: 0.5rem !important;
    }
    [data-testid="stMetric"] label {
        font-size: 0.85rem !important;
    }
    [data-testid="stMetric"] .stMetricValue {
        font-size: 1.5rem !important;
    }
    .stAlert, .stInfo, .stSuccess, .stWarning, .stError {
        padding: 0.5rem !important;
        font-size: 0.85rem !important;
    }
    .stTextArea textarea, .stTextInput input {
        font-size: 0.85rem !important;
    }
    .stExpander {
        margin-bottom: 0.5rem !important;
    }

    /* Правая информационная панель */
    .right-panel {
        position: sticky !important;
        top: 1rem !important;
        max-height: calc(100vh - 2rem) !important;
        overflow-y: auto !important;
        padding: 0.8rem !important;
        background: #f8f9fa !important;
        border-radius: 0.5rem !important;
        border: 1px solid #e9ecef !important;
    }
    
    .right-panel::-webkit-scrollbar {
        width: 4px !important;
    }
    
    .right-panel::-webkit-scrollbar-thumb {
        background: #ccc !important;
        border-radius: 4px !important;
    }

</style>
""", unsafe_allow_html=True)

# Инициализация состояния сессии
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False

# Создание базы данных
def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS sections
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      title TEXT NOT NULL,
                      description TEXT,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS questions
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      section_id INTEGER,
                      question TEXT NOT NULL,
                      answer TEXT,
                      info TEXT,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (section_id) REFERENCES sections (id))''')
        conn.commit()
init_db()

# Функции для работы с БД
def get_sections():
    with get_db_connection() as conn:
        return pd.read_sql("SELECT * FROM sections ORDER BY title", conn)

def get_questions(section_id):
    with get_db_connection() as conn:
        return pd.read_sql("SELECT * FROM questions WHERE section_id = ? ORDER BY id", 
                          conn, params=(section_id,))

def search_questions(search_text):
    with get_db_connection() as conn:
        query = """
        SELECT q.*, s.title as section_title 
        FROM questions q
        JOIN sections s ON q.section_id = s.id
        WHERE q.question LIKE ? OR q.answer LIKE ? OR q.info LIKE ?
        ORDER BY s.title, q.id
        """
        search_param = f"%{search_text}%"
        return pd.read_sql(query, conn, params=(search_param, search_param, search_param))

@st.cache_data(ttl=300)
def get_recent_sections(limit=5):
    with get_db_connection() as conn:
        return pd.read_sql(f"SELECT * FROM sections ORDER BY created_at DESC LIMIT {limit}", conn)

@st.cache_data(ttl=300)
def get_recent_questions(limit=5):
    with get_db_connection() as conn:
        return pd.read_sql(f"""
            SELECT q.*, s.title as section_title 
            FROM questions q
            JOIN sections s ON q.section_id = s.id
            ORDER BY q.created_at DESC LIMIT {limit}
        """, conn)

def get_total_stats():
    with get_db_connection() as conn:
        sections_count = pd.read_sql("SELECT COUNT(*) as count FROM sections", conn).iloc[0]['count']
        questions_count = pd.read_sql("SELECT COUNT(*) as count FROM questions", conn).iloc[0]['count']
        return sections_count, questions_count

def add_section(title, description):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO sections (title, description) VALUES (?, ?)", (title, description))
        conn.commit()
    st.cache_data.clear()

def add_question(section_id, question, answer, info):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO questions (section_id, question, answer, info) VALUES (?, ?, ?, ?)",
                  (section_id, question, answer, info))
        conn.commit()
    st.cache_data.clear()

def update_question(question_id, question, answer, info):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE questions SET question = ?, answer = ?, info = ? WHERE id = ?",
                  (question, answer, info, question_id))
        conn.commit()
    st.cache_data.clear()

def update_section(section_id, title, description):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE sections SET title = ?, description = ? WHERE id = ?",
                  (title, description, section_id))
        conn.commit()
    st.cache_data.clear()

def delete_section(section_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM sections WHERE id = ?", (section_id,))
        c.execute("DELETE FROM questions WHERE section_id = ?", (section_id,))
        conn.commit()
    st.cache_data.clear()

def delete_question(question_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        conn.commit()
    st.cache_data.clear()

# ===== БОКОВАЯ ПАНЕЛЬ =====
with st.sidebar:
    st.header("📚 База знаний")
    
    # Поиск
    search_container = st.container()
    with search_container:
        search_text = st.text_input(
            "🔍 Поиск", 
            placeholder="Введите запрос и нажмите Enter...",
            value=st.session_state.get("search_text", ""),
            key="search_input",
            label_visibility="collapsed"
        )
        col1, col2 = st.columns([3, 1])
        with col1:
            search_clicked = st.button("Найти", use_container_width=True, key="search_button")
        with col2:
            if st.session_state.get("search_mode"):
                if st.button("✖", use_container_width=True, key="clear_search"):
                    if "search_mode" in st.session_state:
                        del st.session_state["search_mode"]
                    if "search_text" in st.session_state:
                        del st.session_state["search_text"]
                    st.rerun()
    
    if search_clicked or (search_text and search_text != st.session_state.get("last_search", "")):
        if search_text.strip():
            st.session_state["search_mode"] = True
            st.session_state["search_text"] = search_text
            st.session_state["last_search"] = search_text
            st.rerun()
        elif search_clicked:
            st.warning("Введите текст для поиска")
    
    st.write("---")
    
    # Разделы
    st.subheader("📂 Разделы")
    
    sections_df = get_sections()
    
    if not sections_df.empty:
        for _, section in sections_df.iterrows():
            if st.button(f" {section['title']}", 
                        use_container_width=True,
                        key=f"nav_{section['id']}"):
                if "search_mode" in st.session_state:
                    del st.session_state["search_mode"]
                if "search_text" in st.session_state:
                    del st.session_state["search_text"]
                # Очищаем режим редактирования раздела
                if "editing_section" in st.session_state:
                    del st.session_state["editing_section"]
                # Очищаем все состояния expander'ов
                keys_to_delete = [key for key in st.session_state.keys() 
                                  if key.startswith("expanded_")]
                for key in keys_to_delete:
                    del st.session_state[key]
                st.session_state["current_section"] = section['id']
                st.session_state["section_title"] = section['title']
                st.rerun()
    else:
        st.info("Нет разделов")
    
    st.write("---")
    
    # Панель админа
    if not st.session_state.admin_logged_in:
        with st.form("admin_login"):
            st.text_input("Пароль админа", type="password", key="admin_pass")
            if st.form_submit_button("Войти как админ"):
                if st.session_state.get("admin_pass") and hash_password(st.session_state["admin_pass"]) == ADMIN_PASSWORD_HASH:
                    st.session_state.admin_logged_in = True
                    st.rerun()
                else:
                    st.error("Неверный пароль")
    else:
        st.success("✅ Админ")
        if st.button("Выйти", use_container_width=True):
            st.session_state.admin_logged_in = False
            st.rerun()

# ===== ГЛАВНАЯ ОБЛАСТЬ =====
# Режим поиска
if st.session_state.get("search_mode"):
    search_text = st.session_state.get("search_text", "")
    if st.button("← Назад"):
        del st.session_state["search_mode"]
        if "search_text" in st.session_state:
            del st.session_state["search_text"]
        st.rerun()
    
    st.subheader(f"🔍 Результаты поиска: '{search_text}'")
    results = search_questions(search_text)
    if not results.empty:
        for _, question in results.iterrows():
            with st.expander(f"📁 {question['section_title']} » {question['question'][:50]}..."):
                if question.get('created_at'):
                    st.caption(f"📅 {format_datetime(question['created_at'])}")
                st.markdown("---")
                
                st.markdown("**📝 Содержание:**")
                st.write(question['answer'] if question['answer'] else "—")
                
                st.markdown("**📌 Тема:**")
                st.write(question['question'])
    else:
        st.info("Ничего не найдено")

# Режим просмотра раздела
elif "current_section" in st.session_state:
    section_id = st.session_state["current_section"]
    section_title = st.session_state.get("section_title", "")
    
    with get_db_connection() as conn:
        section_info = pd.read_sql(f"SELECT * FROM sections WHERE id = {section_id}", conn)
    
    if not section_info.empty:
        current_section = section_info.iloc[0]
        current_desc = current_section['description']
        
        # ===== ДВЕ КОЛОНКИ: ОСНОВНАЯ + ПРАВАЯ ПАНЕЛЬ =====
        col_main, col_right = st.columns([3, 1])
        
        # ===== ОСНОВНАЯ КОЛОНКА =====
        with col_main:
            # Кнопка назад
            col_back, col_spacer = st.columns([1, 5])
            with col_back:
                if st.button("← Назад", use_container_width=True):
                    if "current_section" in st.session_state:
                        del st.session_state["current_section"]
                    if "section_title" in st.session_state:
                        del st.session_state["section_title"]
                    if "editing_section" in st.session_state:
                        del st.session_state["editing_section"]
                    keys_to_delete = [key for key in st.session_state.keys() 
                                      if key.startswith("edit_mode_") or 
                                         key.startswith("confirm_del_") or
                                         key.startswith("expanded_")]
                    for key in keys_to_delete:
                        del st.session_state[key]
                    st.rerun()
            
            # Заголовок раздела
            st.subheader(section_title)
            if current_desc:
                st.caption(current_desc)
            
            # Кнопка редактирования раздела
            if st.session_state.admin_logged_in:
                if st.button("✏️ Редакт. раздел", use_container_width=True):
                    st.session_state["editing_section"] = section_id
            
            # Форма редактирования раздела
            if st.session_state.admin_logged_in and st.session_state.get("editing_section") == section_id:
                with st.form(f"edit_section_{section_id}"):
                    new_title = st.text_input("Название раздела", value=section_title)
                    new_desc = st.text_area("Описание раздела", value=current_desc if current_desc else "")
                    col_save, col_cancel, col_delete = st.columns(3)
                    with col_save:
                        if st.form_submit_button("💾 Сохранить", use_container_width=True):
                            update_section(section_id, new_title, new_desc)
                            st.session_state["section_title"] = new_title
                            del st.session_state["editing_section"]
                            st.success("Раздел обновлен!")
                            st.rerun()
                    with col_cancel:
                        if st.form_submit_button("❌ Отмена", use_container_width=True):
                            del st.session_state["editing_section"]
                            st.rerun()
                    with col_delete:
                        if st.form_submit_button("🗑️ Удалить", use_container_width=True):
                            delete_section(section_id)
                            del st.session_state["editing_section"]
                            del st.session_state["current_section"]
                            st.success("Раздел удален!")
                            st.rerun()
            
            # Форма добавления записи
            if st.session_state.admin_logged_in:
                with st.expander("➕ Добавить новую запись", expanded=False):
                    with st.form(f"add_q_{section_id}", clear_on_submit=True):
                        question_text = st.text_area("Заголовок", height=80)
                        answer_text = st.text_area("Содержание", height=400)
                        if st.form_submit_button("➕ Добавить", use_container_width=True):
                            if question_text.strip():
                                add_question(section_id, question_text, answer_text, "")
                                st.toast("✅ Запись добавлена!", icon="✅")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error("Заголовок не может быть пустым")
            
            # Список записей
            questions_df = get_questions(section_id)
            if not questions_df.empty:
                for _, q in questions_df.iterrows():
                    if st.session_state.get(f"edit_mode_{q['id']}", False):
                        with st.container(border=True):
                            st.markdown(f"**✏️ Редактирование: {q['question'][:60]}**")
                            with st.form(f"edit_inline_{q['id']}"):
                                new_title = st.text_area("Заголовок", value=q['question'], height=80)
                                new_content = st.text_area("Содержание", value=q['answer'] if q['answer'] else "", height=400)
                                col_save, col_cancel = st.columns(2)
                                with col_save:
                                    if st.form_submit_button("💾 Сохранить", use_container_width=True):
                                        if new_title.strip():
                                            update_question(q['id'], new_title, new_content, "")
                                            st.session_state[f"edit_mode_{q['id']}"] = False
                                            st.toast("✅ Сохранено!", icon="✅")
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error("Заголовок не может быть пустым")
                                with col_cancel:
                                    if st.form_submit_button("❌ Отмена", use_container_width=True):
                                        st.session_state[f"edit_mode_{q['id']}"] = False
                                        st.rerun()
                    else:
                        # ===== КОНТЕЙНЕР С КНОПКОЙ ВМЕСТО EXPANDER =====
                        with st.container(border=True):
                            # Заголовок с кнопкой показа/скрытия
                            col_title, col_btn = st.columns([4, 1])
                            with col_title:
                                st.markdown(f"**📌 {q['question'][:100]}**")
                            with col_btn:
                                # Кнопка переключения (▼ / ▲)
                                is_expanded = st.session_state.get(f"expanded_{q['id']}", False)
                                btn_label = "▲" if is_expanded else "▼"
                                if st.button(btn_label, key=f"toggle_{q['id']}", use_container_width=True):
                                    st.session_state[f"expanded_{q['id']}"] = not is_expanded
                                    st.rerun()
                            
                            # Содержимое (показываем только если развёрнуто)
                            if st.session_state.get(f"expanded_{q['id']}", False):
                                # st.markdown("---")
                                if q['created_at']:
                                    st.caption(f"📅 {format_datetime(q['created_at'])}")
                                
                                st.markdown("**📝 Содержание:**")
                                if q['answer'] and q['answer'] != "nan":
                                    st.markdown(q['answer'])
                                else:
                                    st.markdown("—")
                                
                                if st.session_state.admin_logged_in:
                                    st.markdown("---")
                                    col_edit, col_del = st.columns(2)
                                    with col_edit:
                                        if st.button("✏️ Редактировать", key=f"edit_btn_{q['id']}", use_container_width=True):
                                            st.session_state[f"edit_mode_{q['id']}"] = True
                                            st.rerun()
                                    with col_del:
                                        if st.button("🗑️ Удалить", key=f"del_btn_{q['id']}", use_container_width=True):
                                            st.session_state[f"confirm_del_{q['id']}"] = True
                                    
                                    if st.session_state.get(f"confirm_del_{q['id']}", False):
                                        st.warning("⚠️ Вы уверены?")
                                        col_yes, col_no = st.columns(2)
                                        with col_yes:
                                            if st.button("✅ Да, удалить", key=f"confirm_yes_{q['id']}", use_container_width=True):
                                                delete_question(q['id'])
                                                del st.session_state[f"confirm_del_{q['id']}"]
                                                st.rerun()
                                        with col_no:
                                            if st.button("❌ Нет", key=f"confirm_no_{q['id']}", use_container_width=True):
                                                del st.session_state[f"confirm_del_{q['id']}"]
                                                st.rerun()
                            else:
                                # Краткий предпросмотр (всегда виден)
                                if q['answer'] and q['answer'] != "nan":
                                    preview = q['answer'][:100].replace('\n', ' ')
                                    st.caption(f"📝 {preview}...")
                                else:
                                    st.caption("📝 Нет содержания")
            else:
                st.info("В этом разделе пока нет записей.")
        
        # ===== ПРАВАЯ ПАНЕЛЬ (ЗАКРЕПЛЁННАЯ) =====
        with col_right:
            st.markdown('<div class="right-panel">', unsafe_allow_html=True)
            
            questions_df = get_questions(section_id)
            
            # Статистика
            st.markdown("**📊 Статистика**")
            st.metric("📄 Записей", len(questions_df))
            
            # За последнюю неделю
            week_ago = datetime.now() - timedelta(days=7)
            recent = 0
            for _, q in questions_df.iterrows():
                if q.get('created_at'):
                    try:
                        q_date = datetime.strptime(q['created_at'], '%Y-%m-%d %H:%M:%S')
                        if q_date > week_ago:
                            recent += 1
                    except:
                        pass
            st.metric("🆕 За неделю", recent)
            
            if not questions_df.empty:
                last_row = questions_df.iloc[-1]
                if last_row.get('created_at'):
                    st.caption(f"📅 Обновлено: {format_datetime(last_row['created_at'])}")
                else:
                    st.caption("📅 Обновлено: —")
            else:
                st.caption("📅 Обновлено: —")
            
            st.divider()
            
            # Быстрый переход по разделам
            st.markdown("**🔗 Разделы**")
            sections_list = get_sections()
            # Показываем только первые 5 разделов (чтобы не загромождать)
            count = 0
            for _, s in sections_list.iterrows():
                if s['id'] != section_id and count < 5:
                    display_name = s['title'][:20] + "..." if len(s['title']) > 20 else s['title']
                    if st.button(f"📁 {display_name}", key=f"quick_{s['id']}", use_container_width=True):
                        if "editing_section" in st.session_state:
                            del st.session_state["editing_section"]
                        # Очищаем все состояния expander'ов
                        keys_to_delete = [key for key in st.session_state.keys() 
                                          if key.startswith("expanded_") or
                                             key.startswith("edit_mode_") or
                                             key.startswith("confirm_del_")]
                        for key in keys_to_delete:
                            del st.session_state[key]
                        st.session_state["current_section"] = s['id']
                        st.session_state["section_title"] = s['title']
                        st.rerun()
                    count += 1
            
            st.divider()
            
            # Недавние записи в этом разделе
            if not questions_df.empty:
                st.markdown("**🆕 Последние добавленные**")
                for _, q in questions_df.tail(3).iterrows():
                    st.caption(f"• {q['question'][:40]}..." if len(q['question']) > 40 else f"• {q['question']}")
            
            st.markdown('</div>', unsafe_allow_html=True)

# ===== ГЛАВНАЯ СТРАНИЦА =====
else:
    st.title("📚 База знаний")
    
    # Инструкция
    with st.expander("📖 Инструкция по использованию", expanded=False):
        col_user, col_admin = st.columns(2)
        with col_user:
            st.markdown("""
            **👤 ДЛЯ ПОЛЬЗОВАТЕЛЕЙ**
            
            **🔍 Поиск информации:**
            • Введите ключевые слова в поле поиска (боковая панель)
            • Нажмите Enter или кнопку "Найти"
            
            **📂 Просмотр по разделам:**
            • Выберите раздел в боковой панели
            • Кликните на запись для просмотра
            • Используйте кнопку "← Назад" для возврата
            
            **🎯 Быстрый доступ:**
            • Главная страница открывается автоматически
            • Последние обновления показаны ниже
            """)
        
        if st.session_state.admin_logged_in:
            with col_admin:
                st.markdown("""
                **🔧 ДЛЯ АДМИНИСТРАТОРА**
                
                **📁 Управление разделами:**
                • **Создать:** форма ниже
                • **Редактировать:** кнопка "✏️ Редакт. раздел"
                • **Удалить:** в форме редактирования раздела
                
                **📝 Управление записями:**
                • **Добавить:** кнопка "➕ Добавить новую запись"
                • **Редактировать:** кнопка "✏️ Редактировать"
                • **Удалить:** кнопка "🗑️ Удалить" (с подтверждением)
                
                **⚠️ Важно:** изменения сохраняются сразу, удаленные данные не восстанавливаются
                """)
        else:
            with col_admin:
                st.markdown("""
                **🔐 ДЛЯ АДМИНИСТРАТОРОВ**
                
                Войдите в систему через боковую панель для управления базой знаний
                """)
    
    # Форма создания раздела
    if st.session_state.admin_logged_in:
        st.subheader("🛠️ Управление разделами")
        with st.expander("➕ Создать новый раздел", expanded=False):
            with st.form("new_section_form", clear_on_submit=True):
                col1, col2 = st.columns([2, 1])
                with col1:
                    new_section_title = st.text_input("Название раздела")
                with col2:
                    new_section_desc = st.text_input("Описание раздела")
                if st.form_submit_button("✅ Создать раздел", use_container_width=True):
                    if new_section_title.strip():
                        add_section(new_section_title, new_section_desc)
                        st.success(f"Раздел '{new_section_title}' создан!")
                        st.rerun()
        st.divider()
    
    # Последние обновления
    st.subheader("🔄 Последние обновления")
    recent_questions = get_recent_questions(limit=4)
    if not recent_questions.empty:
        for idx, (_, q) in enumerate(recent_questions.iterrows()):
            # Каждая запись — компактная строка
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**📁 {q['section_title']}**")
                    st.markdown(f"📌 {q['question'][:80]}")
                    if q['answer']:
                        preview = q['answer'][:80].replace('\n', ' ')
                        st.caption(preview)
                with col2:
                    st.caption(f"📅 {format_datetime(q['created_at']) if q.get('created_at') else ''}")
                    if st.button("→", key=f"home_q_{q['id']}", use_container_width=True):
                        st.session_state["current_section"] = q['section_id']
                        st.session_state["section_title"] = q['section_title']
                        st.rerun()
    else:
        st.info("Пока нет добавленных записей")
    
    if not st.session_state.admin_logged_in:
        st.caption("💡 **Совет:** Если вы администратор, войдите в систему для управления базой знаний.")