"""
Job applications management module using SQLite.

This module provides pure business logic for creating, listing, retrieving,
updating, and deleting job applications. It performs input validation,
trimming, and enforces a status enum and date format (YYYY-MM-DD).

All database operations use SQLite via the sqlite3 standard library module.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple


ALLOWED_STATUS = {"applied", "interviewing", "offer", "rejected"}


@dataclass
class AppError(Exception):
    status: int
    message: str

    def __str__(self) -> str:
        return f"{self.status}: {self.message}"


class ValidationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(status=400, message=message)


class NotFoundError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(status=404, message=message)


def _utc_today() -> str:
    """Return today's date in YYYY-MM-DD format."""
    return date.today().isoformat()


def _trim(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip()


def _validate_status(status: str) -> None:
    if status not in ALLOWED_STATUS:
        raise ValidationError(
            f"Invalid status '{status}'. Must be one of {sorted(ALLOWED_STATUS)}"
        )


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date_string(date_str: str) -> None:
    """Validate date string is YYYY-MM-DD and represents a valid calendar date."""
    if not _DATE_RE.match(date_str):
        raise ValidationError("applied_date must be in YYYY-MM-DD format")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError("applied_date is not a valid date") from exc


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('applied','interviewing','offer','rejected')),
            applied_date TEXT NOT NULL,
            notes TEXT
        )
        """
    )
    conn.commit()


def _row_to_application(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "company": row["company"],
        "role": row["role"],
        "status": row["status"],
        "applied_date": row["applied_date"],
        "notes": row["notes"],
    }


def create_application(
    company: str,
    role: str,
    status: Optional[str] = None,
    applied_date: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: str = "demo.db",
) -> Dict[str, Any]:
    """
    Create a new job application with validation and defaults.
    - company, role: required, non-empty after trimming.
    - status: optional, defaults to 'applied', must be in allowed enum.
    - applied_date: optional, defaults to today's date in YYYY-MM-DD.
    - notes: optional.
    """
    company_t = _trim(company or "")
    role_t = _trim(role or "")
    if not company_t:
        raise ValidationError("company is required and cannot be empty")
    if not role_t:
        raise ValidationError("role is required and cannot be empty")

    status_t = _trim(status) if status is not None else "applied"
    status_t = status_t.lower() if status_t is not None else "applied"
    _validate_status(status_t)

    if applied_date is None:
        applied_date_t = _utc_today()
    else:
        applied_date_t = _trim(applied_date or "")
    if not applied_date_t:
        raise ValidationError("applied_date cannot be empty")
    _validate_date_string(applied_date_t)

    notes_t = _trim(notes) if notes is not None else None

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO applications (company, role, status, applied_date, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (company_t, role_t, status_t, applied_date_t, notes_t),
        )
        app_id = cur.lastrowid
        conn.commit()
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        assert row is not None
        return _row_to_application(row)


def list_applications(
    status: Optional[str] = None, db_path: str = "demo.db"
) -> List[Dict[str, Any]]:
    """
    List applications with optional status filter.
    - status: optional; if provided, must be one of allowed enum values.
    """
    query = "SELECT id, company, role, status, applied_date, notes FROM applications"
    params: Tuple[Any, ...] = ()
    if status is not None:
        status_t = _trim(status or "")
        if not status_t:
            raise ValidationError("status filter cannot be empty")
        status_t = status_t.lower()
        _validate_status(status_t)
        query += " WHERE status = ?"
        params = (status_t,)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        rows = conn.execute(query, params).fetchall()
        return [_row_to_application(r) for r in rows]


def get_application_by_id(app_id: int, db_path: str = "demo.db") -> Optional[Dict[str, Any]]:
    """
    Retrieve an application by id. Returns None if not found.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_application(row)


def require_application_by_id(app_id: int, db_path: str = "demo.db") -> Dict[str, Any]:
    """
    Retrieve an application by id or raise NotFoundError if it doesn't exist.
    """
    app = get_application_by_id(app_id, db_path=db_path)
    if app is None:
        raise NotFoundError(f"Application with id {app_id} not found")
    return app


def update_application(
    app_id: int,
    company: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    applied_date: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: str = "demo.db",
) -> Dict[str, Any]:
    """
    Update fields of an existing application.
    - Validates provided fields; id is immutable.
    - Returns updated application dict.
    - Raises NotFoundError if id does not exist.
    - Raises ValidationError for invalid inputs or if no updatable fields provided.
    """
    set_clauses: List[str] = []
    values: List[Any] = []

    if company is not None:
        company_t = _trim(company or "")
        if not company_t:
            raise ValidationError("company cannot be empty")
        set_clauses.append("company = ?")
        values.append(company_t)

    if role is not None:
        role_t = _trim(role or "")
        if not role_t:
            raise ValidationError("role cannot be empty")
        set_clauses.append("role = ?")
        values.append(role_t)

    if status is not None:
        status_t = _trim(status or "")
        if not status_t:
            raise ValidationError("status cannot be empty")
        status_t = status_t.lower()
        _validate_status(status_t)
        set_clauses.append("status = ?")
        values.append(status_t)

    if applied_date is not None:
        applied_date_t = _trim(applied_date or "")
        if not applied_date_t:
            raise ValidationError("applied_date cannot be empty")
        _validate_date_string(applied_date_t)
        set_clauses.append("applied_date = ?")
        values.append(applied_date_t)

    if notes is not None:
        notes_t = _trim(notes)
        set_clauses.append("notes = ?")
        values.append(notes_t)

    if not set_clauses:
        raise ValidationError("No updatable fields provided")

    values.append(app_id)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        conn.execute(
            f"UPDATE applications SET {', '.join(set_clauses)} WHERE id = ?",
            tuple(values),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        if row is None:
            # Should not happen if rowcount > 0, but guard anyway
            raise NotFoundError(f"Application with id {app_id} not found")
        return _row_to_application(row)


def delete_application(app_id: int, db_path: str = "demo.db") -> bool:
    """
    Delete an application by id.
    Returns True if a row was deleted, False if not found.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        conn.commit()
        return cur.rowcount > 0


def validate_filter_status(status: Optional[str]) -> Optional[str]:
    """
    Validate an optional status filter string.
    Returns normalized status (lowercase) if provided; returns None if not provided.
    Raises ValidationError if invalid.
    """
    if status is None:
        return None
    status_t = _trim(status or "")
    if not status_t:
        raise ValidationError("status filter cannot be empty")
    status_t = status_t.lower()
    _validate_status(status_t)
    return status_t