from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from streamlit_calendar import calendar

from algorithm import KST, WEEKDAY_LABELS, TaskInputError, ScheduleInputError, deadline_input_date, korean_now, prepare_life_times, schedule_travel_intervals, validate_schedule, validate_task


EXAMPLE_PATH = Path(__file__).resolve().parent / "data" / "example_schedule.json"
EXAMPLE_REVISION = 6
DEFAULT_EXAMPLE_REFERENCE = "2026-11-08T21:30:00+09:00"


def reset_example_editors(state) -> None:
    # 예시 전환 전의 입력 폼과 선택이 다른 작업에 재사용되지 않게 한다.
    for key in ("add_revision", "edit_revision", "weekly_add_revision", "weekly_edit_revision"):
        state[key] = state.get(key, 0) + 1
    for key in ("selected_task_id", "weekly_selected_id"):
        state.pop(key, None)


def set_example_enabled(state, enabled: bool) -> None:
    if enabled == state.get("example_enabled", state.get("example_loaded", False)):
        return
    if enabled:
        hidden = state.pop("example_hidden", {})
        for key in ("tasks", "weekly_schedules"):
            state[key] = {**hidden.get(key, {}), **state[key]}
        for key in ("example_entries", "example_life_times"):
            state[key] = hidden.get(key, [])
    else:
        hidden = {"special_schedules": {}}
        for key, ids_key in (("tasks", "example_task_ids"), ("weekly_schedules", "example_weekly_ids")):
            ids = set(state.get(ids_key, []))
            hidden[key] = {key_id: item for key_id, item in state[key].items() if key_id in ids}
            state[key] = {key_id: item for key_id, item in state[key].items() if key_id not in ids}
        for key in ("example_entries", "example_life_times"):
            hidden[key] = state.get(key, [])
            state[key] = []
        state["example_hidden"] = hidden
    state["example_enabled"] = enabled
    reset_example_editors(state)


def example_id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"priority-system-example:{value}"))


def prepare_example(data: dict):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("예시 데이터 버전을 확인하세요.")
    reference = datetime.fromisoformat(data.get("reference_at", DEFAULT_EXAMPLE_REFERENCE))
    if reference.tzinfo is None:
        raise ValueError("예시 기준 시각에 시간대가 필요합니다.")
    reference = reference.astimezone(KST)
    tasks, schedules, entries = {}, {}, []
    for source in data["entries"]:
        entry = dict(source)
        start, end = date.fromisoformat(entry["start"]), date.fromisoformat(entry["end"])
        if end < start:
            raise ValueError("예시 일정의 날짜 범위를 확인하세요.")
        if type(entry["completed"]) is not bool or type(entry["task"]) is not bool:
            raise ValueError("예시 완료 상태를 확인하세요.")
        if entry["task"]:
            estimate = data["example_estimates"].get(entry["id"], {})
            task = validate_task({
                "title": f"{entry['subject']} - {entry['title']}",
                "deadline_date": end, "deadline_precision": "date", "deadline_time": None,
                "importance": estimate.get("importance", 3),
                "remaining_minutes": 0 if entry["completed"] else estimate["remaining_minutes"],
                "category": entry["subject"], "status": "done" if entry["completed"] else "pending",
                "splittable": True,
                "work_type": entry.get("work_type", "general"),
            }, now=reference)
            task = replace(task, id=example_id(entry["id"]))
            tasks[task.id] = task
            entry["task_id"] = task.id
        entries.append(entry)
    for index, raw in enumerate(data["example_available_times"]):
        schedule = validate_schedule(raw, kind="weekly", now=reference)
        schedule = replace(schedule, id=example_id(raw.get("example_key", f"weekly-{index}")))
        schedules[schedule.id] = schedule
    return tasks, schedules, entries, reference


def read_example() -> dict:
    if EXAMPLE_PATH.exists():
        return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    try:
        text = st.secrets["example_schedule_json"]
    except (StreamlitSecretNotFoundError, KeyError) as error:
        raise FileNotFoundError("예시 자료를 설정해야 합니다. README의 예시 설정을 확인하세요.") from error
    return json.loads(text)


