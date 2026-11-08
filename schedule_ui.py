from datetime import date, datetime, time, timedelta

import streamlit as st

from algorithm import (
    KST,
    WEEKDAY_LABELS,
    AvailabilityRangeError,
    ScheduleInputError,
    SpecialSchedule,
    Task,
    WeeklySchedule,
    assess_task_availability,
    build_available_intervals,
    format_deadline,
    interval_minutes,
    korean_now,
    validate_schedule,
)


def render_schedule_form(kind: str, prefix: str, existing=None) -> None:
    with st.form(f"{prefix}_form"):
        title = st.text_input("일정명", value=existing.title if existing else "", key=f"{prefix}_title")
        days = None
        next_day = False
        start_date = end_date = None
        if kind == "weekly":
            days = st.multiselect(
                "반복 요일", options=list(range(7)),
                default=list(existing.weekdays) if existing else [],
                format_func=lambda value: WEEKDAY_LABELS[value], key=f"{prefix}_weekdays",
            )
        else:
            columns = st.columns(2)
            with columns[0]:
                start_date = st.date_input(
                    "시작일", value=existing.start_at.date() if existing else korean_now().date(),
                    min_value=date.min, max_value=date.max, key=f"{prefix}_start_date",
                )
            with columns[1]:
                end_date = st.date_input(
                    "종료일", value=existing.end_at.date() if existing else korean_now().date(),
                    min_value=date.min, max_value=date.max, key=f"{prefix}_end_date",
                )
        columns = st.columns(2)
        with columns[0]:
            value = existing.start_time if kind == "weekly" and existing else (
                existing.start_at.time() if existing else None
            )
            start_text = st.text_input(
                "시작 시각", value=value.strftime("%H:%M") if value else "",
                placeholder="18:00", key=f"{prefix}_start_time",
            )
        with columns[1]:
            value = existing.end_time if kind == "weekly" and existing else (
                existing.end_at.time() if existing else None
            )
            end_text = st.text_input(
                "종료 시각", value=value.strftime("%H:%M") if value else "",
                placeholder="20:00", key=f"{prefix}_end_time",
            )
        if kind == "weekly":
            next_day = st.checkbox(
                "다음 날 종료", value=existing.end_next_day if existing else False,
                key=f"{prefix}_next_day",
            )
        available = st.selectbox(
            "작업 가능 여부", options=[True, False],
            index=0 if existing is None or existing.available else 1,
            format_func=lambda value: "작업 가능" if value else "작업 불가",
            key=f"{prefix}_available",
        )
        submitted = st.form_submit_button(
            "일정 변경 저장" if existing else "일정 추가", type="primary", key=f"{prefix}_submit"
        )
    if not submitted:
        return
    try:
        result = validate_schedule(
            {
                "title": title, "weekdays": days, "start_time": start_text,
                "end_time": end_text, "end_next_day": next_day, "available": available,
                "start_date": start_date, "end_date": end_date,
            }, kind=kind, existing=existing,
        )
    except ScheduleInputError as error:
        for message in error.errors.values():
            st.error(message)
        return
    state_key = f"{kind}_schedules"
    st.session_state[state_key] = {**st.session_state[state_key], result.id: result}
    st.session_state[f"{kind}_{'edit' if existing else 'add'}_revision"] += 1
    st.session_state["notice"] = "일정을 저장했습니다."
    st.rerun()


def render_schedule_group(kind: str) -> None:
    state_key = f"{kind}_schedules"
    schedules = st.session_state[state_key]
    if schedules:
        rows = []
        for item in schedules.values():
            if kind == "weekly":
                row = {
                    "일정명": item.title,
                    "요일": ", ".join(WEEKDAY_LABELS[day] for day in item.weekdays),
                    "시간": f"{item.start_time:%H:%M}~{'다음 날 ' if item.end_next_day else ''}{item.end_time:%H:%M}",
                }
            else:
                row = {"일정명": item.title, "시작": f"{item.start_at:%Y-%m-%d %H:%M}", "종료": f"{item.end_at:%Y-%m-%d %H:%M}"}
            row["작업"] = "가능" if item.available else "불가"
            rows.append(row)
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption("등록한 일정이 없습니다.")
    mode = st.radio(
        "일정 관리", options=["추가", "수정과 삭제"], horizontal=True, key=f"{kind}_mode"
    )
    if mode == "추가":
        render_schedule_form(kind, f"{kind}_add_{st.session_state[f'{kind}_add_revision']}")
        return
    if not schedules:
        st.info("일정을 먼저 추가하세요.")
        return
    selected_key = f"{kind}_selected_id"
    if st.session_state.get(selected_key) not in schedules:
        st.session_state.pop(selected_key, None)
    labels = {key: f"{number}. {item.title}" for number, (key, item) in enumerate(schedules.items(), 1)}
    selected_id = st.selectbox(
        "수정할 일정", options=list(schedules), format_func=labels.__getitem__, key=selected_key
    )
    prefix = f"{kind}_edit_{selected_id}_{st.session_state[f'{kind}_edit_revision']}"
    render_schedule_form(kind, prefix, schedules[selected_id])
    with st.expander("선택한 일정 삭제"):
        st.write("삭제하면 이 창에서 되돌릴 수 없습니다.")
        confirmed = st.checkbox("선택한 일정을 삭제합니다", key=f"{prefix}_delete_confirm")
        clicked = st.button("일정 삭제", disabled=not confirmed, key=f"{prefix}_delete")
        if clicked and confirmed:
            st.session_state[state_key] = {key: item for key, item in schedules.items() if key != selected_id}
            st.session_state[f"{kind}_edit_revision"] += 1
            st.session_state["notice"] = "일정을 삭제했습니다."
            st.rerun()


