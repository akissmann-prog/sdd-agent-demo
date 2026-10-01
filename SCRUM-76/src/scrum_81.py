"""
scrum_81: Task management business logic with validation, sensible defaults, and SQLite persistence.

Features:
- Enforces non-empty titles and valid statuses ("todo", "doing", "done") on create, update, and filter.
- Applies defaults on create: status defaults to "todo"; created_date defaults to today's UTC date (YYYY-MM-DD).
- Provides CRUD operations and listing with optional status filter.
- Database-level constraints ensure integrity via CHECKs and DEFAULTs.

This module is pure business logic (no HTTP). All functions that access the database accept a db_path argument.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


VALID_STATUSES = ("todo", "doing", "done")


class ValidationError(Exception):
    """Raised when input validation fails (e.g., invalid title or status)."""


class NotFoundError(Exception):
    """Raised when a task with the specified id does not exist."""


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    status: str
    created_date: str  # YYYY-MM-DD

    def __post_init__(self) -> None:
        # Basic sanity checks; DB-level constraints provide authoritative guarantees.
        if self.status not in VALID_STATUSES:
            raise ValidationError(f"Invalid status in Task: {self.status!r}")
        if not isinstance(self.title, str) or len(self.title.strip()) == 0:
            raise ValidationError("Invalid title in Task: must be a non-empty string.")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the tasks table and index if they do not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL CHECK(length(trim(title)) > 0),
          status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','doing','done')),
          created_date TEXT NOT NULL DEFAULT (date('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=int(row["id"]),
        title=str(row["title"]),
        status=str(row["status"]),
        created_date=str(row["created_date"]),
    )


def _normalize_title(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Title must be a string.")
    t = value.strip()
    if len(t) == 0:
        raise ValidationError("Title must be non-empty.")
    return t


def _normalize_status(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Status must be a string.")
    s = value.strip().lower()
    if s not in VALID_STATUSES:
        raise ValidationError(f"Status must be one of {list(VALID_STATUSES)}.")
    return s


def create_task(title: str, status: Optional[str] = None, db_path: str = "demo.db") -> Task:
    """
    Create a new task.
    - title is required and must be non-empty
    - status defaults to "todo" if omitted; must be one of VALID_STATUSES if provided
    - created_date is set by the DB to today's UTC date
    """
    norm_title = _normalize_title(title)
    norm_status = _normalize_status(status) if status is not None else "todo"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        try:
            cur = conn.execute(
                "INSERT INTO tasks (title, status) VALUES (?, ?)",
                (norm_title, norm_status),
            )
        except sqlite3.IntegrityError as e:
            # Should not happen due to pre-validation, but surface as ValidationError.
            raise ValidationError(f"Invalid task data: {e}") from e

        task_id = cur.lastrowid
        row = conn.execute(
            "SELECT id, title, status, created_date FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        assert row is not None, "Inserted row not found unexpectedly."
        return _row_to_task(row)


def get_task(task_id: int, db_path: str = "demo.db") -> Task:
    """Retrieve a task by id or raise NotFoundError if it does not exist."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT id, title, status, created_date FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Task id {task_id} not found.")
        return _row_to_task(row)


def update_task(
    task_id: int,
    title: Optional[str] = None,
    status: Optional[str] = None,
    db_path: str = "demo.db",
) -> Task:
    """
    Update a task's title and/or status.
    - At least one of title or status must be provided.
    - If title is provided: must be non-empty.
    - If status is provided: must be one of VALID_STATUSES.
    - Raises NotFoundError if the task does not exist.
    - Returns the updated Task.
    """
    if title is None and status is None:
        raise ValidationError("No updates provided; specify title and/or status.")

    updates: List[str] = []
    params: List[object] = []

    if title is not None:
        norm_title = _normalize_title(title)
        updates.append("title = ?")
        params.append(norm_title)

    if status is not None:
        norm_status = _normalize_status(status)
        updates.append("status = ?")
        params.append(norm_status)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)

        # Ensure existence first (consistent with design)
        exists_row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if exists_row is None:
            raise NotFoundError(f"Task id {task_id} not found.")

        sql = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
        params.append(task_id)

        try:
            conn.execute(sql, params)
        except sqlite3.IntegrityError as e:
            # DB constraints may trigger (e.g., empty title); map to ValidationError.
            raise ValidationError(f"Invalid task data: {e}") from e

        row = conn.execute(
            "SELECT id, title, status, created_date FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        assert row is not None, "Updated row not found unexpectedly."
        return _row_to_task(row)


def delete_task(task_id: int, db_path: str = "demo.db") -> None:
    """
    Delete a task by id.
    - Raises NotFoundError if the task does not exist.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cur.rowcount is None or cur.rowcount == 0:
            raise NotFoundError(f"Task id {task_id} not found.")


def list_tasks(status: Optional[str] = None, db_path: str = "demo.db") -> List[Task]:
    """
    List tasks, optionally filtered by status.
    - If status is provided, it must be one of VALID_STATUSES.
    - Returns tasks ordered by id ascending.
    """
    where_clause = ""
    params: Sequence[object] = ()

    if status is not None:
        norm_status = _normalize_status(status)
        where_clause = "WHERE status = ?"
        params = (norm_status,)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        rows: Iterable[sqlite3.Row] = conn.execute(
            f"SELECT id, title, status, created_date FROM tasks {where_clause} ORDER BY id ASC",
            params,
        )
        return [_row_to_task(r) for r in rows]