def load_example(state, data: dict) -> bool:
    if state.get("example_loaded", False):
        return False
    tasks, schedules, entries, reference = prepare_example(data)
    life_times = prepare_life_times(data.get("fixed_life_times", []))
    state["tasks"] = {**tasks, **state["tasks"]}
    state["weekly_schedules"] = {**schedules, **state["weekly_schedules"]}
    state["example_entries"] = entries
    state["example_life_times"] = life_times
    state["example_reference"] = reference
    state["example_use_reference"] = True
    state["reference_mode"] = "시연 시각"
    state.pop("reference_mode_widget", None)
    state["example_loaded"] = True
    state["example_enabled"] = True
    state["example_task_ids"] = list(tasks)
    state["example_weekly_ids"] = list(schedules)
    state["example_revision"] = data.get("example_revision", 1)
    state.pop("auto_free", None)
    return True


def update_example_life_times(state, data: dict) -> None:
    proposed_tasks, proposed, _, reference = prepare_example(data)
    life_times = prepare_life_times(data.get("fixed_life_times", []))
    if not life_times:
        raise ValueError("갱신된 예시 원본을 먼저 설정하세요.")
    previous = {}
    previous_sets = data.get("previous_available_by_revision", {}).get(str(state.get("example_revision", 1)))
    if previous_sets is None:
        previous_sets = [data.get("previous_available_times", []), *data.get("previous_available_time_sets", [])]
    for rows in previous_sets:
        for index, raw in enumerate(rows):
            schedule = validate_schedule(raw, kind="weekly", now=reference)
            schedule = replace(schedule, id=example_id(raw.get("example_key", f"weekly-{index}")))
            previous.setdefault(schedule.id, []).append(schedule)
    updated = dict(state["weekly_schedules"])
    for key, candidates in previous.items():
        current = updated.get(key)
        if current is not None and any(all(
            getattr(current, name, 15 if name == "travel_minutes" else False if name == "study_only" else None) == value
            for name, value in asdict(old).items()
        ) for old in candidates):
            updated.pop(key)
            if key in proposed:
                updated[key] = proposed[key]
    for key, schedule in proposed.items():
        if key not in previous:
            updated.setdefault(key, schedule)
    state["weekly_schedules"] = updated
    tasks = dict(state["tasks"])
    for key, proposed_task in proposed_tasks.items():
        current = tasks.get(key)
        if current is not None and getattr(current, "work_type", "general") == "general" and all(
            getattr(current, name, None) == value
            for name, value in asdict(proposed_task).items() if name != "work_type"
        ):
            tasks[key] = proposed_task
    state["tasks"] = tasks
    state["example_life_times"] = life_times
    state["example_revision"] = data.get("example_revision", 1)
    state["example_task_ids"] = sorted(set(state.get("example_task_ids", [])) | set(proposed_tasks))
    state["example_weekly_ids"] = sorted(set(state.get("example_weekly_ids", [])) | set(proposed))
    state.pop("auto_free", None)


def render_example_controls(auto_load: bool = False) -> datetime:
    if auto_load and not st.session_state.get("cloud_example_initialized", False):
        st.session_state["cloud_example_initialized"] = True
        try:
            load_example(st.session_state, read_example())
        except (OSError, KeyError, TypeError, ValueError, TaskInputError, ScheduleInputError) as error:
            st.error(f"채점용 예시를 불러오지 못했습니다. 앱의 예시 설정을 확인하세요. {error}")
    loaded = st.session_state.get("example_loaded", False)
    # 이전 버전 백업에는 예시 소유 ID가 없으므로 원본의 고유 ID로 복구한다.
    ownership_ready = "example_task_ids" in st.session_state and "example_weekly_ids" in st.session_state
    if loaded and not ownership_ready:
        try:
            source = read_example()
            old_tasks, old_weekly, _, _ = prepare_example(source)
            old_ids = set(old_weekly)
            previous_sets = [source.get("previous_available_times", []), *source.get("previous_available_time_sets", [])]
            for rows_by_revision in source.get("previous_available_by_revision", {}).values():
                previous_sets.extend(rows_by_revision)
            for rows in previous_sets:
                old_ids.update(example_id(raw.get("example_key", f"weekly-{index}"))
                               for index, raw in enumerate(rows))
            st.session_state["example_task_ids"] = list(old_tasks)
            st.session_state["example_weekly_ids"] = sorted(old_ids)
        except (OSError, KeyError, TypeError, ValueError) as error:
            st.warning(f"예시 전환을 준비하지 못했습니다. 예시 설정을 확인하세요. {error}")
        else:
            ownership_ready = True
    st.session_state.setdefault("example_enabled", loaded)
    load = st.button("예시 불러오기", disabled=loaded, key="load_example")
    if loaded:
        st.session_state["example_toggle"] = st.session_state["example_enabled"]
        st.toggle(
            "예시 데이터 사용", key="example_toggle", disabled=not ownership_ready,
            help="끄면 예시 작업과 시간표만 숨깁니다. 다시 켜면 편집 내용도 복원됩니다. 직접 추가한 자료는 유지됩니다.",
            on_change=lambda: set_example_enabled(st.session_state, st.session_state["example_toggle"]),
        )
    update = loaded and st.session_state["example_enabled"] and st.session_state.get("example_revision", 0) < EXAMPLE_REVISION and st.button("예시 조건 갱신", key="update_life_times")
    if load or update:
        try:
            data = read_example()
            if update:
                update_example_life_times(st.session_state, data)
            else:
                load_example(st.session_state, data)
        except (OSError, KeyError, TypeError, ValueError, TaskInputError, ScheduleInputError) as error:
            st.error(f"예시를 불러오지 못했습니다. {error}")
        else:
            st.session_state["notice"] = (
                "생활시간표와 수정하지 않은 계산 예시를 갱신했습니다."
                if update else "예시를 불러왔습니다. 일정과 작업을 자유롭게 추가할 수 있습니다."
            )
            st.rerun()
    return render_reference_controls()


