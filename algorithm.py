from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Iterable, Mapping
from uuid import uuid4


KST = timezone(timedelta(hours=9), name="KST")
STATUS_LABELS = {"pending": "미시작", "doing": "진행 중", "done": "완료"}
WORK_TYPE_LABELS = {"general": "프로젝트와 보고서 등", "study": "교과 공부와 문제풀이"}
WEEKDAY_LABELS = ("월", "화", "수", "목", "금", "토", "일")
MAX_CALCULATION_DAYS = 3660
Interval = tuple[datetime, datetime]


@dataclass(frozen=True)
class Task:
    id: str
    owner_id: str | None
    title: str
    deadline_at: datetime
    deadline_precision: str
    importance: int
    remaining_minutes: int
    category: str
    status: str
    splittable: bool
    created_at: datetime
    updated_at: datetime
    work_type: str = "general"


class TaskInputError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("\n".join(errors.values()))


def korean_now() -> datetime:
    return datetime.now(KST)


def parse_deadline_time(value: str) -> time | None:
    value = value.strip()
    if not value:
        return None
    if re.fullmatch(r"[0-9]{2}:[0-9]{2}", value):
        try:
            return time.fromisoformat(value)
        except ValueError:
            pass
    raise TaskInputError({"deadline_time": "마감 시각은 18:30처럼 입력하세요."})


def validate_task(
    raw: Mapping[str, object],
    *,
    existing: Task | None = None,
    now: datetime | None = None,
) -> Task:
    """전부 검증한 뒤 새 작업을 반환한다. 오류 때 기존 데이터는 건드리지 않는다."""
    errors: dict[str, str] = {}
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        errors["title"] = "작업명을 입력하세요."

    category = raw.get("category", "")
    if not isinstance(category, str):
        errors["category"] = "카테고리를 글자로 입력하세요."

    importance = raw.get("importance")
    if type(importance) is not int or not 1 <= importance <= 5:
        errors["importance"] = "중요도는 1부터 5 사이의 정수로 입력하세요."

    status = raw.get("status")
    if not isinstance(status, str) or status not in STATUS_LABELS:
        errors["status"] = "진행 상태를 선택하세요."

    remaining = raw.get("remaining_minutes")
    if type(remaining) is not int or remaining < 0:
        errors["remaining_minutes"] = "예상 작업시간은 0 이상의 정수로 입력하세요."
    elif status != "done" and remaining == 0:
        errors["remaining_minutes"] = "미완료 작업의 예상 작업시간은 1분 이상이어야 합니다."

    splittable = raw.get("splittable")
    if type(splittable) is not bool:
        errors["splittable"] = "나눠서 진행할 수 있는지 선택하세요."
    work_type = raw.get("work_type", "general")
    if not isinstance(work_type, str) or work_type not in WORK_TYPE_LABELS:
        errors["work_type"] = "작업 종류를 선택하세요."

    deadline_date = raw.get("deadline_date")
    precision = raw.get("deadline_precision")
    deadline_time = raw.get("deadline_time")
    deadline_at = None
    if type(deadline_date) is not date:
        errors["deadline_date"] = "마감일을 선택하세요."
    if not isinstance(precision, str) or precision not in ("date", "datetime"):
        errors["deadline_precision"] = "마감 기준을 선택하세요."
    if precision == "datetime" and (
        type(deadline_time) is not time or deadline_time.tzinfo is not None
    ):
        errors["deadline_time"] = "마감 시각을 한국 시각으로 입력하세요."

    if not any(key.startswith("deadline_") for key in errors):
        try:
            if precision == "date":
                deadline_at = datetime.combine(
                    deadline_date + timedelta(days=1), time.min, KST
                )
            else:
                deadline_at = datetime.combine(deadline_date, deadline_time, KST)
        except (OverflowError, ValueError):
            errors["deadline_date"] = "마감일이 계산 가능한 범위를 벗어났습니다."

    if errors:
        raise TaskInputError(errors)

    stamp = now if now is not None else korean_now()
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("현재 시각에는 시간대가 필요합니다.")
    stamp = stamp.astimezone(KST)
    return Task(
        id=existing.id if existing else str(uuid4()),
        owner_id=existing.owner_id if existing else None,
        title=title.strip(),
        deadline_at=deadline_at,
        deadline_precision=precision,
        importance=importance,
        remaining_minutes=0 if status == "done" else remaining,
        category=category.strip(),
        status=status,
        splittable=splittable,
        created_at=existing.created_at if existing else stamp,
        updated_at=stamp,
        work_type=work_type,
    )


