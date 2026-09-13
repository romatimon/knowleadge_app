"""Сводный контроль наполнения и актуальности базы знаний."""

from __future__ import annotations

import streamlit as st

from knowledge_base.materials import is_public_material, material_relevance
from storage import load_branches, load_content_items, load_sections


def _material_line(
    item: dict,
    section_by_id: dict[str, dict],
    branch_by_id: dict[str, dict],
) -> str:
    section = section_by_id.get(str(item.get("section_id", "")), {})
    branch = branch_by_id.get(str(item.get("branch_id", "")), {})
    location = str(section.get("title", "Без раздела"))
    if branch:
        location += f" → {branch['title']}"
    return f"- **{item['title']}** · {location}"


def render_content_control() -> None:
    """Показывает администратору материалы, требующие внимания."""
    sections = load_sections(include_archived=True)
    branches = load_branches(include_archived=True)
    items = load_content_items(include_archived=True)
    active = [item for item in items if not item["is_archived"]]
    section_by_id = {section["id"]: section for section in sections}
    branch_by_id = {branch["id"]: branch for branch in branches}

    attention = [
        item
        for item in active
        if material_relevance(item) in {"review", "overdue"}
    ]
    drafts = [item for item in active if material_relevance(item) == "draft"]
    unassigned = [item for item in active if not str(item.get("branch_id", ""))]
    hidden = [
        item
        for item in active
        if not is_public_material(item) and material_relevance(item) != "draft"
    ]

    st.title("🔎 Контроль базы")
    st.caption(
        "Здесь собраны материалы, которые требуют проверки, публикации или распределения."
    )
    col_attention, col_drafts, col_unassigned, col_hidden = st.columns(4)
    col_attention.metric("Проверить", len(attention))
    col_drafts.metric("Черновики", len(drafts))
    col_unassigned.metric("Без ветки", len(unassigned))
    col_hidden.metric("Скрытые", len(hidden))

    attention_tab, draft_tab, structure_tab, hidden_tab = st.tabs(
        ["Актуальность", "Черновики", "Структура", "Скрытые"]
    )
    with attention_tab:
        if not attention:
            st.success("Нет материалов с просроченной или ручной проверкой.")
        for item in attention:
            st.markdown(_material_line(item, section_by_id, branch_by_id))
            due = str(item.get("review_due_at", "")).strip()
            if due:
                st.caption(f"Срок проверки: {due}")

    with draft_tab:
        if not drafts:
            st.info("Черновиков нет.")
        for item in drafts:
            st.markdown(_material_line(item, section_by_id, branch_by_id))

    with structure_tab:
        if unassigned:
            st.warning(
                "Материалы без ветки доступны, но их желательно распределить "
                "для понятной навигации."
            )
            for item in unassigned:
                st.markdown(_material_line(item, section_by_id, branch_by_id))
        else:
            st.success("Все активные материалы распределены по веткам.")

        st.divider()
        active_section_ids = {
            section["id"] for section in sections if not section["is_archived"]
        }
        active_branches = [
            branch
            for branch in branches
            if not branch["is_archived"] and branch["section_id"] in active_section_ids
        ]
        used_branch_ids = {
            str(item.get("branch_id", "")) for item in active if item.get("branch_id")
        }
        empty_branches = [
            branch for branch in active_branches if branch["id"] not in used_branch_ids
        ]
        st.markdown(f"**Пустых веток:** {len(empty_branches)}")
        for branch in empty_branches:
            section_title = section_by_id.get(branch["section_id"], {}).get(
                "title", "Без раздела"
            )
            st.caption(f"{section_title} → {branch['title']}")

    with hidden_tab:
        if not hidden:
            st.info("Отдельно скрытых материалов нет.")
        for item in hidden:
            st.markdown(_material_line(item, section_by_id, branch_by_id))