def render_reference_controls() -> datetime:
    default = st.session_state.get("example_reference") or datetime.fromisoformat(DEFAULT_EXAMPLE_REFERENCE)
    mode = st.session_state.setdefault(
        "reference_mode", "시연 시각" if st.session_state.get("example_use_reference", False) else "실제 현재 시각"
    )
    with st.expander("기준 시각 설정"):
        mode = st.radio("계산에 사용할 시각", ["실제 현재 시각", "시연 시각"],
                        index=0 if mode == "실제 현재 시각" else 1, key="reference_mode_widget")
        st.session_state["reference_mode"] = mode
        if mode == "시연 시각":
            reference = st.session_state.get("custom_reference") or default
            with st.form("reference_form"):
                chosen_date = st.date_input("시연 날짜", value=reference.date(), min_value=date.min,
                                            max_value=date.max, key="reference_date")
                chosen_time = st.time_input("시연 시각 (한국 시각)", value=reference.time(),
                                            step=60, key="reference_time")
                apply = st.form_submit_button("기준 시각 적용")
            if apply:
                if chosen_date is None or chosen_time is None:
                    st.error("시연 날짜와 시각을 모두 입력하세요.")
                else:
                    st.session_state["custom_reference"] = datetime.combine(chosen_date, chosen_time, KST)
    st.session_state["example_use_reference"] = mode == "시연 시각"
    reference = (st.session_state.get("custom_reference") or default) if mode == "시연 시각" else korean_now()
    st.caption(f"계산 기준: {reference:%Y-%m-%d %H:%M} 한국 시각 ({mode}).")
    return reference


def render_usage_guide() -> None:
    with st.expander("사용 안내"):
        st.markdown("""
1. **작업 추가**에서 작업명, 마감, 남은 예상 작업시간을 입력합니다.
2. **시간표**에서 작업 가능한 구간을 등록합니다. 등록하지 않은 빈 시간은 가용시간으로 계산하지 않습니다.
3. **우선순위**에서 추천과 판단 근거를 확인합니다. ‘개별 시간 충분’은 마감 전까지의 총시간이며, 지금 시작 가능하다는 뜻은 아닙니다.
4. 예시 데이터와 기준 시각은 각각 선택할 수 있습니다. 예시를 꺼도 직접 추가한 작업은 유지됩니다. 예시의 중요도, 예상 작업시간, 가능 시간은 시연용 추정값입니다.
5. 웹에서는 세션이 끝나면 내용이 사라질 수 있습니다. **저장과 백업**에서 JSON을 내려받으세요. 꺼 둔 예시의 편집 내용과 계산 시각 설정도 백업됩니다.
""")


def weekly_travel_events(item) -> list[dict]:
    minutes = getattr(item, "travel_minutes", 15)
    if not minutes:
        return []
    begin = item.start_time.hour * 60 + item.start_time.minute
    finish = item.end_time.hour * 60 + item.end_time.minute + (1440 if item.end_next_day else 0)
    result = []
    for suffix, first, last in (("before", begin - minutes, begin), ("after", finish, finish + minutes)):
        shift = first // 1440
        first, last = first - shift * 1440, last - shift * 1440
        result.append({
            "id": f"{item.id}-travel-{suffix}", "title": "",
            "daysOfWeek": [(day + 1 + shift) % 7 for day in item.weekdays],
            "startTime": f"{first // 60:02d}:{first % 60:02d}",
            "endTime": f"{last // 60:02d}:{last % 60:02d}",
            "display": "background", "color": "#e9eef4",
            "extendedProps": {"description": "가용시간에서 제외되는 이동 구간입니다."},
        })
    return result