def deadline_input_date(task: Task) -> date:
    local_date = task.deadline_at.astimezone(KST).date()
    if task.deadline_precision == "date":
        return local_date - timedelta(days=1)
    return local_date


def format_deadline(task: Task) -> str:
    if task.deadline_precision == "date":
        return f"{deadline_input_date(task).isoformat()} 하루 끝"
    return task.deadline_at.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def deadline_state(task: Task, now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("현재 시각에는 시간대가 필요합니다.")
    if task.status == "done":
        return "완료"
    return "기한 초과" if now >= task.deadline_at else "기한 전"


@dataclass(frozen=True)
class WeeklySchedule:
    id: str
    owner_id: str | None
    title: str
    weekdays: tuple[int, ...]
    start_time: time
    end_time: time
    end_next_day: bool
    available: bool
    created_at: datetime
    updated_at: datetime
    study_only: bool = False
    travel_minutes: int = 15


@dataclass(frozen=True)
class SpecialSchedule:
    id: str
    owner_id: str | None
    title: str
    start_at: datetime
    end_at: datetime
    available: bool
    created_at: datetime
    updated_at: datetime
    study_only: bool = False
    travel_minutes: int = 15


class ScheduleInputError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("\n".join(errors.values()))


class AvailabilityRangeError(ValueError):
    pass


def validate_schedule(
    raw: Mapping[str, object],
    *,
    kind: str,
    existing: WeeklySchedule | SpecialSchedule | None = None,
    now: datetime | None = None,
) -> WeeklySchedule | SpecialSchedule:
    if kind not in ("weekly", "special"):
        raise ValueError("일정 종류가 올바르지 않습니다.")
    expected = WeeklySchedule if kind == "weekly" else SpecialSchedule
    if existing is not None and not isinstance(existing, expected):
        raise ValueError("수정할 일정 종류가 다릅니다.")

    errors = {}
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        errors["title"] = "일정명을 입력하세요."
    available = raw.get("available")
    if type(available) is not bool:
        errors["available"] = "작업 가능 여부를 선택하세요."
    study_only = raw.get("study_only", False)
    if type(study_only) is not bool:
        errors["study_only"] = "공부 전용 여부를 선택하세요."
    travel = raw.get("travel_minutes")
    if isinstance(travel, str):
        text = travel.strip()
        try:
            travel = int(text) if re.fullmatch(r"[0-9]+", text) else None if text else 15
        except ValueError:
            travel = None
    elif travel is None:
        travel = 15
    if type(travel) is not int or not 0 <= travel <= 1440:
        errors["travel_minutes"] = "편도 이동 시간은 0부터 1440분 사이의 정수로 입력하세요. 비우면 15분입니다."
    clocks = {}
    for key, label in (("start_time", "시작 시각"), ("end_time", "종료 시각")):
        try:
            value = raw.get(key)
            clocks[key] = parse_deadline_time(value) if isinstance(value, str) else None
        except TaskInputError:
            clocks[key] = None
        if clocks[key] is None:
            errors[key] = f"{label}을 18:30처럼 입력하세요."

    details = {}
    if kind == "weekly":
        days = raw.get("weekdays")
        next_day = raw.get("end_next_day")
        if not isinstance(days, (list, tuple)) or not days or any(
            type(day) is not int or not 0 <= day <= 6 for day in days
        ):
            errors["weekdays"] = "반복할 요일을 선택하세요."
        if type(next_day) is not bool:
            errors["end_next_day"] = "다음 날 종료 여부를 선택하세요."
        if not errors:
            begin = clocks["start_time"]
            finish = clocks["end_time"]
            duration = (
                finish.hour * 60 + finish.minute - begin.hour * 60 - begin.minute
                + 1440 * int(next_day)
            )
            if not 0 < duration <= 1440:
                errors["end_time"] = "종료 시각과 다음 날 종료를 확인하세요. 일정은 24시간 이내여야 합니다."
            else:
                details = {
                    "weekdays": tuple(sorted(set(days))),
                    **clocks,
                    "end_next_day": next_day,
                }
    else:
        for key in ("start_date", "end_date"):
            if type(raw.get(key)) is not date:
                errors[key] = "시작일과 종료일을 선택하세요."
        if not errors:
            begin = datetime.combine(raw["start_date"], clocks["start_time"], KST)
            finish = datetime.combine(raw["end_date"], clocks["end_time"], KST)
            if finish <= begin:
                errors["end_time"] = "종료는 시작보다 뒤여야 합니다."
            else:
                details = {"start_at": begin, "end_at": finish}

    if errors:
        raise ScheduleInputError(errors)
    stamp = now if now is not None else korean_now()
    _require_aware(stamp)
    return expected(
        id=existing.id if existing else str(uuid4()),
        owner_id=existing.owner_id if existing else None,
        title=title.strip(),
        available=available,
        created_at=existing.created_at if existing else stamp.astimezone(KST),
        updated_at=stamp.astimezone(KST),
        study_only=study_only and available,
        travel_minutes=travel,
        **details,
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("시각에는 시간대가 필요합니다.")


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    cleaned = []
    for begin, finish in intervals:
        _require_aware(begin)
        _require_aware(finish)
        if finish < begin:
            raise ValueError("구간 종료는 시작보다 앞설 수 없습니다.")
        if begin < finish:
            cleaned.append((begin.astimezone(KST), finish.astimezone(KST)))
    merged = []
    for begin, finish in sorted(cleaned):
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
        else:
            merged.append((begin, finish))
    return merged


def subtract_intervals(
    available: Iterable[Interval], blocked: Iterable[Interval]
) -> list[Interval]:
    blocks = merge_intervals(blocked)
    result = []
    index = 0
    for begin, finish in merge_intervals(available):
        cursor = begin
        while index < len(blocks) and blocks[index][1] <= begin:
            index += 1
        scan = index
        while scan < len(blocks) and blocks[scan][0] < finish:
            block_begin, block_end = blocks[scan]
            if cursor < block_begin:
                result.append((cursor, block_begin))
            cursor = max(cursor, block_end)
            if cursor >= finish:
                break
            scan += 1
        if cursor < finish:
            result.append((cursor, finish))
        index = scan
    return result


def schedule_travel_intervals(begin: datetime, finish: datetime, minutes: int) -> list[Interval]:
    travel = timedelta(minutes=minutes)
    try:
        before = begin - travel
    except OverflowError:
        before = datetime.min.replace(tzinfo=KST)
    try:
        after = finish + travel
    except OverflowError:
        after = datetime.max.replace(tzinfo=KST)
    return [(before, begin), (finish, after)] if minutes else []


def build_available_intervals(
    weekly: Iterable[WeeklySchedule],
    special: Iterable[SpecialSchedule],
    start: datetime,
    end: datetime,
    *, work_type: str | None = None,
) -> list[Interval]:
    _require_aware(start)
    _require_aware(end)
    start, end = start.astimezone(KST), end.astimezone(KST)
    if end <= start:
        return []
    if end - start > timedelta(days=MAX_CALCULATION_DAYS):
        raise AvailabilityRangeError("계산 기간이 너무 깁니다. 마감이나 종료일을 10년 이내로 지정하세요.")
    weekly_yes, weekly_no, special_yes, special_no, travel_no = [], [], [], [], []

    def add_clipped(target: list[Interval], begin: datetime, finish: datetime) -> None:
        begin, finish = max(begin, start), min(finish, end)
        if begin < finish:
            target.append((begin, finish))

    def add_occurrence(schedule, begin: datetime, finish: datetime, yes, no) -> None:
        for before, after in schedule_travel_intervals(begin, finish, getattr(schedule, "travel_minutes", 15)):
            add_clipped(travel_no, before, after)
        restricted = getattr(schedule, "study_only", False) and work_type not in (None, "study")
        if not schedule.available or restricted:
            add_clipped(no, begin, finish)
        elif not restricted:
            add_clipped(yes, begin, finish)

    first_day = date.fromordinal(max(1, start.date().toordinal() - 2))
    last_ordinal = min(date.max.toordinal(), end.date().toordinal() + 1)
    for schedule in weekly:
        for weekday in schedule.weekdays:
            first_ordinal = first_day.toordinal() + (weekday - first_day.weekday()) % 7
            for ordinal in range(first_ordinal, last_ordinal + 1, 7):
                day = date.fromordinal(ordinal)
                begin = datetime.combine(day, schedule.start_time, KST)
                if schedule.end_next_day and day == date.max:
                    finish = end
                else:
                    finish = datetime.combine(
                        day + timedelta(days=int(schedule.end_next_day)), schedule.end_time, KST
                    )
                add_occurrence(schedule, begin, finish, weekly_yes, weekly_no)
    for schedule in special:
        add_occurrence(schedule, schedule.start_at, schedule.end_at, special_yes, special_no)
    regular = subtract_intervals(weekly_yes, weekly_no)
    return subtract_intervals([*regular, *special_yes], [*special_no, *travel_no])


def interval_minutes(intervals: Iterable[Interval]) -> float:
    return sum((finish - begin).total_seconds() / 60 for begin, finish in intervals)


@dataclass(frozen=True)
class TaskAvailability:
    available_minutes: float
    current_minutes: float
    longest_minutes: float
    slack_minutes: float
    shortage_minutes: float
    message: str


def assess_task_intervals(
    task: Task,
    intervals: Iterable[Interval],
    now: datetime,
) -> TaskAvailability:
    _require_aware(now)
    if task.status == "done":
        return TaskAvailability(0, 0, 0, 0, 0, "완료")
    intervals = merge_intervals(
        (max(begin, now), min(finish, task.deadline_at))
        for begin, finish in intervals
        if max(begin, now) < min(finish, task.deadline_at)
    )
    total = interval_minutes(intervals)
    longest = max((interval_minutes([item]) for item in intervals), default=0)
    current = next(
        ((finish - now).total_seconds() / 60 for begin, finish in intervals if begin <= now < finish),
        0,
    )
    shortage = max(0, task.remaining_minutes - total)
    if now >= task.deadline_at:
        message = "기한 초과"
    elif shortage:
        message = "시간 부족"
    elif not task.splittable and longest < task.remaining_minutes:
        message = "연속 시간 부족"
    else:
        message = "개별 시간 충분"
    return TaskAvailability(total, current, longest, total - task.remaining_minutes, shortage, message)


def assess_task_availability(
    task: Task,
    weekly: Iterable[WeeklySchedule],
    special: Iterable[SpecialSchedule],
    now: datetime,
) -> TaskAvailability:
    _require_aware(now)
    if task.status == "done":
        return TaskAvailability(0, 0, 0, 0, 0, "완료")
    intervals = build_available_intervals(weekly, special, now, task.deadline_at, work_type=getattr(task, "work_type", "general"))
    return assess_task_intervals(task, intervals, now)


@dataclass(frozen=True)
class PriorityScore:
    task: Task
    availability: TaskAvailability
    pressure: float
    proximity: float
    urgency: float
    importance_score: float
    fit: float
    total: float


@dataclass(frozen=True)
class SharedCapacity:
    deadline_at: datetime
    required_minutes: int
    available_minutes: float
    shortage_minutes: float
    scope: str = "all"


@dataclass(frozen=True)
class PriorityResult:
    ranked: tuple[PriorityScore, ...]
    overdue: tuple[Task, ...]
    out_of_range: tuple[Task, ...]
    shared: tuple[SharedCapacity, ...]
    recommendation: PriorityScore | None


def next_task_start(task: Task, weekly, special, now: datetime) -> datetime | None:
    """마감 전 실제로 착수 가능한 다음 구간의 시작을 찾는다."""
    intervals = build_available_intervals(
        weekly, special, now, task.deadline_at, work_type=task.work_type
    )
    return next((begin for begin, finish in intervals
                 if task.splittable or (finish - begin).total_seconds() / 60 >= task.remaining_minutes), None)


def score_task(task: Task, intervals: Iterable[Interval], now: datetime) -> PriorityScore:
    _require_aware(now)
    if task.status == "done" or task.deadline_at <= now:
        raise ValueError("점수는 미래 마감의 미완료 작업만 계산합니다.")
    if task.deadline_at - now > timedelta(days=MAX_CALCULATION_DAYS):
        raise AvailabilityRangeError("마감을 10년 이내로 지정하세요.")
    availability = assess_task_intervals(task, intervals, now)
    pressure = (
        100 * min(1, task.remaining_minutes / availability.available_minutes)
        if availability.available_minutes > 0 else 100.0
    )
    minutes_to_deadline = (task.deadline_at - now).total_seconds() / 60
    proximity = 100 / (1 + minutes_to_deadline / 1440)
    urgency = 0.7 * pressure + 0.3 * proximity
    importance_score = 25.0 * (task.importance - 1)
    can_start = availability.current_minutes > 0 and (
        task.splittable or availability.current_minutes >= task.remaining_minutes
    )
    fit = 100.0 if can_start else 0.0
    total = 0.6 * urgency + 0.3 * importance_score + 0.1 * fit
    return PriorityScore(task, availability, pressure, proximity, urgency, importance_score, fit, total)


def check_shared_capacity(
    tasks: Iterable[Task], intervals: Iterable[Interval], now: datetime,
    *, scope: str = "all",
) -> tuple[SharedCapacity, ...]:
    _require_aware(now)
    demand = {}
    for task in tasks:
        if task.status != "done" and task.deadline_at > now:
            if task.deadline_at - now > timedelta(days=MAX_CALCULATION_DAYS):
                raise AvailabilityRangeError("마감을 10년 이내로 지정하세요.")
            demand[task.deadline_at] = demand.get(task.deadline_at, 0) + task.remaining_minutes
    available = merge_intervals(intervals)
    required = 0
    results = []
    for deadline, minutes in sorted(demand.items()):
        required += minutes
        total = interval_minutes(
            (max(begin, now), min(finish, deadline))
            for begin, finish in available if max(begin, now) < min(finish, deadline)
        )
        results.append(SharedCapacity(deadline, required, total, max(0, required - total), scope))
    return tuple(results)


def rank_tasks(
    tasks: Iterable[Task], weekly: Iterable[WeeklySchedule],
    special: Iterable[SpecialSchedule], now: datetime,
) -> PriorityResult:
    _require_aware(now)
    weekly, special = tuple(weekly), tuple(special)
    overdue, out_of_range, future = [], [], []
    for task in tasks:
        if task.status == "done":
            continue
        if task.deadline_at <= now:
            overdue.append(task)
        elif task.deadline_at - now > timedelta(days=MAX_CALCULATION_DAYS):
            out_of_range.append(task)
        else:
            future.append(task)
    intervals = build_available_intervals(
        weekly, special, now, max((task.deadline_at for task in future), default=now)
    )
    restricted = any(item.available and getattr(item, "study_only", False) for item in (*weekly, *special))
    general_intervals = build_available_intervals(
        weekly, special, now, max((task.deadline_at for task in future), default=now), work_type="general"
    ) if restricted else intervals
    ranked = sorted(
        (score_task(task, intervals if getattr(task, "work_type", "general") == "study" else general_intervals, now) for task in future),
        key=lambda item: (-item.total, item.task.deadline_at, -item.task.importance, item.task.id),
    )
    shared = check_shared_capacity(future, intervals, now)
    if restricted:
        shared += check_shared_capacity(
            (task for task in future if getattr(task, "work_type", "general") == "general"), general_intervals, now, scope="general"
        )
    return PriorityResult(
        ranked=tuple(ranked),
        overdue=tuple(sorted(overdue, key=lambda task: (task.deadline_at, task.id))),
        out_of_range=tuple(sorted(out_of_range, key=lambda task: (task.deadline_at, task.id))),
        shared=shared,
        recommendation=next((item for item in ranked if item.fit == 100), None),
    )


def prepare_life_times(raw: list) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("생활시간표 형식을 확인하세요.")
    result = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
            raise ValueError("생활시간표의 일정명을 확인하세요.")
        days = item.get("weekdays")
        if not isinstance(days, list) or not days or any(type(day) is not int or not 0 <= day <= 6 for day in days):
            raise ValueError("생활시간표의 요일을 확인하세요.")
        if not isinstance(item.get("time_text"), str) or not item["time_text"].strip():
            raise ValueError("생활시간표의 시간 설명을 확인하세요.")
        if not isinstance(item.get("note", ""), str):
            raise ValueError("생활시간표의 비고를 글자로 입력하세요.")
        begin = item.get("start_time")
        finish = item.get("end_time")
        if begin is None and finish is None:
            raise ValueError("생활시간표의 시작이나 종료 시각이 필요합니다.")
        for clock_value in (begin, finish):
            if clock_value is not None and (not isinstance(clock_value, str) or parse_deadline_time(clock_value) is None):
                raise ValueError("생활시간표의 시각을 확인하세요.")
        if begin is not None and finish is not None and parse_deadline_time(begin) >= parse_deadline_time(finish):
            raise ValueError("생활시간표의 시작과 종료 시각을 확인하세요.")
        result.append({**item, "weekdays": list(days)})
    return result