def render_schedules() -> None:
    st.caption("가능 시간을 먼저 등록하세요. 특별 일정은 정기 시간표를 바꾸며, 특별 불가 시간이 우선합니다.")
    weekly_tab, special_tab = st.tabs(["정기 시간표", "특별 일정"])
    with weekly_tab:
        render_schedule_group("weekly")
    with special_tab:
        render_schedule_group("special")


def render_availability(
    tasks: dict[str, Task],
    weekly: dict[str, WeeklySchedule],
    special: dict[str, SpecialSchedule],
    reference_now: datetime | None = None,
) -> None:
    now = reference_now if reference_now is not None else korean_now()
    st.button("계산 새로고침", key="capacity_refresh")
    st.caption(f"기준: {now:%Y-%m-%d %H:%M} 한국 시각")
    if not weekly and not special:
        st.info("시간표에서 작업 가능 시간을 등록하세요. 등록 전에는 가용시간이 0입니다.")
    try:
        default_end = now.date() + timedelta(days=6)
    except OverflowError:
        default_end = date.max
    saved_end = st.session_state.get("capacity_end_date")
    if isinstance(saved_end, date) and saved_end < now.date():
        st.session_state.pop("capacity_end_date", None)
    query_end = st.date_input(
        "조회 종료일", value=default_end, min_value=now.date(), max_value=date.max,
        key="capacity_end_date",
    )
    if query_end is None:
        st.info("조회 종료일을 선택하세요.")
        return
    if query_end == date.max:
        end = datetime.max.replace(tzinfo=KST)
    else:
        end = datetime.combine(query_end + timedelta(days=1), time.min, KST)
    try:
        intervals = build_available_intervals(weekly.values(), special.values(), now, end)
    except AvailabilityRangeError as error:
        st.error(str(error))
    else:
        st.write(f"조회 기간의 가용시간: {interval_minutes(intervals):,.1f}분")
        with st.expander("사용 가능한 시간 보기"):
            if intervals:
                st.dataframe(
                    [{"시작": f"{begin:%Y-%m-%d %H:%M}", "종료": f"{finish:%Y-%m-%d %H:%M}", "분": round(interval_minutes([(begin, finish)]), 1)} for begin, finish in intervals],
                    hide_index=True, width="stretch",
                )
            else:
                st.write("사용 가능한 시간이 없습니다.")
    st.subheader("작업별 마감 전 시간")
    st.caption("각 작업을 따로 비교합니다. 여러 작업은 같은 시간을 공유하며, 위 조회 종료일과 관계없이 각 마감까지 계산합니다.")
    rows = []
    for task in tasks.values():
        if task.status == "done":
            continue
        try:
            result = assess_task_availability(task, weekly.values(), special.values(), now)
        except AvailabilityRangeError:
            rows.append({
                "작업명": task.title, "마감": format_deadline(task),
                "예상 작업시간(분)": task.remaining_minutes, "가용시간(분)": None,
                "여유(분)": None, "최대 연속(분)": None, "확인": "10년 초과, 미계산",
            })
            continue
        rows.append({
            "작업명": task.title, "마감": format_deadline(task),
            "예상 작업시간(분)": task.remaining_minutes,
            "가용시간(분)": round(result.available_minutes, 1),
            "여유(분)": round(result.slack_minutes, 1),
            "최대 연속(분)": round(result.longest_minutes, 1), "확인": result.message,
        })
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info("비교할 미완료 작업이 없습니다.")
