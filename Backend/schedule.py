"""Read-only calendar projections of special tasks and deadlines."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class ScheduleEntry:
    date: date
    name: str
    kind: str
    group: str
    task_id: str
    completed: bool = False
    detail: str = ""


def parse_date(value):
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except (TypeError, ValueError):
        return None


def repeat_dates(item, start, end, today):
    """Project a normalized rule, preserving the daily generator's cadence.

    Overdue daily rules restart today, just as check_repeat_tasks does.
    Calendar rules skip nonexistent dates (31st, February 29), without rolling.
    """
    created = parse_date(item.get("created_date"))
    anchor = parse_date(item.get("last_date")) or created or today
    if created:
        start = max(start, created)
    kind, value = item["repeat_type"], item["repeat_value"]
    if kind == "day":
        next_due = max(today, anchor + timedelta(days=value))
    current = start
    while current <= end:
        if kind == "week":
            due = current.isoweekday() == value
        elif kind == "month":
            due = current.day == value
        elif kind == "year":
            due = current.strftime("%d-%m") == value
        else:
            base = anchor if current < today or anchor == today == current else next_due
            due = current >= base and (current - base).days % value == 0
            if current < today:
                due = (current - anchor).days % value == 0
        if due:
            yield current
        current += timedelta(days=1)


def build_schedule(data, start, end, today, generated_deadline, group_id=None):
    """Return entries by date without creating tasks or updating last_date."""
    days = {}
    actual_deadlines = set()

    def matches_group(item):
        return (isinstance(item, dict) and
                (group_id is None or (item.get("group") or "default") == group_id))

    def add(item, when, kind, detail=""):
        if when is None or not start <= when <= end:
            return
        name = str(item.get("name") or "").replace("{N}", "\n")
        group = item.get("group") or "default"
        if not name.strip() or (group_id is not None and group != group_id):
            return
        days.setdefault(when, []).append(ScheduleEntry(
            when, name, kind, group, item.get("id", ""),
            bool(item.get("status", False)), detail,
        ))

    # Existing tasks are authoritative, including completed deadlines.
    for item in data.get("tasks", []):
        if not matches_group(item):
            continue
        deadline = parse_date(item.get("deadline"))
        if deadline and item.get("info_type", "deadline") == "deadline":
            actual_deadlines.add((item.get("name"), item.get("group") or "default", deadline))
            add(item, deadline, "deadline")

    def add_deadline(item, occurrence, source):
        deadline = parse_date(generated_deadline(item, occurrence))
        key = (item.get("name"), item.get("group") or "default", deadline)
        if key not in actual_deadlines:
            add(item, deadline, "deadline", f"{source} · {occurrence:%d.%m.%Y}")

    for item in data.get("postponed", []):
        if not matches_group(item):
            continue
        planned = parse_date(item.get("date"))
        if planned:
            add(item, planned, "postponed")
            if item.get("info_type") == "deadline":
                add_deadline(item, planned, "Отложено")

    for item in data.get("repeat_tasks", []):
        if not matches_group(item) or item.get("disabled", False):
            continue
        for occurrence in repeat_dates(item, start, end, today):
            add(item, occurrence, "repeat")
        if item.get("info_type") != "deadline":
            continue
        try:
            offset = int(item.get("deadline_days"))
        except (TypeError, ValueError):
            offset = 0
        if 1 <= offset <= 3650:
            shifted_start = date.fromordinal(max(1, start.toordinal() - offset))
            shifted_end = date.fromordinal(max(1, end.toordinal() - offset))
            for occurrence in repeat_dates(item, shifted_start, shifted_end, today):
                add_deadline(item, occurrence, "Повтор")
        elif parse_date(item.get("deadline")):
            # Legacy templates use one absolute deadline.
            add_deadline(item, today, "Повтор")

    order = {"deadline": 0, "postponed": 1, "repeat": 2}
    for entries in days.values():
        entries.sort(key=lambda entry: (entry.completed, order[entry.kind], entry.name.casefold()))
    return days
