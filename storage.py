from dataclasses import asdict, replace
import os
from pathlib import Path
import tempfile
from datetime import date, datetime, time, timedelta
import hashlib
import json

from algorithm import KST, korean_now, prepare_life_times, validate_schedule, validate_task


MAX_BACKUP_BYTES = 2_000_000
WORKSPACE_PATH = Path(__file__).resolve().parent / "data" / "workspace.json"


class StorageError(Exception):
    pass


def _encode(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M")
    raise TypeError("저장할 수 없는 값이 있습니다.")


def make_snapshot(state) -> dict:
    data = {
        "schema_version": 1,
        "tasks": [asdict(item) for item in state["tasks"].values()],
        "weekly_schedules": [asdict(item) for item in state["weekly_schedules"].values()],
        "special_schedules": [asdict(item) for item in state["special_schedules"].values()],
        "settings": {
            "example_loaded": state.get("example_loaded", False),
            "example_use_reference": state.get("example_use_reference", False),
            "example_reference": state.get("example_reference"),
        },
        "example_entries": state.get("example_entries", []),
        "example_life_times": state.get("example_life_times", []),
    }
    return json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False, default=_encode))


def snapshot_hash(payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _datetime(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("저장된 시각 형식을 확인하세요.")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("저장된 시각에는 시간대가 필요합니다.")
    return stamp.astimezone(KST)


def unpack_snapshot(payload: dict) -> dict:
    try:
        if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
            raise ValueError("지원하지 않는 백업 버전입니다.")
        result = {}
        for name in ("tasks", "weekly_schedules", "special_schedules"):
            rows = payload[name]
            if not isinstance(rows, list):
                raise ValueError("저장된 목록 형식을 확인하세요.")
            items = {}
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip() or row["id"] in items:
                    raise ValueError("항목 ID가 없거나 중복되었습니다.")
                created, updated = _datetime(row["created_at"]), _datetime(row["updated_at"])
                if updated < created or (row.get("owner_id") is not None and not isinstance(row["owner_id"], str)):
                    raise ValueError("저장된 항목의 수정 시각과 소유자 형식을 확인하세요.")
                if name == "tasks":
                    due = _datetime(row["deadline_at"])
                    precision = row["deadline_precision"]
                    raw = {
                        **row, "deadline_date": due.date() - timedelta(days=1) if precision == "date" else due.date(),
                        "deadline_time": due.time() if precision == "datetime" else None,
                    }
                    item = validate_task(raw, now=updated)
                    if item.deadline_at != due:
                        raise ValueError("날짜 마감의 저장 시각을 확인하세요.")
                else:
                    kind = "weekly" if name == "weekly_schedules" else "special"
                    raw = dict(row)
                    if kind == "special":
                        begin, finish = _datetime(row["start_at"]), _datetime(row["end_at"])
                        raw.update(start_date=begin.date(), end_date=finish.date(),
                                   start_time=begin.strftime("%H:%M"), end_time=finish.strftime("%H:%M"))
                    item = validate_schedule(raw, kind=kind, now=updated)
                items[row["id"]] = replace(item, id=row["id"], owner_id=row.get("owner_id"), created_at=created, updated_at=updated)
            result[name] = items
        settings = payload.get("settings", {})
        if not isinstance(settings, dict):
            raise ValueError("계산 설정 형식을 확인하세요.")
        for key in ("example_loaded", "example_use_reference"):
            value = settings.get(key, False)
            if type(value) is not bool:
                raise ValueError("예시 계산 설정을 확인하세요.")
            result[key] = value
        reference = settings.get("example_reference")
        result["example_reference"] = _datetime(reference) if reference is not None else None
        if result["example_loaded"] and reference is None:
            raise ValueError("예시 기준 시각이 없습니다.")
        entries = payload.get("example_entries", [])
        if not isinstance(entries, list):
            raise ValueError("달력 원본 형식을 확인하세요.")
        for entry in entries:
            if not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) for key in ("id", "title", "subject", "status", "start", "end")):
                raise ValueError("달력 원본의 필수 항목을 확인하세요.")
            if date.fromisoformat(entry["end"]) < date.fromisoformat(entry["start"]):
                raise ValueError("달력 원본의 날짜 범위를 확인하세요.")
            if any(type(entry.get(key)) is not bool for key in ("completed", "task")):
                raise ValueError("달력 원본의 상태를 확인하세요.")
            if "task_id" in entry and not isinstance(entry["task_id"], str):
                raise ValueError("달력 원본의 작업 ID를 확인하세요.")
        result["example_entries"] = json.loads(json.dumps(entries))
        result["example_life_times"] = prepare_life_times(payload.get("example_life_times", []))
        return result
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise StorageError(f"자료를 불러올 수 없습니다. {error}") from None


def export_backup(state) -> bytes:
    payload = make_snapshot(state)
    unpack_snapshot(payload)
    payload["exported_at"] = korean_now().isoformat()
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    if len(encoded) > MAX_BACKUP_BYTES:
        raise StorageError("백업은 2MB 이내로 저장하세요.")
    return encoded


def import_backup(content: bytes) -> dict:
    if not isinstance(content, bytes) or len(content) > MAX_BACKUP_BYTES:
        raise StorageError("2MB 이내의 JSON 백업 파일을 선택하세요.")
    try:
        def reject_constant(value):
            raise ValueError(value)
        payload = json.loads(content.decode("utf-8-sig"), parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError):
        raise StorageError("올바른 UTF-8 JSON 백업 파일이 아닙니다.") from None
    return unpack_snapshot(payload)


def save_local(state, path: Path = WORKSPACE_PATH) -> None:
    content = export_backup(state)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="workspace-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    except OSError:
        raise StorageError("로컬 파일에 저장하지 못했습니다. 폴더의 쓰기 권한과 남은 공간을 확인하세요.") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def load_local(path: Path = WORKSPACE_PATH) -> dict:
    try:
        with path.open("rb") as file:
            content = file.read(MAX_BACKUP_BYTES + 1)
    except FileNotFoundError:
        raise StorageError("저장된 파일이 없습니다. 예시를 불러오거나 작업을 추가한 뒤 먼저 저장하세요.") from None
    except OSError:
        raise StorageError("로컬 파일을 읽지 못했습니다. 폴더 접근 권한을 확인하세요.") from None
    return import_backup(content)

