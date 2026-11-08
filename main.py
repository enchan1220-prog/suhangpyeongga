from datetime import date

import streamlit as st

from schedule_ui import render_availability, render_schedules
from calendar_ui import render_calendar, render_example_controls, render_life_times
from storage_ui import apply_pending_workspace, is_cloud_mode, render_storage, render_storage_status

from algorithm import (
    STATUS_LABELS,
    WORK_TYPE_LABELS,
    Task,
    TaskInputError,
    deadline_input_date,
    deadline_state,
    format_deadline,
    korean_now,
    parse_deadline_time,
    rank_tasks,
    validate_task,
)


def render_task_form(prefix: str, task: Task | None = None) -> None:
    with st.form(f"{prefix}_form", clear_on_submit=False):
        title = st.text_input(
            "작업명", value=task.title if task else "", key=f"{prefix}_title"
        )
        due_date = st.date_input(
            "마감일", value=deadline_input_date(task) if task else korean_now().date(),
            min_value=date.min, max_value=date.max, key=f"{prefix}_date",
        )
        remaining = st.number_input(
            "예상 작업시간(분)", min_value=0,
            value=task.remaining_minutes if task else 60, step=1,
            help="지금부터 완료까지 더 필요한 시간을 대략 입력하세요. 작성 1시간과 검토 30분이 남았다면 90분입니다.",
            key=f"{prefix}_remaining",
        )
        st.caption("완료까지 더 필요한 시간의 예상값입니다. 진행한 만큼 직접 줄일 수 있습니다.")
        if task is None:
            st.caption("기본값 60분은 입력 예시입니다. 대략적인 예상으로 바꿔 주세요.")
        with st.expander("선택 설정"):
            st.caption("기본 설정은 중요도 3, 미시작, 나눠서 진행 가능입니다. 마감 시각은 비우면 하루 끝입니다.")
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
            importance = st.number_input(
                "중요도",
                min_value=1,
                max_value=5,
                value=task.importance if task else 3,
                step=1,
                help="1은 가장 낮음, 5는 가장 높음입니다.",
                key=f"{prefix}_importance",
            )
            category = st.text_input(
                "카테고리", value=task.category if task else "", key=f"{prefix}_category"
            )
            work_type = st.selectbox(
                "작업 종류", options=list(WORK_TYPE_LABELS), format_func=WORK_TYPE_LABELS.__getitem__,
                index=list(WORK_TYPE_LABELS).index(getattr(task, "work_type", "general")) if task else 0,
                help="독서실의 공부 전용 시간에는 교과 공부와 문제풀이만 계산합니다.",
                key=f"{prefix}_work_type",
            )
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
                "work_type": work_type,
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


def render_task_list(tasks: dict[str, Task], reference_now=None) -> None:
    columns = st.columns([3, 1], vertical_alignment="bottom")
    with columns[0]:
        choice = st.selectbox(
            "상태", options=["전체", *STATUS_LABELS.values()], key="status_filter"
        )
    with columns[1]:
        st.button("새로고침", key="refresh", width="stretch")
    now = reference_now if reference_now is not None else korean_now()
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
                "예상 작업시간(분)": task.remaining_minutes,
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


