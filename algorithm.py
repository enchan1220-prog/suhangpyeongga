from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Iterable, Mapping
from uuid import uuid4


KST = timezone(timedelta(hours=9), name="KST")
STATUS_LABELS = {"pending": "미시작", "doing": "진행 중", "done": "완료"}
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
        errors["remaining_minutes"] = "잔여시간은 0 이상의 정수로 입력하세요."
    elif status != "done" and remaining == 0:
        errors["remaining_minutes"] = "미완료 작업의 잔여시간은 1분 이상이어야 합니다."

    splittable = raw.get("splittable")
    if type(splittable) is not bool:
        errors["splittable"] = "나눠서 진행할 수 있는지 선택하세요."

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


def build_available_intervals(
    weekly: Iterable[WeeklySchedule],
    special: Iterable[SpecialSchedule],
    start: datetime,
    end: datetime,
) -> list[Interval]:
    _require_aware(start)
    _require_aware(end)
    start, end = start.astimezone(KST), end.astimezone(KST)
    if end <= start:
        return []
    if end - start > timedelta(days=MAX_CALCULATION_DAYS):
        raise AvailabilityRangeError("계산 기간이 너무 깁니다. 마감이나 종료일을 10년 이내로 지정하세요.")
    weekly_yes, weekly_no, special_yes, special_no = [], [], [], []

    def add_clipped(target: list[Interval], begin: datetime, finish: datetime) -> None:
        begin, finish = max(begin, start), min(finish, end)
        if begin < finish:
            target.append((begin, finish))

    first_day = date.fromordinal(max(1, start.date().toordinal() - 1))
    last_ordinal = end.date().toordinal()
    for schedule in weekly:
        target = weekly_yes if schedule.available else weekly_no
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
                add_clipped(target, begin, finish)
    for schedule in special:
        add_clipped(
            special_yes if schedule.available else special_no,
            schedule.start_at,
            schedule.end_at,
        )
    regular = subtract_intervals(weekly_yes, weekly_no)
    return subtract_intervals([*regular, *special_yes], special_no)


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


def assess_task_availability(
    task: Task,
    weekly: Iterable[WeeklySchedule],
    special: Iterable[SpecialSchedule],
    now: datetime,
) -> TaskAvailability:
    _require_aware(now)
    if task.status == "done":
        return TaskAvailability(0, 0, 0, 0, 0, "완료")
    intervals = build_available_intervals(weekly, special, now, task.deadline_at)
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
