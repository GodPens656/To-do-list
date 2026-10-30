"""Completion history, points and daily streaks independent of the task list."""

from datetime import date, timedelta


POINTS_PER_TASK = 10
TASK_MILESTONES = (
    (1, "Первый шаг"),
    (10, "В хорошем темпе"),
    (50, "Мастер дел"),
    (100, "Сотня побед"),
    (500, "Большие свершения"),
    (1000, "Легенда продуктивности"),
)
STREAK_MILESTONES = (
    (3, "Искра привычки"),
    (7, "Неделя в ритме"),
    (14, "Две недели силы"),
    (30, "Месяц постоянства"),
    (100, "Сто дней вперёд"),
    (365, "Год в деле"),
)


def _count_word(number, forms):
    if 11 <= number % 100 <= 14:
        return forms[2]
    ending = number % 10
    return forms[0] if ending == 1 else forms[1] if 2 <= ending <= 4 else forms[2]


def completion_history(data):
    """Import older completed tasks without inventing their completion dates."""
    records = {}
    for item in data.get("achievements", []):
        if not isinstance(item, dict) or not isinstance(item.get("task_id"), str):
            continue
        completed_on = item.get("date")
        try:
            completed_on = date.fromisoformat(completed_on).isoformat()
        except (TypeError, ValueError):
            completed_on = None
        records.setdefault(item["task_id"], {
            "task_id": item["task_id"], "date": completed_on,
        })
    for task in data.get("tasks", []):
        if task.get("status") and isinstance(task.get("id"), str):
            records.setdefault(task["id"], {"task_id": task["id"], "date": None})
    return list(records.values())


def update_completion_history(previous, proposed, today):
    """Reward each task once; unchecking revokes its original completion.

    Deleting tasks preserves their history. Undo restores the entire snapshot,
    including this section, and must bypass this function.
    """
    records = {item["task_id"]: item for item in completion_history(previous)}
    old_tasks = {task.get("id"): task for task in previous.get("tasks", [])}
    for task in proposed.get("tasks", []):
        task_id = task.get("id")
        old = old_tasks.get(task_id)
        if old is None:
            if task.get("status") and isinstance(task_id, str):
                records.setdefault(task_id, {"task_id": task_id, "date": None})
        elif bool(old.get("status")) != bool(task.get("status")):
            if task.get("status"):
                records[task_id] = {"task_id": task_id, "date": today.isoformat()}
            else:
                records.pop(task_id, None)
    proposed["achievements"] = list(records.values())


def achievement_summary(data, today):
    history = completion_history(data)
    active_days = {date.fromisoformat(item["date"]) for item in history if item["date"]}
    active_days = {day for day in active_days if day <= today}
    best = run = 0
    previous = None
    for day in sorted(active_days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        best = max(best, run)
        previous = day

    # Yesterday's streak stays alive until the end of today.
    current = 0
    cursor = today if today in active_days else today - timedelta(days=1)
    while cursor in active_days:
        current += 1
        cursor -= timedelta(days=1)

    total = len(history)
    awards = []
    for kind, milestones, value in (
        ("tasks", TASK_MILESTONES, total),
        ("streak", STREAK_MILESTONES, best),
    ):
        for target, title in milestones:
            unit = (_count_word(target, ("дело", "дела", "дел")) if kind == "tasks"
                    else _count_word(target, ("день", "дня", "дней")) + " подряд")
            awards.append({
                "id": f"{kind}_{target}", "kind": kind, "title": title,
                "target": target, "value": min(value, target),
                "description": f"Выполнить {target} {unit}" if kind == "tasks"
                else f"Выполнять дела {target} {unit}",
                "progress_label": f"{min(value, target)} / {target} {unit}",
                "unlocked": value >= target,
            })
    return {
        "points": total * POINTS_PER_TASK,
        "completed_tasks": total,
        "current_streak": current,
        "best_streak": best,
        "completed_today": today in active_days,
        "today_count": sum(item["date"] == today.isoformat() for item in history),
        "week": [
            {"date": (day := today - timedelta(days=offset)).isoformat(),
             "completed": day in active_days, "today": offset == 0}
            for offset in range(6, -1, -1)
        ],
        "awards": awards,
        "unlocked_count": sum(award["unlocked"] for award in awards),
    }
