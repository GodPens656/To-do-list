"""Persistent ordering of selected records without moving unrelated records."""


def reorder_records(records, ordered_ids):
    """Replace only the slots occupied by these IDs; reject stale/invalid drops."""
    if (not isinstance(ordered_ids, list) or len(ordered_ids) < 2
            or any(not isinstance(ident, str) or not ident for ident in ordered_ids)
            or len(set(ordered_ids)) != len(ordered_ids)):
        return None
    selected = set(ordered_ids)
    positions = [i for i, record in enumerate(records) if record.get("id") in selected]
    by_id = {records[i]["id"]: records[i] for i in positions}
    if len(positions) != len(ordered_ids) or len(by_id) != len(ordered_ids):
        return None
    result = list(records)
    for position, ident in zip(positions, ordered_ids):
        result[position] = by_id[ident]
    return result


class OrderingMixin:
    def reorder_tasks(self, ordered_ids, group_id=None):
        data = self._load()
        if group_id is not None:
            allowed = {task.get("id") for task in data["tasks"]
                       if task.get("group", "default") == group_id}
            if (not isinstance(ordered_ids, list)
                    or any(not isinstance(ident, str) or ident not in allowed for ident in ordered_ids)):
                return False
        tasks = reorder_records(data["tasks"], ordered_ids)
        if tasks is None or tasks == data["tasks"]:
            return False
        data["tasks"] = tasks
        # Moving tasks changes their base order, never the saved filters.
        # Stable sorting uses this order when the selected sort keys are equal.
        self._save(data)
        return True

    def reorder_notes(self, group_id, ordered_ids):
        data = self._load()
        for group in data["groups"]:
            if group.get("id") == group_id and group.get("type") == "notes":
                notes = reorder_records(group.get("notes", []), ordered_ids)
                if notes is None or notes == group.get("notes", []):
                    return False
                group["notes"] = notes
                self._save(data)
                return True
        return False

    def reorder_groups(self, ordered_ids):
        data = self._load()
        groups = reorder_records(data["groups"], ordered_ids)
        if groups is None or groups == data["groups"]:
            return False
        data["groups"] = groups
        self._save(data)
        return True