def calendar_events(tasks, weekly, special, entries, *, view="month"):
    events = []
    linked = {entry["task_id"]: entry for entry in entries if "task_id" in entry}
    for task in tasks.values():
        source = linked.get(task.id)
        day = deadline_input_date(task)
        done = task.status == "done"
        event = {
            "id": task.id, "title": f"{'완료' if done else '마감'}: {task.title}",
            "color": "#edf0f3" if done else "#dfe9f5",
            "extendedProps": {"description": source["status"] if source else "추가한 작업"},
        }
        if task.deadline_precision == "date":
            begin = source["start"] if source and source["end"] == day.isoformat() else day.isoformat()
            event.update(start=begin, allDay=True)
            if day < date.max:
                event["end"] = (day + timedelta(days=1)).isoformat()
        else:
            event.update(start=task.deadline_at.isoformat(), allDay=False)
        events.append(event)
    for entry in entries:
        if "task_id" in entry:
            continue
        end = date.fromisoformat(entry["end"])
        event = {
            "id": f"entry-{entry['id']}",
            "title": f"{entry['subject']}: {entry['title']} ({entry['status']})",
            "start": entry["start"], "allDay": True,
            "color": "#edf0f3" if entry["completed"] else "#ece6f5",
            "extendedProps": {"description": "시각 미지정 일정입니다. 가용시간에서 자동 차감하지 않습니다."},
        }
        if end < date.max:
            event["end"] = (end + timedelta(days=1)).isoformat()
        events.append(event)
    # 월간은 마감과 개별 일정만 표시한다. 정기 시간표는 주간에서 확인한다.
    for item in weekly.values() if view == "week" else ():
        events.extend(weekly_travel_events(item))
        end_hour = item.end_time.hour + (24 if item.end_next_day else 0)
        events.append({
            "id": item.id, "title": f"{'공부만 가능' if getattr(item, 'study_only', False) else '가능' if item.available else '불가'}: {item.title}",
            "daysOfWeek": [(day + 1) % 7 for day in item.weekdays],
            "startTime": item.start_time.strftime("%H:%M"),
            "endTime": f"{end_hour:02d}:{item.end_time.minute:02d}",
            "display": "background", "color": "#edf5ee" if item.available else "#eff0f2",
        })
    for item in special.values():
        travel = schedule_travel_intervals(item.start_at, item.end_at, getattr(item, "travel_minutes", 15)) if view == "week" else ()
        for index, (begin, finish) in enumerate(travel):
            events.append({
                "id": f"{item.id}-travel-{index}", "title": "", "display": "background",
                "start": begin.isoformat(), "end": finish.isoformat(), "color": "#e9eef4",
                "extendedProps": {"description": "가용시간에서 제외되는 이동 구간입니다."},
            })
        events.append({
            "id": item.id, "title": f"{'공부만 가능' if getattr(item, 'study_only', False) else '가능' if item.available else '불가'}: {item.title}",
            "start": item.start_at.isoformat(), "end": item.end_at.isoformat(),
            "display": "block", "color": "#edf5ee" if item.available else "#eff0f2",
        })
    # 생활일정 원본은 '시간표' 탭의 표에 보관한다. 달력에 중복해서 넣지 않는다.
    return events


def render_life_times() -> None:
    items = st.session_state.get("example_life_times", [])
    if not items:
        return
    with st.expander("기본 생활시간표"):
        st.dataframe([
            {"요일": ", ".join(WEEKDAY_LABELS[day] for day in item["weekdays"]),
             "시간": item["time_text"], "활동": item["title"], "비고": item.get("note", "")}
            for item in items
        ], hide_index=True, width="stretch")
        st.caption("생활일정은 참고 기록입니다. 실제 작업 가능 시간은 아래 정기 시간표와 특별 일정에서 조절합니다.")


def calendar_hover_styles(events: list[dict]) -> str:
    rules = []
    for index, event in enumerate(events):
        name = f"calendar-title-{index}"
        event["classNames"] = [*event.get("classNames", []), name]
        title = str(event.get("title", ""))
        escaped = "".join(
            f"\\{ord(char):x} " if char in '\\"<>' or ord(char) < 32 else char
            for char in title
        )
        rules.append(f'.{name} {{ --calendar-full-title: "{escaped}"; }}')
    return "\n".join(rules)