def render_priorities(tasks, weekly, special, reference) -> None:
    st.caption(f"계산 기준: {reference:%Y-%m-%d %H:%M} 한국 시각. 완료 작업은 제외합니다.")
    result = rank_tasks(tasks.values(), weekly.values(), special.values(), reference)
    if result.overdue:
        st.warning("기한 초과 작업이 있습니다. 마감과 진행 상태를 확인하세요. 미래 순위와 누적 시간 검사에서는 제외합니다.")
        st.dataframe([
            {"작업명": task.title, "마감": format_deadline(task), "예상 작업시간(분)": task.remaining_minutes}
            for task in result.overdue
        ], hide_index=True, width="stretch")
    if result.out_of_range:
        st.error("마감이 10년을 넘는 작업은 계산하지 않았습니다. 마감을 수정하세요. 누적 시간 검사에서도 제외합니다.")
        st.dataframe([
            {"작업명": task.title, "마감": format_deadline(task)} for task in result.out_of_range
        ], hide_index=True, width="stretch")
    if not result.ranked:
        st.info("추천할 미래 마감의 미완료 작업이 없습니다.")
        return

    st.subheader("지금 시작할 작업")
    if result.recommendation:
        chosen = result.recommendation
        st.write(chosen.task.title)
        st.caption(
            f"현재 연속 가용시간 {chosen.availability.current_minutes:,.1f}분. "
            + ("나눠서 진행할 수 있는 작업입니다." if chosen.task.splittable else "현재 구간에서 연속 작업이 가능합니다.")
        )
    else:
        st.info("현재 시간표상 시작하기 적합한 작업이 없습니다. 시간표와 필요한 연속 시간을 확인하세요.")

    shortages = [item for item in result.shared if item.shortage_minutes > 0]
    if shortages:
        first = min(shortages, key=lambda item: item.deadline_at)
        scope_label = "프로젝트와 보고서" if first.scope == "general" else "전체 작업"
        st.warning(
            f"{scope_label} 기준, {first.deadline_at:%Y-%m-%d %H:%M}까지 "
            f"누적 작업량 {first.required_minutes:,}분, 공통 가용시간 {first.available_minutes:,.1f}분으로 "
            f"{first.shortage_minutes:,.1f}분 부족합니다."
        )
    st.subheader("우선순위")
    st.dataframe([
        {"순위": index, "작업명": item.task.title, "점수": round(item.total, 2),
         "마감": format_deadline(item.task), "시간 확인": item.availability.message,
         "지금 시작": "가능" if item.fit == 100 else "대기"}
        for index, item in enumerate(result.ranked, start=1)
    ], hide_index=True, width="stretch")
    with st.expander("점수와 판단 근거"):
        st.caption("점수 = 긴급도 60% + 중요도 30% + 현재 착수 적합성 10%. 사용자 위임에 따른 추천 설계값입니다.")
        st.caption("긴급도는 작업량 압박 70%와 마감 근접도 30%를 합칩니다. 나눠서 하는 작업은 짧다는 이유로 가산하지 않습니다.")
        st.dataframe([
            {"작업명": item.task.title, "작업량 압박": round(item.pressure, 2),
             "작업 종류": WORK_TYPE_LABELS[getattr(item.task, "work_type", "general")],
             "예상 작업시간(분)": item.task.remaining_minutes,
             "여유(분)": round(item.availability.slack_minutes, 1),
             "마감 근접도": round(item.proximity, 2), "긴급도": round(item.urgency, 2),
             "중요도 점수": item.importance_score, "착수 적합성": item.fit,
             "가용시간(분)": round(item.availability.available_minutes, 1),
             "최대 연속(분)": round(item.availability.longest_minutes, 1)}
            for item in result.ranked
        ], hide_index=True, width="stretch")
        st.caption("가용시간이 0이면 작업량 압박은 100점, 지금 작업할 구간이 없으면 착수 적합성은 0점입니다. 동점은 마감, 중요도, 고유 ID 순으로 정합니다.")
    with st.expander("마감순과 비교"):
        positions = {item.task.id: index for index, item in enumerate(result.ranked, start=1)}
        by_deadline = sorted(result.ranked, key=lambda item: (item.task.deadline_at, item.task.id))
        st.dataframe([
            {"마감순": index, "작업명": item.task.title, "마감": format_deadline(item.task),
             "가중치순": positions[item.task.id], "우선순위 상승": index - positions[item.task.id]}
            for index, item in enumerate(by_deadline, start=1)
        ], hide_index=True, width="stretch")
        st.caption("상승 값이 양수이면 마감순보다 앞섰다는 뜻입니다. 작업량과 중요도가 반영되어 늦은 마감도 앞설 수 있습니다.")
    with st.expander("마감별 누적 시간"):
        st.dataframe([
            {"마감 경계": f"{item.deadline_at:%Y-%m-%d %H:%M}",
             "검사 대상": "프로젝트와 보고서" if item.scope == "general" else "전체 작업",
             "누적 필요(분)": item.required_minutes, "공통 가용시간(분)": round(item.available_minutes, 1),
             "부족(분)": round(item.shortage_minutes, 1)} for item in result.shared
        ], hide_index=True, width="stretch")
        st.caption("여러 작업이 같은 시간을 공유합니다. 부족하지 않아도 연속 작업의 배치나 전체 완료를 보장하지 않으며 자동으로 시간을 배정하지 않습니다.")


def main() -> None:
    st.set_page_config(page_title="작업 우선순위 결정 시스템", layout="centered")
    st.markdown("""
        <style>
        .block-container { max-width: 1200px; padding-top: 1.8rem; }
        [data-testid="stTabs"] button { padding-left: 0.65rem; padding-right: 0.65rem; }
        </style>
    """, unsafe_allow_html=True)
    for key, value in (
        ("tasks", {}), ("add_revision", 0), ("edit_revision", 0),
        ("weekly_schedules", {}), ("special_schedules", {}),
        ("weekly_add_revision", 0), ("weekly_edit_revision", 0),
        ("special_add_revision", 0), ("special_edit_revision", 0),
    ):
        if key not in st.session_state:
            st.session_state[key] = value
    apply_pending_workspace(st.session_state)
    st.session_state.pop("auto_free", None)

    st.title("작업 관리")
    render_storage_status()
    reference = render_example_controls(auto_load=is_cloud_mode())
    notice = st.session_state.pop("notice", None)
    if notice:
        st.success(notice)

    tasks = st.session_state["tasks"]
    calendar_tab, priority_tab, list_tab, add_tab, edit_tab, schedule_tab, capacity_tab, storage_tab = st.tabs(
        ["달력", "우선순위", "작업 목록", "작업 추가", "수정과 삭제", "시간표", "가용시간", "저장과 백업"]
    )
    with calendar_tab:
        render_calendar(tasks, st.session_state["weekly_schedules"], st.session_state["special_schedules"], reference)
    with priority_tab:
        render_priorities(tasks, st.session_state["weekly_schedules"], st.session_state["special_schedules"], reference)
    with list_tab:
        render_task_list(tasks, reference)
    with add_tab:
        render_task_form(f"add_{st.session_state['add_revision']}")
    with edit_tab:
        render_editor(tasks)
    with schedule_tab:
        render_life_times()
        render_schedules()
    with capacity_tab:
        render_availability(tasks, st.session_state["weekly_schedules"], st.session_state["special_schedules"], reference)
    with storage_tab:
        render_storage()


if __name__ == "__main__":
    main()
