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


def example_id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"priority-system-example:{value}"))


def prepare_example(data: dict):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("예시 데이터 버전을 확인하세요.")
    reference = datetime.fromisoformat(data["reference_at"])
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
    state["example_loaded"] = True
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
    state.pop("auto_free", None)


def render_example_controls(auto_load: bool = False) -> datetime:
    if auto_load and not st.session_state.get("cloud_example_initialized", False):
        st.session_state["cloud_example_initialized"] = True
        try:
            load_example(st.session_state, read_example())
        except (OSError, KeyError, TypeError, ValueError, TaskInputError, ScheduleInputError) as error:
            st.error(f"채점용 예시를 불러오지 못했습니다. 앱의 예시 설정을 확인하세요. {error}")
    loaded = st.session_state.get("example_loaded", False)
    load = st.button("예시 불러오기", disabled=loaded, key="load_example")
    update = loaded and st.session_state.get("example_revision", 0) < EXAMPLE_REVISION and st.button("예시 조건 갱신", key="update_life_times")
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
    if st.session_state.get("example_loaded", False):
        use_reference = st.checkbox("예시 기준 시각으로 계산", key="example_use_reference")
        reference = st.session_state["example_reference"]
        st.caption(f"예시 기준: {reference:%Y-%m-%d %H:%M} 한국 시각. 중요도, 예상 작업시간과 가능 시간은 계산용 예시값입니다.")
        if use_reference:
            return reference
    return korean_now()


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
            "id": f"{item.id}-travel-{suffix}", "title": f"이동: {item.title} ({minutes}분)",
            "daysOfWeek": [(day + 1 + shift) % 7 for day in item.weekdays],
            "startTime": f"{first // 60:02d}:{first % 60:02d}",
            "endTime": f"{last // 60:02d}:{last % 60:02d}",
            "color": "#e9eef4",
            "extendedProps": {"description": "가용시간에서 제외되는 이동 구간입니다."},
        })
    return result


def calendar_events(tasks, weekly, special, entries, life_times=()):
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
    for item in weekly.values():
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
        for index, (begin, finish) in enumerate(schedule_travel_intervals(item.start_at, item.end_at, getattr(item, "travel_minutes", 15))):
            events.append({
                "id": f"{item.id}-travel-{index}", "title": f"이동: {item.title}",
                "start": begin.isoformat(), "end": finish.isoformat(), "color": "#e9eef4",
                "extendedProps": {"description": "가용시간에서 제외되는 이동 구간입니다."},
            })
        events.append({
            "id": item.id, "title": f"{'공부만 가능' if getattr(item, 'study_only', False) else '가능' if item.available else '불가'}: {item.title}",
            "start": item.start_at.isoformat(), "end": item.end_at.isoformat(),
            "display": "background", "color": "#edf5ee" if item.available else "#eff0f2",
        })
    for index, item in enumerate(life_times):
        event = {
            "id": f"life-{index}", "title": f"{item['title']} ({item['time_text']})",
            "daysOfWeek": [(day + 1) % 7 for day in item["weekdays"]],
            "color": "#f5eddf",
            "extendedProps": {"description": "생활일정 기록입니다. 작업 가능 여부는 시간표 설정을 따릅니다. " + item.get("note", "")},
        }
        if item.get("start_time") is None or item.get("end_time") is None:
            event["allDay"] = True
        else:
            event.update(startTime=item["start_time"], endTime=item["end_time"], allDay=False)
        events.append(event)
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
    st.caption("월간은 일정과 마감을, 주간은 시간대와 가능 시간을 확인합니다. 일정 추가는 기존 입력 탭을 사용하세요.")
    events = calendar_events(tasks, weekly, special, st.session_state.get("example_entries", []), st.session_state.get("example_life_times", []))
    hover_styles = calendar_hover_styles(events)
    result = calendar(
        events=events,
        options={
            "initialView": "dayGridMonth", "initialDate": reference.date().isoformat(),
            "now": reference.isoformat(),
            "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,timeGridWeek"},
            "buttonText": {"today": "오늘", "month": "월", "week": "주"},
            "locale": "ko", "firstDay": 1, "aspectRatio": 1.618, "editable": False,
            "height": "auto", "fixedWeekCount": True,
            "displayEventTime": True, "displayEventEnd": False,
            "dayMaxEvents": False, "dayMaxEventRows": False,
            "eventDisplay": "block", "eventTextColor": "#334155",
            "eventBorderColor": "#dce4ec",
        }, key="schedule_calendar_readable", callbacks=["eventClick"],
        custom_css=hover_styles + "\n" + """
            .fc { --fc-border-color: #e5eaf0; --fc-today-bg-color: #f5f0e5; }
            .fc .fc-toolbar-title { font-size: 1.15rem; color: #334155; }
            .fc .fc-button-primary { background: #edf2f6; border-color: #dce4ec; color: #425466; }
            .fc .fc-button-primary:not(:disabled):hover,
            .fc .fc-button-primary:not(:disabled).fc-button-active { background: #dce7ef; border-color: #ccd9e3; color: #334155; }
            .fc .fc-daygrid-day-frame { min-height: 170px; }
            .fc .fc-daygrid-event { white-space: normal; align-items: flex-start; padding: 3px 4px; }
            .fc .fc-event-title { font-size: 0.86rem; line-height: 1.4; }
            .fc .fc-daygrid-event .fc-event-title {
                white-space: normal; overflow-wrap: anywhere; word-break: keep-all;
                display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
                overflow: hidden;
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
    st.caption("연한 초록은 가능 시간, 회색은 불가 시간, 베이지색은 생활일정입니다. 시간 범위가 미정인 생활일정은 날짜 영역에 표시합니다.")
    st.caption("긴 일정명은 마우스를 올리면 전체를 볼 수 있습니다. 클릭하면 아래에도 표시됩니다.")
    if isinstance(result, dict) and result.get("callback") == "eventClick":
        event = result["eventClick"]["event"]
        st.write(event["title"])
        st.caption(event.get("extendedProps", {}).get("description", ""))