def render_calendar(tasks, weekly, special, reference: datetime) -> None:
    view = st.radio("달력 보기", ["월간", "주간"], horizontal=True, key="calendar_view", label_visibility="collapsed")
    month = view == "월간"
    events = calendar_events(tasks, weekly, special, st.session_state.get("example_entries", []), view="month" if month else "week")
    hover_styles = calendar_hover_styles(events)
    result = calendar(
        events=events,
        options={
            "initialView": "dayGridMonth" if month else "timeGridWeek", "initialDate": reference.date().isoformat(),
            "now": reference.isoformat(),
            "headerToolbar": {"left": "prev,next today", "center": "title", "right": ""},
            "buttonText": {"today": "오늘", "month": "월", "week": "주"},
            "locale": "ko", "firstDay": 1, "aspectRatio": 1.618, "editable": False,
            "height": "auto" if month else 650, "fixedWeekCount": True,
            "scrollTime": "08:00:00", "allDayText": "종일",
            "displayEventTime": True, "displayEventEnd": not month,
            "dayMaxEvents": 3, "moreLinkText": "더 보기", "moreLinkClick": "popover",
            "eventDisplay": "block", "eventTextColor": "#334155",
            "eventBorderColor": "#dce4ec",
        }, key=f"schedule_calendar_{'month' if month else 'week'}", callbacks=["eventClick"],
        custom_css=hover_styles + "\n" + """
            .fc { --fc-border-color: #e5eaf0; --fc-today-bg-color: #f5f0e5; }
            .fc .fc-toolbar-title { font-size: 1.15rem; color: #334155; }
            .fc .fc-button-primary { background: #edf2f6; border-color: #dce4ec; color: #425466; }
            .fc .fc-button-primary:not(:disabled):hover,
            .fc .fc-button-primary:not(:disabled).fc-button-active { background: #dce7ef; border-color: #ccd9e3; color: #334155; }
            .fc .fc-daygrid-day-frame { min-height: 95px; }
            .fc .fc-daygrid-event { white-space: normal; align-items: flex-start; padding: 3px 4px; }
            .fc .fc-event-title { font-size: 0.86rem; line-height: 1.4; }
            .fc .fc-bg-event { opacity: 0.65; }
            .fc .fc-bg-event .fc-event-title { color: #334155; font-style: normal; font-size: 0.8rem; }
            .fc .fc-daygrid-event .fc-event-title {
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }
            .fc .fc-daygrid-event .fc-event-time { flex-shrink: 0; }
            .fc .fc-daygrid-event-harness:hover,
            .fc .fc-timegrid-event-harness:hover { z-index: 10000 !important; }
            .fc .fc-event:hover, .fc .fc-event:focus-within { overflow: visible !important; z-index: 10000 !important; }
            .fc .fc-event:hover::after, .fc .fc-event:focus-within::after {
                content: var(--calendar-full-title); position: absolute;
                top: calc(100% + 5px); left: 0; z-index: 10001;
                width: max-content; max-width: min(440px, 82vw); box-sizing: border-box;
                padding: 10px 12px; border: 1px solid #cbd5df; border-radius: 6px;
                background: #ffffff; color: #263544; box-shadow: 0 3px 12px #26354420;
                font-size: 0.9rem; line-height: 1.5; font-weight: 400;
                white-space: pre-wrap; overflow-wrap: anywhere; pointer-events: none;
            }
            .fc .fc-daygrid-day:nth-child(n+5) .fc-event::after,
            .fc .fc-timegrid-col:nth-last-child(-n+2) .fc-event::after { left: auto; right: 0; }
            .fc .fc-daygrid-body tr:nth-last-child(-n+2) .fc-event::after { top: auto; bottom: calc(100% + 5px); }
            @media (max-width: 640px) {
                .fc .fc-toolbar { gap: 8px; flex-wrap: wrap; }
                .fc .fc-toolbar-title { font-size: 1rem; }
            }
        """,
    )
    st.caption("월간은 마감과 개별 일정만 표시합니다. 주간의 초록은 가능 시간, 회색은 불가 시간, 푸른 배경은 이동시간입니다. 생활시간표는 '시간표' 탭에서 확인하세요.")
    st.caption("긴 일정명은 마우스를 올리거나 클릭하면 전체를 확인할 수 있습니다.")
    if isinstance(result, dict) and result.get("callback") == "eventClick":
        event = result["eventClick"]["event"]
        st.write(event["title"])
        st.caption(event.get("extendedProps", {}).get("description", ""))
