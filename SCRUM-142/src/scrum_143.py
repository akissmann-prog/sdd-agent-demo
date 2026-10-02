"""
Business logic for managing job applications for a single-page dashboard.

Provides CRUD operations and status transitions using SQLite via the sqlite3 stdlib module.
All functions that interact with the database accept a db_path: str = "demo.db" parameter.

Schema:
- applications (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    applied_date TEXT NOT NULL,  # ISO date string (YYYY-MM-DD)
    status TEXT NOT NULL CHECK(status IN ('applied','interviewing','offer','rejected')),
    notes TEXT
  )

Conventions:
- Status values are normalized to lowercase with surrounding whitespace stripped.
- On creation, status defaults to "applied" and applied_date defaults to today's date (ISO).
- Input validation ensures required fields (company, role) are non-empty after strip.
- IDs are generated as UUIDv4 strings and inserted explicitly.

No third-party dependencies.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, TypedDict


STATUSES: tuple[str, ...] = ("applied", "interviewing", "offer", "rejected")


class Application(TypedDict):
    id: str
    company: str
    role: str
    applied_date: str
    status: str
    notes: Optional[str]


def init_db(db_path: str = "demo.db") -> None:
    """
    Initialize the database schema (idempotent).
    """
    with _connect(db_path) as conn:
        _ensure_schema(conn)


def create_application(
    company: str,
    role: str,
    notes: Optional[str] = None,
    applied_date: Optional[str] = None,
    status: Optional[str] = None,
    db_path: str = "demo.db",
) -> Application:
    """
    Create a new job application.

    Defaults:
    - status: "applied"
    - applied_date: today's date in ISO format (YYYY-MM-DD)
    """
    company_norm = _normalize_required_text(company, "company")
    role_norm = _normalize_required_text(role, "role")
    notes_norm = _normalize_optional_text(notes)
    status_norm = _normalize_status(status if status is not None else "applied")
    applied_date_val = applied_date.strip() if isinstance(applied_date, str) else date.today().isoformat()
    if not applied_date_val:
        applied_date_val = date.today().isoformat()

    app_id = str(uuid.uuid4())

    with _connect(db_path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO applications (id, company, role, applied_date, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (app_id, company_norm, role_norm, applied_date_val, status_norm, notes_norm),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, company, role, applied_date, status, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()

    return _row_to_application(row)


def get_applications(status: Optional[str] = None, db_path: str = "demo.db") -> List[Application]:
    """
    Retrieve all applications, optionally filtered by status.
    """
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        if status is None:
            rows = conn.execute(
                "SELECT id, company, role, applied_date, status, notes FROM applications ORDER BY applied_date DESC, company COLLATE NOCASE ASC"
            ).fetchall()
        else:
            status_norm = _normalize_status(status)
            rows = conn.execute(
                """
                SELECT id, company, role, applied_date, status, notes
                FROM applications
                WHERE status = ?
                ORDER BY applied_date DESC, company COLLATE NOCASE ASC
                """,
                (status_norm,),
            ).fetchall()

    return [_row_to_application(r) for r in rows]


def get_application(app_id: str, db_path: str = "demo.db") -> Optional[Application]:
    """
    Retrieve a single application by id.
    Returns None if not found.
    """
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT id, company, role, applied_date, status, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
    return _row_to_application(row) if row else None


def update_application(
    app_id: str,
    patch: Dict[str, Any],
    db_path: str = "demo.db",
) -> Optional[Application]:
    """
    Update fields of an application by id.

    Allowed fields in patch: company, role, applied_date, status, notes.

    Returns updated application dict, or None if not found.
    """
    if not patch:
        # No-op update; just return current record if exists
        return get_application(app_id, db_path=db_path)

    # Fetch existing to merge and to check existence
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        existing = conn.execute(
            "SELECT id, company, role, applied_date, status, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        if not existing:
            return None

        current = _row_to_application(existing)

        # Prepare new values with normalization and validation
        new_values: Dict[str, Any] = {}
        for key in ("company", "role", "applied_date", "status", "notes"):
            if key in patch:
                if key == "company":
                    new_values["company"] = _normalize_required_text(patch[key], "company")
                elif key == "role":
                    new_values["role"] = _normalize_required_text(patch[key], "role")
                elif key == "applied_date":
                    val = patch[key]
                    val_str = val.strip() if isinstance(val, str) else str(val)
                    if not val_str:
                        # If provided empty, keep current date
                        val_str = current["applied_date"]
                    new_values["applied_date"] = val_str
                elif key == "status":
                    new_values["status"] = _normalize_status(patch[key])
                elif key == "notes":
                    new_values["notes"] = _normalize_optional_text(patch[key])

        # Merge with current values for any fields not in patch
        merged = {
            "company": new_values.get("company", current["company"]),
            "role": new_values.get("role", current["role"]),
            "applied_date": new_values.get("applied_date", current["applied_date"]),
            "status": new_values.get("status", current["status"]),
            "notes": new_values.get("notes", current["notes"]),
        }

        # Build dynamic UPDATE
        set_clauses: List[str] = []
        params: List[Any] = []
        for col in ("company", "role", "applied_date", "status", "notes"):
            set_clauses.append(f"{col} = ?")
            params.append(merged[col])
        params.append(app_id)

        conn.execute(
            f"UPDATE applications SET {', '.join(set_clauses)} WHERE id = ?",
            params,
        )
        conn.commit()

        row = conn.execute(
            "SELECT id, company, role, applied_date, status, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        return _row_to_application(row) if row else None


def delete_application(app_id: str, db_path: str = "demo.db") -> bool:
    """
    Delete an application by id.
    Returns True if a row was deleted, False otherwise.
    """
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        conn.commit()
        return cur.rowcount > 0


def change_status(app_id: str, new_status: str, db_path: str = "demo.db") -> Optional[Application]:
    """
    Convenience method to change the status of an application by id.
    Returns updated application or None if not found.
    """
    return update_application(app_id, {"status": new_status}, db_path=db_path)


def list_grouped_by_status(db_path: str = "demo.db") -> Dict[str, List[Application]]:
    """
    Return applications grouped by status for efficient dashboard rendering.
    Keys are the defined STATUSES. Each value is a list of applications.
    """
    groups: Dict[str, List[Application]] = {s: [] for s in STATUSES}
    apps = get_applications(db_path=db_path)
    for app in apps:
        status = app["status"]
        if status in groups:
            groups[status].append(app)
        else:
            # Should not happen due to CHECK constraint, but be defensive
            groups.setdefault(status, []).append(app)
    return groups


# Internal helpers


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            applied_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('applied','interviewing','offer','rejected')),
            notes TEXT
        )
        """
    )


def _row_to_application(row: sqlite3.Row) -> Application:
    return Application(
        id=row["id"],
        company=row["company"],
        role=row["role"],
        applied_date=row["applied_date"],
        status=row["status"],
        notes=row["notes"],
    )


def _normalize_status(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("status must be a string")
    normalized = value.lower().strip()
    if normalized not in STATUSES:
        raise ValueError(f"invalid status '{value}'; must be one of {', '.join(STATUSES)}")
    return normalized


def _normalize_required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        # Allow converting non-str to str but still require non-empty after strip
        value = str(value) if value is not None else ""
    s = value.strip()
    if not s:
        raise ValueError(f"{field_name} is required")
    return s


def _normalize_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    s = value.strip()
    return s if s != "" else None


__all__ = [
    "STATUSES",
    "Application",
    "init_db",
    "create_application",
    "get_applications",
    "get_application",
    "update_application",
    "delete_application",
    "change_status",
    "list_grouped_by_status",
]