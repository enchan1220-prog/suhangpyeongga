from datetime import date

import streamlit as st

from schedule_ui import render_availability, render_schedules

from algorithm import (
    STATUS_LABELS,
    Task,
    TaskInputError,
    deadline_input_date,
    deadline_state,
    format_deadline,
    korean_now,
    parse_deadline_time,
    validate_task,
)


def render_task_form(prefix: str, task: Task | None = None) -> None:
    with st.form(f"{prefix}_form", clear_on_submit=False):
        title = st.text_input(
            "작업명", value=task.title if task else "", key=f"{prefix}_title"
        )
        columns = st.columns(2)
        with columns[0]:
            due_date = st.date_input(
                "마감일",
                value=deadline_input_date(task) if task else korean_now().date(),
                min_value=date.min,
                max_value=date.max,
                key=f"{prefix}_date",
            )
        with columns[1]:
            due_time_text = st.text_input(
                "마감 시각 (선택)",
                value=(
                    task.deadline_at.strftime("%H:%M")
                    if task and task.deadline_precision == "datetime"
                    else ""
                ),
                placeholder="18:30",
                help="비워 두면 마감일의 하루 끝까지입니다. 한국 시각 기준입니다.",
                key=f"{prefix}_time_text",
            )
        columns = st.columns(2)
        with columns[0]:
            importance = st.number_input(
                "중요도",
                min_value=1,
                max_value=5,
                value=task.importance if task else 3,
                step=1,
                help="1은 가장 낮음, 5는 가장 높음입니다.",
                key=f"{prefix}_importance",
            )
        with columns[1]:
            remaining = st.number_input(
                "잔여시간(분)",
                min_value=0,
                value=task.remaining_minutes if task else 60,
                step=1,
                help="완료로 저장하면 0분이 됩니다. 다시 진행하려면 1분 이상을 입력하세요.",
                key=f"{prefix}_remaining",
            )
        columns = st.columns(2)
        with columns[0]:
            category = st.text_input(
                "카테고리", value=task.category if task else "", key=f"{prefix}_category"
            )
        with columns[1]:
            status = st.selectbox(
                "진행 상태",
                options=list(STATUS_LABELS),
                format_func=STATUS_LABELS.__getitem__,
                index=list(STATUS_LABELS).index(task.status) if task else 0,
                key=f"{prefix}_status",
            )
        splittable = st.checkbox(
            "나눠서 진행할 수 있음",
            value=task.splittable if task else True,
            key=f"{prefix}_splittable",
        )
        submitted = st.form_submit_button(
            "변경 저장" if task else "작업 추가",
            type="primary",
            key=f"{prefix}_submit",
        )

    if not submitted:
        return

    try:
        due_time = parse_deadline_time(due_time_text)
        result = validate_task(
            {
                "title": title,
                "deadline_date": due_date,
                "deadline_time": due_time,
                "deadline_precision": "datetime" if due_time is not None else "date",
                "importance": importance,
                "remaining_minutes": remaining,
                "category": category,
                "status": status,
                "splittable": splittable,
            },
            existing=task,
        )
    except TaskInputError as error:
        for message in error.errors.values():
            st.error(message)
        return

    st.session_state["tasks"] = {**st.session_state["tasks"], result.id: result}
    revision = "edit_revision" if task else "add_revision"
    st.session_state[revision] += 1
    st.session_state["notice"] = "변경 내용을 반영했습니다." if task else "작업을 추가했습니다."
    st.rerun()


def render_task_list(tasks: dict[str, Task]) -> None:
    columns = st.columns([3, 1], vertical_alignment="bottom")
    with columns[0]:
        choice = st.selectbox(
            "상태", options=["전체", *STATUS_LABELS.values()], key="status_filter"
        )
    with columns[1]:
        st.button("새로고침", key="refresh", width="stretch")
    now = korean_now()
    visible = [
        task for task in tasks.values()
        if choice == "전체" or STATUS_LABELS[task.status] == choice
    ]
    st.caption(f"전체 {len(tasks)}개, 표시 {len(visible)}개")
    if visible:
        rows = [
            {
                "작업명": task.title,
                "마감": format_deadline(task) + (
                    " (기한 초과)" if deadline_state(task, now) == "기한 초과" else ""
                ),
                "중요도": task.importance,
                "잔여시간(분)": task.remaining_minutes,
                "상태": STATUS_LABELS[task.status],
                "카테고리": task.category,
            }
            for task in visible
        ]
        st.dataframe(rows, hide_index=True, width="stretch")
    elif tasks:
        st.info("해당 상태의 작업이 없습니다.")
    else:
        st.info("작업이 없습니다. '작업 추가' 탭에서 등록하세요.")


def render_editor(tasks: dict[str, Task]) -> None:
    if not tasks:
        st.info("작업을 추가하면 수정하거나 삭제할 수 있습니다.")
        return
    if st.session_state.get("selected_task_id") not in tasks:
        st.session_state.pop("selected_task_id", None)
    labels = {
        key: f"{index}. {task.title} ({STATUS_LABELS[task.status]})"
        for index, (key, task) in enumerate(tasks.items(), start=1)
    }
    task_id = st.selectbox(
        "수정할 작업",
        options=list(tasks),
        format_func=labels.__getitem__,
        key="selected_task_id",
    )
    task = tasks[task_id]
    prefix = f"edit_{task_id}_{st.session_state['edit_revision']}"
    render_task_form(prefix, task)

    with st.expander("선택한 작업 삭제"):
        st.write("삭제하면 이 창에서 되돌릴 수 없습니다.")
        confirmed = st.checkbox(
            "선택한 작업을 삭제합니다", key=f"{prefix}_delete_confirm"
        )
        delete_clicked = st.button(
            "작업 삭제", disabled=not confirmed, key=f"{prefix}_delete", type="secondary"
        )
        if delete_clicked and confirmed:
            st.session_state["tasks"] = {
                key: value for key, value in tasks.items() if key != task_id
            }
            st.session_state["edit_revision"] += 1
            st.session_state["notice"] = "작업을 삭제했습니다."
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="작업 우선순위 결정 시스템", layout="centered")
    for key, value in (
        ("tasks", {}), ("add_revision", 0), ("edit_revision", 0),
        ("weekly_schedules", {}), ("special_schedules", {}),
        ("weekly_add_revision", 0), ("weekly_edit_revision", 0),
        ("special_add_revision", 0), ("special_edit_revision", 0),
    ):
        if key not in st.session_state:
            st.session_state[key] = value

    st.title("작업 관리")
    st.warning("임시 저장 중입니다. 브라우저를 새로고침하거나 닫으면 작업이 사라질 수 있습니다.")
    notice = st.session_state.pop("notice", None)
    if notice:
        st.success(notice)

    tasks = st.session_state["tasks"]
    list_tab, add_tab, edit_tab, schedule_tab, capacity_tab = st.tabs(
        ["작업 목록", "작업 추가", "수정과 삭제", "시간표", "가용시간"]
    )
    with list_tab:
        render_task_list(tasks)
    with add_tab:
        render_task_form(f"add_{st.session_state['add_revision']}")
    with edit_tab:
        render_editor(tasks)
    with schedule_tab:
        render_schedules()
    with capacity_tab:
        render_availability(tasks, st.session_state["weekly_schedules"], st.session_state["special_schedules"])


if __name__ == "__main__":
    main()
